"""build: JSON → チャンク → characters/<slug>/knowledge/chunks.jsonl。"""
from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .indexer import Indexer
from .chunker import chunk_character
from .models import Chunk


def chunks_path(settings: Settings, slug: str) -> Path:
    return settings.characters_dir / slug / "knowledge" / "chunks.jsonl"


def run_build(slug: str, settings: Settings) -> list[Chunk]:
    idx = Indexer(settings.characters_dir)
    chunks = chunk_character(slug, idx)
    out = chunks_path(settings, slug)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(c.to_json_line() + "\n")
    return chunks


def load_chunks(settings: Settings, slug: str) -> list[Chunk]:
    p = chunks_path(settings, slug)
    if not p.exists():
        raise FileNotFoundError(f"chunks.jsonl が無い。先に build を実行: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return [Chunk.from_json_line(line) for line in f if line.strip()]


def build_summary(chunks: list[Chunk]) -> dict:
    by_type: dict[str, int] = {}
    excluded = 0
    for c in chunks:
        by_type[c.type] = by_type.get(c.type, 0) + 1
        if not c.rag_include:
            excluded += 1
    return {"total": len(chunks), "by_type": by_type, "rag_excluded": excluded}
