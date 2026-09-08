"""オフライン用 Embedding: feature hashing（語 + CJKバイグラム）。

API キー不要で、語彙的な重なりに応じた類似度が出るためパイプラインの検証に使える。
本番は openai / voyage プロバイダに config で切替。
"""
from __future__ import annotations

import hashlib
import re

import numpy as np

from .base import EmbeddingProvider

_WORD_RE = re.compile(r"[0-9A-Za-z_]+|[぀-ヿ一-鿿]")


def _tokens(text: str) -> list[str]:
    chars = _WORD_RE.findall(text.lower())
    toks: list[str] = []
    prev_cjk = None
    for c in chars:
        toks.append(c)
        if len(c) == 1 and ord(c) > 0x3000:  # CJK 1文字 → バイグラム
            if prev_cjk:
                toks.append(prev_cjk + c)
            prev_cjk = c
        else:
            prev_cjk = None
    return toks


def _hash(tok: str, dim: int) -> tuple[int, float]:
    h = int.from_bytes(hashlib.md5(tok.encode("utf-8")).digest()[:8], "little")
    return h % dim, 1.0 if (h >> 63) & 1 else -1.0


class FakeEmbeddingProvider(EmbeddingProvider):
    name = "fake"

    def __init__(self, dim: int = 256):
        self.dim = int(dim)
        self.model = f"hashing-{self.dim}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in _tokens(t or ""):
                idx, sign = _hash(tok, self.dim)
                out[i, idx] += sign
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (out / norms).tolist()
