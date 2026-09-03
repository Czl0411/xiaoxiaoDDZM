# Commission Private Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all commission-house commands and replies into direct chats while retaining a group broadcast for newly published services and demands.

**Architecture:** Extend the existing asynchronous Socket.IO gateway with discovered direct-room routing, persist user-to-room mappings in SQLite, and let the scheduler process direct messages through the existing command router. Add a single channel guard for commission commands; successful publication keeps the current `bounty` delivery.

**Tech Stack:** Python 3.12, python-socketio `AsyncClient`, aiohttp, SQLite, pytest

**Spec:** `docs/superpowers/specs/2026-09-03-commission-private-chat-design.md`

## Global Constraints

- DDZM is read-only reference material and must not be modified.
- Commission commands execute only in direct chats.
- A successful service or demand publication broadcasts its existing card to the configured `bounty` group.
- Other group commands and all existing Socket.IO image behavior remain unchanged.
- The repository has no Git metadata, so commit steps are omitted.

---

### Task 1: Direct-room Socket.IO transport

**Files:**
- Modify: `app/aikda_socket.py`
- Modify: `app/dzmm_adapter.py`
- Test: `tests/test_aikda_socket.py`
- Test: `tests/test_dzmm_adapter_socket.py`

**Interfaces:**
- Produces: `AikdaSocketGateway.configure_direct_rooms(room_ids: list[str]) -> None`
- Produces: `AikdaSocketGateway.read_direct_new() -> list[dict[str, Any]]`
- Produces: `AikdaSocketGateway.send_text_to_room(chatroom_id: str, text: str) -> str`
- Produces: normalized direct messages with `source_type="direct"` and `chatroom_id`.

- [ ] **Step 1: Write failing transport tests**

```python
async def test_unknown_room_event_is_buffered_as_direct_message():
    await gateway.configure_rooms({"main": MAIN_URL})
    socket.handlers["message:new"]({"chatroomId": DIRECT_ID, "message": incoming})
    assert (await gateway.read_direct_new())[0]["chatroom_id"] == DIRECT_ID

async def test_send_text_to_direct_room_joins_and_sends():
    message_id = await gateway.send_text_to_room(DIRECT_ID, "私聊回复")
    assert message_id
    assert socket.calls[-1][1]["chatroomId"] == DIRECT_ID
```

- [ ] **Step 2: Run tests and verify missing APIs fail**

Run: `pytest -q tests/test_aikda_socket.py -k direct`

- [ ] **Step 3: Implement the minimum direct-room queues, joins, reconnect reset, and destination send**

```python
async def send_text_to_room(self, chatroom_id: str, text: str) -> str:
    return await self._send_room(chatroom_id, {"type": "text", "text": text})
```

Unknown non-group room events are classified as direct instead of discarded. Saved direct rooms are rejoined one at a time during maintenance so one failure cannot block group traffic.

- [ ] **Step 4: Adapt `DzmmAdapter` to expose direct read/send methods and preserve sender identity**

```python
async def read_direct_messages(self) -> list[dict[str, Any]]: ...
async def send_direct_message(self, chatroom_id: str, text: str) -> bool: ...
```

- [ ] **Step 5: Run transport tests**

Run: `pytest -q tests/test_aikda_socket.py tests/test_dzmm_adapter_socket.py`

### Task 2: Persist direct-chat identity mappings

**Files:**
- Modify: `app/database.py`
- Create: `tests/test_direct_chats.py`

**Interfaces:**
- Produces: `Database.upsert_direct_chat(platform_user_id: str, chatroom_id: str) -> None`
- Produces: `Database.list_direct_chatroom_ids() -> list[str]`
- Produces: `Database.get_direct_chatroom_id(platform_user_id: str) -> str | None`

- [ ] **Step 1: Write failing mapping and uniqueness tests**

