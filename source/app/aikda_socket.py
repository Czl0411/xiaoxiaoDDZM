from __future__ import annotations

import asyncio
import os
import re
import urllib.request
from collections import deque
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4


class AikdaAuthenticationError(RuntimeError):
    pass


class AikdaTransportError(RuntimeError):
    pass


class AikdaMessageRejectedError(RuntimeError):
    pass


class AikdaSocketGateway:
    def __init__(
        self,
        *,
        profile_provider: Callable[[], Awaitable[dict[str, Any]]],
        token_provider: Callable[[], Awaitable[str]],
        cookie_provider: Callable[[str], Awaitable[str]],
        socket_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._profile_provider = profile_provider
        self._token_provider = token_provider
        self._cookie_provider = cookie_provider
        self._socket_factory = socket_factory or self._new_socket
        self._socket = None
        self._origin = ""
        self._bot_id = ""
        self._rooms: dict[str, str] = {}
        self._room_keys: dict[str, str] = {}
        self._joined_rooms: set[str] = set()
        self._pending: dict[str, deque[dict[str, Any]]] = {}
        self._direct_pending: deque[dict[str, Any]] = deque()
        self._direct_rooms: set[str] = set()
        self._seen: set[tuple[str, str]] = set()
        self._seen_order: deque[tuple[str, str]] = deque()
        self._state_lock = asyncio.Lock()
        self._call_lock = asyncio.Lock()
        self._send_locks: dict[str, asyncio.Lock] = {}
        self._joined_event = asyncio.Event()
        self._message_handler: Callable[[dict[str, Any], str | None], None] | None = None

    def set_message_handler(
        self, handler: Callable[[dict[str, Any], str | None], None] | None
    ) -> None:
        self._message_handler = handler

    @staticmethod
    def _new_socket():
        import aiohttp
        import socketio

        proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or urllib.request.getproxies().get("https")
            or urllib.request.getproxies().get("http")
        )
        session = aiohttp.ClientSession(trust_env=True, proxy=proxy)
        return socketio.AsyncClient(reconnection=False, http_session=session)

    @staticmethod
    async def _close_socket_http(socket: Any) -> None:
        http = getattr(getattr(socket, "eio", None), "http", None)
        if http is not None and not http.closed:
            await http.close()

    async def configure_rooms(self, urls: dict[str, str]) -> None:
        async with self._state_lock:
            await self._configure_rooms_locked(urls)

    async def _configure_rooms_locked(self, urls: dict[str, str]) -> None:
        old_rooms = dict(self._rooms)
        rooms: dict[str, str] = {}
        origin = ""
        for key, url in urls.items():
            parsed = urlsplit(str(url or "").strip())
            chatroom_id = (parse_qs(parsed.query).get("c") or [""])[0].lower()
            if not parsed.scheme or not parsed.netloc or not chatroom_id:
                continue
            current_origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin and current_origin != origin:
                raise ValueError("all configured chatrooms must use the same origin")
            origin = current_origin
            rooms[key] = chatroom_id
        if self._socket is not None and origin != self._origin:
            await self.close()
        self._origin = origin
        self._rooms = rooms
        self._room_keys = {room_id: key for key, room_id in rooms.items()}
        self._joined_rooms.intersection_update(rooms.values())
        for key in rooms:
            self._pending.setdefault(key, deque())
            if old_rooms.get(key) not in (None, rooms[key]):
                self._pending[key].clear()
        for key in list(self._pending):
            if key not in rooms:
                self._pending.pop(key, None)

    async def maintain(self) -> None:
        async with self._state_lock:
            await self._ensure_connected_locked()
            for room_id in sorted(self._direct_rooms):
                if room_id in self._joined_rooms:
                    continue
                try:
                    await self._join_room(room_id, timeout=2)
                except Exception:
                    break

    async def configure_direct_rooms(self, room_ids: list[str]) -> None:
        self._direct_rooms = {str(room_id).strip() for room_id in room_ids if str(room_id).strip()}

    async def _ensure_connected_locked(self) -> None:
        if not self._origin:
            raise AikdaTransportError("no chatroom configured")
        if self._socket is not None and self._socket.connected and self._joined_event.is_set():
            await self._join_rooms()
            return
        profile = await self._profile_provider()
        self._bot_id = str(profile.get("id") or "")
        if not self._bot_id:
            raise AikdaAuthenticationError("bot identity unavailable")
        token = await self._token_provider()
        if not token:
            raise AikdaAuthenticationError("socket token unavailable")
        if self._socket is None:
            self._socket = self._socket_factory()
            self._socket.on("message:joined", self._on_joined)
            self._socket.on("message:new", self._on_message)
            self._socket.on("disconnect", self._on_disconnect)
        self._joined_event.clear()
        cookies = await self._cookie_provider(self._origin)
        options: dict[str, Any] = {
            "socketio_path": "ws/matching",
            "auth": {"token": token},
            "transports": ["websocket"],
        }
        if cookies:
            options["headers"] = {"Cookie": cookies}
        try:
            try:
                await self._socket.connect(self._origin, **options)
            except Exception:
                if self._socket.connected:
                    await self._socket.disconnect()
                fallback_options = {**options, "transports": ["polling"]}
                await self._socket.connect(self._origin, **fallback_options)
            await asyncio.wait_for(self._joined_event.wait(), timeout=10)
            await self._join_rooms()
        except (AikdaAuthenticationError, AikdaMessageRejectedError):
            raise
        except Exception as exc:
            await self._discard_socket()
            raise AikdaTransportError(str(exc) or type(exc).__name__) from exc

    async def _discard_socket(self) -> None:
        socket = self._socket
        self._socket = None
        self._joined_event.clear()
        self._joined_rooms.clear()
        if socket is not None and socket.connected:
            await socket.disconnect()
        if socket is not None:
            await self._close_socket_http(socket)

    async def _join_rooms(self) -> None:
        for room_id in sorted(self._rooms.values()):
            if room_id in self._joined_rooms:
                continue
            await self._join_room(room_id)

    async def _join_room(self, room_id: str, timeout: float = 10) -> None:
        if room_id in self._joined_rooms:
            return
        reply = await self._call(
            "message:join-room", {"chatroomId": room_id}, timeout=timeout
        )
        if not isinstance(reply, dict) or reply.get("success") is not True:
            raise AikdaTransportError(
                str(reply.get("error") if isinstance(reply, dict) else "room join failed")
            )
        self._joined_rooms.add(room_id)

    async def read_new(self, group_key: str) -> list[dict[str, Any]]:
        await self.maintain()
        pending = self._pending.setdefault(group_key, deque())
        messages = list(pending)
        pending.clear()
        return messages

    async def read_direct_new(self) -> list[dict[str, Any]]:
        await self.maintain()
        messages = list(self._direct_pending)
        self._direct_pending.clear()
        return messages

    def clear_pending(self) -> None:
        for pending in self._pending.values():
            pending.clear()
        self._direct_pending.clear()

    async def send_text(self, group_key: str, text: str) -> str:
        return await self._send(group_key, {"type": "text", "text": text})

    async def send_text_to_room(self, chatroom_id: str, text: str) -> str:
        room_id = str(chatroom_id or "").strip()
        if not room_id:
            raise AikdaTransportError("direct chatroom not configured")
        return await self._send_room(room_id, {"type": "text", "text": text})

    async def send_image(
        self,
        group_key: str,
        image_url: str,
        alt: str = "image",
        *,
        expected_room_id: str | None = None,
    ) -> str:
        return await self._send(
            group_key,
            {"type": "image", "url": image_url, "alt": alt or "image"},
            expected_room_id=expected_room_id,
        )

    async def _send(
        self,
        group_key: str,
        content: dict[str, Any],
        *,
        expected_room_id: str | None = None,
    ) -> str:
        async with self._send_locks.setdefault(group_key, asyncio.Lock()):
            async with self._state_lock:
                room_id = self._rooms.get(group_key, "")
                if not room_id:
                    raise AikdaTransportError(f"chatroom not configured: {group_key}")
                if expected_room_id is not None and room_id != expected_room_id:
                    raise AikdaTransportError("chatroom changed before message send")
                return await self._send_room_locked(room_id, content)

    async def _send_room(self, room_id: str, content: dict[str, Any]) -> str:
        async with self._send_locks.setdefault(room_id, asyncio.Lock()):
            async with self._state_lock:
                return await self._send_room_locked(room_id, content)

    async def _send_room_locked(self, room_id: str, content: dict[str, Any]) -> str:
        await self._ensure_connected_locked()
        await self._join_room(room_id)
        message_id = str(uuid4())
        message = {
            "message_id": message_id,
            "sent_by": self._bot_id,
            "chatroom_id": room_id,
            "sent_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "content": content,
        }
        try:
            reply = await self._call(
                "message:send", {"chatroomId": room_id, "message": message}, timeout=3
            )
        except Exception as exc:
            raise AikdaTransportError(str(exc) or type(exc).__name__) from exc
        if not isinstance(reply, dict) or reply.get("success") is not True:
            error = reply.get("error", "message acknowledgement failed") if isinstance(reply, dict) else "message acknowledgement failed"
            raise AikdaMessageRejectedError(str(error))
        return message_id

    async def _call(self, event: str, payload: dict[str, Any], *, timeout: float):
        async with self._call_lock:
            return await self._socket.call(event, payload, timeout=timeout)

    async def _on_joined(self, _payload=None) -> None:
        self._joined_event.set()

    async def _on_disconnect(self) -> None:
        self._joined_event.clear()
        self._joined_rooms.clear()

    async def _on_message(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        room_id = payload.get("chatroomId")
        message = payload.get("message")
        group_key = self._room_keys.get(room_id)
        if not isinstance(room_id, str) or not room_id or not isinstance(message, dict):
            return
        normalized = self._normalize_message(room_id, message)
        if normalized is None or normalized["sent_by"] == self._bot_id:
            return
        seen_key = (room_id, normalized["message_id"])
        if seen_key in self._seen:
            return
        self._seen.add(seen_key)
        self._seen_order.append(seen_key)
        while len(self._seen_order) > 1000:
            self._seen.discard(self._seen_order.popleft())
        if group_key is None:
            normalized["source_type"] = "direct"
            self._direct_rooms.add(room_id)
        handler = self._message_handler
        if handler is not None:
            handler(normalized, group_key)
        elif group_key is None:
            self._direct_pending.append(normalized)
        else:
            self._pending.setdefault(group_key, deque()).append(normalized)

    @classmethod
    def _normalize_message(cls, room_id: str, message: dict[str, Any]):
        message_id = message.get("message_id")
        sent_by = message.get("sent_by")
        sent_at = message.get("sent_at")
        content = message.get("content")
        if not all(isinstance(value, str) and value for value in (message_id, sent_by, sent_at)) or not isinstance(content, dict):
            return None
        try:
            datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        content_type = content.get("type")
        image_url = image_alt = None
        image_width = image_height = None
        if content_type == "text":
            text = content.get("text")
            if not isinstance(text, str):
                return None
        elif content_type == "system":
            text = content.get("text")
            if not isinstance(text, str):
                return None
            portal_join = re.fullmatch(
                r"\s*(?P<newcomer>.+?)\s+通过\s+(?P<inviter>.+?)\s+的链接加入了群聊\s*",
                text,
            )
            if portal_join is None:
                return None
        elif content_type == "image":
            image_url = content.get("url")
            parsed = urlsplit(image_url) if isinstance(image_url, str) else None
            if parsed is None or parsed.scheme != "https" or not parsed.netloc:
                return None
            image_alt = content.get("alt")
            image_width = content.get("width")
            image_height = content.get("height")
            if image_alt is not None and not isinstance(image_alt, str):
                return None
            if any(value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1) for value in (image_width, image_height)):
                return None
            text = "[图片]"
        else:
            return None
        normalized = {
            "message_id": message_id,
            "sent_by": sent_by,
            "sent_at": sent_at,
            "text": text,
            "content_type": content_type,
            "image_url": image_url,
            "image_alt": image_alt,
            "image_width": image_width,
            "image_height": image_height,
            "reference": cls._normalize_reference(content.get("reference")),
            "chatroom_id": room_id,
        }
        if content_type == "system":
            normalized.update(
                {
                    "event_type": "member_joined_by_invite",
                    "newcomer_name": portal_join.group("newcomer").strip(),
                    "inviter_name": portal_join.group("inviter").strip(),
                }
            )
        return normalized

    @staticmethod
    def _normalize_reference(reference: Any):
        if not isinstance(reference, dict) or not isinstance(reference.get("content"), dict):
            return None
        message_id = reference.get("id")
        sent_by = reference.get("sentBy")
        content = reference["content"]
        if not isinstance(message_id, str) or not message_id or not isinstance(sent_by, str) or not sent_by:
            return None
        if content.get("type") == "text":
            text = content.get("text")
        elif content.get("type") == "image":
            text = "[图片]"
        else:
            return None
        if not isinstance(text, str):
            return None
        return {"message_id": message_id, "sent_by": sent_by, "text": text}

    async def close(self) -> None:
        socket = self._socket
        self._socket = None
        self._joined_event.clear()
        self._joined_rooms.clear()
        if socket is not None and socket.connected:
            await socket.disconnect()
        if socket is not None:
            await self._close_socket_http(socket)
