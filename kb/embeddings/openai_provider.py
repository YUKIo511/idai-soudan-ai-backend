"""OpenAI Embedding（text-embedding-3-*）。要: pip install openai, 環境変数 OPENAI_API_KEY。"""
from __future__ import annotations

from .base import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"

    def __init__(self, model: str = "text-embedding-3-large", dim: int = 3072):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("openai 未インストール: pip install openai") from e
        self._client = OpenAI()
        self.model = model
        self.dim = int(dim)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        B = 128
        for i in range(0, len(texts), B):
            batch = [t or " " for t in texts[i:i + B]]
            resp = self._client.embeddings.create(model=self.model, input=batch, dimensions=self.dim)
            out.extend(d.embedding for d in resp.data)
        return out
