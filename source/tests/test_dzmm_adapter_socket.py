from __future__ import annotations

import asyncio

from app.dzmm_adapter import DzmmAdapter


MAIN_URL = "https://www.ainvmei.com/chat?c=11111111-1111-1111-1111-111111111111"


class FakeDb:
    def get_config(self):
        return {"dzmm": {"group_url": MAIN_URL}}

    def get_user(self, identity):
        if identity.get("platform_user_id") == "known-id":
            return {"nickname": "已知用户"}
        return None

    def list_direct_chatroom_ids(self):
        return ["direct-room"]


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
    async def ensure_page(self):
        return object()

    async def socket_profile(self):
        return {"id": "bot"}

    async def socket_token(self):
        return "token"

    async def socket_cookie_header(self, _origin):
        return "cookie=x"


class LoggedOutBrowser(FakeBrowser):
    async def socket_profile(self):
        raise RuntimeError("status=401")


class FakeGateway:
    def __init__(self):
        self.rooms = []
        self.sent = []
        self.messages = []
        self.cleared = False
        self.closed = False
        self.direct_messages = []
        self.direct_rooms = []

    async def configure_rooms(self, rooms):
        self.rooms.append(rooms)

    async def read_new(self, group_key):
        result, self.messages = self.messages, []
        return result

    async def configure_direct_rooms(self, room_ids):
        self.direct_rooms = list(room_ids)

    async def read_direct_new(self):
        result, self.direct_messages = self.direct_messages, []
        return result

    async def send_text_to_room(self, chatroom_id, text):
        self.sent.append(("direct", chatroom_id, text))
        return "direct-outbound-id"

    async def send_text(self, group_key, text):
        self.sent.append((group_key, text))
        return "outbound-id"

    async def send_image(self, group_key, url, alt, **_kwargs):
        self.sent.append((group_key, url, alt))
        return "outbound-image-id"

    def clear_pending(self):
        self.cleared = True

    async def close(self):
        self.closed = True


def test_adapter_reads_socket_messages_with_stable_platform_identity():
    async def run():
        gateway = FakeGateway()
        gateway.messages = [
            {
                "message_id": "message-1",
                "sent_by": "known-id",
                "sent_at": "2026-09-02T01:02:03Z",
                "text": "/签到",
                "content_type": "text",
                "image_url": None,
                "image_alt": None,
                "image_width": None,
                "image_height": None,
                "reference": None,
                "chatroom_id": "11111111-1111-1111-1111-111111111111",
            }
        ]
        adapter = DzmmAdapter(
            FakeBrowser(), FakeDb(), FakeLogger(), gateway_factory=lambda **_kwargs: gateway
        )

        messages = await adapter.read_recent_messages("main")

        assert messages[0]["message_id"] == "message-1"
        assert messages[0]["platform_user_id"] == "known-id"
        assert messages[0]["user_id"] == "known-id"
        assert messages[0]["sender"] == "已知用户"
        assert messages[0]["identity_source"] == "platform"
        assert messages[0]["source_stable"] is True
        assert gateway.rooms == [{"main": MAIN_URL}]

    asyncio.run(run())


def test_adapter_preserves_portal_join_event_for_scheduler():
    adapter = DzmmAdapter(FakeBrowser(), FakeDb(), FakeLogger())
    messages = adapter._normalize_socket_messages(
        [{
            "message_id": "join-1", "sent_by": "system",
            "sent_at": "2026-09-04T01:19:00Z",
            "text": "鸿鸿鸿 通过 紫苑 的链接加入了群聊",
            "content_type": "system", "chatroom_id": "room-1",
            "event_type": "member_joined_by_invite",
            "newcomer_name": "鸿鸿鸿", "inviter_name": "紫苑",
        }],
        "main",
    )
    assert messages[0]["sender"] == "系统"
    assert messages[0]["platform_user_id"] == ""
    assert messages[0]["event_type"] == "member_joined_by_invite"
    assert messages[0]["newcomer_name"] == "鸿鸿鸿"
    assert messages[0]["inviter_name"] == "紫苑"


def test_adapter_sends_text_through_socket_and_cleans_up():
    async def run():
        gateway = FakeGateway()
        adapter = DzmmAdapter(
            FakeBrowser(), FakeDb(), FakeLogger(), gateway_factory=lambda **_kwargs: gateway
        )

        assert await adapter.send_message("第一行\n第二行") is True
        assert gateway.sent == [("main", "第一行\n第二行")]
        adapter.clear_pending_messages()
        await adapter.close()
        assert gateway.cleared is True
        assert gateway.closed is True

    asyncio.run(run())


def test_adapter_reads_and_sends_direct_socket_messages():
    async def run():
        gateway = FakeGateway()
        gateway.direct_messages = [
            {
                "message_id": "direct-1",
                "sent_by": "known-id",
                "sent_at": "2026-09-03T01:02:03Z",
                "text": "/查看市场",
                "content_type": "text",
                "reference": None,
                "chatroom_id": "direct-room",
                "source_type": "direct",
            }
        ]
        adapter = DzmmAdapter(
            FakeBrowser(), FakeDb(), FakeLogger(), gateway_factory=lambda **_kwargs: gateway
        )

        messages = await adapter.read_direct_messages()
        sent = await adapter.send_direct_message("direct-room", "私聊指引")

        assert messages[0]["source_type"] == "direct"
        assert messages[0]["chatroom_id"] == "direct-room"
        assert messages[0]["group_key"] == "direct:direct-room"
        assert gateway.direct_rooms == ["direct-room"]
        assert sent is True
        assert gateway.sent[-1] == ("direct", "direct-room", "私聊指引")

    asyncio.run(run())


def test_adapter_login_status_uses_authenticated_profile_not_dom_messages():
    async def run():
        logged_in = DzmmAdapter(FakeBrowser(), FakeDb(), FakeLogger())
        logged_out = DzmmAdapter(LoggedOutBrowser(), FakeDb(), FakeLogger())

        assert await logged_in.is_logged_in() is True
        assert await logged_out.is_logged_in() is False

    asyncio.run(run())
