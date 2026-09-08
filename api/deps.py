"""共有インスタンスと補助。Consultant / Indexer は起動時に1度だけ構築。"""
from __future__ import annotations

import os
import re
from functools import lru_cache

import anyio

from kb.config import load_settings, Settings
from kb.indexer import Indexer
from kb.answer import Consultant


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


@lru_cache(maxsize=1)
def get_indexer() -> Indexer:
    return Indexer(get_settings().characters_dir)


@lru_cache(maxsize=1)
def get_consultant() -> Consultant:
    # Embedding / VectorStore / LLM プロバイダをここで1度だけ初期化
    return Consultant(get_settings())


def reload_all() -> None:
    """reindex 後などにキャッシュを破棄（/admin/reload から）。"""
    get_settings.cache_clear()
    get_indexer.cache_clear()
    get_consultant.cache_clear()


async def run_blocking(fn, *args, **kwargs):
    """同期の重い処理（numpy 等）をスレッドプールで実行。"""
    return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_user_message(text: str) -> str:
    """ユーザー入力の正規化。制御文字除去・トリム・長さ制限。

    相談文は system prompt ではなく user メッセージとして kb 側へ渡る
    （プロンプトインジェクション対策は kb.prompts のシステム側ルールで担保）。
    """
    text = _CTRL.sub("", text or "")
    text = text.replace("\r\n", "\n").strip()
    return text[:2000]


def admin_token_ok(supplied: str | None) -> bool:
    expected = os.environ.get("KB_ADMIN_TOKEN")
    if not expected:
        return True  # 未設定なら誰でも可（開発用）
    return bool(supplied) and supplied == expected
