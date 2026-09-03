from __future__ import annotations

import asyncio

from app.dzmm_adapter import DzmmAdapter


GROUP_URL = "https://www.ainvmei.com/chat?c=11111111-1111-1111-1111-111111111111"


class FakeDb:
    def get_config(self):
        return {"dzmm": {"group_url": GROUP_URL}}


class FakeLogger:
    def __init__(self):
        self.errors = []

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, message, **_kwargs):
        self.errors.append(str(message))


class FakeBrowser:
    async def socket_profile(self):
        return {"id": "bot"}

    async def socket_token(self):
        return "token"

    async def socket_cookie_header(self, _origin):
        return "cookie=x"


class SerialGateway:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.sent = []

    async def configure_rooms(self, _rooms):
        pass

    async def send_text(self, group_key, text):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.sent.append((group_key, text))
        self.active -= 1
        return "message-id"


def test_text_send_uses_socket_and_preserves_newlines():
    async def run():
        gateway = SerialGateway()
        adapter = DzmmAdapter(
            FakeBrowser(), FakeDb(), FakeLogger(), gateway_factory=lambda **_kwargs: gateway
        )

        assert await adapter.send_message("第一行\n第二行") is True
        assert gateway.sent == [("main", "第一行\n第二行")]

    asyncio.run(run())


def test_text_sends_to_same_group_are_serialized():
    async def run():
        gateway = SerialGateway()
        adapter = DzmmAdapter(
            FakeBrowser(), FakeDb(), FakeLogger(), gateway_factory=lambda **_kwargs: gateway
        )

        results = await asyncio.gather(
            adapter.send_message("消息一", "main"),
            adapter.send_message("消息二", "main"),
        )

        assert results == [True, True]
        assert gateway.max_active == 1

    asyncio.run(run())
