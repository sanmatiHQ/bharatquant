"""Dashboard admin auth tests."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from src.api.dashboard import create_app
from src.api.dashboard_auth import authenticate, create_session_token, verify_session_token


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("DASHBOARD_ADMIN_USER", "owner")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret123")
    return TestClient(create_app())


def test_authenticate(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ADMIN_USER", "owner")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret123")
    assert authenticate("owner", "secret123") is True
    assert authenticate("owner", "wrong") is False


def test_session_roundtrip():
    tok = create_session_token("owner")
    assert verify_session_token(tok) is True
    assert verify_session_token("bad") is False


def test_public_feed_no_auth(client):
    r = client.get("/api/feed/live")
    assert r.status_code == 200
    assert "activity" in r.json()


def test_post_requires_admin(client):
    r = client.post("/api/halt", json={"reason": "test"})
    assert r.status_code == 401


def test_admin_login_and_halt(client):
    r = client.post("/api/admin/login", json={"username": "owner", "password": "secret123"})
    assert r.status_code == 200
    r = client.post("/api/halt", json={"reason": "test"})
    assert r.status_code == 200
