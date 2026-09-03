# Commission Publishing Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add non-AI, private-chat step-by-step publishing flows for `/需求` and `/服务` while preserving the existing AI paths when command text is supplied.

**Architecture:** `CommissionHouse` owns persisted wizard sessions and deterministic field parsing; `CommandRouter` selects wizard commands before the existing AI draft path and renders prompts/previews. Completed wizard data is passed into the existing `commission_drafts_v2` flow so publication, money handling, identifiers, and bounty-group broadcasts remain unchanged.

**Tech Stack:** Python 3.12, SQLite, pytest, existing `CommandRouter` and `CommissionHouse` modules.

**Spec:** `docs/superpowers/specs/2026-09-03-commission-wizard-design.md`

## Global Constraints

- Empty `/需求` and `/服务` must not invoke AI.
- Every prompt states the accepted format, includes an example, and includes `/上一步｜/取消发布`.
- `/需求：...` and `/服务：...` retain the existing AI parser.
- Wizard input is consumed only in direct chat.
- Wizard input and preview never deduct points; `/确认发布` remains the only publication action.
- Existing settlement and publication implementations are not duplicated.

---

### Task 1: Persist wizard sessions

**Files:**
- Modify: `app/commission_house.py`
- Test: `tests/test_commission_wizard.py`

**Interfaces:**
- Produces: `start_wizard(ref, kind, step, expires_seconds=600) -> dict`, `get_wizard(ref) -> dict | None`, `update_wizard(ref, step, values, history) -> dict`, `cancel_wizard(ref) -> bool`, and `complete_wizard(ref) -> bool`.
- Session dictionaries expose `wizard_kind`, `current_step`, `values`, and `history`.

- [ ] **Step 1: Write failing persistence tests**

```python
def test_wizard_session_round_trip_and_user_isolation(db):
    db.commission_house.start_wizard(message(USER1, "/需求"), "demand", "title")
    db.commission_house.update_wizard(message(USER1, "标题"), "content", {"title": "称呼任务"}, ["title"])
    assert db.commission_house.get_wizard(message(USER1, ""))["values"]["title"] == "称呼任务"
    assert db.commission_house.get_wizard(message(USER2, "")) is None

def test_cancel_and_complete_remove_active_wizard(db):
    db.commission_house.start_wizard(message(USER1, "/服务"), "service", "title")
    assert db.commission_house.cancel_wizard(message(USER1, ""))
    assert db.commission_house.get_wizard(message(USER1, "")) is None
```

- [ ] **Step 2: Run persistence tests and verify they fail because the schema/API is missing**

Run: `PYTHONPATH=. uv run --with-requirements requirements.txt --with pytest --with pillow pytest -q tests/test_commission_wizard.py -k 'round_trip or cancel_and_complete'`

- [ ] **Step 3: Add `commission_wizard_sessions` schema and the five session methods**

Use one active row per `(publisher_user_pk, group_id)`, JSON encode values/history with `ensure_ascii=False`, expire stale active rows in `get_wizard`, and refresh `expires_at` in `update_wizard`.

- [ ] **Step 4: Re-run persistence tests and verify PASS**

Run the command from Step 2.

### Task 2: Deterministic wizard routing and validation

**Files:**
- Modify: `app/command_router.py`
- Test: `tests/test_commission_wizard.py`

**Interfaces:**
- Consumes: Task 1 session methods.
- Produces: `_start_commission_wizard(message, kind, features) -> CommandResult`, `_handle_commission_wizard(message, text, features) -> CommandResult | None`, `_commission_wizard_prompt(kind, step, values) -> str`, and `_commission_wizard_preview(message, wizard, features) -> CommandResult`.

- [ ] **Step 1: Write failing demand-flow tests**

```python
def test_empty_demand_command_runs_non_ai_wizard_with_examples(db):
    result = CommandRouter(db, ai_client_factory=FailIfCalledAI).handle(message(USER1, "/需求"))
    assert "第1/6步" in result.replies[0]
    assert "示例：群聊称呼任务" in result.replies[0]
    assert "/上一步｜/取消发布" in result.replies[0]

def test_demand_wizard_rejects_bad_people_and_completes_existing_draft(db):
    router = CommandRouter(db, ai_client_factory=FailIfCalledAI)
    for text in ["/需求", "称呼任务", "在群里喊我主人", "1"]:
        result = router.handle(message(USER1, text))
    bad = router.handle(message(USER1, "四个人"))
    assert "1～100" in bad.replies[0]
    for text in ["4", "50", "3天"]:
        result = router.handle(message(USER1, text))
    assert "需求发布预览" in result.replies[0]
    assert db.commission_house.get_draft(message(USER1, ""))["parsed"]["required_people"] == 4
```

- [ ] **Step 2: Run demand tests and verify the empty command follows the old missing-content reply**

Run: `PYTHONPATH=. uv run --with-requirements requirements.txt --with pytest --with pillow pytest -q tests/test_commission_wizard.py -k demand`

