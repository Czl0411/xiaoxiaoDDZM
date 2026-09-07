from __future__ import annotations

import asyncio

from app.aikda_socket import AikdaMessageRejectedError, AikdaSocketGateway


MAIN_URL = "https://www.ainvmei.com/chat?c=11111111-1111-1111-1111-111111111111"
IMAGE_URL = "https://www.ainvmei.com/chat?c=22222222-2222-2222-2222-222222222222"
OTHER_URL = "https://chat.example.com/chat?c=33333333-3333-3333-3333-333333333333"
REPLACEMENT_URL = "https://www.ainvmei.com/chat?c=33333333-3333-3333-3333-333333333333"
DIRECT_ID = "44444444-4444-4444-4444-444444444444"


class FakeSocket:
    def __init__(self):
        self.connected = False
        self.handlers = {}
        self.connect_calls = []
        self.calls = []
        self.call_results = {}
        self.emit_joined = True
        self.disconnect_count = 0
        self.active_calls = 0
        self.max_active_calls = 0
        self.yield_calls = False
        self.fail_websocket = False

    def on(self, event, handler):
        self.handlers[event] = handler

    async def connect(self, url, **options):
        self.connect_calls.append((url, options))
        if self.fail_websocket and options.get("transports") == ["websocket"]:
            raise OSError("websocket blocked")
        self.connected = True
        if self.emit_joined:
            await self.handlers["message:joined"]({})

    async def call(self, event, payload, timeout):
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        if self.yield_calls:
            await asyncio.sleep(0)
        self.calls.append((event, payload, timeout))
        self.active_calls -= 1
        return self.call_results.get(event, {"success": True})

    async def disconnect(self):
        self.disconnect_count += 1
        self.connected = False
        handler = self.handlers.get("disconnect")
        if handler:
            await handler()

    async def trigger(self, event, payload):
        await self.handlers[event](payload)


def make_gateway(socket):
    async def profile():
        return {"id": "bot-id", "fullName": "机器人"}

    async def token():
        return "access-token"

    async def cookies(_origin):
        return "session=cookie"

    return AikdaSocketGateway(
        profile_provider=profile,
        token_provider=token,
        cookie_provider=cookies,
        socket_factory=lambda: socket,
    )


def test_incoming_message_is_enriched_with_cached_user_profile():
    async def run():
        socket = FakeSocket()
        calls = []

        async def user_profile(user_id, chatroom_id):
            calls.append((user_id, chatroom_id))
            return {
                "fullName": "真实昵称",
                "avatarUrl": "https://cdn.example/avatar/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.png",
            }

        gateway = make_gateway(socket)
        gateway._user_profile_provider = user_profile
        await gateway.configure_rooms({"main": MAIN_URL})
        await gateway.maintain()
        for message_id in ("m1", "m2"):
            await socket.trigger("message:new", {
                "chatroomId": "11111111-1111-1111-1111-111111111111",
                "message": {
                    "message_id": message_id,
                    "sent_by": "person-id",
                    "sent_at": "2026-09-07T01:00:00Z",
                    "content": {"type": "text", "text": "你好"},
                },
            })

        messages = await gateway.read_new("main")
        assert [item["sender_name"] for item in messages] == ["真实昵称", "真实昵称"]
        assert messages[0]["avatar_url"].endswith("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.png")
        assert calls == [("person-id", "11111111-1111-1111-1111-111111111111")]

    asyncio.run(run())


