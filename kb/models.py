"""パイプライン共通のデータ構造。"""
from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

# ファイル種別 → チャンク type（表示・フィルタ用の短い名前）
CHUNK_TYPES = [
    "profile", "timeline", "achievement", "failure", "quote", "statement",
    "philosophy", "personality", "relationship", "episode", "work", "context", "criticism",
]

RELIABILITY_JP = {
    "primary": "一次資料",
    "secondary_reliable": "信頼できる二次資料",
    "common_knowledge": "周知の事実",
    "uncertain": "出典不確か",
    "legend": "伝説・逸話",
}

LIST_META_KEYS = ("themes", "people", "source_ids", "tags")


@dataclass
class RawEntry:
    """Indexer が JSON から取り出した1エントリ。"""
    character: str
    chunk_type: str            # CHUNK_TYPES のいずれか
    source_file: str           # 例: "characters/steve_jobs/quotes.json"
    entry_pointer: str         # 例: "/quotes/3" or "/summary"
    entry_id: str              # ファイル内 id（無い場合は pointer 由来の合成 id）
    data: dict[str, Any]       # エントリ本体
    parent: dict[str, Any] = field(default_factory=dict)  # profile/personality の親オブジェクト（sources 継承用）


@dataclass
class Chunk:
    """Embedding 前の中間表現。chunks.jsonl に1行1チャンクで保存。"""
    id: str                    # 例: "steve_jobs/quote/stay_hungry_stay_foolish"
    character: str
    type: str
    title: str
    text: str
    # トレーサビリティ（#14）
    source_file: str
    entry_id: str
    entry_pointer: str
    # 継承メタ（#4）— リストは list のまま保持
    reliability: str = "uncertain"
    confidence: float | None = None
    disputed: bool = False
    approx: bool = False
    rag_include: bool = True
    themes: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    # 型固有メタ
    date: str | None = None
    attribution_status: str | None = None   # quote
    authenticity: str | None = None         # episode
    domain: str | None = None               # philosophy / context

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json_line(line: str) -> "Chunk":
        return Chunk(**json.loads(line))

    def store_metadata(self) -> dict[str, Any]:
        """Vector Store 用のフラットなスカラー辞書（リストは '; ' 連結）。"""
        md: dict[str, Any] = {
            "character": self.character,
            "type": self.type,
            "title": self.title,
            "source_file": self.source_file,
            "entry_id": self.entry_id,
            "entry_pointer": self.entry_pointer,
            "reliability": self.reliability,
            "disputed": bool(self.disputed),
            "approx": bool(self.approx),
            "rag_include": bool(self.rag_include),
            "themes": "; ".join(self.themes),
            "people": "; ".join(self.people),
            "source_ids": "; ".join(self.source_ids),
            "tags": "; ".join(self.tags),
        }
        if self.confidence is not None:
            md["confidence"] = float(self.confidence)
        for k in ("date", "attribution_status", "authenticity", "domain"):
            v = getattr(self, k)
            if v is not None and v != "":
                md[k] = v
        return md


@dataclass
class StoredChunk:
    id: str
    text: str
    metadata: dict[str, Any]
    embedding: list[float] | None = None


@dataclass
class QueryHit:
    id: str
    text: str
    metadata: dict[str, Any]
    score: float               # 類似度（大きいほど近い）


def _split_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    if not v:
        return []
    return [s for s in str(v).split("; ") if s]


