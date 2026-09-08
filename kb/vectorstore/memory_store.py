"""依存ゼロの Vector Store。numpy コサイン類似度、偉人ごとに JSON ファイルで永続。

chromadb が無い環境でもパイプラインを完走させるためのフォールバック。
本番は ChromaStore（backend: chroma）へ config で切替。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ..models import StoredChunk, QueryHit
from .base import VectorStore, match_where


class MemoryVectorStore(VectorStore):
    def __init__(self, root: Path, prefix: str = "char__"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.prefix = prefix

    def _path(self, character: str) -> Path:
        return self.root / f"{self.prefix}{character}.json"

    def _load(self, character: str) -> dict[str, Any]:
        p = self._path(character)
        if not p.exists():
            return {"character": character, "records": []}
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, character: str, data: dict[str, Any]) -> None:
        with open(self._path(character), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def upsert(self, character: str, chunks: list[StoredChunk]) -> None:
        data = self._load(character)
        by_id = {r["id"]: r for r in data["records"]}
        for c in chunks:
            by_id[c.id] = {"id": c.id, "text": c.text, "metadata": c.metadata, "embedding": list(c.embedding or [])}
        data["records"] = list(by_id.values())
        self._save(character, data)

    def delete_character(self, character: str) -> None:
        p = self._path(character)
        if p.exists():
            p.unlink()

    def _matrix(self, records: list[dict]) -> np.ndarray:
        if not records:
            return np.zeros((0, 0), dtype=np.float32)
        return np.asarray([r["embedding"] for r in records], dtype=np.float32)

    def query(self, character: str, embedding: list[float], *, k: int,
              where: dict[str, Any] | None = None) -> list[QueryHit]:
        records = [r for r in self._load(character)["records"] if match_where(r["metadata"], where)]
        if not records:
            return []
        M = self._matrix(records)
        q = np.asarray(embedding, dtype=np.float32)
        qn = np.linalg.norm(q) or 1.0
        Mn = np.linalg.norm(M, axis=1)
        Mn[Mn == 0] = 1.0
        sims = (M @ q) / (Mn * qn)
        order = np.argsort(-sims)[:k]
        return [
            QueryHit(id=records[i]["id"], text=records[i]["text"],
                     metadata=records[i]["metadata"], score=float(sims[i]))
            for i in order
        ]

    def count(self, character: str, where: dict[str, Any] | None = None) -> int:
        return sum(1 for r in self._load(character)["records"] if match_where(r["metadata"], where))

    def get(self, character: str, *, ids: list[str] | None = None,
            where: dict[str, Any] | None = None) -> list[StoredChunk]:
        out = []
        idset = set(ids) if ids else None
        for r in self._load(character)["records"]:
            if idset is not None and r["id"] not in idset:
                continue
            if not match_where(r["metadata"], where):
                continue
            out.append(StoredChunk(id=r["id"], text=r["text"], metadata=r["metadata"], embedding=r["embedding"]))
        return out

    def list_characters(self) -> list[str]:
        out = []
        for p in sorted(self.root.glob(f"{self.prefix}*.json")):
            out.append(p.stem[len(self.prefix):])
        return out
