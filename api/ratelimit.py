"""最小限のレート制限（固定ウィンドウ・インメモリ）。

App Store 公開に必要な「同一 IP からの異常連打」対策。外部ストア（Redis 等）は使わない。
Railway hobby は 1 レプリカ想定なのでプロセス内カウンタで十分。複数レプリカにした場合は
各レプリカごとの制限になる（それでも無制限よりは有効）。

環境変数:
  KB_RATELIMIT_PER_MIN  1 IP あたり毎分の許可リクエスト数（既定 20、0 で無効化）
"""
from __future__ import annotations

import os
import time
from collections import deque

from fastapi import HTTPException, Request

_WINDOW_SEC = 60
_hits: dict[str, deque[float]] = {}
_last_gc = 0.0


def _limit_per_min() -> int:
    try:
        return int(os.environ.get("KB_RATELIMIT_PER_MIN", "20"))
    except ValueError:
        return 20


def _client_ip(request: Request) -> str:
    # Railway は X-Forwarded-For を付ける。先頭が実クライアント。
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _gc(now: float) -> None:
    global _last_gc
    if now - _last_gc < _WINDOW_SEC:
        return
    _last_gc = now
    for ip in list(_hits):
        dq = _hits[ip]
        while dq and dq[0] < now - _WINDOW_SEC:
            dq.popleft()
        if not dq:
            del _hits[ip]


async def rate_limit(request: Request) -> None:
    """FastAPI 依存として使う。超過時は 429。"""
    limit = _limit_per_min()
    if limit <= 0:
        return
    now = time.monotonic()
    _gc(now)
    ip = _client_ip(request)
    dq = _hits.setdefault(ip, deque())
    while dq and dq[0] < now - _WINDOW_SEC:
        dq.popleft()
    if len(dq) >= limit:
        retry = max(1, int(_WINDOW_SEC - (now - dq[0])))
        raise HTTPException(
            status_code=429,
            detail="リクエストが多すぎます。少し時間をおいてからお試しください。",
            headers={"Retry-After": str(retry)},
        )
    dq.append(now)
