# Referral Rewards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track portal joins and grant the inviter one configurable merit reward plus one saintess-affection point after the newcomer posts three messages.

**Architecture:** Normalize join system events at the Socket.IO boundary, persist referral state in SQLite, and count messages before normal command routing. Commit reward, affection, ledger, and idempotency state in one transaction; deliver the announcement afterward.

**Tech Stack:** Python 3.12, python-socketio, FastAPI, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-server-admin-referral-design.md`

## Global Constraints

- Default reward is 40; administrator range is 0 through 100000.
- Message reads and sends remain on `python-socketio.AsyncClient`; no DOM message polling or sending.
- DDZM is read-only reference code.
- A referral and a message ID can each settle at most once.

---

### Task 1: Normalize portal join events

**Files:**
- Modify: `source/app/aikda_socket.py`
- Test: `source/tests/test_aikda_socket.py`

**Interfaces:**
- Produces: normalized dictionaries with `event_type="member_joined_by_invite"`, `newcomer_name`, `inviter_name`, optional stable IDs, `message_id`, `chatroom_id`, and `sent_at`.

- [ ] Add tests using the captured text `鸿鸿鸿 通过 紫苑 的链接加入了群聊`, plus an ordinary message that must not match.
- [ ] Run `python -m pytest -q source/tests/test_aikda_socket.py` and confirm the new test fails because the system content type is rejected.
- [ ] Extend `_normalize_message()` only for the observed system-event payload shapes and parse the exact Chinese sentence with anchored matching.
- [ ] Re-run the test and confirm it passes.
- [ ] Commit with `git commit -am "feat: normalize portal join events"`.

### Task 2: Persist referral progress and settle atomically

**Files:**
- Create: `source/app/referrals.py`
- Modify: `source/app/database.py`
- Test: `source/tests/test_referrals.py`

**Interfaces:**
- Produces: `ReferralCore.record_join(message) -> dict`, `ReferralCore.observe_message(message) -> ReferralOutcome | None`, `ReferralCore.list_admin() -> dict`.
- `ReferralOutcome` contains `group_key`, `newcomer_name`, `inviter_name`, `reward_amount`, and `announcement`.

- [ ] Add failing tests for join persistence, first-message ID binding, 1/3 and 2/3 progress, third-message settlement, duplicate message IDs, duplicate system events, restart idempotency, self-invite rejection, nickname ambiguity, and reward zero.
- [ ] Run `python -m pytest -q source/tests/test_referrals.py` and confirm failure because `app.referrals` is absent.
- [ ] Add `users.saintess_affection`, `referral_invites`, `referral_message_counts`, and referral audit tables/indexes through idempotent `Database.init()` migration SQL.
- [ ] Implement unique nickname/history resolution and a single `BEGIN IMMEDIATE` settlement transaction that updates points, `total_merit`, affection, transactions, and referral status.
- [ ] Re-run `python -m pytest -q source/tests/test_referrals.py` and confirm all cases pass.
- [ ] Commit `source/app/referrals.py`, database changes, and tests with message `feat: settle referral rewards after three messages`.

### Task 3: Integrate counting, commands, profile, and announcements

**Files:**
- Modify: `source/app/scheduler.py`
- Modify: `source/app/command_router.py`
- Modify: `source/app/database.py`
- Modify: `source/app/help_system.py`
- Test: `source/tests/test_referrals.py`
- Test: `source/tests/test_rule_engine.py`

**Interfaces:**
- Consumes: `ReferralCore.record_join()` and `ReferralCore.observe_message()`.
- Produces: administrator command `/设置拉新奖励 <amount>` and `/我` line `圣女好感度：<value>`.

- [ ] Add failing integration tests proving system events bypass ordinary commands, every complete group identity is counted before slash filtering, only administrators can set the reward, config persists, `/我` shows affection, and the exact three-line announcement is returned once.
- [ ] Run the named referral/router tests and verify expected failures.
- [ ] Wire `ReferralCore` into `Database`, process join events before `save_message`, observe eligible messages before command routing, and send a post-commit announcement to the source group.
- [ ] Add strict command parsing `^/设置拉新奖励\s+(\d{1,6})$`, authorization, config save, profile rendering, and admin help entry.
- [ ] Re-run focused tests, then `python -m pytest -q source/tests`.
- [ ] Commit with message `feat: expose referral rewards in commands and profiles`.

