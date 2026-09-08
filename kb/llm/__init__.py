"""LLM プロバイダの factory。"""
from __future__ import annotations

import logging

from ..config import Settings
from .base import LLMProvider, LLMMessage, LLMUnavailableError
from .fake import FakeLLMProvider

log = logging.getLogger("kb.llm")


def get_llm_provider(settings: Settings) -> LLMProvider:
    """config.yaml / 環境変数 KB_LLM_PROVIDER で選ばれたプロバイダを生成する。

    provider が不正なら ValueError を投げる（Fake へ暗黙フォールバックしない）。
    """
    prov = settings.llm_provider
    cfg = settings.llm_cfg()

    if prov == "fake":
        p: LLMProvider = FakeLLMProvider()
    elif prov == "ollama":
        from .ollama_provider import OllamaLLMProvider
        o = settings.ollama_options()
        p = OllamaLLMProvider(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            keep_alive=o.get("keep_alive"),
            num_ctx=o.get("num_ctx"),
            num_predict=o.get("num_predict"),
            temperature=o.get("temperature"),
            think=o.get("think"),
            no_think_prefill=o.get("no_think_prefill", ""),
            stop=o.get("stop"),
            request_timeout=float(o.get("request_timeout", 120)),
        )
    elif prov == "cloudflare":
        from .cloudflare_provider import CloudflareLLMProvider
        if not settings.cloudflare_account_id or not settings.cloudflare_api_token:
            raise ValueError(
                "llm.provider=cloudflare には環境変数 CLOUDFLARE_ACCOUNT_ID と "
                "CLOUDFLARE_API_TOKEN が必要です（.env に設定・バックエンド限定。"
                "Expo/アプリ側には絶対に置かない）。"
            )
        p = CloudflareLLMProvider(
            model=settings.cloudflare_model,
            account_id=settings.cloudflare_account_id,
            api_token=settings.cloudflare_api_token,
            temperature=cfg.get("temperature"),
            max_tokens=cfg.get("max_tokens"),
            request_timeout=float(cfg.get("request_timeout", 120)),
        )
    elif prov == "anthropic":
        from .anthropic_provider import AnthropicLLMProvider
        p = AnthropicLLMProvider(model=cfg.get("model", "claude-sonnet-5"))
    elif prov == "openai":
        from .openai_provider import OpenAILLMProvider
        p = OpenAILLMProvider(model=cfg.get("model", "gpt-4.1"))
    else:
        raise ValueError(
            f"未知の llm.provider: {prov!r}（fake | ollama | cloudflare | anthropic | openai）"
        )

    extra = f" base_url={getattr(p, 'base_url', '')}" if prov == "ollama" else ""
    log.info("LLM provider initialised: provider=%s model=%s%s", p.name, p.model or "-", extra)
    return p


__all__ = ["LLMProvider", "LLMMessage", "LLMUnavailableError", "get_llm_provider"]
