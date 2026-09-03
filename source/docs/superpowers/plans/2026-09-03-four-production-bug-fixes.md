# Four Production Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the obsolete site origin, make wage activity robust to temporarily unresolved sender names, expire abandoned multiplayer games, and prevent migrated bounty refunds from being issued twice.

**Architecture:** Preserve platform user IDs and room IDs as authoritative identifiers. Add narrowly scoped database transitions for stale games and migrated legacy rows, invoked from the existing scheduler loop. Keep DDZM as a read-only behavioral reference.

**Tech Stack:** Python 3.12, SQLite, FastAPI, python-socketio AsyncClient, pytest.

**Spec:** User-provided four-item production bug report dated 2026-09-03.

## Global Constraints

- Do not modify `/Users/zhijian/Desktop/DDZM`.
- Use `https://www.aikda.com` while preserving existing chatroom UUIDs.
- Default inactivity timeout is 120 seconds.
- Never issue a second refund for a migrated legacy bounty.

---

### Task 1: Site origin migration

**Files:** Modify `app/database.py`, `main.py`; test `tests/test_database.py`, `tests/test_browser_socket_auth.py`.

- [ ] Write a failing test proving persisted `ainvmei.com`/`dzmm.ai` URLs migrate to `aikda.com` without changing `c` IDs.
- [ ] Run the test and confirm the old origin remains.
- [ ] Add the smallest load-time config migration and accept only `dzmm.ai` in edited group URLs.
- [ ] Run socket/browser routing tests.

### Task 2: Wage identity fallback

**Files:** Modify `app/database.py`; test `tests/test_facility_wages.py`.

- [ ] Write a failing test with yesterday activity carrying a valid platform ID but sender `未知用户`.
- [ ] Confirm wage claim incorrectly reports no activity.
- [ ] Treat the platform-ID activity as valid and match the verified user's stored nickname when all observed sender labels are invalid.
- [ ] Run all wage tests.

### Task 3: Multiplayer inactivity expiry

**Files:** Modify `app/database.py`, `app/scheduler.py`, `app/command_router.py`; test `tests/test_six_seal.py` and multiplayer tests.

- [ ] Preserve the existing six-seal 120-second active-turn expiry test.
- [ ] Write a failing ordinary card-battle timeout test proving every joined player's stake is refunded once and the waiting row is finished.
- [ ] Add a claim/finalize timeout transition and scheduler notification using a 120-second default.
- [ ] Run six-seal and card-battle tests.

### Task 4: Migrated bounty refund idempotency

**Files:** Modify `app/commission_house.py`; test `tests/test_commission_house_v2.py`.

- [ ] Write a failing migration test: close a migrated demand, then run weekly cleanup, and assert only one refund.
- [ ] Confirm weekly cleanup currently refunds the legacy escrow again.
- [ ] In the same close transaction, mark the linked legacy bounty cancelled/refunded after the V2 refund.
- [ ] Run commission and weekly cleanup tests.

### Task 5: Runtime verification

**Files:** No production edits.

- [ ] Run the focused suites and syntax compilation.
- [ ] Verify historical豪龙 correction already exists and make no second balance mutation.
- [ ] Restart without proxy environment variables, resume the scheduler, and verify logged-in/socket status.
