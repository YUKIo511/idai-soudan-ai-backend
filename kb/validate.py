"""JSON Schema 検証 + 参照整合チェック（source_id / *_id）。"""
from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .indexer import Indexer, ARRAY_FILES

_FILE_TO_SCHEMA = {
    "profile.json": "profile.schema.json",
    "sources.json": "sources.schema.json",
    "timeline.json": "timeline.schema.json",
    "achievements.json": "achievements.schema.json",
    "failures.json": "failures.schema.json",
    "quotes.json": "quotes.schema.json",
    "statements.json": "statements.schema.json",
    "philosophy.json": "philosophy.schema.json",
    "personality.json": "personality.schema.json",
    "relationships.json": "relationships.schema.json",
    "episodes.json": "episodes.schema.json",
    "works.json": "works.schema.json",
    "historical_context.json": "historical_context.schema.json",
    "criticisms.json": "criticisms.schema.json",
    "manifest.json": "manifest.schema.json",
}


def _load_registry(schemas_dir: Path):
    from referencing import Registry, Resource
    resources = []
    for p in schemas_dir.glob("*.json"):
        resources.append((p.name, Resource.from_contents(json.loads(p.read_text(encoding="utf-8")))))
    return Registry().with_resources(resources)


def validate_character(slug: str, settings: Settings) -> list[str]:
    """問題点のリストを返す（空なら OK）。"""
    problems: list[str] = []
    idx = Indexer(settings.characters_dir)
    cdir = idx.char_dir(slug)
    if not cdir.is_dir():
        return [f"ディレクトリが無い: {cdir}"]

    # --- スキーマ検証 ---
    try:
        from jsonschema import Draft202012Validator
        reg = _load_registry(settings.schemas_dir)
        schemas = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in settings.schemas_dir.glob("*.json")}
        for fname, sname in _FILE_TO_SCHEMA.items():
            fp = cdir / fname
            if not fp.exists():
                continue
            data = json.loads(fp.read_text(encoding="utf-8"))
            v = Draft202012Validator(schemas[sname], registry=reg)
            for err in sorted(v.iter_errors(data), key=lambda e: list(e.path)):
                loc = "/".join(str(x) for x in err.path)
                problems.append(f"[schema] {fname}:{loc}: {err.message}")
    except ImportError:
        problems.append("[warn] jsonschema/referencing 未導入のためスキーマ検証をスキップ")

    # --- 参照整合 ---
    raw = idx.load_raw(slug)
    source_ids = {s["id"] for s in raw.get("sources.json", {}).get("sources", [])}
    quote_ids = {q.get("id") for q in raw.get("quotes.json", {}).get("quotes", [])}
    episode_ids = {e.get("id") for e in raw.get("episodes.json", {}).get("episodes", [])}
    work_ids = {w.get("id") for w in raw.get("works.json", {}).get("works", [])}

    def check_sources(holder: dict, where: str):
        for s in holder.get("sources", []) or []:
            sid = s.get("source_id")
            if sid and sid not in source_ids:
                problems.append(f"[ref] {where}: 未登録の source_id '{sid}'")
        if holder.get("reliability") == "primary" and not holder.get("sources"):
            problems.append(f"[ref] {where}: reliability=primary だが sources が空")

    for fname, (_ctype, key) in ARRAY_FILES.items():
        for i, e in enumerate(raw.get(fname, {}).get(key, [])):
            where = f"{fname}/{key}/{i}"
            check_sources(e, where)
            for qid in e.get("quote_ids", []) or []:
                if qid not in quote_ids:
                    problems.append(f"[ref] {where}: 未登録の quote_id '{qid}'")
            for eid in e.get("episode_ids", []) or []:
                if eid not in episode_ids:
                    problems.append(f"[ref] {where}: 未登録の episode_id '{eid}'")
            for wid in e.get("work_ids", []) or []:
                if wid not in work_ids:
                    problems.append(f"[ref] {where}: 未登録の work_id '{wid}'")
            if fname == "quotes.json" and not e.get("attribution_status"):
                problems.append(f"[ref] {where}: 名言に attribution_status が無い")

    for tr in raw.get("personality.json", {}).get("traits", []):
        check_sources(tr, f"personality.json/traits/{tr.get('id')}")

    return problems
