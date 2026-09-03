# Socket.IO Message Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace DZMMBot's DOM/history-based message reading and DOM-based text/image sending with an asynchronous Socket.IO transport compatible with the Aikda protocol.

**Architecture:** Add an asyncio-native gateway around `python-socketio.AsyncClient`; keep Playwright only as the provider of authenticated tRPC requests, cookies, and image upload. Preserve `DzmmAdapter`'s public async interface so the existing scheduler and business features continue to work.

**Tech Stack:** Python 3.13, asyncio, python-socketio 5.x, Playwright async API, pytest

**Spec:** `docs/superpowers/specs/2026-09-02-socketio-message-transport-design.md`

## Global Constraints

- Modify only `/Users/zhijian/Desktop/DZMMBot-Portable(20260826)/source`; `/Users/zhijian/Desktop/DDZM` is read-only reference material.
- Use `socketio.AsyncClient`, `socketio_path="ws/matching"`, fresh token/Cookie authentication, explicit room joins, and ACK-validated sends.
- Do not replay message history after startup or reconnect.
- Preserve current scheduler-facing adapter method signatures and message dictionary fields.
- Do not automatically retry a send after it may have reached the server.

---

### Task 1: Async Socket.IO Gateway Receive Path

**Files:**
- Create: `app/aikda_socket.py`
- Create: `tests/test_aikda_socket.py`

**Interfaces:**
- Consumes: async token provider, profile provider, Cookie provider, configured `{group_key: chat_url}` mapping, injected AsyncClient factory.
- Produces: `AikdaSocketGateway.configure_rooms(urls)`, `read_new(group_key)`, `clear_pending()`, `close()`, and gateway error classes.

- [ ] **Step 1: Write failing receive tests**

Add tests using a protocol-complete fake AsyncClient. Verify connection options, `message:joined` readiness, explicit `message:join-room` calls, per-group routing, self-message filtering, payload validation, `(chatroomId, message_id)` deduplication, image and reference parsing, and disconnect state reset. Each expected normalized message is a hand-written literal.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_aikda_socket.py -q`

Expected: collection fails because `app.aikda_socket` does not exist.

- [ ] **Step 3: Implement minimal receive gateway**

Implement an asyncio-only state machine with an async state lock, pending deques per group, bounded seen-ID memory, event registration, `connect()`, ACK-based joins, validation, and explicit reconnect on the next operation. Do not implement send or upload behavior beyond signatures needed by the fake.

- [ ] **Step 4: Run receive tests and verify GREEN**

Run: `python -m pytest tests/test_aikda_socket.py -q`

Expected: receive tests pass.

### Task 2: Socket Text and Image Sending

**Files:**
- Modify: `app/aikda_socket.py`
- Modify: `tests/test_aikda_socket.py`

**Interfaces:**
- Consumes: `send_text(group_key, text)`, `send_image(group_key, image_url, alt)`, and an async image uploader supplied by the browser layer.
- Produces: server-acknowledged Boolean success behavior and typed exceptions for authentication, transport, and message rejection.

- [ ] **Step 1: Write failing send tests**

Verify literal outbound message fields, UUID message ID, UTC timestamp, correct destination, per-room join before send, `message:send` ACK success, 3-second timeout behavior, rejection behavior, image content, and same-room serialization. Verify no second emit occurs after an ambiguous timeout.

- [ ] **Step 2: Run targeted tests and verify RED**

Run: `python -m pytest tests/test_aikda_socket.py -q`

Expected: send tests fail because gateway send methods are missing.

- [ ] **Step 3: Implement minimal send behavior**

Use per-room `asyncio.Lock` instances. Build the Aikda message envelope, ensure a fresh valid connection and joined room, call AsyncClient `call("message:send", payload, timeout=3)`, accept only `{"success": true}`, and surface other results without an automatic retry.

- [ ] **Step 4: Run gateway tests and verify GREEN**

Run: `python -m pytest tests/test_aikda_socket.py -q`

Expected: all gateway tests pass.

### Task 3: Browser Authentication and Upload Boundary

**Files:**
- Modify: `app/browser.py`
- Create: `tests/test_browser_socket_auth.py`

**Interfaces:**
- Produces: `socket_token() -> str`, `socket_profile() -> dict`, `socket_cookie_header(origin) -> str`, and `upload_chat_image(origin, chatroom_id, path, mime_type) -> dict`, all async.
- Consumes: the existing authenticated Playwright page and browser context.

- [ ] **Step 1: Write failing browser boundary tests**

Use small async fakes at the Playwright page/context/request boundary. Verify token evaluation, `user.getMe`, origin-filtered Cookie formatting, Supabase cookie fallback, multipart upload fields, response extraction, and errors that do not expose secrets.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_browser_socket_auth.py -q`

