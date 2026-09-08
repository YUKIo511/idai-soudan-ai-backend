"""Voyage AI Embedding。要: pip install voyageai, 環境変数 VOYAGE_API_KEY。"""
from __future__ import annotations

from .base import EmbeddingProvider


class VoyageEmbeddingProvider(EmbeddingProvider):
    name = "voyage"

    def __init__(self, model: str = "voyage-3", dim: int = 1024):
        try:
            import voyageai
        except ImportError as e:
            raise RuntimeError("voyageai 未インストール: pip install voyageai") from e
        self._client = voyageai.Client()
        self.model = model
        self.dim = int(dim)

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        out: list[list[float]] = []
        B = 128
        for i in range(0, len(texts), B):
            batch = [t or " " for t in texts[i:i + B]]
            r = self._client.embed(batch, model=self.model, input_type=input_type)
            out.extend(r.embeddings)
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]
