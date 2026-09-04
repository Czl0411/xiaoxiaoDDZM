import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin_auth import AdminAuth, hash_password, install_admin_auth


def test_login_session_csrf_and_logout():
    auth = AdminAuth("admin", hash_password("strong-password", salt=b"0123456789abcdef"), session_seconds=60)
    assert auth.login("admin", "wrong") is None
    session = auth.login("admin", "strong-password")
    assert session and auth.require_session(session.token).username == "admin"
    assert auth.valid_csrf(session.token, session.csrf_token)
    assert not auth.valid_csrf(session.token, "wrong")
    auth.logout(session.token)
    assert auth.require_session(session.token) is None


def test_expired_session_is_rejected():
    auth = AdminAuth("admin", hash_password("password", salt=b"0123456789abcdef"), session_seconds=1)
    session = auth.login("admin", "password")
    session.expires_at = time.time() - 1
    assert auth.require_session(session.token) is None


def test_http_admin_login_and_csrf_protection():
    app = FastAPI()
    auth = AdminAuth("admin", hash_password("secret", salt=b"0123456789abcdef"))
    install_admin_auth(app, auth)

    @app.get("/")
    async def home():
        return {"ok": True}

    @app.post("/api/change")
    async def change():
        return {"changed": True}

    client = TestClient(app)
    login_html = client.get("/login").text
    assert '<form id="f">' in login_html
    assert '\n            "<' not in login_html
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401

    response = client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    assert response.status_code == 200
    csrf = response.json()["csrf_token"]
    assert client.get("/api/auth/check").status_code == 204
    assert client.get("/").json() == {"ok": True}
    assert client.post("/api/change").status_code == 403
    assert client.post("/api/change", headers={"X-CSRF-Token": csrf}).json() == {"changed": True}

    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/", follow_redirects=False).status_code == 303
