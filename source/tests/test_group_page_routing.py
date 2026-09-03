from __future__ import annotations

import asyncio

from app.browser import BrowserController
from app.dzmm_adapter import DzmmAdapter


MAIN_URL = "https://www.ainvmei.com/chat?c=11111111-1111-1111-1111-111111111111"
BOUNTY_URL = "https://www.ainvmei.com/chat?c=22222222-2222-2222-2222-222222222222"


class FakeLogger:
    def __init__(self):
        self.warnings = []
        self.errors = []

    def warning(self, text):
        self.warnings.append(text)

    def error(self, text):
        self.errors.append(text)

    def info(self, _text):
        pass


class FakePage:
    def __init__(self, url):
        self.url = url
        self.goto_calls = []
        self.evaluate_called = False

    def is_closed(self):
        return False

    async def goto(self, url, wait_until):
        self.goto_calls.append((url, wait_until))
        self.url = url

    async def evaluate(self, _script):
        self.evaluate_called = True
        return []


class FakeContext:
    async def new_page(self):
        raise AssertionError("已有群标签页不应新建页面")


class FakeDb:
    def __init__(self, lock_enabled=False):
        self.lock_enabled = lock_enabled

    def get_config(self):
        return {
            "dzmm": {
                "group_url": MAIN_URL,
                "bounty_group_url": BOUNTY_URL,
                "lock_group_urls": self.lock_enabled,
            },
            "selectors": {},
        }


class FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.calls = []

    async def ensure_group_page(self, _group_key, _url):
        self.calls.append((_group_key, _url))
        return self.page


def test_existing_bounty_page_is_restored_after_drifting_to_main(tmp_path):
    logger = FakeLogger()
    page = FakePage(MAIN_URL)
    browser = BrowserController(tmp_path, logger)
    browser.context = FakeContext()
    browser.pages = {"bounty": page}

    result = asyncio.run(browser.ensure_group_page("bounty", BOUNTY_URL))

    assert result is page
    assert page.goto_calls == [(BOUNTY_URL, "domcontentloaded")]
    assert logger.warnings


def test_adapter_refuses_to_label_main_page_as_bounty():
    logger = FakeLogger()
    page = FakePage(MAIN_URL)
    adapter = DzmmAdapter(FakeBrowser(page), FakeDb(), logger)

    messages = asyncio.run(adapter._read_recent_messages_by_dom_once("bounty"))

    assert messages == []
    assert page.evaluate_called is False
    assert logger.errors
    assert "拒绝读取串群页面" in logger.errors[0]


def test_group_page_lock_is_off_by_default_and_does_not_force_login_page():
    logger = FakeLogger()
    browser = FakeBrowser(FakePage("https://www.ainvmei.com/login"))
    adapter = DzmmAdapter(browser, FakeDb(), logger)

    asyncio.run(adapter.is_logged_in("main"))

    assert browser.calls == [("main", "")]


def test_group_page_lock_passes_configured_url_only_after_enabled():
    logger = FakeLogger()
    browser = FakeBrowser(FakePage("https://www.ainvmei.com/login"))
    adapter = DzmmAdapter(browser, FakeDb(lock_enabled=True), logger)

    asyncio.run(adapter.is_logged_in("main"))

    assert browser.calls == [("main", MAIN_URL)]


def test_chatroom_comparison_ignores_unrelated_query_parameters():
    current = MAIN_URL + "&tab=latest"

    assert BrowserController._same_chatroom(current, MAIN_URL)
    assert not BrowserController._same_chatroom(current, BOUNTY_URL)


def test_open_group_does_not_reload_the_current_chatroom():
    logger = FakeLogger()
    page = FakePage(MAIN_URL + "&tab=latest")
    browser = BrowserController(".", logger)
    browser.context = FakeContext()
    browser.page = page
    browser.pages = {"main": page}
    adapter = DzmmAdapter(browser, FakeDb(lock_enabled=True), logger)

    asyncio.run(adapter.open_group(MAIN_URL, "main"))

    assert page.goto_calls == []