- [ ] **Step 3: Implement the demand state machine and prompt renderer**

Use steps `title`, `content`, `fulfillment_type`, optional `fulfillment_duration`, `required_people`, `reward_per_person`, `recruitment_duration`. Parse choice `1|2`, integers with full-string regex, duration as `N小时|N天|不限`, and call existing `save_draft` plus the existing preview templates on completion.

- [ ] **Step 4: Write failing service-flow tests**

```python
def test_service_wizard_supports_duration_stock_limit_and_listing(db):
    router = CommandRouter(db, ai_client_factory=FailIfCalledAI)
    replies = []
    for text in ["/服务", "陪聊服务", "陪你聊天", "2", "1天", "50", "小时", "10", "2", "3天"]:
        replies = router.handle(message(USER1, text)).replies
    draft = db.commission_house.get_draft(message(USER1, ""))["parsed"]
    assert "服务发布预览" in replies[0]
    assert draft["stock_quantity"] == 10 and draft["max_per_buyer"] == 2
    assert draft["fulfillment_duration_unit"] == "day"
```

- [ ] **Step 5: Implement the service state machine**

Use steps `title`, `description`, `fulfillment_type`, optional `fulfillment_duration`, `unit_price`, `unit_label`, `stock`, `max_per_buyer`, `listing_duration`; reject a finite per-buyer limit greater than finite stock.

- [ ] **Step 6: Run demand and service tests and verify PASS**

Run: `PYTHONPATH=. uv run --with-requirements requirements.txt --with pytest --with pillow pytest -q tests/test_commission_wizard.py`

### Task 3: Navigation, command priority, compatibility, and regression

**Files:**
- Modify: `app/command_router.py`
- Modify: `app/help_system.py` only if the generated private help does not already distinguish empty and full publishing commands.
- Test: `tests/test_commission_wizard.py`
- Test: `tests/test_commission_house_v2.py`

**Interfaces:**
- Consumes: Tasks 1 and 2 wizard APIs.
- Produces: final routing behavior for `/上一步`, cancellation aliases, help passthrough, command rejection during an active wizard, and legacy AI compatibility.

- [ ] **Step 1: Write failing navigation and priority tests**

```python
def test_back_uses_actual_history_and_cancel_alias_clears_session(db):
    router = CommandRouter(db, ai_client_factory=FailIfCalledAI)
    for text in ["/需求", "称呼任务", "喊我主人", "1"]:
        router.handle(message(USER1, text))
    back = router.handle(message(USER1, "/上一步"))
    assert "履行类型" in back.replies[0]
    cancelled = router.handle(message(USER1, "/取消发布草稿"))
    assert "已取消" in cancelled.replies[0]
    assert db.commission_house.get_wizard(message(USER1, "")) is None

def test_help_preserves_wizard_and_other_commands_do_not_become_values(db):
    router = CommandRouter(db, ai_client_factory=FailIfCalledAI)
    router.handle(message(USER1, "/需求"))
    assert router.handle(message(USER1, "/市场帮助")).name == "委托帮助"
    blocked = router.handle(message(USER1, "/余额"))
    assert "先完成或取消" in blocked.replies[0]
    assert db.commission_house.get_wizard(message(USER1, ""))["current_step"] == "title"
```

- [ ] **Step 2: Run navigation tests and verify FAIL**

Run: `PYTHONPATH=. uv run --with-requirements requirements.txt --with pytest --with pillow pytest -q tests/test_commission_wizard.py -k 'back or help'`

- [ ] **Step 3: Implement navigation and routing priority**

Check direct active wizard after help resolution but before ordinary command handlers; handle wizard control commands first. Store actual visited steps in history so conditional steps are skipped correctly in both directions.

- [ ] **Step 4: Add and run compatibility tests**

Assert that `/需求：完整内容` and `/服务：完整内容` invoke the fake AI and reach the existing preview, while group ordinary text never advances a private wizard.

Run: `PYTHONPATH=. uv run --with-requirements requirements.txt --with pytest --with pillow pytest -q tests/test_commission_wizard.py tests/test_commission_house_v2.py`

- [ ] **Step 5: Run syntax and focused regression verification**

Run: `PYTHONPATH=. uv run --with-requirements requirements.txt --with pytest --with pillow pytest -q tests/test_commission_wizard.py tests/test_commission_house_v2.py tests/test_outgoing_text_limit.py`

Run: `PYTHONPATH=. uv run --with-requirements requirements.txt --with pillow python -m py_compile app/commission_house.py app/command_router.py app/help_system.py`

- [ ] **Step 6: Restart and verify runtime status**

Restart `main.py` with the existing `DZMM_DATA_DIR`, proxy variables unset, then confirm `/api/status` reports `running=true`, `paused=false`, `logged_in=true`, and zero loop failures.

> This workspace is not a Git repository, so commit steps are intentionally omitted.
