from __future__ import annotations

from datetime import datetime
import asyncio

import pytest

from app.bounty_core import BEIJING_TZ
from app.command_router import CommandRouter
from app.database import Database
from app.outgoing_text import prepare_outgoing_text_messages


PUBLISHER = "10000000-0000-0000-0000-000000000001"
USERS = [f"20000000-0000-0000-0000-{index:012d}" for index in range(1, 13)]


def message(user_id: str, nickname: str, text: str, group: str = "main") -> dict:
    return {
        "platform_user_id": user_id,
        "user_id": user_id,
        "sender": nickname,
        "message_id": f"{group}-{user_id}-{text}",
        "text": text,
        "is_self": False,
        "group_key": group,
        "source_group": group,
    }


@pytest.fixture
def db(tmp_path):
    instance = Database(tmp_path / "bot.db")
    instance.init()
    yield instance
    instance.close()


def add_user(db: Database, uid: str, name: str, points: int = 0) -> dict:
    user = db.ensure_user(message(uid, name, "/测试"))
    if points:
        db.add_points(user, points, "测试初始化")
    return db.get_user(user)


def publish(
    db: Database,
    *,
    count: int = 1,
    reward: int = 100,
    duration_type: str = "single",
    duration_days: int = 0,
) -> dict:
    return db.create_bounty(
        message(PUBLISHER, "发布者", "/发布悬赏"),
        duration_type=duration_type,
        duration_days=duration_days,
        reward=reward,
        reward_per_person=reward,
        required_count=count,
        content="定向测试悬赏",
        source_group="main",
    )


def test_old_publish_formats_are_discarded_and_core_fee_floor_is_preserved(db):
    publisher = add_user(db, PUBLISHER, "发布者", 2000)
    start_balance = publisher["points"]
    router = CommandRouter(db)
    old = router.handle(message(PUBLISHER, "发布者", "/发布悬赏 单次 400 旧格式"))
    another_old = router.handle(message(PUBLISHER, "发布者", "/发布悬赏 3天 3人 15 旧格式"))
    assert not old.handled and not another_old.handled
    first = publish(db, count=1, reward=400)
    second = publish(db, count=3, reward=15, duration_type="days", duration_days=3)
    assert (first["required_count"], first["reward_escrow"], first["fee_escrow"]) == (1, 400, 40)
    assert (second["required_count"], second["reward_escrow"], second["fee_escrow"], second["total_charge"]) == (3, 45, 4, 49)
    assert db.get_user(publisher)["points"] == start_balance - 489


def test_two_people_four_hundred_charges_880(db):
    publisher = add_user(db, PUBLISHER, "发布者", 1000)
    start_balance = publisher["points"]
    bounty = publish(db, count=2, reward=400)
    assert (bounty["reward_escrow"], bounty["fee_escrow"], bounty["total_charge"]) == (800, 80, 880)
    assert db.get_user(publisher)["points"] == start_balance - 880


def test_multi_count_survives_database_restart(tmp_path):
    path = tmp_path / "restart.db"
    first = Database(path)
    first.init()
    add_user(first, PUBLISHER, "发布者", 1000)
    publish(first, count=5, reward=20)
    first.close()
    reopened = Database(path)
    reopened.init()
    bounty = reopened.get_bounty(1)
    assert (bounty["required_count"], bounty["reward_per_person"], bounty["reward_escrow"], bounty["fee_escrow"]) == (5, 20, 100, 10)
    reopened.close()


@pytest.mark.parametrize("count", [0, 11])
def test_invalid_people_rejected(db, count):
    add_user(db, PUBLISHER, "发布者", 1000)
    with pytest.raises(ValueError, match="1 到 10"):
        publish(db, count=count)


@pytest.mark.parametrize("days", [0, 11])
def test_invalid_days_rejected(db, days):
    add_user(db, PUBLISHER, "发布者", 1000)
    with pytest.raises(ValueError, match="1 到 10"):
        publish(db, duration_type="days", duration_days=days)