def test_default_async_client_uses_operating_system_https_proxy(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.setattr(
        "urllib.request.getproxies",
        lambda: {"https": "http://127.0.0.1:7897"},
    )

    async def run():
        socket = AikdaSocketGateway._new_socket()
        try:
            assert socket.eio.http._trust_env is True
            assert str(socket.eio.http._default_proxy) == "http://127.0.0.1:7897"
        finally:
            await socket.eio.http.close()

    asyncio.run(run())


def test_connects_with_browser_credentials_and_joins_all_rooms():
    async def run():
        socket = FakeSocket()
        gateway = make_gateway(socket)
        await gateway.configure_rooms({"main": MAIN_URL, "image": IMAGE_URL})
        await gateway.maintain()

        assert socket.connect_calls == [
            (
                "https://www.ainvmei.com",
                {
                    "socketio_path": "ws/matching",
                    "auth": {"token": "access-token"},
                    "headers": {"Cookie": "session=cookie"},
                    "transports": ["websocket"],
                },
            )
        ]
        joins = [call for call in socket.calls if call[0] == "message:join-room"]
        assert joins == [
            ("message:join-room", {"chatroomId": "11111111-1111-1111-1111-111111111111"}, 10),
            ("message:join-room", {"chatroomId": "22222222-2222-2222-2222-222222222222"}, 10),
        ]

    asyncio.run(run())


def test_websocket_connection_failure_falls_back_to_polling():
    async def run():
        socket = FakeSocket()
        socket.fail_websocket = True
        gateway = make_gateway(socket)
        await gateway.configure_rooms({"main": MAIN_URL})

        await gateway.maintain()

        assert [call[1]["transports"] for call in socket.connect_calls] == [
            ["websocket"],
            ["polling"],
        ]

    asyncio.run(run())


def test_empty_configuration_closes_old_origin_before_new_origin():
    async def run():
        socket = FakeSocket()
        gateway = make_gateway(socket)
        await gateway.configure_rooms({"main": MAIN_URL})
        await gateway.maintain()

        await gateway.configure_rooms({})
        assert socket.connected is False

        await gateway.configure_rooms({"main": OTHER_URL})
        await gateway.maintain()
        assert socket.connect_calls[-1][0] == "https://chat.example.com"

    asyncio.run(run())


def test_room_reconfiguration_waits_for_inflight_send_state():
    async def run():
        socket = FakeSocket()
        profile_started = asyncio.Event()
        release_profile = asyncio.Event()
        profile_calls = 0

        async def profile():
            nonlocal profile_calls
            profile_calls += 1
            if profile_calls == 2:
                profile_started.set()
                await release_profile.wait()
            return {"id": "bot-id"}

        async def token():
            return "token"

        async def cookies(_origin):
            return ""

        gateway = AikdaSocketGateway(
            profile_provider=profile,
            token_provider=token,
            cookie_provider=cookies,
            socket_factory=lambda: socket,
        )
        await gateway.configure_rooms({"main": MAIN_URL})
        await gateway.maintain()
        await socket.disconnect()

        sending = asyncio.create_task(gateway.send_text("main", "old room message"))
        await profile_started.wait()
        reconfiguring = asyncio.create_task(gateway.configure_rooms({"main": OTHER_URL}))
        await asyncio.sleep(0)
        assert reconfiguring.done() is False
        release_profile.set()
        await sending
        await reconfiguring

        send = next(call for call in socket.calls if call[0] == "message:send")
        assert send[1]["chatroomId"] == "11111111-1111-1111-1111-111111111111"

    asyncio.run(run())


def test_joined_timeout_cleans_partial_connection_for_next_recovery(monkeypatch):
    async def run():
        socket = FakeSocket()
        socket.emit_joined = False
        gateway = make_gateway(socket)
        await gateway.configure_rooms({"main": MAIN_URL})

        real_wait_for = asyncio.wait_for

        async def immediate_timeout(awaitable, timeout):
            if timeout == 10:
                if hasattr(awaitable, "close"):
                    awaitable.close()
                raise TimeoutError()
            return await real_wait_for(awaitable, timeout)

        monkeypatch.setattr(asyncio, "wait_for", immediate_timeout)
        try:
            await gateway.maintain()
        except Exception:
            pass
        else:
            raise AssertionError("missing message:joined must fail")

        assert socket.connected is False
        assert socket.disconnect_count == 1

    asyncio.run(run())


def test_routes_valid_messages_and_deduplicates_platform_id():
    async def run():
        socket = FakeSocket()
        gateway = make_gateway(socket)
        await gateway.configure_rooms({"main": MAIN_URL})
        await gateway.maintain()
        payload = {
            "chatroomId": "11111111-1111-1111-1111-111111111111",
            "message": {
                "message_id": "message-1",
                "sent_by": "user-1",
                "sent_at": "2026-09-02T01:02:03Z",
                "content": {"type": "text", "text": "/签到"},
            },
        }
        await socket.trigger("message:new", payload)
        await socket.trigger("message:new", payload)

        assert await gateway.read_new("main") == [
            {
                "message_id": "message-1",
                "sent_by": "user-1",
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
        assert await gateway.read_new("main") == []

    asyncio.run(run())


def test_normalizes_portal_join_system_message_without_treating_it_as_chat():
    normalized = AikdaSocketGateway._normalize_message(
        "11111111-1111-1111-1111-111111111111",
        {
            "message_id": "portal-join-1",
            "sent_by": "system",
            "sent_at": "2026-09-04T01:19:00Z",
            "content": {
                "type": "system",
                "text": "鸿鸿鸿 通过 紫苑 的链接加入了群聊",
            },
        },
    )

    assert normalized["event_type"] == "member_joined_by_invite"
    assert normalized["newcomer_name"] == "鸿鸿鸿"
    assert normalized["inviter_name"] == "紫苑"
    assert normalized["text"] == "鸿鸿鸿 通过 紫苑 的链接加入了群聊"


def test_does_not_classify_ordinary_text_as_portal_join_event():
    normalized = AikdaSocketGateway._normalize_message(
        "11111111-1111-1111-1111-111111111111",
        {
            "message_id": "ordinary-1",
            "sent_by": "user-1",
            "sent_at": "2026-09-04T01:20:00Z",
            "content": {"type": "text", "text": "我通过 紫苑 的链接加入了群聊"},
        },
    )

    assert "event_type" not in normalized


def test_message_handler_receives_event_immediately_without_polling_buffer():
    async def run():
        socket = FakeSocket()
        gateway = make_gateway(socket)
        received = []
        gateway.set_message_handler(lambda message, group_key: received.append((group_key, message)))
        await gateway.configure_rooms({"main": MAIN_URL})
        await gateway.maintain()

        await socket.trigger("message:new", {
            "chatroomId": "11111111-1111-1111-1111-111111111111",
            "message": {
                "message_id": "event-message-1",
                "sent_by": "user-1",
                "sent_at": "2026-09-02T01:02:03Z",
                "content": {"type": "text", "text": "/签到"},
            },
        })

        assert received[0][0] == "main"
        assert received[0][1]["message_id"] == "event-message-1"
        assert await gateway.read_new("main") == []

    asyncio.run(run())


def test_unknown_room_event_is_buffered_as_direct_message():
    async def run():
        socket = FakeSocket()
        gateway = make_gateway(socket)
        await gateway.configure_rooms({"main": MAIN_URL})
        await gateway.maintain()
        await socket.trigger(
            "message:new",
            {
                "chatroomId": DIRECT_ID,
                "message": {
                    "message_id": "direct-message-1",
                    "sent_by": "direct-user",
                    "sent_at": "2026-09-03T01:02:03Z",
                    "content": {"type": "text", "text": "/查看市场"},
                },
            },
        )

        result = await gateway.read_direct_new()
        assert result[0]["chatroom_id"] == DIRECT_ID
        assert result[0]["source_type"] == "direct"
        assert result[0]["text"] == "/查看市场"

    asyncio.run(run())


def test_send_text_to_direct_room_joins_and_sends():
    async def run():
        socket = FakeSocket()
        gateway = make_gateway(socket)
        await gateway.configure_rooms({"main": MAIN_URL})

        message_id = await gateway.send_text_to_room(DIRECT_ID, "私聊回复")

        assert message_id
        joins = [call for call in socket.calls if call[0] == "message:join-room"]
        assert any(call[1]["chatroomId"] == DIRECT_ID for call in joins)
        send = [call for call in socket.calls if call[0] == "message:send"][-1]
        assert send[1]["chatroomId"] == DIRECT_ID
        assert send[1]["message"]["content"]["text"] == "私聊回复"

    asyncio.run(run())


def test_replacing_room_for_same_group_discards_old_pending_messages():
    async def run():
        socket = FakeSocket()
        gateway = make_gateway(socket)
        await gateway.configure_rooms({"main": MAIN_URL})
        await gateway.maintain()
        await socket.trigger(
            "message:new",
            {
                "chatroomId": "11111111-1111-1111-1111-111111111111",
                "message": {
                    "message_id": "old-room-message",
                    "sent_by": "user-1",
                    "sent_at": "2026-09-02T01:02:03Z",
                    "content": {"type": "text", "text": "/签到"},
                },
            },
        )

        await gateway.configure_rooms({"main": REPLACEMENT_URL})

        assert await gateway.read_new("main") == []

    asyncio.run(run())


def test_send_text_requires_success_ack_and_never_retries_rejection():
    async def run():
        socket = FakeSocket()
        socket.call_results["message:send"] = {"success": False, "error": "denied"}
        gateway = make_gateway(socket)
        await gateway.configure_rooms({"main": MAIN_URL})

        try:
            await gateway.send_text("main", "第一行\n第二行")
        except AikdaMessageRejectedError as exc:
            assert str(exc) == "denied"
        else:
            raise AssertionError("rejected message must raise")

        sends = [call for call in socket.calls if call[0] == "message:send"]
        assert len(sends) == 1
        message = sends[0][1]["message"]
        assert sends[0][1]["chatroomId"] == "11111111-1111-1111-1111-111111111111"
        assert message["sent_by"] == "bot-id"
        assert message["chatroom_id"] == "11111111-1111-1111-1111-111111111111"
        assert message["content"] == {"type": "text", "text": "第一行\n第二行"}
        assert sends[0][2] == 3

    asyncio.run(run())


def test_calls_across_rooms_are_serialized_on_one_socket_client():
    async def run():
        socket = FakeSocket()
        socket.yield_calls = True
        gateway = make_gateway(socket)
        await gateway.configure_rooms({"main": MAIN_URL, "image": IMAGE_URL})
        await gateway.maintain()
        socket.max_active_calls = 0

        await asyncio.gather(
            gateway.send_text("main", "群一"),
            gateway.send_text("image", "群二"),
        )

        assert socket.max_active_calls == 1

    asyncio.run(run())


def test_image_and_reference_payloads_are_normalized():
    async def run():
        socket = FakeSocket()
        gateway = make_gateway(socket)
        await gateway.configure_rooms({"image": IMAGE_URL})
        await gateway.maintain()
        await socket.trigger(
            "message:new",
            {
                "chatroomId": "22222222-2222-2222-2222-222222222222",
                "message": {
                    "message_id": "image-1",
                    "sent_by": "user-2",
                    "sent_at": "2026-09-02T02:03:04+00:00",
                    "content": {
                        "type": "image",
                        "url": "https://cdn.example/p.png",
                        "alt": "图片",
                        "width": 640,
                        "height": 480,
                        "reference": {
                            "id": "quoted-1",
                            "sentBy": "user-3",
                            "content": {"type": "text", "text": "原消息"},
                        },
                    },
                },
            },
        )
        result = (await gateway.read_new("image"))[0]
        assert result["text"] == "[图片]"
        assert result["image_url"] == "https://cdn.example/p.png"
        assert result["image_width"] == 640
        assert result["reference"] == {
            "message_id": "quoted-1",
            "sent_by": "user-3",
            "text": "原消息",
        }

    asyncio.run(run())


def test_image_send_rejects_changed_expected_room_without_emitting():
    async def run():
        socket = FakeSocket()
        gateway = make_gateway(socket)
        await gateway.configure_rooms({"image": IMAGE_URL})
        await gateway.configure_rooms({"image": REPLACEMENT_URL})

        try:
            await gateway.send_image(
                "image",
                "https://cdn.example/old-room.png",
                "old.png",
                expected_room_id="22222222-2222-2222-2222-222222222222",
            )
        except Exception as exc:
            assert "changed" in str(exc)
        else:
            raise AssertionError("changed image room must be rejected")
        assert not [call for call in socket.calls if call[0] == "message:send"]

    asyncio.run(run())


def test_invalid_timestamp_and_unknown_reference_type_are_not_trusted():
    invalid = {
        "message_id": "bad-time",
        "sent_by": "user-1",
        "sent_at": "not-a-time",
        "content": {"type": "text", "text": "hello"},
    }
    assert AikdaSocketGateway._normalize_message("room", invalid) is None

    valid = {
        **invalid,
        "message_id": "valid",
        "sent_at": "2026-09-02T01:02:03Z",
        "content": {
            "type": "text",
            "text": "hello",
            "reference": {
                "id": "quoted",
                "sentBy": "user-2",
                "content": {"type": "video", "url": "https://example/video"},
            },
        },
    }
    assert AikdaSocketGateway._normalize_message("room", valid)["reference"] is None
