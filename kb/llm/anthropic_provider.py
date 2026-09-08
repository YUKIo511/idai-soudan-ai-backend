"""Anthropic Claude。要: pip install anthropic, 環境変数 ANTHROPIC_API_KEY。"""
from __future__ import annotations

from typing import Iterator

from .base import LLMProvider, LLMMessage


class AnthropicLLMProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-5"):
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("anthropic 未インストール: pip install anthropic") from e
        self._client = anthropic.Anthropic()
        self.model = model

    def chat(self, system: str, messages: list[LLMMessage], *,
             temperature: float = 0.7, max_tokens: int = 1200) -> str:
        resp = self._client.messages.create(
            model=self.model,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")

    def stream_chat(self, system: str, messages: list[LLMMessage], *,
                    temperature: float = 0.7, max_tokens: int = 1200,
                    stats: dict | None = None) -> Iterator[str]:  # stats は未使用（互換のため受け取る）
        with self._client.messages.stream(
            model=self.model,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        ) as stream:
            for text in stream.text_stream:
                yield text
