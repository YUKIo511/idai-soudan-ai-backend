"""Vector Store の抽象（#6, #8, #9）。

- character を第一級引数にして偉人ごとに Knowledge Base を分離（#9）。
- where は最小の共通 DSL:
    {"key": value}                完全一致
    {"key": {"in": [...]}}        いずれかに一致
    {"key": {"nin": [...]}}       いずれにも一致しない
    {"key": {"ne": value}}        不一致
  複数キーは AND。リスト要素の部分一致（themes/people）はここでは扱わず retrieve 層で行う。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import StoredChunk, QueryHit


def match_where(md: dict[str, Any], where: dict[str, Any] | None) -> bool:
    """Python 側での where 評価（memory ストア／post-filter 共用）。"""
    if not where:
        return True
    for key, cond in where.items():
        v = md.get(key)
        if isinstance(cond, dict):
            if "in" in cond and v not in cond["in"]:
                return False
            if "nin" in cond and v in cond["nin"]:
                return False
            if "ne" in cond and v == cond["ne"]:
                return False
        else:
            if v != cond:
                return False
    return True


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, character: str, chunks: list[StoredChunk]) -> None: ...

    @abstractmethod
    def delete_character(self, character: str) -> None: ...

    @abstractmethod
    def query(self, character: str, embedding: list[float], *, k: int,
              where: dict[str, Any] | None = None) -> list[QueryHit]: ...

    @abstractmethod
    def count(self, character: str, where: dict[str, Any] | None = None) -> int: ...

    @abstractmethod
    def get(self, character: str, *, ids: list[str] | None = None,
            where: dict[str, Any] | None = None) -> list[StoredChunk]: ...

    @abstractmethod
    def list_characters(self) -> list[str]: ...

    def describe(self) -> str:
        return self.__class__.__name__