```python
def test_direct_chat_mapping_updates_by_user_and_room(db):
    db.upsert_direct_chat("user-a", "room-1")
    db.upsert_direct_chat("user-a", "room-2")
    assert db.get_direct_chatroom_id("user-a") == "room-2"
    assert db.list_direct_chatroom_ids() == ["room-2"]
```

- [ ] **Step 2: Verify the tests fail because the table and APIs are absent**

Run: `pytest -q tests/test_direct_chats.py`

- [ ] **Step 3: Add the SQLite table during `Database.init()` and implement the three APIs**

```sql
create table if not exists direct_chats (
  platform_user_id text primary key,
  chatroom_id text not null unique,
  discovered_at text not null
)
```

- [ ] **Step 4: Run database tests**

Run: `pytest -q tests/test_direct_chats.py`

### Task 3: Private-only commission routing and group publication broadcast

**Files:**
- Modify: `app/command_router.py`
- Modify: `app/scheduler.py`
- Test: `tests/test_commission_house.py`
- Test: `tests/test_outgoing_text_limit.py`

**Interfaces:**
- Consumes: direct messages with `source_type`, `chatroom_id`, and stable platform user ID.
- Produces: group guidance reply and, when a saved room exists, a direct guidance delivery for commission commands sent outside direct chat.
- Produces: direct command replies plus `deliveries=[{"group_key": "bounty", "text": card}]` on publication.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_group_commission_command_only_returns_private_chat_guidance(router):
    result = router.handle(message("/查看市场", source_type="group"))
    assert result.reason == "委托指令仅限私聊"
    assert "私聊" in result.replies[0]

def test_group_commission_command_guides_known_user_in_saved_direct_room(router):
    result = router.handle(message("/查看市场", source_type="group", platform_user_id="known"))
    assert result.replies == ["圣喻已给你单独指引"]
    assert result.direct_deliveries[0]["chatroom_id"] == "known-room"

def test_direct_confirm_service_returns_private_reply_and_bounty_card(router):
    result = publish_service_in_direct_chat(router)
    assert result.handled
    assert result.deliveries[0]["group_key"] == "bounty"
```

- [ ] **Step 2: Verify tests fail because group commands still execute and direct messages are not scheduled**

Run: `pytest -q tests/test_commission_house.py -k 'private or direct'`

- [ ] **Step 3: Add one commission-command classifier and guard before command execution**

```python
if self._is_commission_command(command, features) and source_type != "direct":
    return CommandResult(True, [private_guide], name="委托私聊引导", reason="委托指令仅限私聊")
```

- [ ] **Step 4: Poll direct messages, persist discovered mappings, and send replies to their exact room**

The scheduler uses a direct destination helper for the original reply and retains the existing delivery loop for the `bounty` broadcast.

- [ ] **Step 5: Run routing and scheduler tests**

Run: `pytest -q tests/test_commission_house.py tests/test_outgoing_text_limit.py`

### Task 4: Regression and live verification

**Files:**
- Modify only files required by failing regression tests.

**Interfaces:**
- Consumes all APIs introduced by Tasks 1–3.
- Produces a running bot with direct commission workflow and unchanged group/image transport.

- [ ] **Step 1: Run focused regression tests**

Run: `pytest -q tests/test_direct_chats.py tests/test_aikda_socket.py tests/test_dzmm_adapter_socket.py tests/test_commission_house.py tests/test_outgoing_text_limit.py tests/test_browser_socket_auth.py`

- [ ] **Step 2: Compile changed Python modules**

Run: `python -m py_compile app/aikda_socket.py app/dzmm_adapter.py app/database.py app/command_router.py app/scheduler.py`

- [ ] **Step 3: Restart the service with the existing proxy and data-directory environment**

Verify `/api/status` reports `running=true`, `paused=false`, `logged_in=true`, and all configured group login states true.

- [ ] **Step 4: Perform live private-chat verification**

Send `/查看市场` in an established private chat and verify the reply record targets the same `chatroomId`. Then publish a reversible test listing, verify the private confirmation and `bounty` broadcast, and remove the listing through the normal command flow.
