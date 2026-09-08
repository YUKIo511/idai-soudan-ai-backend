"""answer: 相談 → RAG検索 → 人格・思想適用 → LLM回答生成。"""
from __future__ import annotations

from time import perf_counter
from typing import Iterator

from .config import Settings
from .indexer import Indexer
from .retrieve import Retriever
from .prompts import build_system_prompt, build_user_prompt
from .llm import get_llm_provider, LLMMessage
from .models import AnswerResult, RetrievalReport


class Consultant:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.indexer = Indexer(settings.characters_dir)
        self.retriever = Retriever(settings)
        self.llm = get_llm_provider(settings)

    # ---- 検索 + プロンプト組み立て（計測付き）----
    def _retrieve_and_build(self, character: str, question: str, **kw):
        t0 = perf_counter()
        report: RetrievalReport = self.retriever.retrieve(character, question, **kw)
        t1 = perf_counter()
        persona = self.indexer.persona_bundle(character)
        system = build_system_prompt(
            persona, report.kept, style=self.settings.answer_style,
            max_chunk_chars=int(self.settings.retrieval.get("max_chunk_chars", 240)),
        )
        user = build_user_prompt(question)
        t2 = perf_counter()
        timings = {
            "retrieval_ms": round((t1 - t0) * 1000, 1),
            "prompt_build_ms": round((t2 - t1) * 1000, 1),
            "retrieved_chunk_count": len(report.kept),
            "prompt_char_count": len(system) + len(user),
        }
        return report, system, user, timings

    def prepare(self, character: str, question: str, **kw) -> tuple[RetrievalReport, str, str]:
        """検索 + プロンプト組み立てまで（LLM 呼び出し前）。"""
        report, system, user, _ = self._retrieve_and_build(character, question, **kw)
        return report, system, user

    # ---- 非ストリーミング（既存 API / CLI / テスト用）----
    def consult(self, character: str, question: str, *,
                k: int | None = None,
                themes: list[str] | None = None,
                people: list[str] | None = None,
                reliability: list[str] | None = None,
                types: list[str] | None = None,
                multi_query: bool | None = None) -> AnswerResult:
        report, system, user, timings = self._retrieve_and_build(
            character, question, k=k, themes=themes, people=people,
            reliability=reliability, types=types, multi_query=multi_query,
        )
        t = perf_counter()
        answer = self.llm.chat(
            system, [LLMMessage(role="user", content=user)],
            temperature=self.settings.gen_temperature,
            max_tokens=self.settings.gen_max_tokens,
        )
        timings["llm_ms"] = round((perf_counter() - t) * 1000, 1)
        timings["answer_char_count"] = len(answer)
        if isinstance(getattr(self.llm, "last_stats", None), dict) and self.llm.last_stats:
            timings["ollama_stats"] = dict(self.llm.last_stats)
        return AnswerResult(
            character=character, question=question, answer=answer, report=report,
            system_prompt=system, user_prompt=user,
            llm_provider=self.llm.name, llm_model=self.llm.model, timings=timings,
        )

    # ---- ストリーミング（新 API /consult/stream 用）----
    def consult_stream(self, character: str, question: str, **kw):
        """イベントを順に yield する:
          ("timings", dict)   検索+プロンプトの計測（LLM 呼び出し前）
          ("report",  RetrievalReport)
          ("delta",   str)    生成テキストの増分（複数回）
          ("stats",   dict)   Ollama の生成統計（load_duration 等。対応プロバイダのみ）
        既存 consult() は変更していない。
        """
        report, system, user, timings = self._retrieve_and_build(character, question, **kw)
        yield ("timings", timings)
        yield ("report", report)
        stats: dict = {}
        for delta in self.llm.stream_chat(
            system, [LLMMessage(role="user", content=user)],
            temperature=self.settings.gen_temperature,
            max_tokens=self.settings.gen_max_tokens,
            stats=stats,
        ):
            yield ("delta", delta)
        yield ("stats", stats)