Expected: tests fail because the browser methods do not exist.

- [ ] **Step 3: Implement browser boundary**

Port only the authenticated scripts and response extraction needed from the DDZM reference, converted to Playwright's async API. Keep existing browser startup/navigation behavior unchanged.

- [ ] **Step 4: Run browser tests and verify GREEN**

Run: `python -m pytest tests/test_browser_socket_auth.py -q`

Expected: browser boundary tests pass.

### Task 4: Adapter and Scheduler Integration

**Files:**
- Modify: `app/dzmm_adapter.py`
- Modify: `app/scheduler.py`
- Modify: `main.py`
- Modify: `tests/test_dzmm_adapter_send.py`
- Create: `tests/test_dzmm_adapter_socket.py`
- Modify: relevant scheduler lifecycle tests if their existing assertions require it.

**Interfaces:**
- Consumes: gateway receive/send methods and browser upload/auth methods.
- Produces: unchanged `read_recent_messages(group_key)`, `send_message(text, group_key)`, `send_image(path, group_key)`, plus `close()` and `clear_pending_messages()` lifecycle methods.

- [ ] **Step 1: Write failing adapter integration tests**

Verify group URL configuration, normalized inbound dictionaries, database nickname lookup with stable platform-ID fallback, existing text limits, image extension/MIME mapping, Boolean failure semantics, queue clearing on resume, and gateway closure before browser shutdown.

- [ ] **Step 2: Run targeted tests and verify RED**

Run: `python -m pytest tests/test_dzmm_adapter_socket.py tests/test_dzmm_adapter_send.py tests/test_group_page_routing.py -q`

Expected: new tests fail because the adapter still uses DOM transport.

- [ ] **Step 3: Integrate gateway minimally**

Instantiate/configure the gateway lazily from current database URLs; translate gateway messages to existing dictionaries; replace text/image DOM sends; add lifecycle calls. Remove only state and helper methods that become unused because of this transport change.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run: `python -m pytest tests/test_dzmm_adapter_socket.py tests/test_dzmm_adapter_send.py tests/test_group_page_routing.py tests/test_message_identity_retry.py tests/test_image_generation.py -q`

Expected: targeted transport and regression tests pass.

### Task 5: Runtime Dependencies, Packaging, and Full Verification

**Files:**
- Modify: `requirements.txt`
- Modify: `DZMMBot.spec`
- Modify or create: packaging dependency test only if an existing executable analysis test pattern exists.

**Interfaces:**
- Produces: installed and packaged Socket.IO/Engine.IO async-client runtime.

- [ ] **Step 1: Add a failing runtime import/package collection check**

Verify the runtime can import `socketio.AsyncClient` and PyInstaller collection includes `socketio` and `engineio` through executable analysis rather than source-text assertions.

- [ ] **Step 2: Run the check and verify RED**

Run the smallest repository-supported dependency/packaging check discovered during implementation.

Expected: it fails before requirements/spec collection is updated.

- [ ] **Step 3: Add dependencies and collection**

Pin `python-socketio[asyncio_client]>=5,<6` consistently with the reference project and collect Socket.IO/Engine.IO runtime data, binaries, and hidden imports in `DZMMBot.spec`.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
python -m pytest tests/test_aikda_socket.py tests/test_browser_socket_auth.py tests/test_dzmm_adapter_socket.py tests/test_dzmm_adapter_send.py tests/test_group_page_routing.py tests/test_message_identity_retry.py tests/test_image_generation.py -q
python -m pytest tests -q
```

Expected: both commands exit 0 with no failures.

- [ ] **Step 5: Verify reference project was untouched**

If DDZM has Git metadata, run `git -C /Users/zhijian/Desktop/DDZM status --short`; otherwise compare its file modification times against the start of implementation. Expected: no changes made by this task.

## Plan Self-Review

- Every design requirement maps to a task: protocol and receive path (Task 1), ACK sending (Task 2), browser auth/upload (Task 3), application integration (Task 4), dependencies and verification (Task 5).
- Public adapter compatibility is preserved; the gateway owns only transport concerns.
- No private chat, recall, history replay, business refactor, or DDZM write is included.
- Tests assert normalized messages and outbound payloads, not fake implementation details.
