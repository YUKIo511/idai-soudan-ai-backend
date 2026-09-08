"""API テスト。pytest が無くても `python -m tests.test_api` で実行可能。

既定の config（fake embedding / memory store / fake LLM）で動く。
事前に `python -m kb.cli build steve_jobs && python -m kb.cli embed steve_jobs` が必要。
"""
from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)
SLUG = "steve_jobs"


def test_health():
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["characters"] >= 1


def test_characters_list():
    r = client.get("/characters")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(body["characters"]) >= 1
    c = next(c for c in body["characters"] if c["slug"] == SLUG)
    for key in ("name", "icon", "occupation", "categories", "one_line"):
        assert key in c
    assert c["knowledge_count"] > 0


def test_character_detail():
    r = client.get(f"/characters/{SLUG}")
    assert r.status_code == 200
    d = r.json()
    assert d["intro"] and d["name"]
    assert len(d["timeline"]) > 0
    assert len(d["philosophy"]) > 0
    # 詳細に出す名言は本人発言と確認/推定できるもののみ
    assert all(q["attribution_status"] in ("verified", "likely") for q in d["quotes"])


def test_character_detail_404():
    assert client.get("/characters/does_not_exist").status_code == 404


def test_consult():
    r = client.post("/consult", json={"character": SLUG, "message": "起業すべきか迷っています"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"].strip()
    assert len(body["knowledge"]) > 0
    for k in body["knowledge"]:
        assert k["reliability"] and k["ref"]
    assert body["disclaimer"]
    # APIキーや内部プロンプトが漏れていない
    blob = r.text.lower()
    assert "sk-ant" not in blob and "api_key" not in blob and "<rules>" not in blob


def test_consult_bad_character():
    assert client.post("/consult", json={"character": "nobody", "message": "hi"}).status_code == 404


def test_consult_empty_message():
    r = client.post("/consult", json={"character": SLUG, "message": "   "})
    assert r.status_code == 422


def test_consult_stream():
    with client.stream("POST", "/consult/stream",
                       json={"character": SLUG, "message": "失敗が怖いです"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        raw = "".join(chunk for chunk in r.iter_text())
    # SSE: data: {"type": ...}  形式（meta / token / done）
    assert '"type": "meta"' in raw
    assert '"type": "token"' in raw
    assert '"type": "done"' in raw
    # done イベントに sources（根拠）が入る
    assert '"sources"' in raw


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