def test_multi_accept_duplicate_self_full_and_states(db):
    add_user(db, PUBLISHER, "发布者", 1000)
    for index in range(3):
        add_user(db, USERS[index], f"用户{index}")
    publish(db, count=2)
    assert db.accept_bounty(1, message(PUBLISHER, "发布者", "/接悬赏"))["reason"] == "self"
    first = db.accept_bounty(1, message(USERS[0], "用户0", "/接悬赏"))
    duplicate = db.accept_bounty(1, message(USERS[0], "用户0", "/接悬赏"))
    second = db.accept_bounty(1, message(USERS[1], "用户1", "/接悬赏"))
    full = db.accept_bounty(1, message(USERS[2], "用户2", "/接悬赏"))
    assert first["bounty"]["status"] == "recruiting"
    assert duplicate["reason"] == "duplicate"
    assert second["bounty"]["status"] == "active"
    assert full["reason"] in {"not_waiting", "full"}
    assert db.conn.execute("select count(*) from bounty_participants where bounty_id=1").fetchone()[0] == 2


def test_multi_completion_is_settled_one_participant_at_a_time(db):
    publisher = add_user(db, PUBLISHER, "发布者", 1000)
    takers = [add_user(db, USERS[i], f"用户{i}", 10) for i in range(2)]
    publisher_start = publisher["points"]
    taker_starts = [user["points"] for user in takers]
    bounty = publish(db, count=2, reward=200)
    for i in range(2):
        db.accept_bounty(1, message(USERS[i], f"用户{i}", "/接悬赏"))
    first = db.request_bounty_completion(1, message(USERS[0], "用户0", "/完成悬赏"))
    assert first["bounty"]["status"] == "active"
    assert db.get_user(takers[0])["points"] == taker_starts[0]
    second = db.request_bounty_completion(1, message(USERS[1], "用户1", "/完成悬赏"))
    assert second["bounty"]["status"] == "awaiting_confirmation"
    first_settled = db.confirm_bounty_completion(1, message(PUBLISHER, "发布者", "/确认完成"))
    assert first_settled["paid_total"] == 200
    assert not first_settled["all_settled"]
    assert first_settled["fee_burned"] == 0
    assert [db.get_user(user)["points"] for user in takers] == [taker_starts[0] + 200, taker_starts[1]]
    assert db.get_bounty(1)["status"] == "active"
    second_settled = db.confirm_bounty_completion(1, message(PUBLISHER, "发布者", "/确认完成"))
    assert second_settled["paid_total"] == 200
    assert second_settled["all_settled"]
    assert second_settled["fee_burned"] == 40
    assert [db.get_user(user)["points"] for user in takers] == [value + 200 for value in taker_starts]
    assert db.get_user(publisher)["points"] == publisher_start - 440
    assert db.conn.execute("select count(*) from merit_recovery_records where bounty_id=1 and amount=40").fetchone()[0] == 1


def test_single_participant_settlement_failure_rolls_back(db, monkeypatch):
    add_user(db, PUBLISHER, "发布者", 1000)
    takers = [add_user(db, USERS[i], f"用户{i}", 5) for i in range(2)]
    taker_starts = [user["points"] for user in takers]
    publish(db, count=2, reward=100)
    for i in range(2):
        db.accept_bounty(1, message(USERS[i], f"用户{i}", "/接悬赏"))
        db.request_bounty_completion(1, message(USERS[i], f"用户{i}", "/完成悬赏"))
    original = db.bounty_core._tx
    def fail_second(user, amount, reason, balance_after, now):
        if reason.startswith("完成悬赏结算"):
            raise RuntimeError("模拟参与者发放失败")
        return original(user, amount, reason, balance_after, now)

    monkeypatch.setattr(db.bounty_core, "_tx", fail_second)
    with pytest.raises(RuntimeError, match="参与者"):
        db.confirm_bounty_completion(1, message(PUBLISHER, "发布者", "/确认完成"))
    assert [db.get_user(user)["points"] for user in takers] == taker_starts
    assert db.get_bounty(1)["status"] == "awaiting_confirmation"
    assert db.conn.execute("select count(*) from merit_recovery_records").fetchone()[0] == 0


