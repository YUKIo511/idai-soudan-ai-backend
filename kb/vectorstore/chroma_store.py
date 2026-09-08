"""Chroma 実装（#7）。偉人ごとにコレクション char__<slug> を分ける（#9）。

要: pip install chromadb。埋め込みはこちらで生成して渡す（Chroma の内蔵EFは使わない）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import StoredChunk, QueryHit
from .base import VectorStore


def _to_chroma_where(where: dict[str, Any] | None) -> dict[str, Any] | None:
    if not where:
        return None
    clauses: list[dict[str, Any]] = []
    for k, cond in where.items():
        if isinstance(cond, dict):
            if "in" in cond:
                clauses.append({k: {"$in": list(cond["in"])}})
            elif "nin" in cond:
                clauses.append({k: {"$nin": list(cond["nin"])}})
            elif "ne" in cond:
                clauses.append({k: {"$ne": cond["ne"]}})
        else:
            clauses.append({k: {"$eq": cond}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


class ChromaVectorStore(VectorStore):
    def __init__(self, path: Path, prefix: str = "char__"):
        try:
            import chromadb
        except ImportError as e:
            raise RuntimeError("chromadb 未インストール: pip install chromadb（または config で backend: memory）") from e
        self._client = chromadb.PersistentClient(path=str(path))
        self.prefix = prefix

    def _col(self, character: str, create: bool = True):
        name = f"{self.prefix}{character}"
        if create:
            return self._client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
        try:
            return self._client.get_collection(name=name)
        except Exception:
            return None

    def upsert(self, character: str, chunks: list[StoredChunk]) -> None:
        if not chunks:
            return
        col = self._col(character)
        col.upsert(
            ids=[c.id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=[list(c.embedding) for c in chunks],
            metadatas=[c.metadata for c in chunks],
        )

    def delete_character(self, character: str) -> None:
        try:
            self._client.delete_collection(name=f"{self.prefix}{character}")
        except Exception:
            pass

    def query(self, character: str, embedding: list[float], *, k: int,
              where: dict[str, Any] | None = None) -> list[QueryHit]:
        col = self._col(character, create=False)
        if col is None:
            return []
        res = col.query(
            query_embeddings=[list(embedding)],
            n_results=k,
            where=_to_chroma_where(where),
            include=["documents", "metadatas", "distances"],
        )
        hits: list[QueryHit] = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for i, cid in enumerate(ids):
            hits.append(QueryHit(id=cid, text=docs[i], metadata=metas[i], score=1.0 - float(dists[i])))
        return hits

    def count(self, character: str, where: dict[str, Any] | None = None) -> int:
        col = self._col(character, create=False)
        if col is None:
            return 0
        if not where:
            return col.count()
        return len(col.get(where=_to_chroma_where(where), include=[]).get("ids", []))

    def get(self, character: str, *, ids: list[str] | None = None,
            where: dict[str, Any] | None = None) -> list[StoredChunk]:
        col = self._col(character, create=False)
        if col is None:
            return []
        res = col.get(ids=ids, where=_to_chroma_where(where), include=["documents", "metadatas", "embeddings"])
        out = []
        for i, cid in enumerate(res.get("ids", [])):
            emb = res.get("embeddings") or []
            out.append(StoredChunk(
                id=cid,
                text=(res.get("documents") or [None] * (i + 1))[i],
                metadata=(res.get("metadatas") or [{}] * (i + 1))[i],
                embedding=list(emb[i]) if i < len(emb) else None,
            ))
        return out

    def list_characters(self) -> list[str]:
        out = []
        for c in self._client.list_collections():
            nm = c.name if hasattr(c, "name") else str(c)
            if nm.startswith(self.prefix):
                out.append(nm[len(self.prefix):])
        return sorted(out)
