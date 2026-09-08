"""オフライン用 LLM: 実際の生成はせず、組み立てられたプロンプトと採用 Knowledge を可視化する。

パイプライン（検索→人格適用→生成）の流れを API キー無しで確認するためのもの。
本番は anthropic / openai プロバイダへ config で切替。
"""
from __future__ import annotations

import re
from typing import Iterator

from .base import LLMProvider, LLMMessage


class FakeLLMProvider(LLMProvider):
    name = "fake"
    model = "echo"

    def chat(self, system: str, messages: list[LLMMessage], *,
             temperature: float = 0.7, max_tokens: int = 1200) -> str:
        question = messages[-1].content if messages else ""
        persona = _between(system, "<persona>", "</persona>")
        rules = _between(system, "<rules>", "</rules>")
        knowledge = _between(system, "<knowledge>", "</knowledge>")
        k_titles = re.findall(r"^\[K\d+\][^\n]*", knowledge, flags=re.M)
        name_m = re.search(r"あなたは(.+?)として", system)
        name = name_m.group(1) if name_m else "この偉人"

        lines = [
            "【FAKE LLM 出力 — 実際の文章生成は行っていません】",
            "",
            f"■ 応答する人物: {name}",
            f"■ 受け取った相談: {question}",
            "",
            f"■ 適用する人格・話し方（抜粋）:\n{_head(persona, 6)}",
            "",
            f"■ 回答に使う Knowledge（{len(k_titles)}件、信頼性・帰属を考慮した順）:",
            *[f"   {t}" for t in k_titles[:12]],
            "",
            "■ 遵守する回答ルール:",
            _head(rules, 8),
            "",
            "■ 本番プロバイダ（anthropic / openai）ではここに、",
            "   上記 Knowledge を根拠に、人格・思想・語り口を反映した相談への回答が入ります。",
        ]
        return "\n".join(lines)

    def stream_chat(self, system: str, messages: list[LLMMessage], *,
                    temperature: float = 0.7, max_tokens: int = 1200,
                    stats: dict | None = None) -> Iterator[str]:  # stats は未使用（互換のため受け取る）
        text = self.chat(system, messages, temperature=temperature, max_tokens=max_tokens)
        # 行単位で分割し、ストリーミングを模倣
        buf = ""
        for ch in text:
            buf += ch
            if ch == "\n" or len(buf) >= 24:
                yield buf
                buf = ""
        if buf:
            yield buf


def _between(s: str, a: str, b: str) -> str:
    i, j = s.find(a), s.find(b)
    return s[i + len(a):j].strip() if (i >= 0 and j > i) else ""


def _head(s: str, n: int) -> str:
    return "\n".join(s.splitlines()[:n]).strip()
