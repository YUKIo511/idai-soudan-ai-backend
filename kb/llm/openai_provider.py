"""OpenAI Chat。要: pip install openai, 環境変数 OPENAI_API_KEY。"""
from __future__ import annotations

from typing import Iterator

from .base import LLMProvider, LLMMessage


class OpenAILLMProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str = "gpt-4.1"):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("openai 未インストール: pip install openai") from e
        self._client = OpenAI()
        self.model = model

    def chat(self, system: str, messages: list[LLMMessage], *,
             temperature: float = 0.7, max_tokens: int = 1200) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
        )
        return resp.choices[0].message.content or ""

    def stream_chat(self, system: str, messages: list[LLMMessage], *,
                    temperature: float = 0.7, max_tokens: int = 1200,
                    stats: dict | None = None) -> Iterator[str]:  # stats は未使用（互換のため受け取る）
        stream = self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            messages=[{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
