"""kb.Indexer から一覧・詳細を読み取り専用で組み立てる。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from kb.indexer import Indexer
from .schemas import (
    CharacterSummary, CharacterDetail, TimelineItem, AchievementItem,
    PhilosophyItem, QuoteItem,
)

# カテゴリー/職業キーワード → 絵文字（portrait 未設定時のフォールバック）
_ICONS = [
    ("科学", "🔬"), ("物理", "🔬"), ("数学", "📐"), ("発明", "💡"), ("技術", "⚙️"),
    ("テクノロジー", "💻"), ("プログラ", "💻"), ("起業", "🚀"), ("実業", "📈"), ("経営", "📈"),
    ("政治", "🏛️"), ("軍事", "⚔️"), ("哲学", "📜"), ("思想", "📜"), ("文学", "✍️"),
    ("作家", "✍️"), ("詩", "✍️"), ("画家", "🎨"), ("芸術", "🎨"), ("音楽", "🎼"),
    ("建築", "🏗️"), ("医学", "🩺"), ("宗教", "🕊️"), ("教育", "📚"), ("探検", "🧭"),
    ("スポーツ", "🏅"), ("映画", "🎬"), ("デザイン", "🎨"),
]
_DEFAULT_ICON = "🧠"


def _pick_icon(*texts: str) -> str:
    blob = " ".join(t for t in texts if t)
    for kw, emoji in _ICONS:
        if kw in blob:
            return emoji
    return _DEFAULT_ICON


def _ja(d: Any) -> str:
    if isinstance(d, dict):
        return d.get("ja") or d.get("en") or d.get("original") or ""
    return str(d or "")


def _load_index(indexer: Indexer) -> list[dict]:
    p = indexer.characters_dir / "index.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("characters", [])
        except Exception:
            pass
    # フォールバック: manifest を直接走査
    out = []
    for slug in indexer.list_characters():
        m = indexer.manifest(slug)
        out.append(m)
    return out


def _summary_from_index_row(row: dict) -> CharacterSummary:
    tags = row.get("tags") or []
    occ = row.get("occupations") or []
    kb = row.get("kb") or {}
    counts = row.get("counts") or {}
    kc = kb.get("chunk_count")
    if kc is None:
        kc = sum(v for v in counts.values() if isinstance(v, int))
    return CharacterSummary(
        slug=row["slug"],
        name=_ja(row.get("display_name")) or row["slug"],
        name_en=(row.get("display_name") or {}).get("en"),
        icon=_pick_icon(" ".join(tags), " ".join(occ), row.get("one_line", "")),
        portrait=row.get("portrait"),
        occupation=occ[0] if occ else "",
        categories=tags,
        one_line=row.get("one_line") or "",
        era=row.get("era") or "",
        birth_year=row.get("birth_year"),
        death_year=row.get("death_year"),
        status=row.get("status") or "draft",
        knowledge_count=int(kc or 0),
    )


def list_characters(indexer: Indexer) -> list[CharacterSummary]:
    rows = _load_index(indexer)
    items = [_summary_from_index_row(r) for r in rows if r.get("slug")]
    items.sort(key=lambda c: (c.status != "published", c.name))
    return items


def get_character_detail(indexer: Indexer, slug: str) -> CharacterDetail | None:
    if slug not in set(indexer.list_characters()):
        return None
    raw = indexer.load_raw(slug)
    prof = raw.get("profile.json", {})
    mani = raw.get("manifest.json", {})

    tags = mani.get("tags") or []
    occ = prof.get("occupations") or mani.get("occupations") or []
    name = _ja(prof.get("display_name")) or _ja(mani.get("display_name")) or slug

    # 生涯（代表的な出来事）
    phases_priority = {"turning_point": 0, "rise": 1, "peak": 1, "setback": 1, "death": 2}
    events = raw.get("timeline.json", {}).get("events", [])
    tl = [
        TimelineItem(
            year=e.get("date"), age=e.get("age"),
            title=e.get("title", ""),
            summary=(e.get("event") or "")[:200],
        )
        for e in events
    ][:12]

    ach = [
        AchievementItem(title=a.get("title", ""), summary=(a.get("what") or "")[:200], year=a.get("year"))
        for a in raw.get("achievements.json", {}).get("achievements", [])
    ][:8]

    phil = [
        PhilosophyItem(domain=v.get("domain", ""), title=v.get("title", ""), view=(v.get("view") or "")[:240])
        for v in raw.get("philosophy.json", {}).get("views", [])
    ][:10]

    quotes = []
    for q in raw.get("quotes.json", {}).get("quotes", []):
        if q.get("attribution_status") not in ("verified", "likely"):
            continue  # 本人発言と確認/推定できるもののみ詳細に出す
        t = q.get("text", {})
        quotes.append(QuoteItem(
            text=_ja(t), original=(t.get("original") if isinstance(t, dict) else None),
            context=(q.get("context") or q.get("background") or "")[:160],
            attribution_status=q["attribution_status"],
            source_ids=[s.get("source_id") for s in q.get("sources", []) if s.get("source_id")],
        ))
    quotes = quotes[:10]

    ss = prof.get("speaking_style", {}) or {}
    base = _summary_from_index_row({
        "slug": slug, "display_name": prof.get("display_name") or mani.get("display_name"),
        "tags": tags, "occupations": occ, "one_line": prof.get("one_line") or mani.get("one_line"),
        "era": prof.get("era") or mani.get("era"),
        "birth_year": (prof.get("birth") or {}).get("date") or mani.get("birth_year"),
        "death_year": (prof.get("death") or {}).get("date") or mani.get("death_year"),
        "status": mani.get("status"), "portrait": mani.get("portrait"),
        "kb": mani.get("kb"), "counts": mani.get("counts"),
    })

    return CharacterDetail(
        **base.model_dump(),
        intro=prof.get("summary", ""),
        real_name=_ja(prof.get("real_name")) or None,
        nationality=prof.get("nationality") or [],
        titles=prof.get("titles") or [],
        speaking_style_note=" / ".join(x for x in [ss.get("tone"), ss.get("caveats")] if x),
        timeline=tl, achievements=ach, philosophy=phil, quotes=quotes,
        sources_count=len(raw.get("sources.json", {}).get("sources", [])),
    )
