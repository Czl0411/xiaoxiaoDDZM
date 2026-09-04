from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel


_PBKDF2_ITERATIONS = 600_000


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, expected_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


@dataclass
class AdminSession:
    username: str
    token: str
    csrf_token: str
    expires_at: float


class AdminAuth:
    def __init__(self, username: str, password_hash: str, *, session_seconds: int = 8 * 60 * 60):
        self.username = username
        self.password_hash = password_hash
        self.session_seconds = session_seconds
        self._sessions: dict[str, AdminSession] = {}

    def login(self, username: str, password: str) -> AdminSession | None:
        valid_user = hmac.compare_digest(username, self.username)
        valid_password = verify_password(password, self.password_hash)
        if not (valid_user and valid_password):
            return None
        session = AdminSession(
            username=self.username,
            token=secrets.token_urlsafe(32),
            csrf_token=secrets.token_urlsafe(32),
            expires_at=time.time() + self.session_seconds,
        )
        self._sessions[session.token] = session
        return session

    def require_session(self, token: str | None) -> AdminSession | None:
        if not token:
            return None
        session = self._sessions.get(token)
        if session is None:
            return None
        if session.expires_at <= time.time():
            self._sessions.pop(token, None)
            return None
        return session

    def valid_csrf(self, token: str | None, csrf_token: str | None) -> bool:
        session = self.require_session(token)
        return bool(session and csrf_token and hmac.compare_digest(session.csrf_token, csrf_token))

    def logout(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)


class _LoginPayload(BaseModel):
    username: str
    password: str


def install_admin_auth(app: FastAPI, auth: AdminAuth, *, cookie_secure: bool = False) -> None:
    @app.middleware("http")
    async def require_admin(request: Request, call_next):
        path = request.url.path
        if path in {"/login", "/api/auth/login"}:
            return await call_next(request)
        token = request.cookies.get("dzmm_admin_session")
        session = auth.require_session(token)
        if session is None:
            if path.startswith("/api/"):
                return JSONResponse({"detail": "请先登录管理后台"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf_token = request.headers.get("X-CSRF-Token")
            if not auth.valid_csrf(token, csrf_token):
                return JSONResponse({"detail": "CSRF 校验失败"}, status_code=403)
        request.state.admin_session = session
        return await call_next(request)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page():
        return HTMLResponse(
            "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>DZMM 管理后台登录</title><style>body{font-family:system-ui;background:#10151c;color:#eee;"
            "display:grid;place-items:center;height:100vh;margin:0}form{display:grid;gap:14px;width:min(360px,80vw);"
            "padding:30px;background:#18212b;border-radius:14px}input,button{font:inherit;padding:12px;border-radius:8px;"
            "border:1px solid #445}button{cursor:pointer}</style><form id=\"f\"><h1>DZMM 管理后台</h1>"
            "<input name=\"username\" autocomplete=\"username\" placeholder=\"管理员账号\" required>"
            "<input name=\"password\" type=\"password\" autocomplete=\"current-password\" placeholder=\"密码\" required>"
            "<button>登录</button><div id=\"e\"></div></form><script>f.onsubmit=async x=>{x.preventDefault();"
            "let r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},"
            "body:JSON.stringify(Object.fromEntries(new FormData(f)))});if(r.ok){let d=await r.json();"
            "sessionStorage.setItem('dzmm_csrf',d.csrf_token);location='/'}else{e.textContent='账号或密码错误'}}</script></html>"
        )

    @app.post("/api/auth/login")
    async def login(payload: _LoginPayload):
        session = auth.login(payload.username, payload.password)
        if session is None:
            return JSONResponse({"detail": "账号或密码错误"}, status_code=401)
        response = JSONResponse({"ok": True, "csrf_token": session.csrf_token})
        response.set_cookie(
            "dzmm_admin_session",
            session.token,
            httponly=True,
            secure=cookie_secure,
            samesite="strict",
            max_age=auth.session_seconds,
        )
        return response

    @app.get("/api/auth/check", status_code=204)
    async def auth_check():
        return None

    @app.get("/api/auth/session")
    async def auth_session(request: Request):
        session = request.state.admin_session
        return {"username": session.username, "csrf_token": session.csrf_token}

    @app.post("/api/auth/logout")
    async def logout(request: Request):
        auth.logout(request.cookies.get("dzmm_admin_session"))
        response = JSONResponse({"ok": True})
        response.delete_cookie("dzmm_admin_session")
        return response
