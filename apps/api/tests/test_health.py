from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_live_returns_ok_and_request_id():
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["x-request-id"]


def test_request_id_is_propagated():
    r = client.get("/health/live", headers={"x-request-id": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
