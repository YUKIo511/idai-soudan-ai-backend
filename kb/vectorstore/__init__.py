"""Vector Store の factory。"""
from __future__ import annotations

from ..config import Settings
from .base import VectorStore
from .memory_store import MemoryVectorStore


def get_vector_store(settings: Settings) -> VectorStore:
    backend = settings.vectorstore_backend
    prefix = settings.collection_prefix
    if backend == "memory":
        return MemoryVectorStore(root=settings.vectorstore_dir, prefix=prefix)
    if backend == "chroma":
        from .chroma_store import ChromaVectorStore
        return ChromaVectorStore(path=settings.chroma_dir, prefix=prefix)
    raise ValueError(f"未知の vectorstore.backend: {backend}")


__all__ = ["VectorStore", "get_vector_store"]
