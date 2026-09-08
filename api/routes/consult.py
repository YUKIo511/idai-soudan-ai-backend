"""相談エンドポイント。

  POST /consult          … 非ストリーミング（従来どおり。CLI/テスト/後方互換）
  POST /consult/stream   … SSE ストリーミング（スマホ向け。生成トークンを逐次配信）
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from kb.models import RetrievedKnowledge, RELIABILITY_JP
from kb.llm import LLMUnavailableError
from ..deps import get_consultant, get_indexer, get_settings, run_blocking, clean_user_message
from ..ratelimit import rate_limit
from ..schemas import ConsultRequest, ConsultResponse, KnowledgeCitation
from ..sse import SSE_HEADERS

router = APIRouter(tags=["consult"])
log = logging.getLogger("api.consult")

DISCLAIMER = (
    "この回答は、公開されている史料・伝記・本人の発言記録などに基づく推定です。"
    "本人の発言そのものではなく、出典の信頼性ラベルに従って生成されています。"
)


def _citation(k: RetrievedKnowledge) -> KnowledgeCitation:
    body = k.text.split("\n", 1)[1] if "\n" in k.text else k.text
    return KnowledgeCitation(
        id=k.chunk_id, type=k.type, title=k.title,
        reliability=k.reliability,
        attribution_status=k.attribution_status,
        authenticity=k.authenticity,
        disputed=k.disputed,
        source_ids=k.source_ids,
        ref=f"{k.source_file.split('/')[-1]}#{k.entry_pointer}",
        excerpt=body.strip()[:180],
    )


def _require_character(slug: str) -> None:
    if slug not in set(get_indexer().list_characters()):
        raise HTTPException(status_code=404, detail=f"偉人が見つかりません: {slug}")


def _pick_k(message: str) -> int:
    """質問内容に応じて LLM へ渡すチャンク数を決める（品質を落とさず速度を優先）。

    通常相談: retrieval.k（既定 6） / 長い・複数の問い: retrieval.k_complex（既定 8）
    """
    s = get_settings()
    q_marks = message.count("？") + message.count("?")
    if len(message) > 120 or q_marks >= 2:
        return s.retrieval_k_complex
    return s.retrieval_k


def _ns_to_s(v) -> float:
    return round((v or 0) / 1e9, 2)


# ------------------------------------------------------------------ non-stream
@router.post("/consult", response_model=ConsultResponse, dependencies=[Depends(rate_limit)])
async def consult(req: ConsultRequest):
    _require_character(req.character)
    message = clean_user_message(req.message)
    if not message:
        raise HTTPException(status_code=422, detail="メッセージが空です")

    consultant = get_consultant()
    llm = consultant.llm
    k = _pick_k(message)
    log.info("POST /consult  character=%s provider=%s model=%s k=%d msg=%r",
             req.character, llm.name, llm.model or "-", k,
             message[:60] + ("…" if len(message) > 60 else ""))

    t0 = time.perf_counter()
    try:
        result = await run_blocking(consultant.consult, req.character, message, k=k)
    except LLMUnavailableError as e:
        log.warning("POST /consult  LLM 到達不可 (provider=%s): %s", llm.name, e)
        raise HTTPException(status_code=503, detail=str(e))
    total_ms = (time.perf_counter() - t0) * 1000

    tm = result.timings
    st = tm.get("ollama_stats", {}) or {}
    log.info(
        "api.consult:\n"
        "  retrieval=%sms\n  prompt=%sms\n  ollama_total=%sms\n  total=%.0fms\n"
        "  chunks=%s\n  prompt_chars=%s\n  answer_chars=%s\n"
        "  ollama_load=%ss  prompt_eval=%ss  eval=%ss  eval_count=%s  done_reason=%s",
        tm.get("retrieval_ms"), tm.get("prompt_build_ms"), tm.get("llm_ms"), total_ms,
        tm.get("retrieved_chunk_count"), tm.get("prompt_char_count"), tm.get("answer_char_count"),
        _ns_to_s(st.get("load_duration")), _ns_to_s(st.get("prompt_eval_duration")),
        _ns_to_s(st.get("eval_duration")), st.get("eval_count"), st.get("done_reason"),
    )
    return ConsultResponse(
        character=req.character,
        answer=result.answer,
        knowledge=[_citation(kk) for kk in result.report.kept],
        llm_provider=result.llm_provider,
        llm_model=result.llm_model,
        disclaimer=DISCLAIMER,
    )


# ------------------------------------------------------------------ streaming (SSE)
def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@router.post("/consult/stream", dependencies=[Depends(rate_limit)])
async def consult_stream(req: ConsultRequest):
    _require_character(req.character)
    message = clean_user_message(req.message)
    if not message:
        raise HTTPException(status_code=422, detail="メッセージが空です")

    consultant = get_consultant()
    llm = consultant.llm
    k = _pick_k(message)
    log.info("POST /consult/stream  character=%s provider=%s model=%s k=%d msg=%r",
             req.character, llm.name, llm.model or "-", k,
             message[:60] + ("…" if len(message) > 60 else ""))

    async def event_gen():
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        SENTINEL = object()

        def worker():
            try:
                for kind, payload in consultant.consult_stream(req.character, message, k=k):
                    loop.call_soon_threadsafe(q.put_nowait, (kind, payload))
            except LLMUnavailableError as e:
                loop.call_soon_threadsafe(q.put_nowait, ("error", str(e)))
            except Exception as e:  # noqa: BLE001
                log.exception("consult_stream worker error")
                loop.call_soon_threadsafe(q.put_nowait, ("error", f"内部エラー: {e}"))
            finally:
                loop.call_soon_threadsafe(q.put_nowait, SENTINEL)

        t_start = time.perf_counter()
        fut = loop.run_in_executor(None, worker)

        # 1) meta（即時。クライアントは受信した時点でストリーム開始と分かる）
        yield _sse({"type": "meta", "character": req.character,
                    "provider": llm.name, "model": llm.model or "-",
                    "disclaimer": DISCLAIMER})

        sources: list[dict] = []
        prep_timings: dict = {}
        gen_stats: dict = {}
        first_token_at: float | None = None
        answer_chars = 0

        try:
            while True:
                item = await q.get()
                if item is SENTINEL:
                    break
                kind, payload = item
                if kind == "timings":
                    prep_timings = payload
                elif kind == "report":
                    sources = [_citation(kk).model_dump() for kk in payload.kept]
                elif kind == "delta":
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                        log.info("POST /consult/stream  first_token=%.0fms (provider=%s model=%s)",
                                 (first_token_at - t_start) * 1000, llm.name, llm.model or "-")
                    answer_chars += len(payload)
                    yield _sse({"type": "token", "text": payload})
                elif kind == "stats":
                    gen_stats = payload or {}
                elif kind == "error":
                    yield _sse({"type": "error", "message": payload})
                    return

            total_ms = (time.perf_counter() - t_start) * 1000
            first_ms = round((first_token_at - t_start) * 1000) if first_token_at else None
            yield _sse({
                "type": "done",
                "sources": sources,
                "timings": {
                    "retrieval_ms": prep_timings.get("retrieval_ms"),
                    "prompt_build_ms": prep_timings.get("prompt_build_ms"),
                    "ollama_first_token_ms": first_ms,
                    "ollama_total_ms": round(total_ms),
                    "total_ms": round(total_ms),
                    "retrieved_chunk_count": prep_timings.get("retrieved_chunk_count"),
                    "prompt_char_count": prep_timings.get("prompt_char_count"),
                    "answer_char_count": answer_chars,
                },
            })
            log.info(
                "api.consult (stream):\n"
                "  retrieval=%sms\n  prompt=%sms\n  first_token=%sms\n  ollama_total=%.0fms\n  total=%.0fms\n"
                "  chunks=%s\n  prompt_chars=%s\n  answer_chars=%s\n"
                "  ollama_load=%ss  prompt_eval=%ss  eval=%ss  eval_count=%s  done_reason=%s",
                prep_timings.get("retrieval_ms"), prep_timings.get("prompt_build_ms"), first_ms,
                total_ms, total_ms,
                prep_timings.get("retrieved_chunk_count"), prep_timings.get("prompt_char_count"),
                answer_chars,
                _ns_to_s(gen_stats.get("load_duration")), _ns_to_s(gen_stats.get("prompt_eval_duration")),
                _ns_to_s(gen_stats.get("eval_duration")), gen_stats.get("eval_count"),
                gen_stats.get("done_reason"),
            )
        finally:
            await fut

    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=SSE_HEADERS)