def test_partial_settlement_then_cancel_refunds_only_unpaid_escrow(db):
    publisher = add_user(db, PUBLISHER, "发布者", 1000)
    takers = [add_user(db, USERS[i], f"用户{i}", 0) for i in range(2)]
    start = publisher["points"]
    publish(db, count=2, reward=100)
    for i in range(2):
        db.accept_bounty(1, message(USERS[i], f"用户{i}", "/接悬赏"))
    db.request_bounty_completion(1, message(USERS[0], "用户0", "/完成悬赏"))
    db.confirm_bounty_completion(1, message(PUBLISHER, "发布者", "/确认完成"))
    cancelled = db.cancel_bounty(1, message(PUBLISHER, "发布者", "/取消悬赏"))
    assert cancelled["refund"] == 120
    assert db.get_user(publisher)["points"] == start - 100
    assert db.get_user(takers[0])["points"] == takers[0]["points"] + 100
    assert db.get_user(takers[1])["points"] == takers[1]["points"]


def test_publisher_can_select_one_pending_participant(db):
    add_user(db, PUBLISHER, "发布者", 1000)
    takers = [add_user(db, USERS[i], f"用户{i}", 0) for i in range(2)]
    publish(db, count=2, reward=100)
    for i in range(2):
        db.accept_bounty(1, message(USERS[i], f"用户{i}", "/接悬赏"))
        db.request_bounty_completion(1, message(USERS[i], f"用户{i}", "/完成悬赏"))
    selected = db.confirm_bounty_completion(
        1, message(PUBLISHER, "发布者", "/确认完成0001 2"), 2
    )
    assert selected["participant_name"] == "用户1"
    assert db.get_user(takers[0])["points"] == takers[0]["points"]
    assert db.get_user(takers[1])["points"] == takers[1]["points"] + 100


def test_repeat_confirmation_does_not_pay_twice(db):
    add_user(db, PUBLISHER, "发布者", 500)
    taker = add_user(db, USERS[0], "用户", 0)
    taker_start = taker["points"]
    publish(db, reward=100)
    db.accept_bounty(1, message(USERS[0], "用户", "/接悬赏"))
    db.request_bounty_completion(1, message(USERS[0], "用户", "/完成悬赏"))
    assert db.confirm_bounty_completion(1, message(PUBLISHER, "发布者", "/确认完成"))["ok"]
    repeat = db.confirm_bounty_completion(1, message(PUBLISHER, "发布者", "/确认完成"))
    assert repeat["reason"] == "invalid_status"
    assert db.get_user(taker)["points"] == taker_start + 100
    assert db.conn.execute("select count(*) from transactions where reason like '完成悬赏结算%'").fetchone()[0] == 1


def test_cancel_refunds_reward_and_fee_for_waiting_and_active(db):
    publisher = add_user(db, PUBLISHER, "发布者", 1000)
    publisher_start = publisher["points"]
    add_user(db, USERS[0], "用户")
    publish(db, count=2, reward=100)
    waiting = db.cancel_bounty(1, message(PUBLISHER, "发布者", "/取消悬赏"))
    assert waiting["refund"] == 220
    publish(db, count=2, reward=100)
    db.accept_bounty(2, message(USERS[0], "用户", "/接悬赏"))
    active = db.cancel_bounty(2, message(PUBLISHER, "发布者", "/取消悬赏"))
    assert active["refund"] == 220
    assert db.get_user(publisher)["points"] == publisher_start
    assert db.conn.execute("select count(*) from merit_recovery_records").fetchone()[0] == 0


def test_admin_delete_active_refunds_and_completed_only_archives(db):
    publisher = add_user(db, PUBLISHER, "发布者", 1000)
    taker = add_user(db, USERS[0], "用户")
    publisher_start = publisher["points"]
    taker_start = taker["points"]
    publish(db, reward=100)
    db.accept_bounty(1, message(USERS[0], "用户", "/接悬赏"))
    deleted = db.admin_delete_bounty(1, admin_identity="tester", reason="违规内容")
    assert deleted["refund"] == 110
    assert deleted["bounty"]["business_status"] == "archived"
    assert db.get_user(publisher)["points"] == publisher_start

    publish(db, reward=100)
    db.accept_bounty(2, message(USERS[0], "用户", "/接悬赏"))
    db.request_bounty_completion(2, message(USERS[0], "用户", "/完成悬赏"))
    db.confirm_bounty_completion(2, message(PUBLISHER, "发布者", "/确认完成"))
    before = db.get_user(publisher)["points"]
    archived = db.admin_delete_bounty(2, admin_identity="tester", reason="整理历史")
    assert archived["refund"] == 0
    assert db.get_user(publisher)["points"] == before
    assert db.get_user(taker)["points"] == taker_start + 100
    assert db.conn.execute("select count(*) from bounties").fetchone()[0] == 2


