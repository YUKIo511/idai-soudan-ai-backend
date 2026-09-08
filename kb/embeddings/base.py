"""Embedding プロバイダの抽象（#5, #8）。実装を差し替えても他は不変。"""
from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    name: str = "base"
    model: str = ""
    dim: int = 0

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """文書テキスト群 → ベクトル群（順序対応）。"""

    def embed_query(self, text: str) -> list[float]:
        """相談文 → ベクトル。既定は文書と同じ埋め込み。"""
        return self.embed_documents([text])[0]

    def describe(self) -> str:
        return f"{self.name}(model={self.model or '-'}, dim={self.dim})"
