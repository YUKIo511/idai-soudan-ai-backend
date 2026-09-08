"""Ollama（ローカル LLM）プロバイダ。

Ollama の HTTP API（POST {base_url}/api/chat）を使う。API キー不要・完全ローカル。
既存の LLMProvider.chat(system, messages) インターフェースに準拠する。

設計方針:
- 構築時（__init__）にネットワーク接続をしない → Ollama 未起動でも FastAPI は落ちない。
- 接続不可 / モデル未取得などは LLMUnavailableError（原因の分かる日本語メッセージ）を投げる。
- 特定モデルに依存しない。reasoning 系モデル（qwen3 等）の <think>...</think> は汎用的に除去する。
- think は既定 false（思考出力を止めて高速化＋チャット向き）。config で上書き可。
- stream_chat は message.content の増分だけを yield する。stats を渡すと生成統計を書き込む。
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterator

import httpx

from .base import LLMProvider, LLMMessage, LLMUnavailableError

_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_STAT_KEYS = (
    "total_duration", "load_duration",
    "prompt_eval_count", "prompt_eval_duration",
    "eval_count", "eval_duration", "done_reason",
)
# 古い Ollama（<0.5）では qwen3 の非思考モードが効かず、英語の思考メモが content に混入することがある。
_EN_REASON_START = re.compile(
    r"^\s*(okay[,.\s]|alright[,.\s]|first[,.\s]|let me\b|let's\b|i need to\b|i should\b|"
    r"the user\b|we need\b|thinking:|reasoning:)",
    re.IGNORECASE,
)
_JA_CHAR = re.compile(r"[぀-ヿ一-鿿。、！？「」]")


def _looks_english_reasoning(text: str) -> bool:
    head = text.lstrip()[:400]
    if not head:
        return False
    ja = len(_JA_CHAR.findall(head))
    return bool(_EN_REASON_START.match(head)) and ja < 8


def _strip_thinking(text: str) -> str:
    """思考出力を取り除く。

    1) <think>...</think>（reasoning 系モデル共通）
    2) 古い Ollama + qwen3 で content 先頭に混入する英語の思考メモ
       → 最後に現れる日本語のまとまった段落を最終回答とみなして抜き出す（保険。完全ではない）
    """
    text = _THINK_BLOCK.sub("", text)
    low = text.lower()
    if "<think>" in low and "</think>" not in low:
        text = text[: low.index("<think>")]
    text = text.strip()

    if _looks_english_reasoning(text):
        # 日本語が連続する段落だけを残す（英語のメモ行を捨てる）
        ja_paras = [
            p.strip() for p in re.split(r"\n\s*\n", text)
            if len(_JA_CHAR.findall(p)) >= max(20, len(p) * 0.3)
        ]
        if ja_paras:
            text = max(ja_paras, key=len).strip("「」 \n")
    return text.strip()


class OllamaLLMProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        *,
        keep_alive: str | int | None = None,
        num_ctx: int | None = None,
        num_predict: int | None = None,
        temperature: float | None = None,
        think: bool | None = None,
        no_think_prefill: str = "",
        stop: list[str] | None = None,
        request_timeout: float = 120.0,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.keep_alive = keep_alive
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.temperature = temperature
        self.stop = [s for s in (stop or []) if s]  # 生成停止シーケンス（自己注釈・繰り返し対策）
        # think は既定 False（思考出力を完全に止める）。config で True を明示したときだけ有効化。
        self.think = False if think is None else bool(think)
        # think=False でも思考メモを content に垂れ流すモデル（例: 一部 Ollama 版の qwen3:4b/1.7b）向け。
        # assistant ロールをこの文字列で先取り（prefill）すると、モデルは「回答の続き」を書き始め、
        # 思考フェーズをスキップする。空文字なら無効。
        self.no_think_prefill = no_think_prefill or ""
        self.request_timeout = float(request_timeout)
        self.last_stats: dict[str, Any] = {}

    def _use_prefill(self) -> bool:
        return bool(self.no_think_prefill) and not self.think

    # ---------- payload ----------
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
        npredict = max_tokens if max_tokens else self.num_predict

        options: dict[str, Any] = {}
        if temp is not None:
            options["temperature"] = float(temp)
        if npredict:
            options["num_predict"] = int(npredict)
        if self.num_ctx:
            options["num_ctx"] = int(self.num_ctx)
        if self.stop:
            options["stop"] = list(self.stop)

        msgs: list[dict[str, str]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend({"role": m.role, "content": m.content} for m in messages)

        # think=False のとき、qwen3 系の soft switch `/no_think` を最後の user 発話に付与。
        # API の think パラメータが効かない/無視されるモデルでも思考出力を抑えられる（他モデルは無害に無視）。
        if not self.think and msgs:
            for mm in reversed(msgs):
                if mm["role"] == "user":
                    if "/no_think" not in mm["content"]:
                        mm["content"] = mm["content"].rstrip() + " /no_think"
                    break

        # assistant プレフィル（think 抑制の最終手段）。モデルは prefill の「続き」から書き始める。
        if self._use_prefill():
            msgs.append({"role": "assistant", "content": self.no_think_prefill})

        body: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "stream": stream,
            "think": self.think,          # 思考出力の on/off（qwen3 等）
            "options": options,
        }
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        return body

    # ---------- error mapping ----------
    def _connect_error(self, exc: Exception) -> LLMUnavailableError:
        return LLMUnavailableError(
            f"Ollama に接続できません（{self.base_url}）。"
            "Ollama が起動しているか確認してください（PowerShell で `ollama serve`、"
            "またはアプリ版 Ollama を起動）。接続先は config.yaml の llm.ollama.base_url / "
            "環境変数 KB_OLLAMA_BASE_URL で変更できます。"
        )

    def _timeout_error(self, exc: Exception) -> LLMUnavailableError:
        return LLMUnavailableError(
            f"Ollama の応答がタイムアウトしました（timeout={self.request_timeout}s）。"
            f"モデル '{self.model}' の初回ロード中か、PC 性能に対してモデルが大きい可能性があります。"
            f"事前に `ollama run {self.model}` でロードしておくか、より軽いモデル"
            "（qwen3:4b / qwen3:1.7b など）に変更してください。"
        )

    def _http_error(self, resp: httpx.Response) -> LLMUnavailableError:
        body = (resp.text or "")[:500]
        if resp.status_code == 404 or "not found" in body.lower():
            return LLMUnavailableError(
                f"モデル '{self.model}' が見つかりません。"
                f"PowerShell で `ollama pull {self.model}` を実行してください。"
                "（取得済みモデルは `ollama list` で確認できます）"
            )
        return LLMUnavailableError(f"Ollama がエラーを返しました（HTTP {resp.status_code}）: {body}")

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
                f"{self.base_url}/api/chat", json=payload, timeout=self.request_timeout
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise self._connect_error(e) from e
        except httpx.TimeoutException as e:
            raise self._timeout_error(e) from e
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"Ollama への接続に失敗しました: {e}") from e

        if resp.status_code >= 400:
            raise self._http_error(resp)

        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise LLMUnavailableError(
                f"Ollama の応答を解析できませんでした: {(resp.text or '')[:300]}"
            ) from e

        self.last_stats = {k: data.get(k) for k in _STAT_KEYS if data.get(k) is not None}
        content = (data.get("message") or {}).get("content", "") or ""
        if self._use_prefill():
            # プレフィルした文字列は応答に含まれないので前置する
            cleaned = (self.no_think_prefill + content).strip()
        else:
            cleaned = _strip_thinking(content) or content.strip()
        cleaned = _cut_junk_tail(cleaned)  # 末尾の字数申告・英語の独り言・stray タグを除去
        if not cleaned:
            raise LLMUnavailableError(
                f"Ollama（{self.model}）が空の応答を返しました。"
                "num_ctx / num_predict / プロンプト長を確認してください。"
            )
        # num_predict 上限で末尾が切れた場合、最後の文末で丸める（文の途中で終えない）
        if self.last_stats.get("done_reason") == "length":
            cleaned = _trim_to_sentence(cleaned)
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
                "POST", f"{self.base_url}/api/chat", json=payload, timeout=self.request_timeout
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise self._connect_error(e) from e

        # undecided → (in_think | skip_en_reason | passthrough)
        # プレフィル時は出力がクリーンなので判定不要（先頭に prefill を出してから素通し）
        prefill = self.no_think_prefill if self._use_prefill() else ""
        state = "passthrough" if prefill else "undecided"
        head = ""
        tail = ""            # passthrough 時の末尾バッファ（ゴミ検出・部分一致保持用）
        try:
            if prefill:
                yield prefill
            with ctx as resp:
                if resp.status_code >= 400:
                    resp.read()
                    raise self._http_error(resp)
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("error"):
                        raise LLMUnavailableError(f"Ollama エラー: {obj['error']}")

                    if obj.get("done"):
                        s = {k: obj.get(k) for k in _STAT_KEYS if obj.get(k) is not None}
                        self.last_stats = s
                        if stats is not None:
                            stats.update(s)
                        break

                    piece = (obj.get("message") or {}).get("content", "") or ""
                    if not piece:
                        continue

                    if state == "passthrough":
                        # 末尾に「字数申告 / 英語の独り言 / stray タグ」が現れたらそこで打ち切る
                        tail += piece
                        m = _JUNK_TAIL.search(tail)
                        if m:
                            safe = tail[: m.start()]
                            if safe:
                                yield safe
                            tail = ""
                            break  # ゴミ検出：即座に打ち切り（残りは待たない）
                        # 直近 40 字は部分一致の可能性があるので保持、それ以前を流す
                        if len(tail) > 40:
                            yield tail[:-40]
                            tail = tail[-40:]
                        continue

                    head += piece

                    if state == "undecided":
                        stripped = head.lstrip()
                        if stripped.lower().startswith("<think>"):
                            state = "in_think"
                        elif len(head) < 40 and "<think>".startswith(stripped[:7].lower()):
                            pass  # まだ判定できない
                        elif _looks_english_reasoning(head):
                            state = "skip_en_reason"  # 古い Ollama + qwen3 の英語思考メモを捨てる
                        else:
                            state = "passthrough"
                            tail = head
                            head = ""
                        continue

                    if state == "in_think":
                        end = head.lower().find("</think>")
                        if end != -1:
                            state = "passthrough"
                            tail = head[end + len("</think>") :].lstrip()
                            head = ""
                        continue

                    # state == "skip_en_reason": 日本語の文が続き始めたら本文とみなす
                    m = re.search(r"[぀-ヿ一-鿿][^\n]*?[。！？]", head)
                    if m and len(_JA_CHAR.findall(head[m.start():])) >= 12:
                        state = "passthrough"
                        tail = head[m.start():].lstrip("「 \n")
                        head = ""
        except (httpx.ReadTimeout, httpx.TimeoutException) as e:
            raise self._timeout_error(e) from e
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"Ollama ストリーム中に接続エラー: {e}") from e

        # 残りバッファを最終フラッシュ（末尾のゴミは除去）
        if tail:
            yield _cut_junk_tail(tail)


_SENT_END = "。．.!?！？」』"

# 回答本文のあとに続きがちな「ゴミ」の始まり
#   例: （499字） / （※…調整） / ※注記 / </think> / Okay, let's… / <note> / ---
_JUNK_TAIL = re.compile(
    r"(?:\n+\s*[（(]\s*\d+\s*字"
    r"|\n+\s*[（(]?\s*[※＊*]\s*"
    r"|\n+\s*[（(]\s*(?:注|補足|備考|メモ|Note)"
    r"|\n+\s*</?think>"
    r"|\n{2,}\s*(?:Okay|Alright|Wait|First|Now|Note|The user|Let me|I need to|I should|Here'?s)\b"
    r"|\n{2,}\s*<note>"
    r"|\n{2,}-{3,}\s*(?:\n|$))",
    re.IGNORECASE,
)


_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_LINE = re.compile(r"^\s*(?:[#>]+\s*|[-*・]\s+|\d+[.)]\s+)", re.MULTILINE)
_JISU_NOTE = re.compile(r"[（(]?\s*字数[:：].*", re.DOTALL)
_META_LINE = re.compile(r"\n\s*(?:この返信は|上記(?:の返信)?は|以下を満たし|補足[:：]).*", re.DOTALL)


def _cut_junk_tail(text: str) -> str:
    m = _JUNK_TAIL.search(text)
    if m:
        text = text[: m.start()]
    text = _JISU_NOTE.sub("", text)
    text = _META_LINE.sub("", text)
    text = _MD_BOLD.sub(r"\1", text)          # **強調** → 強調
    text = _MD_LINE.sub("", text)             # 行頭の # / - / 1. などの記号を除去
    # 連続する ？ や 空白の重複を整理
    text = re.sub(r"[？?]\s*[？?]+", "？", text)
    text = re.sub(r"[ 　]+\n", "\n", text)
    return text.rstrip()


def _trim_to_sentence(text: str) -> str:
    """末尾が文の途中で切れている場合、最後の文末記号までで丸める。"""
    text = text.rstrip()
    if not text or text[-1] in _SENT_END:
        return text
    for i in range(len(text) - 1, max(0, len(text) - 200), -1):
        if text[i] in _SENT_END:
            return text[: i + 1]
    return text