def test_weekly_cleanup_scope_and_idempotency(db):
    publisher = add_user(db, PUBLISHER, "发布者", 5000)
    for i in range(5):
        add_user(db, USERS[i], f"用户{i}")
    waiting = publish(db, reward=100)
    recruiting = publish(db, count=2, reward=100)
    db.accept_bounty(recruiting["id"], message(USERS[0], "用户0", "/接悬赏"))
    active = publish(db, count=2, reward=100)
    db.accept_bounty(active["id"], message(USERS[1], "用户1", "/接悬赏"))
    db.accept_bounty(active["id"], message(USERS[2], "用户2", "/接悬赏"))
    pending = publish(db, reward=100)
    db.accept_bounty(pending["id"], message(USERS[3], "用户3", "/接悬赏"))
    db.request_bounty_completion(pending["id"], message(USERS[3], "用户3", "/完成悬赏"))
    completed = publish(db, reward=100)
    db.accept_bounty(completed["id"], message(USERS[4], "用户4", "/接悬赏"))
    db.request_bounty_completion(completed["id"], message(USERS[4], "用户4", "/完成悬赏"))
    db.confirm_bounty_completion(completed["id"], message(PUBLISHER, "发布者", "/确认完成"))

    run_at = datetime(2026, 8, 10, 0, 0, tzinfo=BEIJING_TZ)
    first = db.run_weekly_bounty_cleanup(run_at)
    balance = db.get_user(publisher)["points"]
    second = db.run_weekly_bounty_cleanup(run_at)
    assert (first["cancelled_count"], first["archived_count"]) == (1, 1)
    assert second["ran"] is False
    assert db.get_user(publisher)["points"] == balance
    assert db.get_bounty(waiting["id"])["status"] == "cancelled"
    assert db.get_bounty(recruiting["id"])["status"] == "recruiting"
    assert db.get_bounty(active["id"])["status"] == "active"
    assert db.get_bounty(pending["id"])["status"] == "awaiting_confirmation"
    assert db.get_bounty(completed["id"])["business_status"] == "archived"


def test_admin_people_and_reward_edits_move_real_funds(db):
    publisher = add_user(db, PUBLISHER, "发布者", 1000)
    publisher_start = publisher["points"]
    publish(db, count=2, reward=100)
    increased = db.admin_update_bounty(
        1,
        {"required_count": 3, "reward_per_person": 100, "reason": "增加一个名额"},
        admin_identity="tester",
    )
    assert increased["balance_delta"] == -110
    assert db.get_user(publisher)["points"] == publisher_start - 330
    reduced = db.admin_update_bounty(
        1,
        {"required_count": 1, "reward_per_person": 50, "reason": "缩减预算"},
        admin_identity="tester",
    )
    assert reduced["balance_delta"] == 275
    assert db.get_user(publisher)["points"] == publisher_start - 55
    assert (reduced["bounty"]["reward_escrow"], reduced["bounty"]["fee_escrow"]) == (50, 5)
    assert db.conn.execute("select count(*) from bounty_admin_audit where bounty_id=1").fetchone()[0] == 2


def test_admin_cannot_reduce_below_accepted_or_spend_missing_balance(db):
    add_user(db, PUBLISHER, "发布者", 250)
    for i in range(2):
        add_user(db, USERS[i], f"用户{i}")
    publish(db, count=2, reward=100)
    db.accept_bounty(1, message(USERS[0], "用户0", "/接悬赏"))
    db.accept_bounty(1, message(USERS[1], "用户1", "/接悬赏"))
    with pytest.raises(ValueError, match="不能小于已接取人数"):
        db.admin_update_bounty(1, {"required_count": 1, "reason": "非法缩减"}, admin_identity="tester")
    with pytest.raises(ValueError, match="余额不足"):
        db.admin_update_bounty(1, {"reward_per_person": 1000, "reason": "非法加价"}, admin_identity="tester")
    assert db.get_bounty(1)["reward_per_person"] == 100


