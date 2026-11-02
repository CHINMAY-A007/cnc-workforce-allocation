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
