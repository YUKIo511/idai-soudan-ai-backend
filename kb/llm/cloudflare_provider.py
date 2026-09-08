"""Cloudflare Workers AI プロバイダ（本番用）。

Cloudflare の OpenAI 互換エンドポイントを使う:
  POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions
  Authorization: Bearer {api_token}

既存の openai_provider.py と同じ構造。認証情報は環境変数
  CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN
からのみ受け取る（バックエンド限定。Expo 側には絶対に置かない）。

設計方針（ollama_provider.py と同じ）:
- 構築時（__init__）にネットワーク接続をしない。
- 到達不可 / 認証不備 / モデル不正 / レート制限 は LLMUnavailableError（日本語）に変換する。
- reasoning 系モデル（qwen QwQ 等）の <think>...</think> は汎用的に除去する。
- stream_chat は delta.content の増分だけを yield し、stats に usage を書き込む。
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterator

import httpx

from .base import LLMProvider, LLMMessage, LLMUnavailableError

_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    text = _THINK_BLOCK.sub("", text)
    low = text.lower()
    if "<think>" in low and "</think>" not in low:
        text = text[: low.index("<think>")]
    return text.strip()


class CloudflareLLMProvider(LLMProvider):
    name = "cloudflare"

    def __init__(
        self,
        model: str,
        account_id: str,
        api_token: str,
        *,
        base_url: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_timeout: float = 120.0,
    ):
        if not account_id or not api_token:
            # factory 側で弾いている想定だが保険
            raise LLMUnavailableError(
                "Cloudflare の認証情報がありません。環境変数 CLOUDFLARE_ACCOUNT_ID と "
                "CLOUDFLARE_API_TOKEN を設定してください（.env、バックエンド限定）。"
            )
        self.model = model
        self.account_id = account_id
        self._api_token = api_token
        self.base_url = (
            base_url.rstrip("/")
            if base_url
            else f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
        )
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.request_timeout = float(request_timeout)
        self.last_stats: dict[str, Any] = {}

    # ---------- payload ----------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        system: str,
        messages: list[LLMMessage],
        *,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        temp = temperature if temperature is not None else self.temperature
        mtok = max_tokens if max_tokens else self.max_tokens

        msgs: list[dict[str, str]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend({"role": m.role, "content": m.content} for m in messages)

        body: dict[str, Any] = {"model": self.model, "messages": msgs, "stream": stream}
        if temp is not None:
            body["temperature"] = float(temp)
        if mtok:
            body["max_tokens"] = int(mtok)  # コスト暴走防止の上限
        return body

    # ---------- error mapping ----------
    def _connect_error(self, exc: Exception) -> LLMUnavailableError:
        return LLMUnavailableError(
            "Cloudflare Workers AI に接続できません。ネットワーク、または "
            f"接続先（{self.base_url}）を確認してください。"
        )

    def _timeout_error(self) -> LLMUnavailableError:
        return LLMUnavailableError(
            f"Cloudflare Workers AI の応答がタイムアウトしました（timeout={self.request_timeout}s）。"
        )

    def _http_error(self, status: int, body: str) -> LLMUnavailableError:
        snippet = (body or "")[:500]
        if status in (401, 403):
            return LLMUnavailableError(
                "Cloudflare の API トークンが無効か、Workers AI の権限がありません。"
                "CLOUDFLARE_API_TOKEN を確認してください。"
            )
        if status == 404:
            return LLMUnavailableError(
                f"Cloudflare のモデル名が不正です: {self.model!r}。"
                "config.yaml の llm.cloudflare.model を確認してください。"
            )
        if status == 429:
            return LLMUnavailableError(
                "Cloudflare Workers AI のレート制限、または利用上限に達しました。"
                "しばらく待つか、Cloudflare ダッシュボードで使用量を確認してください。"
            )
        return LLMUnavailableError(
            f"Cloudflare Workers AI がエラーを返しました（HTTP {status}）: {snippet}"
        )

    def _extract_error(self, data: Any) -> str:
        """Cloudflare の {"errors":[{"message":...}]} 形式からメッセージを拾う。"""
        if isinstance(data, dict):
            errs = data.get("errors")
            if isinstance(errs, list) and errs:
                return "; ".join(str(e.get("message") or e) for e in errs)
        return ""

    # ---------- chat (non-streaming) ----------
    def chat(
        self,
        system: str,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        payload = self._payload(
            system, messages, temperature=temperature, max_tokens=max_tokens, stream=False
        )
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self.request_timeout,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise self._connect_error(e) from e
        except httpx.TimeoutException as e:
            raise self._timeout_error() from e
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"Cloudflare への接続に失敗しました: {e}") from e

        if resp.status_code >= 400:
            raise self._http_error(resp.status_code, resp.text)

        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise LLMUnavailableError(
                f"Cloudflare の応答を解析できませんでした: {(resp.text or '')[:300]}"
            ) from e

        err = self._extract_error(data)
        if err:
            raise LLMUnavailableError(f"Cloudflare Workers AI エラー: {err}")

        self.last_stats = dict(data.get("usage") or {})
        choices = data.get("choices") or []
        content = ""
        if choices:
            content = (choices[0].get("message") or {}).get("content", "") or ""
        cleaned = _strip_thinking(content) or content.strip()
        if not cleaned:
            raise LLMUnavailableError(
                f"Cloudflare（{self.model}）が空の応答を返しました。"
                "モデル名 / max_tokens / プロンプト長を確認してください。"
            )
        return cleaned

    # ---------- chat (streaming) ----------
    def stream_chat(
        self,
        system: str,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stats: dict | None = None,
    ) -> Iterator[str]:
        payload = self._payload(
            system, messages, temperature=temperature, max_tokens=max_tokens, stream=True
        )
        try:
            ctx = httpx.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self.request_timeout,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise self._connect_error(e) from e

        in_think = False          # <think> 内は捨てる
        undecided = ""            # 先頭が <think> か判定するための小バッファ
        started = False
        try:
            with ctx as resp:
                if resp.status_code >= 400:
                    resp.read()
                    raise self._http_error(resp.status_code, resp.text)
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if not line or line == "[DONE]":
                        if line == "[DONE]":
                            break
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    err = self._extract_error(obj)
                    if err:
                        raise LLMUnavailableError(f"Cloudflare Workers AI エラー: {err}")

                    if obj.get("usage"):
                        self.last_stats = dict(obj["usage"])
                        if stats is not None:
                            stats.update(obj["usage"])

                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    piece = (choices[0].get("delta") or {}).get("content", "") or ""
                    if not piece:
                        continue

                    if not started:
                        undecided += piece
                        low = undecided.lstrip().lower()
                        if low.startswith("<think>"):
                            in_think = True
                            started = True
                            undecided = ""
                        elif len(undecided) < 8 and "<think>".startswith(low[:7]):
                            continue  # まだ判定できない
                        else:
                            started = True
                            piece = undecided
                            undecided = ""

                    if in_think:
                        idx = piece.lower().find("</think>")
                        if idx == -1:
                            continue
                        in_think = False
                        piece = piece[idx + len("</think>"):].lstrip()
                        if not piece:
                            continue

                    yield piece
        except (httpx.ReadTimeout, httpx.TimeoutException) as e:
            raise self._timeout_error() from e
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"Cloudflare ストリーム中に接続エラー: {e}") from e
