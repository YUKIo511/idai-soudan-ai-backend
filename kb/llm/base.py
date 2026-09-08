"""LLM プロバイダの抽象（Claude / OpenAI 両対応・切替可能）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator


@dataclass
class LLMMessage:
    role: str      # "user" | "assistant"
    content: str


class LLMUnavailableError(RuntimeError):
    """LLM プロバイダに到達できない / 設定不備（例: Ollama 未起動、モデル未取得）。

    プロバイダの chat() / stream_chat() が投げる。API 層でキャッチして、
    原因の分かるメッセージをユーザー（開発者）へ返すために使う。
    FastAPI 全体を落とさないための境界。
    """


class LLMProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def chat(self, system: str, messages: list[LLMMessage], *,
             temperature: float = 0.7, max_tokens: int = 1200) -> str:
        ...

    def stream_chat(self, system: str, messages: list[LLMMessage], *,
                    temperature: float = 0.7, max_tokens: int = 1200,
                    stats: dict | None = None) -> Iterator[str]:
        """テキストの増分を逐次 yield する。

        既定は chat() の結果を1回だけ返す後方互換ラッパ。ストリーミング対応の
        プロバイダはこのメソッドをオーバーライドする（chat() は変更しない）。
        stats: 渡すと、対応プロバイダが生成統計（load_duration 等）を書き込む。
        """
        yield self.chat(system, messages, temperature=temperature, max_tokens=max_tokens)

    def describe(self) -> str:
        return f"{self.name}({self.model or '-'})"