@dataclass
class RetrievedKnowledge:
    """検索で採用された1件。回答生成とデバッグ表示の両方で使う。"""
    chunk_id: str
    character: str
    type: str
    title: str
    text: str
    raw_score: float
    weighted_score: float
    reliability: str
    attribution_status: str | None
    authenticity: str | None
    disputed: bool
    themes: list[str]
    people: list[str]
    source_ids: list[str]
    source_file: str
    entry_id: str
    entry_pointer: str
    matched_by: list[str] = field(default_factory=list)  # どの展開クエリで引かれたか

    @staticmethod
    def from_hit(hit: QueryHit, raw: float, weighted: float, matched_by: list[str]) -> "RetrievedKnowledge":
        md = hit.metadata
        return RetrievedKnowledge(
            chunk_id=hit.id,
            character=md.get("character", ""),
            type=md.get("type", ""),
            title=md.get("title", ""),
            text=hit.text,
            raw_score=raw,
            weighted_score=weighted,
            reliability=md.get("reliability", "uncertain"),
            attribution_status=md.get("attribution_status"),
            authenticity=md.get("authenticity"),
            disputed=bool(md.get("disputed", False)),
            themes=_split_list(md.get("themes")),
            people=_split_list(md.get("people")),
            source_ids=_split_list(md.get("source_ids")),
            source_file=md.get("source_file", ""),
            entry_id=md.get("entry_id", ""),
            entry_pointer=md.get("entry_pointer", ""),
            matched_by=matched_by,
        )

    def ref(self) -> str:
        """人間可読な出典参照。"""
        f = self.source_file.split("/")[-1] if self.source_file else "?"
        src = ", ".join(self.source_ids) if self.source_ids else "出典未登録"
        return f"{f}#{self.entry_pointer} | 出典: {src}"


@dataclass
class RetrievalReport:
    """#15 デバッグ: 回答生成前に取得 Knowledge を確認する。"""
    character: str
    query: str
    filters: dict[str, Any]
    expanded_queries: list[str]
    kept: list[RetrievedKnowledge]
    dropped: list[tuple[RetrievedKnowledge, str]]   # フィルタで除外（themes/people/reliability）
    below_cutoff: list[RetrievedKnowledge] = field(default_factory=list)  # 検索されたが top-k 圏外
    pool_size: int = 0

    def to_text(self, width: int = 100, show_below: int = 8) -> str:
        L: list[str] = []
        L.append("=" * width)
        L.append(f"RETRIEVAL REPORT  character={self.character}")
        L.append(f"query   : {self.query}")
        L.append(f"filters : {json.dumps(self.filters, ensure_ascii=False)}")
        L.append(f"pool    : {self.pool_size} 件を検索 → フィルタ除外 {len(self.dropped)} / "
                 f"採用 {len(self.kept)} / 圏外 {len(self.below_cutoff)}")
        L.append(f"expanded queries ({len(self.expanded_queries)}):")
        for q in self.expanded_queries:
            L.append(f"    - {q}")
        L.append("-" * width)
        L.append(f"KEPT ({len(self.kept)}) — 回答に渡す Knowledge:")
        for i, k in enumerate(self.kept, 1):
            L.append(
                f"[{i:2d}] w={k.weighted_score:6.3f} raw={k.raw_score:6.3f}  "
                f"{k.type:11s} 信頼性={RELIABILITY_JP.get(k.reliability, k.reliability)}"
                + (f" 帰属={k.attribution_status}" if k.attribution_status else "")
                + (f" 史実性={k.authenticity}" if k.authenticity else "")
            )
            L.append(f"      title : {k.title}")
            L.append(f"      ref   : {k.ref()}")
            L.append(f"      by    : {', '.join(k.matched_by)}")
            L.append("      text  : " + textwrap.shorten(k.text.replace("\n", " "), width=width - 14))
        if self.dropped:
            L.append("-" * width)
            L.append(f"DROPPED — フィルタ除外 ({len(self.dropped)}):")
            for k, reason in self.dropped:
                L.append(f"  - [{reason}] {k.type} 「{k.title}」  ({k.ref()})")
        if self.below_cutoff:
            L.append("-" * width)
            L.append(f"BELOW CUTOFF — 検索されたが top-{len(self.kept)} 圏外 ({len(self.below_cutoff)}件、上位{min(show_below,len(self.below_cutoff))}件):")
            for k in self.below_cutoff[:show_below]:
                L.append(f"  - w={k.weighted_score:6.3f}  {k.type:11s} 「{k.title}」  ({k.ref()})")
        L.append("=" * width)
        return "\n".join(L)


@dataclass
class AnswerResult:
    character: str
    question: str
    answer: str
    report: RetrievalReport
    system_prompt: str
    user_prompt: str
    llm_provider: str
    llm_model: str
    timings: dict[str, Any] = field(default_factory=dict)  # retrieval_ms / prompt_build_ms / llm_ms / ...
