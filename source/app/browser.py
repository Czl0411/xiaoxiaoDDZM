from __future__ import annotations

import asyncio
import base64
import ctypes
import inspect
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import playwright
from playwright.async_api import BrowserContext, Page, async_playwright


def _windows_short_path(path: Path) -> str:
    value = str(path)
    if os.name != "nt":
        return value
    try:
        get_short_path = ctypes.windll.kernel32.GetShortPathNameW
        required = get_short_path(value, None, 0)
        if not required:
            return value
        buffer = ctypes.create_unicode_buffer(required)
        written = get_short_path(value, buffer, required)
        return buffer.value if written else value
    except (AttributeError, OSError, ValueError):
        return value


def _configure_playwright_driver_paths() -> None:
    if os.name != "nt":
        return
    from playwright._impl import _driver, _transport

    driver_path = Path(inspect.getfile(playwright)).resolve().parent / "driver"
    executable_path = _windows_short_path(driver_path / "node.exe")
    entrypoint_path = _windows_short_path(driver_path / "package" / "cli.js")

    def compute_driver_executable() -> tuple[str, str]:
        return executable_path, entrypoint_path

    _driver.compute_driver_executable = compute_driver_executable
    _transport.compute_driver_executable = compute_driver_executable


class BrowserController:
    def __init__(self, data_dir: Path, logger):
        self.data_dir = data_dir
        self.logger = logger
        self.playwright = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.pages: dict[str, Page] = {}

    async def start(self) -> None:
        if self.context and self.page and not self.page.is_closed():
            return
        await self.stop()
        config = self._config()
        profile = self.data_dir / "browser_profile"
        profile.mkdir(parents=True, exist_ok=True)
        _configure_playwright_driver_paths()
        for attempt in range(2):
            try:
                self.playwright = await async_playwright().start()
                break
            except Exception:
                if attempt:
                    raise
                self.logger.warning("Playwright 驱动首次启动失败，正在自动重试")
                await asyncio.sleep(0.3)
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=bool(config.get("dzmm", {}).get("headless", False)),
            viewport={"width": 1280, "height": 850},
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.page.on("close", lambda _: setattr(self, "page", None))
        self.pages = {"main": self.page}
        self.logger.info("DZMM 浏览器已启动，登录状态会保存到 data/browser_profile")

    async def ensure_page(self) -> Page:
        if not self.context or not self.page or self.page.is_closed():
            self.logger.warning("DZMM 浏览器已关闭，正在重新打开")
            await self.start()
        return self.get_page()

    async def ensure_group_page(self, group_key: str, url: str = "") -> Page:
        key = (group_key or "main").strip()
        if not self.context:
            await self.start()
        page = self.pages.get(key)
        if page and not page.is_closed():
            if url and not self._same_chatroom(page.url, url):
                self.logger.warning(
                    f"{key} 群标签页已漂移，正在恢复到配置的群聊页面"
                )
                await self._navigate_group_page(page, url)
            return page
        if key == "main" and self.page and not self.page.is_closed():
            page = self.page
        else:
            page = await self.context.new_page()
        self.pages[key] = page
        if key == "main":
            self.page = page

        def forget_page(_: Page) -> None:
            if self.pages.get(key) is page:
                self.pages.pop(key, None)
            if key == "main" and self.page is page:
                self.page = None

        page.on("close", forget_page)
        if url and not self._same_chatroom(page.url, url):
            await self._navigate_group_page(page, url)
        return page

    async def _navigate_group_page(self, page: Page, url: str) -> None:
        """优先使用站内链接进入群聊，避免重复整页加载触发站点脚本竞态。"""
        if self._same_chatroom(page.url, url):
            return
        target_id = self._chatroom_id(url)
        if target_id and hasattr(page, "locator"):
            try:
                link = page.locator(f'a[href*="c={target_id}"]')
                if await link.count() > 0:
                    await link.first.click(timeout=5000)
                    await page.wait_for_url(
                        lambda current: self._same_chatroom(current, url), timeout=10000
                    )
                    return
            except Exception as exc:
                self.logger.warning(f"站内切换群聊失败，将使用直接地址恢复：{exc}")
        await page.goto(url, wait_until="domcontentloaded")

    @staticmethod
    def _chatroom_id(value: str) -> str:
        try:
            return (parse_qs(urlparse(value or "").query).get("c") or [""])[0].lower()
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _same_chatroom(current_url: str, expected_url: str) -> bool:
        expected_id = BrowserController._chatroom_id(expected_url)
        if expected_id:
            return BrowserController._chatroom_id(current_url) == expected_id
        return (current_url or "").rstrip("/") == (expected_url or "").rstrip("/")

    async def stop(self) -> None:
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
            self.context = None
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
        self.page = None
        self.pages = {}

    async def reset_profile(self) -> None:
        await self.stop()
        profile = self.data_dir / "browser_profile"
        if profile.exists():
            shutil.rmtree(profile)
        profile.mkdir(parents=True, exist_ok=True)
        await self.start()

    def get_page(self) -> Page:
        if not self.page or self.page.is_closed():
            raise RuntimeError("DZMM 浏览器尚未启动或已关闭")
        return self.page

    async def socket_token(self) -> str:
        page = await self.ensure_page()
        try:
            token = str(await page.evaluate(_TOKEN_SCRIPT) or "")
            if token:
                return token
        except Exception:
            pass
        session = await self._stored_auth_session()
        token = (session or {}).get("access_token")
        if isinstance(token, str) and token:
            return token
        return ""

    async def socket_profile(self) -> dict:
        page = await self.ensure_page()
        try:
            result = await page.evaluate(
                _TRPC_SCRIPT,
                {"procedure": "user.getMe", "payload": None, "timeoutMs": 5000},
            )
        except Exception:
            result = None
        if not isinstance(result, dict) or not isinstance(result.get("id"), str):
            session = await self._stored_auth_session()
            result = (session or {}).get("user")
        return result if isinstance(result, dict) else {}

    async def _stored_auth_session(self) -> dict | None:
        if not self.context:
            return None
        chunks: dict[str, list[tuple[int, str]]] = {}
        for cookie in await self.context.cookies():
            name = str(cookie.get("name") or "")
            value = str(cookie.get("value") or "")
            match = re.fullmatch(r"(sb-.*-auth-token)(?:\.(\d+))?", name)
            if not match or not value:
                continue
            chunks.setdefault(match.group(1), []).append(
                (int(match.group(2) or 0), value)
            )
        for values in chunks.values():
            value = "".join(item[1] for item in sorted(values))
            if not value.startswith("base64-"):
                continue
            try:
                encoded = value.removeprefix("base64-")
                decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                session = json.loads(decoded)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(session, dict):
                return session
        return None

    async def socket_cookie_header(self, origin: str) -> str:
        if not self.context:
            return ""
        cookies = await self.context.cookies([origin])
        return "; ".join(
            f"{cookie['name']}={cookie['value']}"
            for cookie in cookies
            if cookie.get("name") and cookie.get("value")
        )

    async def upload_chat_image(
        self, origin: str, chatroom_id: str, path: Path, mime_type: str
    ) -> dict:
        if not self.context:
            raise RuntimeError("DZMM 浏览器尚未启动")
        import aiohttp

        form = aiohttp.FormData()
        form.add_field("file", path.read_bytes(), filename=path.name, content_type=mime_type)
        form.add_field("chatroomId", chatroom_id)
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        headers = {
            "Cookie": await self.socket_cookie_header(origin),
            "Origin": origin.rstrip("/"),
            "Referer": origin.rstrip("/") + "/",
        }
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout, trust_env=True) as session:
            async with session.post(
                f"{origin.rstrip('/')}/api/trpc/chatroom.uploadImage",
                data=form,
                proxy=proxy,
            ) as response:
                if not response.ok:
                    detail = (await response.text())[:300]
                    raise RuntimeError(f"DZMM 图片上传失败（HTTP {response.status}）：{detail}")
                body = await response.json()
        result = body.get("result", {}).get("data", {}).get("json", body)
        return result if isinstance(result, dict) else {}

    def _config(self) -> dict:
        path = self.data_dir / "config.json"
        if not path.exists():
            return {"dzmm": {"headless": False}}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)


_TOKEN_SCRIPT = """async () => {
  const response = await fetch('/api/auth/token');
  if (response.status === 401 || response.status === 403) {
    throw new Error(`Aikda access token unavailable status=${response.status}`);
  }
  const body = await response.json();
  if (!response.ok || !body.access_token) {
    throw new Error('Aikda access token unavailable');
  }
  return body.access_token;
}"""


_TRPC_SCRIPT = """async ({ procedure, payload, timeoutMs }) => {
  const input = { json: payload ?? null };
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(
      `/api/trpc/${procedure}?input=${encodeURIComponent(JSON.stringify(input))}`,
      { signal: controller.signal }
    );
    if (!response.ok) {
      throw new Error(`Aikda ${procedure} request failed status=${response.status}`);
    }
    const body = await response.json();
    return body?.result?.data?.json ?? body?.json ?? body?.[0]?.result?.data?.json;
  } finally {
    clearTimeout(timeout);
  }
}"""
