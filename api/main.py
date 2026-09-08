"""FastAPI アプリ本体。API ルータ + 静的フロントエンド配信。

起動:  uvicorn api.main:app --host 0.0.0.0 --port 8000
スマホからは同一 Wi-Fi で http://<PCのLAN IP>:8000 を開く。
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .deps import get_settings, get_indexer, get_consultant, reload_all, admin_token_ok
from .schemas import HealthResponse
from .routes import characters as characters_routes
from .routes import consult as consult_routes

# アプリ側ログ（kb.*, api.*）を uvicorn のコンソールに出す
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _ensure_rag_index() -> None:
    """Vector Store（.vectorstore/char__<slug>.json）が無い偉人を起動時に自動ビルドする。

    本番（Railway）ではリポジトリに .vectorstore/ を同梱しているので通常は何もしない。
    同梱が無い / 偉人を追加して embed し忘れた場合だけ、その場で build → embed する保険。
    memory backend は消えても再構築可能なのでプロセス再起動でも安全。
    """
    s = get_settings()
    if s.vectorstore_backend != "memory":
        return  # chroma 等は別管理
    idx = get_indexer()
    try:
        chars = idx.list_characters()
    except Exception as e:  # noqa: BLE001
        log.warning("偉人一覧の取得に失敗（index 初期化スキップ）: %s", e)
        return
    missing = [c for c in chars if not (s.vectorstore_dir / f"char__{c}.json").exists()]
    if not missing:
        return
    log.info("Vector Store 未生成の偉人を自動ビルドします: %s", ", ".join(missing))
    from kb.build import run_build
    from kb.embed import run_embed
    for slug in missing:
        try:
            run_build(slug, s)
            r = run_embed(slug, s, reset=True)
            log.info("  [%s] embed %s 件", slug, r.get("embedded"))
        except Exception as e:  # noqa: BLE001
            log.error("  [%s] 自動ビルド失敗: %s", slug, e)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    _ensure_rag_index()
    # 使用中の LLM プロバイダ / モデルを起動時に明示表示（要件4）
    if s.llm_provider == "ollama":
        model_info = f"{s.llm_provider}  model={s.ollama_model}  base_url={s.ollama_base_url}"
    else:
        model_info = f"{s.llm_provider}  model={(s.llm_cfg() or {}).get('model', '-')}"
    log.info("=" * 72)
    log.info("偉人相談AI API  起動")
    log.info("  LLM          : %s", model_info)
    log.info("  answer_style : %s", s.answer_style)
    log.info("  embeddings   : %s", s.embeddings_provider)
    log.info("  vectorstore  : %s", s.vectorstore_backend)
    log.info("  characters   : %s", ", ".join(get_indexer().list_characters()))
    if s.llm_provider == "ollama":
        log.info("  ※ Ollama 未起動/モデル未取得時は POST /consult が 503 を返します（Fake へは切り替わりません）")
    log.info("=" * 72)
    # LLM プロバイダを起動時に構築してログを出す（kb.llm の factory ログもここで出る）
    try:
        consultant = get_consultant()
    except Exception as e:  # 構築自体は失敗しない想定だが、保険
        log.warning("Consultant の事前構築に失敗: %s", e)
        consultant = None

    # 起動時 warmup（オプション）: モデルを先にロードして初回リクエストを速くする。
    # 失敗しても FastAPI は落とさず警告のみ。起動は待たず背後で実行。
    warmup_task = None
    if (consultant is not None and s.llm_provider == "ollama"
            and s.ollama_options().get("warmup_on_start")):
        warmup_task = asyncio.create_task(_warmup(consultant))

    yield

    if warmup_task and not warmup_task.done():
        warmup_task.cancel()


async def _warmup(consultant) -> None:
    """モデルをロードし、各偉人の system プロンプトの不変プレフィックスを
    Ollama にキャッシュさせる。→ 各偉人への最初の実リクエストで prompt_eval が
    「可変部分（knowledge + 質問）」だけになり、first_token が大きく縮む。
    失敗しても FastAPI は落とさず警告のみ。起動はブロックしない（背後で順次実行）。"""
    from kb.llm import LLMMessage, LLMUnavailableError

    llm = consultant.llm
    loop = asyncio.get_running_loop()
    s = get_settings()
    try:
        all_chars = consultant.indexer.list_characters()
    except Exception:  # noqa: BLE001
        all_chars = []
    if not all_chars:
        return

    # llm.ollama.warmup_characters: 明示リスト / "all" / 未指定=先頭1名のみ
    #   （他の偉人は初回相談時にプレフィックスが温まる）
    wc = (s.ollama_options() or {}).get("warmup_characters")
    if wc == "all":
        chars = all_chars
    elif isinstance(wc, list) and wc:
        chars = [c for c in wc if c in all_chars] or all_chars[:1]
    else:
        chars = all_chars[:1]

    t0 = time.perf_counter()
    for i, slug in enumerate(chars):
        t = time.perf_counter()
        try:
            _, system, _user = await loop.run_in_executor(
                None, lambda s=slug: consultant.prepare(s, "こんにちは。少し相談させてください。"))
            await loop.run_in_executor(
                None,
                lambda sysp=system: llm.chat(sysp, [LLMMessage(role="user", content="こんにちは")], max_tokens=1),
            )
            st = getattr(llm, "last_stats", {}) or {}
            load_s = (st.get("load_duration") or 0) / 1e9
            log.info("Ollama warmup [%d/%d] %s  %.1fs（load %.1fs, prefix キャッシュ化）",
                     i + 1, len(chars), slug, time.perf_counter() - t, load_s)
        except LLMUnavailableError as e:
            log.warning("Ollama warmup 失敗（起動は継続）: %s", e)
            return
        except Exception as e:  # noqa: BLE001
            log.warning("Ollama warmup 失敗（%s、起動は継続）: %s", slug, e)
    log.info("Ollama warmup 完了: %d 偉人  合計 %.1fs", len(chars), time.perf_counter() - t0)


app = FastAPI(title="偉人相談AI API", version="0.1.0", lifespan=lifespan)

# CORS: ネイティブアプリ（React Native / Expo）は Origin を送らないので CORS の影響を受けない。
# 影響するのはブラウザ（web/ の SPA や動作確認）だけ。
#   - 開発:  未設定なら "*"（ローカルのブラウザ確認を楽にする）
#   - 本番:  KB_CORS_ORIGINS に許可オリジンをカンマ区切りで指定（例: https://example.com）。
#           未設定のままだと "*" になるので、web を公開しないなら "none" を設定してブラウザ拒否にできる。
_env = os.environ.get("KB_ENV", "development")
_origins = os.environ.get("KB_CORS_ORIGINS", "*")
if _origins.lower() in ("none", ""):
    _allow_origins: list[str] = []
elif _origins == "*":
    _allow_origins = ["*"]
    if _env == "production":
        log.warning("CORS allow_origins=* （本番）。web を公開しないなら KB_CORS_ORIGINS=none を推奨")
else:
    _allow_origins = [o.strip() for o in _origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(characters_routes.router)
app.include_router(consult_routes.router)


@app.get("/health")
def health():
    """Railway ヘルスチェック用の軽量エンドポイント。

    LLM 推論・RAG 検索は一切しない。秘密情報（API キー等）は返さない。
    provider 名（cloudflare / ollama など）だけ内部確認用に含める。
    """
    return {"status": "ok", "provider": get_settings().llm_provider}


@app.get("/healthz", response_model=HealthResponse)
def healthz():
    s = get_settings()
    return HealthResponse(
        status="ok",
        embeddings=s.embeddings_provider,
        vectorstore=s.vectorstore_backend,
        llm=s.llm_provider,
        characters=len(get_indexer().list_characters()),
    )


@app.post("/admin/reload")
def admin_reload(x_admin_token: str | None = Header(default=None)):
    if not admin_token_ok(x_admin_token):
        raise HTTPException(status_code=401, detail="invalid admin token")
    reload_all()
    return {"status": "reloaded", "characters": len(get_indexer().list_characters())}


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception):
    # 内部例外の詳細（スタックトレース・鍵など）をクライアントに漏らさない
    log.exception("unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "内部エラーが発生しました"})


# --- 静的フロントエンド（API ルート登録後にマウント）---
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
