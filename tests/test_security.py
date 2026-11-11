import json
import os


def test_gemini_off_by_default_and_never_calls_network(client, monkeypatch):
    from core import notes
    import httpx
    def boom(*a, **k):
        raise AssertionError("network call attempted")
    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx, "get", boom)
    monkeypatch.setattr(httpx.Client, "post", boom, raising=False)
    r = client.get("/api/parse-notes", params={"text": "Needs titanium, certified inspector only"})
    assert r.status_code == 200
    assert "keyword" in json.dumps(r.json()).lower() or "titanium" in json.dumps(r.json()).lower()


def test_key_never_in_api_output(client):
    secret = os.environ["GEMINI_API_KEY"]
    for p in ("/api/state", "/api/meta", "/api/policy", "/api/export", "/api/orders", "/api/requirements"):
        assert secret not in client.get(p).text, p


def test_reset_needs_confirmation(client):
    r = client.post("/api/reset", json={}, headers={"x-role": "Production Manager"})
    assert r.status_code == 400
    assert client.get("/api/orders").json()


def test_gemini_daily_cap_persists_across_process_resets(client, monkeypatch):
    """The daily cap lives in the DB, so a process restart cannot reset it."""
    from core import notes
    from core.db import get_conn
    from core.config import today_local

    monkeypatch.setenv("GEMINI_ENABLED", "1")
    monkeypatch.setattr(notes, "GEMINI_DAILY_MAX", 3)

    calls = {"n": 0}
    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        class R:
            def raise_for_status(self): pass
            def json(self):
                return {"steps": [{"type": "model_output",
                                   "content": [{"type": "text", "text": "hi"}]}]}
        return R()
    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    assert notes.gemini_generate("a") == "hi"
    assert notes.gemini_generate("b") == "hi"
    assert notes.gemini_generate("c") == "hi"
    assert notes.gemini_generate("d") is None  # 4th call blocked by the daily cap
    assert calls["n"] == 3                     # and the API was never hit a 4th time

    # Simulate a process restart: the in-process counter resets, the DB one does not.
    notes._gemini_calls = 0
    assert notes.gemini_generate("e") is None
    assert calls["n"] == 3

    day = today_local().isoformat()
    conn = get_conn()
    try:
        row = conn.execute("SELECT calls FROM gemini_usage WHERE day = ?", (day,)).fetchone()
        assert row["calls"] == 3
    finally:
        conn.close()