def test_content_duration_status_validation_and_immutable_identity(db):
    add_user(db, PUBLISHER, "发布者", 1000)
    add_user(db, USERS[0], "用户")
    publish(db, reward=100)
    db.accept_bounty(1, message(USERS[0], "用户", "/接悬赏"))
    changed = db.admin_update_bounty(
        1,
        {"content": "只改内容", "duration_type": "days", "duration_days": 3, "reason": "修正文案"},
        admin_identity="tester",
    )["bounty"]
    assert changed["content"] == "只改内容" and changed["deadline_at"]
    assert changed["total_charge"] == 110
    with pytest.raises(ValueError, match="参与者数据决定"):
        db.admin_update_bounty(1, {"status": "waiting", "reason": "非法倒退"}, admin_identity="tester")
    with pytest.raises(ValueError, match="禁止修改人员"):
        db.admin_update_bounty(1, {"publisher_user_id": USERS[1], "reason": "篡改人员"}, admin_identity="tester")
    with pytest.raises(ValueError, match="禁止修改人员"):
        db.admin_update_bounty(1, {"participants": [], "reason": "清空人员"}, admin_identity="tester")


def test_admin_completed_status_really_settles_and_terminal_cannot_reactivate(db):
    add_user(db, PUBLISHER, "发布者", 500)
    taker = add_user(db, USERS[0], "用户")
    taker_start = taker["points"]
    publish(db, reward=100)
    db.accept_bounty(1, message(USERS[0], "用户", "/接悬赏"))
    with pytest.raises(ValueError, match="待确认"):
        db.admin_update_bounty(1, {"status": "completed", "reason": "提前完成"}, admin_identity="tester")
    db.request_bounty_completion(1, message(USERS[0], "用户", "/完成悬赏"))
    done = db.admin_update_bounty(1, {"status": "completed", "reason": "管理员核验"}, admin_identity="tester")
    assert done["bounty"]["status"] == "completed"
    assert db.get_user(taker)["points"] == taker_start + 100
    with pytest.raises(ValueError, match="不能重新激活"):
        db.admin_update_bounty(1, {"status": "waiting", "reason": "非法重开"}, admin_identity="tester")


def test_grouped_counts_empty_groups_and_archive_group(db):
    add_user(db, PUBLISHER, "发布者", 1000)
    publish(db)
    grouped = db.list_all_bounties_grouped()
    assert grouped["groups"]["waiting"]["count"] == 1
    assert grouped["groups"]["recruiting"]["count"] == 0
    assert grouped["groups"]["archived"]["items"] == []
    assert grouped["total"] == sum(group["count"] for group in grouped["groups"].values())


def test_admin_api_routes_group_and_reject_identity_fields(db):
    import main
    from fastapi import HTTPException

    add_user(db, PUBLISHER, "发布者", 1000)
    publish(db)
    main.app.state.db = db
    paths = {route.path for route in main.app.routes}
    assert {
        "/api/bounties/all",
        "/api/bounties/{bounty_id}",
        "/api/bounties/{bounty_id}/delete-preview",
        "/api/commission-house/orders",
        "/api/commission-house/orders/{order_id}",
    } <= paths
    grouped = asyncio.run(main.get_all_bounties())
    assert grouped["groups"]["waiting"]["count"] == 1
    with pytest.raises(HTTPException, match="禁止修改人员"):
        asyncio.run(main.update_bounty(1, {"publisher_user_id": USERS[0], "reason": "篡改"}))


def test_invalid_identity_rejected_and_dual_group_permissions_preserved(db):
    add_user(db, PUBLISHER, "发布者", 1000)
    publish(db)
    router = CommandRouter(db)
    blocked = router.handle(message(USERS[0], "用户", "/查看需求", "main"))
    allowed = router.handle(message(USERS[0], "用户", "/查看需求", "bounty"))
    invalid = router.handle({"sender": "无ID", "text": "/接取需求D0001", "group_key": "bounty"})
    assert "悬赏群" in blocked.replies[0]
    assert "D0001" in allowed.replies[0]
    assert "平台唯一 ID" in invalid.replies[0]


def test_bounty_list_final_messages_stay_within_ten_lines_and_two_parts(db):
    add_user(db, PUBLISHER, "发布者", 10000)
    router = CommandRouter(db)
    for index in range(12):
        publish(db, reward=10)
    result = router.handle(message(USERS[0], "用户", "/查看需求", "bounty"))
    parts = prepare_outgoing_text_messages(result.replies[0])
    assert 1 <= len(parts) <= 2
    assert all(part.count("\n") + 1 <= 9 for part in parts)
    assert "/下一页" not in "\n".join(parts)
