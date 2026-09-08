"""Embedding プロバイダの factory。"""
from __future__ import annotations

from ..config import Settings
from .base import EmbeddingProvider
from .fake import FakeEmbeddingProvider


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    prov = settings.embeddings_provider
    cfg = settings.embeddings_cfg()
    if prov == "fake":
        return FakeEmbeddingProvider(dim=cfg.get("dim", 256))
    if prov == "openai":
        from .openai_provider import OpenAIEmbeddingProvider
        return OpenAIEmbeddingProvider(model=cfg.get("model", "text-embedding-3-large"), dim=cfg.get("dim", 3072))
    if prov == "voyage":
        from .voyage_provider import VoyageEmbeddingProvider
        return VoyageEmbeddingProvider(model=cfg.get("model", "voyage-3"), dim=cfg.get("dim", 1024))
    raise ValueError(f"未知の embeddings.provider: {prov}")


__all__ = ["EmbeddingProvider", "get_embedding_provider"]
