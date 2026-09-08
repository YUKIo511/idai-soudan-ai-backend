"""embed: chunks.jsonl → Embedding → Vector Store。rag_include=false は登録しない（#11）。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .build import load_chunks, chunks_path
from .models import Chunk, StoredChunk
from .embeddings import get_embedding_provider
from .vectorstore import get_vector_store


def _content_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def run_embed(slug: str, settings: Settings, reset: bool = True) -> dict:
    chunks = load_chunks(settings, slug)
    included = [c for c in chunks if c.rag_include]
    excluded = [c for c in chunks if not c.rag_include]

    emb = get_embedding_provider(settings)
    store = get_vector_store(settings)

    vectors = emb.embed_documents([c.text for c in included])
    stored = [
        StoredChunk(id=c.id, text=c.text, metadata=c.store_metadata(), embedding=v)
        for c, v in zip(included, vectors)
    ]
    if reset:
        store.delete_character(slug)
    store.upsert(slug, stored)

    # manifest.kb を更新
    mpath = settings.characters_dir / slug / "manifest.json"
    if mpath.exists():
        m = json.loads(mpath.read_text(encoding="utf-8"))
        m["kb"] = {
            "embedding_model": emb.describe(),
            "embedding_dim": emb.dim,
            "vectorstore": store.describe(),
            "chunk_count": len(stored),
            "rag_excluded": len(excluded),
            "last_built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "content_hash": _content_hash(chunks_path(settings, slug)),
        }
        mpath.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "embedded": len(stored),
        "rag_excluded": [c.id for c in excluded],
        "embedding": emb.describe(),
        "vectorstore": f"{store.describe()} :: {settings.collection_prefix}{slug}",
        "store_count": store.count(slug),
    }
