from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from app.browser import BrowserController


class FakePage:
    def __init__(self):
        self.calls = []

    def is_closed(self):
        return False

    async def evaluate(self, script, argument=None):
        self.calls.append((script, argument))
        if argument is None:
            return "token-1"
        return {"id": "bot-1", "fullName": "机器人"}


class FakeResponse:
    ok = True

    async def json(self):
        return {"result": {"data": {"json": {"url": "https://cdn.example/image.png"}}}}


class FakeRequest:
    def __init__(self):
        self.posts = []

    async def post(self, url, multipart):
        self.posts.append((url, multipart))
        return FakeResponse()


class FakeContext:
    def __init__(self):
        self.request = FakeRequest()

    async def cookies(self, origins=None):
        assert origins == ["https://www.ainvmei.com"]
        return [
            {"name": "session", "value": "abc"},
            {"name": "empty", "value": ""},
        ]


class FakeLogger:
    def warning(self, *_args, **_kwargs):
        pass


class FailingPage(FakePage):
    async def evaluate(self, script, argument=None):
        raise RuntimeError("endpoint unavailable")


class LoggedOutPage(FakePage):
    async def evaluate(self, script, argument=None):
        return "" if argument is None else {}


class CookieFallbackContext(FakeContext):
    def __init__(self, session, *, chunked=False):
        super().__init__()
        encoded = base64.urlsafe_b64encode(json.dumps(session).encode()).decode().rstrip("=")
        value = "base64-" + encoded
        if chunked:
            middle = len(value) // 2
            self.values = [
                {"name": "sb-project-auth-token.0", "value": value[:middle]},
                {"name": "sb-project-auth-token.1", "value": value[middle:]},
            ]
        else:
            self.values = [{"name": "sb-project-auth-token", "value": value}]

    async def cookies(self, origins=None):
        return self.values


def test_browser_provides_socket_credentials_and_upload(tmp_path, monkeypatch):
    requests = []

    class FakeUploadResponse:
        ok = True
        status = 200

        async def json(self):
            return {"result": {"data": {"json": {"url": "https://cdn.example/image.png"}}}}

        async def text(self):
            return ""

    class FakePostContext:
        async def __aenter__(self):
            return FakeUploadResponse()

        async def __aexit__(self, *_args):
            return False

    class FakeSession:
        def __init__(self, **kwargs):
            requests.append(("session", kwargs))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def post(self, url, **kwargs):
            requests.append((url, kwargs))
            return FakePostContext()

    monkeypatch.setattr("aiohttp.ClientSession", FakeSession)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")

    async def run():
        browser = BrowserController(tmp_path, FakeLogger())
        browser.page = FakePage()
        browser.context = FakeContext()

        assert await browser.socket_token() == "token-1"
        assert await browser.socket_profile() == {"id": "bot-1", "fullName": "机器人"}
        assert await browser.socket_cookie_header("https://www.ainvmei.com") == "session=abc"

        image = tmp_path / "picture.png"
        image.write_bytes(b"png-data")
        uploaded = await browser.upload_chat_image(
            "https://www.ainvmei.com", "room-1", image, "image/png"
        )
        assert uploaded == {"url": "https://cdn.example/image.png"}
        _, session_options = requests[0]
        url, request_options = requests[1]
        assert url == "https://www.ainvmei.com/api/trpc/chatroom.uploadImage"
        assert session_options["headers"]["Cookie"] == "session=abc"
        assert request_options["proxy"] == "http://127.0.0.1:7897"
        assert request_options["data"].is_multipart

    asyncio.run(run())


def test_browser_falls_back_to_supabase_auth_cookie(tmp_path):
    async def run():
        browser = BrowserController(tmp_path, FakeLogger())
        browser.page = FailingPage()
        browser.context = CookieFallbackContext(
            {"access_token": "cookie-token", "user": {"id": "cookie-user"}},
            chunked=True,
        )

        assert await browser.socket_token() == "cookie-token"
        assert await browser.socket_profile() == {"id": "cookie-user"}

    asyncio.run(run())


def test_browser_falls_back_to_cookie_when_new_origin_page_is_logged_out(tmp_path):
    async def run():
        browser = BrowserController(tmp_path, FakeLogger())
        browser.page = LoggedOutPage()
        browser.context = CookieFallbackContext(
            {"access_token": "migrated-token", "user": {"id": "migrated-user"}}
        )

        assert await browser.socket_token() == "migrated-token"
        assert await browser.socket_profile() == {"id": "migrated-user"}

    asyncio.run(run())
