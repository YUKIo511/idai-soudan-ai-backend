"""Indexer: characters/<slug>/*.json を Source of Truth として読み込み、エントリを列挙する（#1, #2）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from .models import RawEntry

# ファイル名 → (chunk_type, 配列キー)。配列キーが None のオブジェクト型は _iter_object_file で個別処理。
ARRAY_FILES: dict[str, tuple[str, str]] = {
    "timeline.json": ("timeline", "events"),
    "achievements.json": ("achievement", "achievements"),
    "failures.json": ("failure", "failures"),
    "quotes.json": ("quote", "quotes"),
    "statements.json": ("statement", "statements"),
    "philosophy.json": ("philosophy", "views"),
    "relationships.json": ("relationship", "people"),
    "episodes.json": ("episode", "episodes"),
    "works.json": ("work", "works"),
    "historical_context.json": ("context", "contexts"),
    "criticisms.json": ("criticism", "items"),
}
OBJECT_FILES = ("profile.json", "personality.json")
ALL_DATA_FILES = tuple(ARRAY_FILES) + OBJECT_FILES + ("sources.json", "manifest.json")


class Indexer:
    def __init__(self, characters_dir: Path):
        self.characters_dir = Path(characters_dir)

    # ---- 一覧 ----
    def list_characters(self) -> list[str]:
        out = []
        for d in sorted(self.characters_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("_") and (d / "manifest.json").exists():
                out.append(d.name)
        return out

    def char_dir(self, slug: str) -> Path:
        return self.characters_dir / slug

    # ---- 生データ ----
    def load_raw(self, slug: str) -> dict[str, Any]:
        d = self.char_dir(slug)
        if not d.is_dir():
            raise FileNotFoundError(f"偉人ディレクトリが無い: {d}")
        raw: dict[str, Any] = {}
        for name in ALL_DATA_FILES:
            p = d / name
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    raw[name] = json.load(f)
        return raw

    def manifest(self, slug: str) -> dict[str, Any]:
        return self.load_raw(slug).get("manifest.json", {})

    # ---- エントリ列挙 ----
    def iter_entries(self, slug: str, raw: dict[str, Any] | None = None) -> Iterator[RawEntry]:
        raw = raw if raw is not None else self.load_raw(slug)
        rel_base = f"{self.characters_dir.name}/{slug}"

        for fname, (ctype, key) in ARRAY_FILES.items():
            doc = raw.get(fname)
            if not doc:
                continue
            arr = doc.get(key, [])
            for i, entry in enumerate(arr):
                eid = str(entry.get("id") or f"{ctype}_{i}")
                yield RawEntry(
                    character=slug, chunk_type=ctype,
                    source_file=f"{rel_base}/{fname}",
                    entry_pointer=f"/{key}/{i}",
                    entry_id=eid, data=entry,
                )

        # profile.json（オブジェクト）→ summary / identity / speaking_style
        prof = raw.get("profile.json")
        if prof:
            for sub in ("summary", "identity", "speaking_style"):
                yield RawEntry(
                    character=slug, chunk_type="profile",
                    source_file=f"{rel_base}/profile.json",
                    entry_pointer=f"/{sub}",
                    entry_id=f"profile_{sub}", data=prof, parent=prof,
                )

        # personality.json（オブジェクト）→ traits[] 個別 + summary
        pers = raw.get("personality.json")
        if pers:
            for i, tr in enumerate(pers.get("traits", [])):
                eid = str(tr.get("id") or f"trait_{i}")
                yield RawEntry(
                    character=slug, chunk_type="personality",
                    source_file=f"{rel_base}/personality.json",
                    entry_pointer=f"/traits/{i}",
                    entry_id=eid, data=tr, parent=pers,
                )
            yield RawEntry(
                character=slug, chunk_type="personality",
                source_file=f"{rel_base}/personality.json",
                entry_pointer="/summary",
                entry_id="personality_summary", data=pers, parent=pers,
            )

    # ---- 回答用の人格バンドル ----
    def persona_bundle(self, slug: str, raw: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = raw if raw is not None else self.load_raw(slug)
        prof = raw.get("profile.json", {})
        pers = raw.get("personality.json", {})
        phil = raw.get("philosophy.json", {})
        mani = raw.get("manifest.json", {})
        return {
            "slug": slug,
            "display_name": prof.get("display_name", {}) or mani.get("display_name", {}),
            "one_line": prof.get("one_line") or mani.get("one_line", ""),
            "summary": prof.get("summary", ""),
            "speaking_style": prof.get("speaking_style", {}),
            "personality_summary": pers.get("summary", {}),
            "personality_caveats": pers.get("caveats", ""),
            "personality_traits": pers.get("traits", []),
            "philosophy_views": phil.get("views", []),
            "era": prof.get("era", ""),
            "occupations": prof.get("occupations", []),
        }
