"""retrieve: 相談文 → 偉人分離・フィルタ・多観点検索・信頼性重み → RetrievalReport。

要件対応:
  #9  character ごとに分離した Vector Store を引く
  #10 themes / people / reliability / type でフィルタ
  #11 rag_include=false は常に除外（store 側 + ここでも二重に）
  #12 uncertain / legend は reliability_weights で減衰（drop で完全除外可）
  #13 quote は attribution_status、episode は authenticity で減衰
  #14 取得元ファイル・エントリを RetrievedKnowledge に保持
  #15 採用/除外理由・展開クエリを RetrievalReport で確認
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings
from .models import QueryHit, RetrievedKnowledge, RetrievalReport
from .embeddings import get_embedding_provider, EmbeddingProvider
from .vectorstore import get_vector_store, VectorStore
from .vectorstore.base import match_where

# 多観点クエリ: (ラベル, 付加キーワード, type フィルタ)
_ASPECTS: list[tuple[str, str, list[str] | None]] = [
    ("baseline", "", None),
    ("人生経験", "人生 経験 転機 若い頃", ["timeline", "episode"]),
    ("失敗", "失敗 挫折 判断ミス 後悔 教訓", ["failure"]),
    ("思想", "考え方 価値観 信条 哲学", ["philosophy"]),
    ("実績", "業績 成果 成し遂げた", ["achievement", "work"]),
    ("名言", "言葉 名言 発言", ["quote", "statement"]),
    ("人間関係", "人間関係 仲間 対立 師 弟子", ["relationship"]),
    ("人格", "性格 気質 意思決定", ["personality"]),
    ("時代背景", "時代 当時 社会 常識", ["context"]),
]


@dataclass
class RetrievalConfig:
    k: int = 6
    over_fetch: int = 5
    multi_query: bool = True
    reliability_weights: dict[str, float] = None
    drop_reliability: list[str] = None
    quote_attribution_weights: dict[str, float] = None
    episode_authenticity_weights: dict[str, float] = None

    @staticmethod
    def from_settings(s: Settings) -> "RetrievalConfig":
        r = s.retrieval
        return RetrievalConfig(
            k=r.get("k", 6),
            over_fetch=r.get("over_fetch", 5),
            multi_query=r.get("multi_query", True),
            reliability_weights=r.get("reliability_weights", {}),
            drop_reliability=r.get("drop_reliability", []) or [],
            quote_attribution_weights=r.get("quote_attribution_weights", {}),
            episode_authenticity_weights=r.get("episode_authenticity_weights", {}),
        )


class Retriever:
    def __init__(self, settings: Settings,
                 emb: EmbeddingProvider | None = None,
                 store: VectorStore | None = None):
        self.settings = settings
        self.cfg = RetrievalConfig.from_settings(settings)
        self.emb = emb or get_embedding_provider(settings)
        self.store = store or get_vector_store(settings)

    # ---- 重み ----
    def _weight(self, md: dict[str, Any]) -> float:
        w = float(self.cfg.reliability_weights.get(md.get("reliability", ""), 0.7))
        if md.get("type") == "quote" and md.get("attribution_status"):
            w *= float(self.cfg.quote_attribution_weights.get(md["attribution_status"], 0.5))
        if md.get("type") == "episode" and md.get("authenticity"):
            w *= float(self.cfg.episode_authenticity_weights.get(md["authenticity"], 0.8))
        return w

    def retrieve(self, character: str, query: str, *,
                 k: int | None = None,
                 themes: list[str] | None = None,
                 people: list[str] | None = None,
                 reliability: list[str] | None = None,
                 types: list[str] | None = None,
                 multi_query: bool | None = None) -> RetrievalReport:
        k = k or self.cfg.k
        mq = self.cfg.multi_query if multi_query is None else multi_query
        fetch = max(k * self.cfg.over_fetch, k + 5)

        # store ネイティブ where（#10, #11, #12 の一部）
        base_where: dict[str, Any] = {"rag_include": True}
        drop = list(self.cfg.drop_reliability)
        if reliability:
            base_where["reliability"] = {"in": list(reliability)}
        elif drop:
            base_where["reliability"] = {"nin": drop}
        if types:
            base_where["type"] = {"in": list(types)}

        aspects = _ASPECTS if mq else [("baseline", "", None)]
        expanded: list[str] = []
        pool: dict[str, tuple[QueryHit, list[str]]] = {}

        for label, kw, atypes in aspects:
            if types and atypes and not (set(types) & set(atypes)):
                continue
            sub_where = dict(base_where)
            if atypes and not types:
                sub_where["type"] = {"in": atypes}
            q = query if not kw else f"{query} / {kw}"
            expanded.append(f"[{label}] {q}")
            vec = self.emb.embed_query(q)
            for hit in self.store.query(character, vec, k=fetch, where=sub_where):
                if hit.id in pool:
                    prev_hit, labels = pool[hit.id]
                    if hit.score > prev_hit.score:
                        pool[hit.id] = (hit, labels)
                    if label not in labels:
                        labels.append(label)
                else:
                    pool[hit.id] = (hit, [label])

        # RetrievedKnowledge 化 + 重み付け
        items: list[RetrievedKnowledge] = []
        for hit, labels in pool.values():
            w = self._weight(hit.metadata)
            items.append(RetrievedKnowledge.from_hit(hit, raw=hit.score, weighted=hit.score * w, matched_by=labels))

        # Python 側 post-filter（#10: themes / people、#11 念のため）
        passed: list[RetrievedKnowledge] = []
        dropped: list[tuple[RetrievedKnowledge, str]] = []
        tset = set(themes or [])
        pset = set(people or [])
        for it in sorted(items, key=lambda x: -x.weighted_score):
            if tset and not (tset & set(it.themes)):
                dropped.append((it, f"themes 不一致 {sorted(tset)}"))
                continue
            if pset and not (pset & set(it.people)):
                dropped.append((it, f"people 不一致 {sorted(pset)}"))
                continue
            if it.reliability in drop:
                dropped.append((it, f"drop_reliability={drop}"))
                continue
            passed.append(it)

        kept = passed[:k]
        below = passed[k:]

        return RetrievalReport(
            character=character, query=query,
            filters={"themes": themes, "people": people, "reliability": reliability,
                     "types": types, "multi_query": mq, "k": k,
                     "store_where": base_where},
            expanded_queries=expanded, kept=kept, dropped=dropped,
            below_cutoff=below, pool_size=len(items),
        )
