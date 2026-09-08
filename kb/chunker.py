"""Chunker: RawEntry を Chunk（自然文 + 継承メタ）へ変換する（#3, #4）。"""
from __future__ import annotations

import re
from typing import Any, Iterable

from .models import Chunk
from .indexer import Indexer

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _slug(s: str) -> str:
    return _SLUG_RE.sub("_", str(s).lower()).strip("_") or "x"


def _lt(v: Any) -> str:
    """localizedText → 表示用文字列。"""
    if isinstance(v, dict):
        return v.get("ja") or v.get("en") or v.get("original") or ""
    return str(v or "")


def _join(pairs: Iterable[tuple[str, Any]], sep: str = "\n") -> str:
    out = []
    for label, val in pairs:
        if val is None:
            continue
        if isinstance(val, (list, tuple)):
            val = "、".join(str(x) for x in val if x)
        val = str(val).strip()
        if not val:
            continue
        out.append(f"{label}: {val}" if label else val)
    return sep.join(out)


def _source_ids(entry: dict[str, Any], parent: dict[str, Any] | None = None) -> list[str]:
    ids: list[str] = []
    for holder in (entry, parent or {}):
        for s in holder.get("sources", []) or []:
            sid = s.get("source_id") if isinstance(s, dict) else None
            if sid and sid not in ids:
                ids.append(sid)
    return ids


def _apply_meta(chunk: Chunk, entry: dict[str, Any], parent: dict[str, Any] | None = None) -> Chunk:
    """entryMeta を chunk へ継承（#4）。"""
    chunk.reliability = entry.get("reliability") or chunk.reliability
    if entry.get("confidence") is not None:
        chunk.confidence = float(entry["confidence"])
    chunk.disputed = bool(entry.get("disputed", False))
    chunk.approx = bool(entry.get("approx", False))
    chunk.rag_include = bool(entry.get("rag_include", True))
    chunk.themes = list(entry.get("themes", []) or [])
    chunk.people = list(entry.get("people", []) or [])
    chunk.tags = list(entry.get("tags", []) or [])
    chunk.source_ids = _source_ids(entry, parent)
    return chunk


# ---------------- 型別レンダラ ----------------
# それぞれ (title, body) を返す。

def _r_profile(sub: str, prof: dict, name: str):
    if sub == "summary":
        return "人物概要", prof.get("summary", "")
    if sub == "speaking_style":
        ss = prof.get("speaking_style", {})
        return "話し方・語り口", _join([
            ("言語", ss.get("language")), ("文体", ss.get("register")), ("トーン", ss.get("tone")),
            ("特徴", ss.get("traits")), ("口ぶりの例", ss.get("example_phrases")),
            ("史料上の注意", ss.get("caveats")),
        ])
    # identity
    edu = "；".join(
        _join([("", e.get("institution")), ("専攻", e.get("field")),
               ("修了", "はい" if e.get("completed") else "いいえ" if e.get("completed") is not None else None)], sep=" ")
        for e in prof.get("education", [])
    )
    fam = "；".join(f"{f.get('relation','')}={f.get('name','')}" for f in prof.get("family", []))
    return "基本プロフィール", _join([
        ("本名", _lt(prof.get("real_name"))), ("別名", prof.get("aliases")), ("愛称", prof.get("nicknames")),
        ("生", _join([("", (prof.get("birth") or {}).get("date")), ("", (prof.get("birth") or {}).get("place"))], sep=" ")),
        ("没", _join([("", (prof.get("death") or {}).get("date")), ("", (prof.get("death") or {}).get("place")),
                      ("死因", (prof.get("death") or {}).get("cause"))], sep=" ")),
        ("国籍", prof.get("nationality")), ("時代", prof.get("era")),
        ("職業", prof.get("occupations")), ("肩書き", prof.get("titles")),
        ("学歴", edu), ("家族", fam),
        ("師", prof.get("mentors")), ("弟子", prof.get("students")),
        ("主な活動地", prof.get("main_regions")),
    ])


def _r_timeline(e: dict, name: str):
    age = f"{e['age']}歳" if e.get("age") is not None else None
    head = _join([("", e.get("date")), ("", age), ("", e.get("phase")), ("", e.get("place"))], sep=" ")
    body = _join([
        ("", head), ("出来事", e.get("event")), ("背景", e.get("background")), ("原因", e.get("cause")),
        ("本人の行動", e.get("his_action")), ("本人の発言", e.get("his_words")),
        ("結果", e.get("result")), ("関係人物", e.get("related_people")),
        ("歴史的意味", e.get("historical_significance")),
    ])
    return e.get("title", "年表"), body


