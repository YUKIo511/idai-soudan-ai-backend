"""SSE（text/event-stream）ヘルパ。依存追加なし。"""
from __future__ import annotations

import json
from typing import Any

# StreamingResponse(media_type="text/event-stream") と併用するため Content-Type は入れない
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",   # nginx 等でのバッファリング抑止（トークンを即座に届ける）
}


def sse_data(obj: Any) -> str:
    """`data: {json}\\n\\n` 形式（1メッセージ = 1 JSON、type フィールドで種別）。"""
    payload = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    body = "".join(f"data: {line}\n" for line in payload.split("\n"))
    return body + "\n"
