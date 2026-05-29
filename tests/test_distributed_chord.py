import json
from pathlib import Path

import pytest

from chord_dht import hash_identifier, in_clockwise_interval


def test_hash_identifier_stays_inside_m_bit_space():
    value = hash_identifier("resource-0001", m=16)
    assert 0 <= value < 2**16


def test_clockwise_interval_handles_wraparound():
    assert in_clockwise_interval(2, 14, 4)
    assert in_clockwise_interval(15, 14, 4)
    assert not in_clockwise_interval(8, 14, 4)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app

    monkeypatch.setattr(app, "STATE_PATH", tmp_path / "state.json")

    # Reset ring and force autoload behavior for each test
    app.ring = app.ChordRing(m=16, seed=61, replication_count=3)
    app.ring_startup_completed = False

    yield app.app.test_client()


def test_initialize_persists_state_json(client, tmp_path):
    resp = client.post(
        "/api/initialize",
        json={
            "nodes": 10,
            "resources": 12,
            "m": 10,
            "seed": 61,
            "replication_count": 2,
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True

    state_path = tmp_path / "state.json"
    assert state_path.exists()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert int(payload["config"]["m"]) == 10


def test_state_endpoint_autoloads_json(client, tmp_path):
    import app

    # initialize first
    client.post(
        "/api/initialize",
        json={"nodes": 10, "resources": 12, "m": 10, "seed": 61, "replication_count": 2},
    )

    # clear in-memory and ensure /api/state reloads
    app.ring = app.ChordRing(m=16, seed=61, replication_count=3)
    app.ring_startup_completed = False

    resp = client.get("/api/state")
    body = resp.get_json()
    assert body["ok"] is True
    assert body["state"]["active_node_count"] == 10
    assert body["state"]["resource_count"] == 12


def test_lookup_returns_trace(client):
    client.post(
        "/api/initialize",
        json={"nodes": 10, "resources": 12, "m": 10, "seed": 61, "replication_count": 2},
    )
    resp = client.post("/api/lookup", json={"resource_id": "resource-0001"})
    body = resp.get_json()
    assert body["ok"] is True
    assert "path" in body["result"]
    assert isinstance(body["result"]["path"], list)


def test_resource_crud_updates_json(client, tmp_path):
    client.post(
        "/api/initialize",
        json={"nodes": 10, "resources": 0, "m": 10, "seed": 61, "replication_count": 2},
    )

    created = client.post("/api/resource", json={"resource_id": "student-score"}).get_json()
    assert created["ok"] is True

    deleted = client.delete("/api/resource", json={"resource_id": "student-score"}).get_json()
    assert deleted["ok"] is True

    state_path = tmp_path / "state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert "student-score" not in payload.get("resources", [])