def _r_achievement(e: dict, name: str):
    yr = e.get("year") or _range(e.get("year_range"))
    body = _join([
        ("時期", yr), ("場所", e.get("place")),
        ("何を", e.get("what")), ("なぜ", e.get("why")), ("どうやって", e.get("how")),
        ("難しさ", e.get("difficulties")), ("結果", e.get("outcome")),
        ("当時の影響", e.get("impact_contemporary")), ("後世への影響", e.get("impact_legacy")),
        ("協力者", e.get("collaborators")),
    ])
    return e.get("title", "業績"), body


def _r_failure(e: dict, name: str):
    yr = e.get("year") or _range(e.get("year_range"))
    body = _join([
        ("時期", yr), ("分類", e.get("category")),
        ("何が起きたか", e.get("what_happened")), ("背景", e.get("context")),
        ("本人の関与・判断", e.get("his_role")), ("批判", e.get("criticism")),
        ("帰結・代償", e.get("consequence")), ("立て直し", e.get("recovery")),
        ("教訓", e.get("lesson")), ("関係人物", e.get("related_people")),
    ])
    return e.get("title", "失敗・挫折"), body


def _r_quote(e: dict, name: str):
    t = e.get("text", {})
    body = _join([
        ("言葉", f"「{_lt(t)}」"),
        ("原文", t.get("original") if isinstance(t, dict) else None),
        ("帰属状態", e.get("attribution_status")),
        ("いつ・どこで", _join([("", e.get("said_on")), ("", e.get("said_at"))], sep=" ")),
        ("相手", e.get("audience")), ("状況", e.get("context")), ("背景", e.get("background")),
        ("初出", e.get("first_appearance")),
        ("意味", e.get("meaning")), ("思想との関係", e.get("relation_to_thought")),
    ])
    return _lt(t)[:40] or "名言", body


def _r_statement(e: dict, name: str):
    body = _join([
        ("種別", e.get("type")), ("日付", e.get("date")), ("場所", e.get("place")),
        ("聴衆・宛先", e.get("audience")), ("媒体", e.get("medium")),
        ("要旨", e.get("summary")), ("抜粋", e.get("excerpt")), ("訳", e.get("translation")),
        ("トピック", e.get("topics")),
    ])
    return e.get("title", "発言・文章"), body


def _r_philosophy(e: dict, name: str):
    body = _join([
        ("領域", e.get("domain")),
        ("考え", e.get("view")), ("詳細", e.get("elaboration")), ("根拠", e.get("evidence")),
        ("矛盾・例外", e.get("tensions")), ("変遷", e.get("evolution")),
    ])
    return e.get("title") or f"{e.get('domain','')}についての考え", body


def _r_personality_trait(e: dict, name: str):
    body = _join([
        ("極性", e.get("polarity")), ("説明", e.get("description")), ("根拠", e.get("evidence")),
    ])
    return f"人格特性: {e.get('trait','')}", body


def _r_personality_summary(pers: dict, name: str):
    s = pers.get("summary", {})
    body = _join([
        ("強み", s.get("strengths")), ("弱み", s.get("weaknesses")),
        ("思考パターン", s.get("thinking_pattern")), ("意思決定", s.get("decision_making")),
        ("怒るポイント", s.get("anger_triggers")), ("喜ぶポイント", s.get("joy_triggers")),
        ("部下への接し方", s.get("with_subordinates")), ("上司への接し方", s.get("with_superiors")),
        ("ライバルへの接し方", s.get("with_rivals")), ("対人一般", s.get("interpersonal_general")),
        ("プレッシャー下", s.get("under_pressure")), ("困難への対応", s.get("facing_difficulty")),
        ("リスクの取り方", s.get("risk_taking")),
        ("史料上の注意", pers.get("caveats")),
    ])
    return "人格サマリー", body


def _r_relationship(e: dict, name: str):
    ke = "；".join(
        _join([("", k.get("date")), ("", k.get("event")), ("→", k.get("outcome"))], sep=" ")
        for k in e.get("key_events", [])
    )
    body = _join([
        ("相手", _lt(e.get("name"))), ("関係", _join([("", e.get("relation_type")), ("", e.get("relation_label"))], sep=" ")),
        ("時期", _range(e.get("period"))), ("出会い", e.get("how_they_met")),
        ("関係の力学", e.get("dynamic")), ("主な出来事", ke),
        ("相手が本人に与えた影響", e.get("influence_on_subject")),
        ("本人が相手に与えた影響", e.get("influence_on_other")),
    ])
    return f"人間関係: {_lt(e.get('name'))}", body


def _r_episode(e: dict, name: str):
    body = _join([
        ("いつ・どこ", _join([("", e.get("date")), ("", e.get("place"))], sep=" ")),
        ("登場人物", e.get("people_involved")),
        ("起きたこと", e.get("what_happened")), ("背景", e.get("background")),
        ("本人の行動", e.get("his_action")), ("本人の発言", e.get("his_words")),
        ("結果", e.get("result")), ("分かる価値観", e.get("values_revealed")),
        ("歴史的評価", e.get("historical_assessment")), ("史実性", e.get("authenticity")),
    ])
    return e.get("title", "エピソード"), body


