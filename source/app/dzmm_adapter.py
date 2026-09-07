from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import hashlib
import json
import re
import time
import unicodedata
import uuid
import mimetypes
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from app.aikda_socket import AikdaSocketGateway

from app.outgoing_text import (
    MAX_OUTGOING_CHARS,
    MAX_OUTGOING_LINES,
    normalize_outgoing_text,
    outgoing_char_count,
    outgoing_line_count,
)


class DzmmAdapter:
    def __init__(self, browser, db, logger, gateway_factory=None):
        self.browser = browser
        self.db = db
        self.logger = logger
        self.self_name = "我"
        self.platform_message_cache: dict[str, dict[str, Any]] = {}
        self.platform_message_cache_order: deque[str] = deque()
        self.dom_observation_state: dict[str, list[dict[str, str]]] = {}
        self.platform_api_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self.platform_api_backoff_until: dict[str, float] = {}
        self.platform_api_failures: dict[str, int] = {}
        self.platform_api_last_error_log: dict[str, float] = {}
        self.avatar_conflict_logged: set[str] = set()
        self._text_send_locks: dict[str, asyncio.Lock] = {}
        self._gateway_factory = gateway_factory or AikdaSocketGateway
        self._gateway = None
        self._message_handler = None

    def set_message_handler(self, handler) -> None:
        self._message_handler = handler
        if self._gateway is not None and hasattr(self._gateway, "set_message_handler"):
            self._gateway.set_message_handler(self._dispatch_socket_message if handler else None)

    def _dispatch_socket_message(self, message: dict[str, Any], group_key: str | None) -> None:
        source = group_key or "direct"
        normalized = self._normalize_socket_messages([message], source)
        if normalized and self._message_handler is not None:
            self._message_handler(normalized[0])

    def group_url(self, group_key: str = "main") -> str:
        dzmm = self.db.get_config().get("dzmm", {})
        if group_key == "bounty":
            return str(dzmm.get("bounty_group_url") or "").strip()
        if group_key == "image":
            return str(dzmm.get("image_group_url") or "").strip()
        return str(dzmm.get("group_url") or "").strip()

    def group_url_lock_enabled(self) -> bool:
        return bool(self.db.get_config().get("dzmm", {}).get("lock_group_urls", False))

    async def _group_page(self, group_key: str = "main"):
        # 未登录的新设备必须能够停留在登录页。只有管理员明确开启地址锁定后，
        # 状态检测、轮询和发送流程才允许把标签页纠正回配置的群聊。
        url = self.group_url(group_key) if self.group_url_lock_enabled() else ""
        if hasattr(self.browser, "ensure_group_page"):
            return await self.browser.ensure_group_page(group_key, url)
        return await self.browser.ensure_page()

    async def open_home(self) -> None:
        url = self.db.get_config().get("dzmm", {}).get("home_url") or "https://www.aikda.com"
        page = await self.browser.ensure_page()
        await page.goto(url, wait_until="domcontentloaded")
        self.logger.info("已打开 DZMM 首页")

    async def open_group(self, url: str, group_key: str = "main") -> None:
        prefix = f"{group_key}:"
        for key in [key for key in self.platform_message_cache if key.startswith(prefix)]:
            self.platform_message_cache.pop(key, None)
        self.platform_message_cache_order = deque(
            key for key in self.platform_message_cache_order if not key.startswith(prefix)
        )
        self.dom_observation_state.pop(group_key, None)
        page = (
            await self.browser.ensure_group_page(group_key)
            if hasattr(self.browser, "ensure_group_page")
            else await self.browser.ensure_page()
        )
        same_chatroom = getattr(self.browser, "_same_chatroom", None)
        if callable(same_chatroom) and same_chatroom(page.url, url):
            self.logger.info(f"{group_key}群聊页已在目标地址，跳过重复刷新：{url}")
            return
        navigate_group = getattr(self.browser, "_navigate_group_page", None)
        if callable(navigate_group):
            await navigate_group(page, url)
        else:
            await page.goto(url, wait_until="domcontentloaded")
        self.logger.info(f"已打开{group_key}群聊页面：{url}")

    async def is_logged_in(self, group_key: str = "main") -> bool:
        try:
            await self._group_page(group_key)
            profile = await self.browser.socket_profile()
            return isinstance(profile, dict) and bool(profile.get("id"))
        except Exception:
            return False

    async def detect_selectors(self) -> dict[str, str]:
        page = await self.browser.ensure_page()
        observed = {
            "message_list": "div.pt-10.pb-4.px-2.flex-1.min-h-0.overflow-y-auto.overflow-x-hidden.relative",
            "message_item": "div.pt-10.pb-4.px-2.flex-1.min-h-0.overflow-y-auto.overflow-x-hidden.relative > div > div",
            "sender": ".text-xs.font-medium.text-muted-foreground span",
            "message_text": "span.whitespace-pre-wrap.break-words.w-full",
            "message_time": "",
            "self_message": ".items-end",
            "input_box": "textarea[placeholder='输入消息 (Shift+Enter 换行)']",
            "send_button": "",
        }
        try:
            if await page.locator(observed["input_box"]).count() > 0:
                self.logger.info("已识别到当前 DZMM 群聊页面结构")
                return observed
        except Exception:
            pass
        self.logger.warning("页面结构识别不完整，请确认已进入 DZMM 群聊页面")
        return observed

    async def validate_selectors(self) -> tuple[bool, str]:
        selectors = self.db.get_config().get("selectors", {})
        page = await self.browser.ensure_page()
        for key in ["message_item", "input_box"]:
            sel = selectors.get(key)
            if not sel:
                return False, f"缺少选择器：{key}"
            try:
                if await page.locator(sel).count() == 0:
                    return False, f"页面上找不到：{key} = {sel}"
            except Exception as exc:
                return False, f"选择器错误：{key} = {sel}，{exc}"
        return True, "选择器可用"

    async def read_recent_messages(self, group_key: str = "main") -> list[dict[str, Any]]:
        gateway = await self._socket_gateway()
        messages = await gateway.read_new(group_key)
        return self._normalize_socket_messages(messages, group_key)

    async def read_direct_messages(self) -> list[dict[str, Any]]:
        gateway = await self._socket_gateway()
        await gateway.configure_direct_rooms(self.db.list_direct_chatroom_ids())
        messages = await gateway.read_direct_new()
        return self._normalize_socket_messages(messages, "direct")

    def _normalize_socket_messages(
        self, messages: list[dict[str, Any]], group_key: str
    ) -> list[dict[str, Any]]:
        results = []
        for message in messages:
            is_portal_join = message.get("event_type") == "member_joined_by_invite"
            platform_user_id = str(message.get("sent_by") or "").strip().lower()
            user = self.db.get_user({"platform_user_id": platform_user_id}) if platform_user_id else None
            sender = str(message.get("sender_name") or (user or {}).get("nickname") or "").strip()
            avatar_id = str(message.get("avatar_id") or "").strip().lower()
            if not avatar_id:
                avatar_match = re.search(
                    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                    str(message.get("avatar_url") or ""),
                    re.IGNORECASE,
                )
                avatar_id = avatar_match.group(0).lower() if avatar_match else ""
            if is_portal_join:
                sender = "系统"
                platform_user_id = ""
            elif not sender:
                sender = f"用户-{platform_user_id[:8]}" if platform_user_id else "未知用户"
            reference = message.get("reference") or {}
            sent_at = str(message.get("sent_at") or "")
            try:
                display_time = datetime.fromisoformat(sent_at.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
            except ValueError:
                display_time = datetime.now().strftime("%H:%M:%S")
            chatroom_id = str(message.get("chatroom_id") or "")
            is_direct = str(message.get("source_type") or "") == "direct"
            source_key = f"direct:{chatroom_id}" if is_direct else group_key
            results.append(
                {
                    "message_id": str(message.get("message_id") or ""),
                    "user_id": platform_user_id,
                    "platform_user_id": platform_user_id,
                    "identity_source": "platform",
                    "avatar_id": avatar_id,
                    "gender": "unknown",
                    "sender": sender,
                    "text": str(message.get("text") or ""),
                    "time": display_time,
                    "is_self": False,
                    "raw_html": "",
                    "reply_to_message_id": str(reference.get("message_id") or ""),
                    "reply_to_text": str(reference.get("text") or ""),
                    "reply_to_sender": str(reference.get("sent_by") or ""),
                    "source_index": str(message.get("message_id") or ""),
                    "source_stable": True,
                    "group_key": source_key,
                    "source_group": source_key,
                    "source_type": "direct" if is_direct else "group",
                    "chatroom_id": chatroom_id,
                    "content_type": message.get("content_type"),
                    "image_url": message.get("image_url"),
                    "image_alt": message.get("image_alt"),
                    "image_width": message.get("image_width"),
                    "image_height": message.get("image_height"),
                    "event_type": message.get("event_type"),
                    "newcomer_name": message.get("newcomer_name"),
                    "inviter_name": message.get("inviter_name"),
                    "sent_at": sent_at,
                }
            )
        return results

    def _configured_group_urls(self) -> dict[str, str]:
        dzmm = self.db.get_config().get("dzmm", {})
        urls = {
            "main": str(dzmm.get("group_url") or "").strip(),
            "bounty": str(dzmm.get("bounty_group_url") or "").strip(),
            "image": str(dzmm.get("image_group_url") or "").strip(),
        }
        return {key: url for key, url in urls.items() if url}

    async def _socket_gateway(self):
        if self._gateway is None:
            self._gateway = self._gateway_factory(
                profile_provider=self.browser.socket_profile,
                token_provider=self.browser.socket_token,
                cookie_provider=self.browser.socket_cookie_header,
                user_profile_provider=getattr(self.browser, "socket_user_profile", None),
            )
            if hasattr(self._gateway, "set_message_handler"):
                self._gateway.set_message_handler(
                    self._dispatch_socket_message if self._message_handler else None
                )
        await self._gateway.configure_rooms(self._configured_group_urls())
        return self._gateway

    async def maintain_socket(self) -> None:
        gateway = await self._socket_gateway()
        await gateway.configure_direct_rooms(self.db.list_direct_chatroom_ids())
        await gateway.maintain()

    def clear_pending_messages(self) -> None:
        if self._gateway is not None:
            self._gateway.clear_pending()

    async def close(self) -> None:
        if self._gateway is not None:
            await self._gateway.close()
            self._gateway = None

    def _remember_platform_message(self, source_index: str, message: dict[str, Any]) -> None:
        if not source_index or not message:
            return
        if source_index not in self.platform_message_cache:
            self.platform_message_cache_order.append(source_index)
        self.platform_message_cache[source_index] = message
        while len(self.platform_message_cache_order) > 500:
            expired = self.platform_message_cache_order.popleft()
            self.platform_message_cache.pop(expired, None)

    def _platform_identity_matches_dom(
        self,
        dom_message: dict[str, Any],
        platform_message: dict[str, Any] | None,
        *,
        allow_new_user: bool,
    ) -> bool:
        """Reject API/DOM identity pairs that could have been crossed during a redraw.

        The platform API owns the stable account ID while the DOM owns the visible
        nickname and avatar.  Repeated commands (for example several ``/加入``
        messages) cannot be aligned by text alone, so an existing account must
        still agree with at least one of its current visible identity fields.
        A unique message is allowed to carry a simultaneous nickname/avatar
        change, provided it does not impersonate another current account.
        """
        if not platform_message:
            return False
        platform_user_id = str(
            platform_message.get("sent_by") or platform_message.get("sender_id") or ""
        ).strip().lower()
        if not platform_user_id:
            return False

        sender = str(dom_message.get("sender") or "").strip()
        avatar_id = self._extract_avatar_id(str(dom_message.get("raw_html") or ""))
        normalized_sender = self._normalize_identity_name(sender)
        existing = self.db.get_user({"platform_user_id": platform_user_id})

        # If the visible nickname+avatar pair currently belongs to another
        # account, the API row and DOM row were crossed.  Never authorize it.
        if normalized_sender and avatar_id:
            for row in self.db.conn.execute(
                """select platform_user_id,nickname from users
                   where platform_user_id!='' and avatar_id=?""",
                (avatar_id,),
            ).fetchall():
                owner_id = str(row["platform_user_id"] or "").strip().lower()
                if (
                    owner_id
                    and owner_id != platform_user_id
                    and self._normalize_identity_name(row["nickname"] or "") == normalized_sender
                ):
                    return False

        if not existing:
            return True

        known_name = self._normalize_identity_name(existing.get("nickname") or "")
        known_avatar = str(existing.get("avatar_id") or "").strip().lower()
        name_matches = bool(normalized_sender and known_name and normalized_sender == known_name)
        avatar_matches = bool(avatar_id and known_avatar and avatar_id == known_avatar)
        if name_matches or avatar_matches:
            return True

        # Both visible fields changed.  Only a text-unique API/DOM pairing is
        # strong enough to accept that as a genuine profile update.
        return bool(allow_new_user)

    @staticmethod
    def _normalize_identity_name(value: str) -> str:
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or "").strip())

    @staticmethod
    def _identity_match_text(value: str) -> str:
        """Normalize presentation-only differences without changing stored text."""
        text = unicodedata.normalize("NFKC", value or "").replace("\r\n", "\n").strip()
        text = re.sub(r"\s*\(\s*已编辑\s*\)\s*$", "", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _dom_identity_signature(cls, message: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            cls._normalize_identity_name(str(message.get("sender") or "")),
            cls._extract_avatar_id(str(message.get("raw_html") or "")),
            cls._identity_match_text(str(message.get("text") or "")),
            "1" if message.get("is_self") else "0",
        )

    def _assign_dom_observation_ids(
        self, group_key: str, messages: list[dict[str, Any]]
    ) -> tuple[list[str], bool]:
        """Carry an internal observation ID across virtual-list index changes."""
        previous = self.dom_observation_state.get(group_key, [])
        old_signatures = [item["signature"] for item in previous]
        new_signatures = ["\x1f".join(self._dom_identity_signature(item)) for item in messages]
        assigned: list[str | None] = [None] * len(messages)
        matcher = SequenceMatcher(a=old_signatures, b=new_signatures, autojunk=False)
        for old_start, new_start, size in matcher.get_matching_blocks():
            for offset in range(size):
                assigned[new_start + offset] = previous[old_start + offset]["observation_id"]
        has_new = False
        for index, value in enumerate(assigned):
            if value:
                continue
            assigned[index] = uuid.uuid4().hex
            has_new = True
        self.dom_observation_state[group_key] = [
            {"signature": signature, "observation_id": str(assigned[index])}
            for index, signature in enumerate(new_signatures)
        ]
        return [str(value) for value in assigned], has_new

    def _resolve_avatar_fallback(
        self, avatar_id: str
    ) -> tuple[dict[str, Any] | None, str]:
        user, reason = self.db.resolve_unique_user_by_avatar_uuid(avatar_id)
        if reason == "conflict" and avatar_id not in self.avatar_conflict_logged:
            self.avatar_conflict_logged.add(avatar_id)
            self.logger.warning(
                f"头像UUID对应多个已验证用户，已拒绝备用识别：UUID={avatar_id}"
            )
        return user, reason

    @staticmethod
    def _extract_avatar_id(raw_html: str) -> str:
        match = re.search(r"/avatar/([0-9a-f-]{36})\.png", raw_html or "", re.I)
        return match.group(1).lower() if match else ""

    @staticmethod
    def _extract_gender(raw_html: str) -> str:
        html = raw_html or ""
        if re.search(r"\blucide-venus\b", html, re.I):
            return "female"
        if re.search(r"\blucide-mars\b", html, re.I):
            return "male"
        return ""

    @staticmethod
    def _extract_trpc_messages(payload: Any) -> list[dict[str, Any]]:
        """Extract message objects from the nested tRPC response."""
        found: list[dict[str, Any]] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                sender_id = value.get("sent_by") or value.get("sender_id")
                message_id = value.get("message_id") or value.get("id")
                if sender_id and message_id and "content" in value:
                    found.append(value)
                    return
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)
        unique: dict[str, dict[str, Any]] = {}
        for item in found:
            unique[str(item.get("message_id") or item.get("id"))] = item
        messages = list(unique.values())
        if messages and all(item.get("sent_at") for item in messages):
            messages.sort(key=lambda item: str(item.get("sent_at")))
        return messages

    @staticmethod
    def _message_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, dict):
            for key in ("text", "content", "value"):
                if isinstance(content.get(key), str):
                    return content[key].strip()
        return ""

    @classmethod
    def _reply_reference(
        cls,
        message: dict[str, Any] | None,
        messages_by_id: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        """Read common tRPC reply/quote shapes without trusting one provider version."""
        if not isinstance(message, dict):
            return {"reply_to_message_id": "", "reply_to_text": "", "reply_to_sender": ""}
        id_keys = (
            "reply_to_message_id", "reply_to_id", "quoted_message_id", "reference_message_id",
            "replyToMessageId", "replyToId", "quotedMessageId", "referenceMessageId",
        )
        object_keys = (
            "reply_to", "replyTo", "quoted_message", "quotedMessage", "quote", "quoted",
            "referenced_message", "referencedMessage", "parent_message", "parentMessage",
        )
        reference_id = next((str(message.get(key) or "").strip() for key in id_keys if message.get(key)), "")
        candidate: Any = None
        for key in object_keys:
            value = message.get(key)
            if value not in (None, "", False):
                candidate = value
                break
        if isinstance(candidate, str) and not reference_id:
            reference_id = candidate.strip()
            candidate = None
        if isinstance(candidate, dict):
            if not reference_id:
                reference_id = next(
                    (
                        str(candidate.get(key) or "").strip()
                        for key in ("message_id", "id", *id_keys)
                        if candidate.get(key)
                    ),
                    "",
                )
        referenced = (messages_by_id or {}).get(reference_id) if reference_id else None
        source = candidate if isinstance(candidate, dict) else referenced
        if not isinstance(source, dict):
            source = {}
        text = ""
        for key in ("content", "text", "value", "message"):
            text = cls._message_text(source.get(key))
            if text:
                break
        sender = next(
            (
                str(source.get(key) or "").strip()
                for key in ("sender_name", "senderName", "nickname", "display_name", "displayName")
                if source.get(key)
            ),
            "",
        )
        nested_sender = source.get("sender") or source.get("author") or source.get("user")
        if not sender and isinstance(nested_sender, dict):
            sender = next(
                (
                    str(nested_sender.get(key) or "").strip()
                    for key in ("nickname", "display_name", "displayName", "name")
                    if nested_sender.get(key)
                ),
                "",
            )
        if referenced and referenced is not source:
            if not text:
                text = cls._message_text(referenced.get("content"))
            if not sender:
                sender = next(
                    (
                        str(referenced.get(key) or "").strip()
                        for key in ("sender_name", "senderName", "nickname", "display_name", "displayName")
                        if referenced.get(key)
                    ),
                    "",
                )
        return {
            "reply_to_message_id": reference_id,
            "reply_to_text": text,
            "reply_to_sender": sender,
        }

    @classmethod
    def _align_platform_messages(
        cls, dom_messages: list[dict[str, Any]], api_messages: list[dict[str, Any]]
    ) -> list[dict[str, Any] | None]:
        """Match newest DOM rows to newest API messages while preserving order."""
        matches: list[dict[str, Any] | None] = [None] * len(dom_messages)
        cursor = len(api_messages) - 1
        for dom_index in range(len(dom_messages) - 1, -1, -1):
            wanted = cls._identity_match_text(dom_messages[dom_index].get("text") or "")
            for api_index in range(cursor, -1, -1):
                if cls._identity_match_text(
                    cls._message_text(api_messages[api_index].get("content"))
                ) == wanted:
                    matches[dom_index] = api_messages[api_index]
                    cursor = api_index - 1
                    break
        return matches

    @classmethod
    def _discard_ambiguous_identity_matches(
        cls,
        dom_messages: list[dict[str, Any]],
        matches: list[dict[str, Any] | None],
    ) -> list[dict[str, Any] | None]:
        """Drop repeated DOM identities paired with different platform users.

        During a React list redraw the same visible row can briefly appear in two
        slots.  If those duplicate rows were paired to different API senders,
        there is no safe way to decide which account sent which command.  The
        reader leaves both pending and retries on the next poll instead of
        executing business logic under the wrong user.
        """
        safe_matches = list(matches)
        groups: dict[tuple[str, str, str], list[int]] = {}
        for index, (dom_message, platform_message) in enumerate(zip(dom_messages, matches)):
            if not platform_message:
                continue
            signature = (
                str(dom_message.get("text") or "").strip(),
                cls._normalize_identity_name(str(dom_message.get("sender") or "")),
                cls._extract_avatar_id(str(dom_message.get("raw_html") or "")),
            )
            if all(signature):
                groups.setdefault(signature, []).append(index)
        for indexes in groups.values():
            platform_ids = {
                str(
                    matches[index].get("sent_by") or matches[index].get("sender_id") or ""
                ).strip().lower()
                for index in indexes
                if matches[index]
            }
            platform_ids.discard("")
            if len(indexes) > 1 and len(platform_ids) > 1:
                for index in indexes:
                    safe_matches[index] = None
        return safe_matches

    async def _read_platform_messages(
        self, page, *, force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        chatroom_id = self._chatroom_id(page.url or "")
        if not chatroom_id:
            return []
        now = time.monotonic()
        cached_at, cached_messages = self.platform_api_cache.get(chatroom_id, (0.0, []))
        if now < self.platform_api_backoff_until.get(chatroom_id, 0.0):
            return []
        cache_age = now - cached_at
        if cached_messages and not force_refresh and cache_age < 3.0:
            return list(cached_messages)
        if cached_messages and force_refresh and cache_age < 0.75:
            return list(cached_messages)
        request_input = {
            "json": {"chatroomId": chatroom_id, "limit": 50, "before": None},
            "meta": {"values": {"before": ["undefined"]}, "v": 1},
        }
        endpoint = "/api/trpc/chatroom.getMessages?input=" + quote(
            json.dumps(request_input, ensure_ascii=False, separators=(",", ":")), safe=""
        )
        try:
            payload = await page.evaluate(
                """async endpoint => {
                    const response = await fetch(endpoint, {credentials: 'include'});
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    return await response.json();
                }""",
                endpoint,
            )
            messages = self._extract_trpc_messages(payload)
            self.platform_api_cache[chatroom_id] = (time.monotonic(), messages)
            self.platform_api_failures[chatroom_id] = 0
            self.platform_api_backoff_until.pop(chatroom_id, None)
            return messages
        except Exception as exc:
            failures = self.platform_api_failures.get(chatroom_id, 0) + 1
            self.platform_api_failures[chatroom_id] = failures
            self.platform_api_backoff_until[chatroom_id] = time.monotonic() + min(
                60.0, 2.0 ** min(failures, 5)
            )
            last_log = self.platform_api_last_error_log.get(chatroom_id, 0.0)
            if time.monotonic() - last_log >= 60.0:
                self.platform_api_last_error_log[chatroom_id] = time.monotonic()
                self.logger.warning(
                    f"读取群聊消息身份接口失败，已进入退避并启用唯一头像UUID兜底：{exc}"
                )
            return []

    @staticmethod
    def _chatroom_id(url: str) -> str:
        match = re.search(r"[?&]c=([0-9a-f-]{36})", url or "", re.I)
        return match.group(1).lower() if match else ""

    async def send_message(self, text: str, group_key: str = "main") -> bool:
        text = normalize_outgoing_text(text)
        if not text:
            self.logger.warning("拒绝发送空文字消息")
            return False
        if outgoing_line_count(text) > MAX_OUTGOING_LINES:
            self.logger.error("拒绝发送超过单页行数的文字消息：调用方必须先完成拆分")
            return False
        if outgoing_char_count(text) > MAX_OUTGOING_CHARS:
            self.logger.error("拒绝发送超过单页字数限制的文字消息：调用方必须先完成拆分")
            return False
        lock = self._text_send_locks.setdefault(group_key, asyncio.Lock())
        async with lock:
            try:
                gateway = await self._socket_gateway()
                message_id = await gateway.send_text(group_key, text)
                self.logger.info(
                    f"已发送消息[{group_key}] id={message_id} "
                    f"chars={outgoing_char_count(text)} lines={outgoing_line_count(text)}",
                    kind="send",
                )
                return True
            except Exception as exc:
                self.logger.error(f"发送消息失败：{exc}")
                return False

    async def send_direct_message(self, chatroom_id: str, text: str) -> bool:
        text = normalize_outgoing_text(text)
        if not text or outgoing_line_count(text) > MAX_OUTGOING_LINES:
            return False
        if outgoing_char_count(text) > MAX_OUTGOING_CHARS:
            return False
        room_id = str(chatroom_id or "").strip().lower()
        if not room_id:
            return False
        lock = self._text_send_locks.setdefault(f"direct:{room_id}", asyncio.Lock())
        async with lock:
            try:
                gateway = await self._socket_gateway()
                message_id = await gateway.send_text_to_room(room_id, text)
                self.logger.info(
                    f"已发送私聊消息[{room_id}] id={message_id} "
                    f"chars={outgoing_char_count(text)} lines={outgoing_line_count(text)}",
                    kind="send",
                )
                return True
            except Exception as exc:
                self.logger.error(f"发送私聊消息失败：{exc}")
                return False

    @staticmethod
    async def _select_editable_composer(page, input_sel: str):
        """选择当前真正可见、可编辑的聊天输入框，避开页面残留的隐藏节点。"""
        locator = page.locator(input_sel)
        if not hasattr(locator, "count") or not hasattr(locator, "nth"):
            return locator.last
        try:
            count = await locator.count()
        except Exception:
            return locator.last
        for index in range(count - 1, -1, -1):
            candidate = locator.nth(index)
            try:
                if hasattr(candidate, "is_visible") and not await candidate.is_visible():
                    continue
                if hasattr(candidate, "is_enabled") and not await candidate.is_enabled():
                    continue
                return candidate
            except Exception:
                continue
        return locator.last

    @staticmethod
    async def _page_wait(page, milliseconds: int) -> None:
        if hasattr(page, "wait_for_timeout"):
            await page.wait_for_timeout(milliseconds)
        else:
            await asyncio.sleep(milliseconds / 1000)

    async def _wait_for_composer_ready(
        self, page, box, *, timeout_ms: int = 30000, stable_checks: int = 3
    ) -> bool:
        """等待图片预览和上传状态消失，并确认文字框连续处于稳定可编辑状态。"""
        if not hasattr(box, "evaluate"):
            return True
        deadline = asyncio.get_running_loop().time() + max(1000, timeout_ms) / 1000
        stable = 0
        while asyncio.get_running_loop().time() < deadline:
            try:
                ready = bool(
                    await box.evaluate(
                        """textarea => {
                          const style = window.getComputedStyle(textarea);
                          const rect = textarea.getBoundingClientRect();
                          const hidden = !textarea.isConnected || textarea.hidden ||
                            rect.width <= 0 || rect.height <= 0 ||
                            style.display === 'none' || style.visibility === 'hidden';
                          let composer = textarea.closest('form');
                          if (!composer) {
                            let node = textarea.parentElement;
                            while (node && node !== document.body) {
                              if (node.querySelector('input[type="file"][accept*="image"]')) {
                                composer = node;
                                break;
                              }
                              node = node.parentElement;
                            }
                          }
                          composer = composer || textarea.parentElement;
                          const disabled = textarea.disabled || textarea.readOnly ||
                            textarea.getAttribute('aria-disabled') === 'true';
                          const filesPending = [...composer.querySelectorAll(
                            'input[type="file"][accept*="image"]'
                          )].some(input => input.files && input.files.length > 0);
                          const busy = !!composer.querySelector(
                            '[aria-busy="true"], progress, [role="progressbar"], '
                            + '[data-uploading="true"], [class*="uploading"], [class*="animate-spin"]'
                          );
                          const imagePending = [...composer.querySelectorAll('img')].some(img => {
                            const src = img.getAttribute('src') || '';
                            const owner = img.closest('[class*="preview"], [data-preview], [data-upload]');
                            return src.startsWith('blob:') || src.startsWith('data:image/') || !!owner;
                          });
                          return !hidden && !disabled && !filesPending && !busy && !imagePending;
                        }"""
                    )
                )
            except Exception:
                ready = False
            stable = stable + 1 if ready else 0
            if stable >= max(1, stable_checks):
                return True
            await self._page_wait(page, 250)
        return False

    @staticmethod
    def _ordinary_image_input_score(metadata: dict[str, Any], index: int) -> int | None:
        descriptor = json.dumps(metadata or {}, ensure_ascii=False).lower()
        if re.search(r"闪照|flash|ephemeral|view[-_ ]?once|burn[-_ ]?after", descriptor, re.I):
            return None
        score = 1 if index == 0 else 0
        if re.search(r"普通|图片|照片|相册|photo|image|media", descriptor, re.I):
            score += 10
        return score

    async def send_image(self, image_path: str, group_key: str = "main") -> bool:
        lock = self._text_send_locks.setdefault(group_key, asyncio.Lock())
        async with lock:
            path = Path(image_path).expanduser().resolve()
            if not path.is_file():
                self.logger.error(f"图片文件不存在，无法发送：{path}")
                return False
            if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                self.logger.error(f"不支持的图片格式：{path.suffix}")
                return False
            try:
                url = self.group_url(group_key)
                parsed = urlsplit(url)
                room_id = (parse_qs(parsed.query).get("c") or [""])[0].lower()
                origin = f"{parsed.scheme}://{parsed.netloc}"
                mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                uploaded = await self.browser.upload_chat_image(
                    origin, room_id, path, mime_type
                )
                if self.group_url(group_key) != url:
                    raise RuntimeError("图片上传期间群聊配置已变化，已取消发送")
                image_url = str(uploaded.get("url") or uploaded.get("imageUrl") or "").strip()
                image_parsed = urlsplit(image_url)
                if image_parsed.scheme != "https" or not image_parsed.netloc:
                    raise RuntimeError("图片上传响应缺少安全 URL")
                gateway = await self._socket_gateway()
                await gateway.send_image(
                    group_key, image_url, path.name, expected_room_id=room_id
                )
                self.logger.info(f"已发送图片：{path.name}", kind="send")
                return True
            except Exception as exc:
                self.logger.error(f"发送图片失败：{exc}")
                return False

    async def _send_image_unlocked(self, image_path: str, group_key: str = "main") -> bool:
        path = Path(image_path).expanduser().resolve()
        if not path.is_file():
            self.logger.error(f"图片文件不存在，无法发送：{path}")
            return False
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            self.logger.error(f"不支持的图片格式：{path.suffix}")
            return False
        page = await self._group_page(group_key)
        try:
            file_inputs = page.locator(
                "input[type='file'][accept*='image']:not([accept='.json'])"
            )
            input_count = await file_inputs.count()
            if input_count == 0:
                self.logger.error("群聊输入区没有找到图片上传控件")
                return False
            candidates: list[tuple[int, int, Any]] = []
            for index in range(input_count):
                candidate = file_inputs.nth(index)
                metadata = await candidate.evaluate(
                    """el => {
                      const owner = el.closest('label,button,[role="button"]') || el.parentElement;
                      return {
                        id: el.id || '', name: el.name || '', className: el.className || '',
                        accept: el.accept || '', title: el.title || '', aria: el.getAttribute('aria-label') || '',
                        mode: el.getAttribute('data-mode') || el.getAttribute('data-upload-type') || '',
                        ownerText: owner?.innerText?.trim() || '', ownerTitle: owner?.title || '',
                        ownerAria: owner?.getAttribute?.('aria-label') || ''
                      };
                    }"""
                )
                score = self._ordinary_image_input_score(metadata or {}, index)
                if score is None:
                    continue
                candidates.append((score, -index, candidate))
            if not candidates:
                self.logger.error("只找到闪照上传控件，已拒绝发送以避免图片变成闪照")
                return False
            file_input = max(candidates, key=lambda item: (item[0], item[1]))[2]
            await file_input.set_input_files(str(path), timeout=10000)
            await page.wait_for_timeout(1200)

            input_sel = self.db.get_config().get("selectors", {}).get("input_box")
            if not input_sel:
                self.logger.error("未配置输入框选择器，无法确认图片发送")
                return False
            box = await self._select_editable_composer(page, input_sel)
            composer = file_input.locator("xpath=ancestor::div[.//textarea][1]")
            send_button = None
            for _ in range(20):
                buttons = composer.locator("button:visible:not(:disabled)")
                if await buttons.count() >= 2:
                    send_button = buttons.last
                    break
                await page.wait_for_timeout(250)
            if send_button is not None:
                await send_button.click(timeout=5000)
            else:
                await box.click(timeout=5000)
                await page.keyboard.press("Enter")
            # 点击发送不代表上传已经结束。继续持有群聊发送锁，直到上传预览、
            # 忙碌状态消失且文字框连续稳定可编辑，下一条文字才允许进入。
            await self._page_wait(page, 1000)
            if not await self._wait_for_composer_ready(page, box):
                self.logger.error("图片发送后聊天输入区未在30秒内恢复，禁止紧接着发送文字")
                return False
            await self._page_wait(page, 500)
            self.logger.info(f"已发送图片：{path.name}", kind="send")
            return True
        except Exception as exc:
            self.logger.error(f"发送图片失败：{exc}")
            return False

    async def get_self_name(self) -> str:
        return self.self_name

    async def take_debug_screenshot(self) -> str:
        page = await self.browser.ensure_page()
        path = Path("data/logs/debug.png").resolve()
        await page.screenshot(path=str(path), full_page=True)
        return str(path)

    async def debug_page_state(self, group_key: str = "main") -> dict[str, Any]:
        page = await self._group_page(group_key)
        selectors = self.db.get_config().get("selectors", {})
        state: dict[str, Any] = {
            "url": page.url,
            "title": await page.title(),
            "selectors": {},
            "body_text": "",
            "recent_messages": [],
        }
        try:
            state["body_text"] = (await page.locator("body").inner_text(timeout=2000))[:1500]
        except Exception as exc:
            state["body_text"] = f"读取 body 失败：{exc}"
        for key, selector in selectors.items():
            if not selector:
                state["selectors"][key] = {"selector": "", "count": 0}
                continue
            try:
                state["selectors"][key] = {"selector": selector, "count": await page.locator(selector).count()}
            except Exception as exc:
                state["selectors"][key] = {"selector": selector, "error": str(exc)}
        return state

    async def _read_child_text(self, item, selector: str | None) -> str:
        if not selector:
            return ""
        try:
            loc = item.locator(selector)
            if await loc.count() > 0:
                return (await loc.first.inner_text(timeout=1000)).strip()
        except Exception:
            return ""
        return ""

    async def _read_recent_messages_by_dom(self, group_key: str = "main") -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for attempt in range(3):
            results = await self._read_recent_messages_by_dom_once(
                group_key, force_platform_refresh=attempt > 0
            )
            incomplete_commands = [
                message
                for message in results
                if not message.get("is_self")
                and (message.get("text") or "").strip().startswith("/")
                and (
                    not (message.get("platform_user_id") or "").strip()
                    or not self.db.is_valid_user_nickname(message.get("sender") or "")
                )
            ]
            if not incomplete_commands or attempt == 2:
                break
            page = await self._group_page(group_key)
            await page.wait_for_timeout(350 * (attempt + 1))
        return results

    async def _read_recent_messages_by_dom_once(
        self, group_key: str = "main", *, force_platform_refresh: bool = False
    ) -> list[dict[str, Any]]:
        page = await self._group_page(group_key)
        try:
            expected_chatroom_id = self._chatroom_id(self.group_url(group_key))
            actual_chatroom_id = self._chatroom_id(page.url or "")
            if expected_chatroom_id and actual_chatroom_id != expected_chatroom_id:
                self.logger.error(
                    f"拒绝读取串群页面：期望={group_key}:{expected_chatroom_id}，"
                    f"实际={actual_chatroom_id or 'unknown'}"
                )
                return []
            raw_messages = await page.evaluate(
                """() => {
                    const wrap = document.querySelector('div.pt-10.pb-4.px-2.flex-1.min-h-0.overflow-y-auto.overflow-x-hidden.relative > div');
                    if (!wrap) return [];
                    return [...wrap.children].slice(-50).map((el, position) => {
                      const sender = el.querySelector('.text-xs.font-medium.text-muted-foreground span')?.innerText?.trim() || '';
                      const texts = [...el.querySelectorAll('span.whitespace-pre-wrap.break-words.w-full, [class*="whitespace-pre-wrap"]')]
                        .map(x => x.innerText.trim()).filter(Boolean);
                      const text = texts[texts.length - 1] || '';
                      const html = el.outerHTML || '';
                      const isSelf = !!el.querySelector('.items-end,.justify-end,.ml-auto') || /items-end|justify-end|ml-auto/.test(html);
                      const quoted = el.querySelector('[data-reply-to-message-id],[data-quoted-message-id],[class*="reply-preview"],[class*="quote-preview"],blockquote');
                      const quotedSender = quoted?.querySelector('.text-xs,[class*="sender"],[class*="author"]')?.innerText?.trim() || '';
                      const quotedText = quoted?.innerText?.trim() || '';
                      const quotedId = quoted?.getAttribute('data-reply-to-message-id') || quoted?.getAttribute('data-quoted-message-id') || '';
                      return {
                        sender, text, is_self: isSelf, raw_html: html,
                        reply_to_message_id: quotedId, reply_to_text: quotedText, reply_to_sender: quotedSender,
                        data_index: el.getAttribute('data-index') || '', position
                      };
                    }).filter(x => x.text);
                }"""
            )
            observation_ids, has_new_observations = self._assign_dom_observation_ids(
                group_key, raw_messages
            )
            platform_messages = await self._read_platform_messages(
                page,
                force_refresh=force_platform_refresh or has_new_observations,
            )
            platform_messages_by_id = {
                str(item.get("message_id") or item.get("id") or ""): item
                for item in platform_messages
                if str(item.get("message_id") or item.get("id") or "")
            }
            platform_matches = self._align_platform_messages(raw_messages, platform_messages)
            platform_matches = self._discard_ambiguous_identity_matches(
                raw_messages, platform_matches
            )
            api_text_counts: dict[str, int] = {}
            dom_text_counts: dict[str, int] = {}
            for platform_message in platform_messages:
                content = self._identity_match_text(
                    self._message_text(platform_message.get("content"))
                )
                api_text_counts[content] = api_text_counts.get(content, 0) + 1
            for raw_message in raw_messages:
                content = self._identity_match_text(raw_message.get("text") or "")
                dom_text_counts[content] = dom_text_counts.get(content, 0) + 1
            results = []
            for position, msg in enumerate(raw_messages):
                text = (msg.get("text") or "").strip()
                if not text or self._is_system_text(text):
                    continue
                sender = (msg.get("sender") or "").strip()
                is_self = bool(msg.get("is_self"))
                if not sender:
                    sender = self.self_name if is_self else "未知用户"
                raw_html = msg.get("raw_html") or ""
                avatar_id = self._extract_avatar_id(raw_html)
                gender = self._extract_gender(raw_html)
                observation_id = observation_ids[position]
                cache_index = f"{group_key}:observation:{observation_id}"
                fresh_platform_message = platform_matches[position]
                platform_message = fresh_platform_message or self.platform_message_cache.get(cache_index)
                normalized_text = self._identity_match_text(text)
                allow_new_user = bool(
                    fresh_platform_message
                    and api_text_counts.get(normalized_text, 0) == 1
                    and dom_text_counts.get(normalized_text, 0) == 1
                )
                if not self._platform_identity_matches_dom(
                    msg,
                    platform_message,
                    allow_new_user=allow_new_user,
                ):
                    platform_message = None
                elif fresh_platform_message:
                    self._remember_platform_message(cache_index, fresh_platform_message)
                platform_user_id = ""
                platform_message_id = ""
                identity_source = "pending"
                reference = {
                    "reply_to_message_id": str(msg.get("reply_to_message_id") or "").strip(),
                    "reply_to_text": str(msg.get("reply_to_text") or "").strip(),
                    "reply_to_sender": str(msg.get("reply_to_sender") or "").strip(),
                }
                if platform_message:
                    platform_user_id = str(
                        platform_message.get("sent_by") or platform_message.get("sender_id") or ""
                    ).strip().lower()
                    platform_message_id = str(
                        platform_message.get("message_id") or platform_message.get("id") or ""
                    ).strip()
                    identity_source = "platform"
                    api_reference = self._reply_reference(platform_message, platform_messages_by_id)
                    reference = {
                        key: str(api_reference.get(key) or reference.get(key) or "").strip()
                        for key in reference
                    }
                elif avatar_id:
                    fallback_user, fallback_reason = self._resolve_avatar_fallback(avatar_id)
                    if fallback_user:
                        platform_user_id = str(
                            fallback_user.get("platform_user_id")
                            or fallback_user.get("user_id")
                            or ""
                        ).strip().lower()
                        identity_source = "avatar_uuid"
                fingerprint = "|".join(
                    [group_key, observation_id]
                )
                message_id = platform_message_id or hashlib.sha256(
                    fingerprint.encode("utf-8", errors="ignore")
                ).hexdigest()[:24]
                results.append(
                    {
                        "message_id": message_id,
                        "user_id": platform_user_id,
                        "platform_user_id": platform_user_id,
                        "identity_source": identity_source,
                        "avatar_id": avatar_id,
                        "gender": gender,
                        "sender": sender,
                        "text": text,
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "is_self": is_self,
                        "raw_html": raw_html,
                        **reference,
                        "source_index": observation_id,
                        "source_stable": True,
                        "group_key": group_key,
                        "source_group": group_key,
                    }
                )
            return results
        except Exception as exc:
            self.logger.error(f"结构识别读取消息失败：{exc}")
            return []

    async def _is_self(self, item, selector: str | None) -> bool:
        try:
            if selector and await item.locator(selector).count() > 0:
                return True
            class_name = await item.evaluate(
                """el => {
                    const node = el.querySelector('.items-end, .justify-end, .ml-auto');
                    return node ? node.className : '';
                }"""
            )
            return any(flag in str(class_name) for flag in ["items-end", "justify-end", "ml-auto"])
        except Exception:
            return False

    def _is_system_text(self, text: str) -> bool:
        blocked = ["撤回了一条消息", "对方撤回了一条消息", "加入群聊", "退出群聊"]
        return any(x in text for x in blocked)