def _r_work(e: dict, name: str):
    rc = e.get("reception", {}) or {}
    body = _join([
        ("種別", e.get("type")), ("年", e.get("year") or _range(e.get("year_range"))),
        ("内容", e.get("description")), ("背景", e.get("context")), ("目的", e.get("purpose")),
        ("協力者", e.get("collaborators")), ("影響", e.get("impact")),
        ("当時の評価", rc.get("contemporary")), ("現代の評価", rc.get("modern")),
    ])
    return f"作品: {_lt(e.get('title'))}", body


def _r_context(e: dict, name: str):
    body = _join([
        ("領域", e.get("domain")), ("地域", e.get("region")), ("時期", _range(e.get("period"))),
        ("概要", e.get("summary")),
        ("本人との関わり", e.get("relevance_to_subject")),
        ("現代との違い", e.get("contrast_with_today")),
    ])
    return e.get("title") or f"時代背景: {e.get('domain','')}", body


def _r_criticism(e: dict, name: str):
    body = _join([
        ("種別", e.get("kind")), ("主張", e.get("claim")), ("論者", e.get("by_whom")),
        ("時期", e.get("when")), ("根拠", e.get("basis")), ("反論・擁護", e.get("rebuttal")),
        ("位置づけ", e.get("status")), ("意義", e.get("significance")),
    ])
    return e.get("title") or "評価・批判", body


def _range(r: dict | None) -> str | None:
    if not r:
        return None
    a, b = r.get("start"), r.get("end")
    if a and b:
        return f"{a}〜{b}"
    return a or b or None


# ---------------- メイン ----------------

def chunk_character(slug: str, indexer: Indexer, raw: dict[str, Any] | None = None) -> list[Chunk]:
    raw = raw if raw is not None else indexer.load_raw(slug)
    persona = indexer.persona_bundle(slug, raw)
    name = _lt(persona["display_name"]) or slug
    chunks: list[Chunk] = []

    for re_ in indexer.iter_entries(slug, raw):
        e, ct = re_.data, re_.chunk_type
        title = body = None
        domain = None

        if ct == "profile":
            sub = re_.entry_pointer.strip("/")
            title, body = _r_profile(sub, e, name)
        elif ct == "timeline":
            title, body = _r_timeline(e, name)
        elif ct == "achievement":
            title, body = _r_achievement(e, name)
        elif ct == "failure":
            title, body = _r_failure(e, name)
        elif ct == "quote":
            title, body = _r_quote(e, name)
        elif ct == "statement":
            title, body = _r_statement(e, name)
        elif ct == "philosophy":
            title, body = _r_philosophy(e, name)
            domain = e.get("domain")
        elif ct == "personality":
            if re_.entry_pointer == "/summary":
                title, body = _r_personality_summary(e, name)
            else:
                title, body = _r_personality_trait(e, name)
        elif ct == "relationship":
            title, body = _r_relationship(e, name)
        elif ct == "episode":
            title, body = _r_episode(e, name)
        elif ct == "work":
            title, body = _r_work(e, name)
        elif ct == "context":
            title, body = _r_context(e, name)
            domain = e.get("domain")
        elif ct == "criticism":
            title, body = _r_criticism(e, name)
        else:
            continue

        if not body:
            continue

        cid = f"{slug}/{ct}/{_slug(re_.entry_id)}"
        text = f"【{_TYPE_LABEL.get(ct, ct)}】{name} — {title}\n{body}"
        chunk = Chunk(
            id=cid, character=slug, type=ct, title=title, text=text,
            source_file=re_.source_file, entry_id=re_.entry_id, entry_pointer=re_.entry_pointer,
        )
        # メタ継承（profile は親から sources、personality trait はエントリ自身から）
        if ct == "profile" or (ct == "personality" and re_.entry_pointer == "/summary"):
            chunk.reliability = "secondary_reliable"
            chunk.rag_include = True
            chunk.source_ids = _source_ids({}, re_.parent)
        else:
            _apply_meta(chunk, e, re_.parent)

        chunk.date = e.get("date") or e.get("said_on") or e.get("when") or None
        chunk.attribution_status = e.get("attribution_status")
        chunk.authenticity = e.get("authenticity")
        chunk.domain = domain
        chunks.append(chunk)

    return chunks


_TYPE_LABEL = {
    "profile": "プロフィール", "timeline": "年表", "achievement": "業績", "failure": "失敗・挫折",
    "quote": "名言", "statement": "発言・文章", "philosophy": "思想", "personality": "人格",
    "relationship": "人間関係", "episode": "エピソード", "work": "作品", "context": "時代背景",
    "criticism": "評価・批判",
}
