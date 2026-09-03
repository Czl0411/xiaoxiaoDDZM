import sqlite3

import pytest

from app.command_router import CommandRouter
from app.outgoing_text import prepare_outgoing_text_messages
from app.database import (
    Database,
    THEFT_ABSOLUTE_ITEM,
    THEFT_MULTI_DEFENSE_ITEM,
    THEFT_SINGLE_DEFENSE_ITEM,
)


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    return db


def set_points(db, nickname, points):
    user = db.ensure_user(nickname)
    db.conn.execute("update users set points=? where id=?", (points, user["id"]))
    db.conn.commit()
    return db.get_user(nickname)


def test_ordinary_theft_success_transfers_points_and_records_attempt(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    set_points(db, "小偷", 50)
    set_points(db, "目标", 40)
    rolls = iter([1, 17, 1])
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: next(rolls))

    reply = CommandRouter(db).handle({"sender": "小偷", "text": "/偷窃 目标"}).replies[0]

    assert "偷得 17 功德点" in reply
    assert "值班修女收取 1 功德点" in reply
    assert "实际获得 16 功德点" in reply
    assert db.get_user("小偷")["points"] == 66
    assert db.get_user("目标")["points"] == 23
    attempt = db.conn.execute("select * from theft_attempts").fetchone()
    assert attempt["outcome"] == "success"
    assert attempt["settled_amount"] == 17
    assert db.conn.execute("select sum(change_amount) from transactions where reason like '%偷窃%'").fetchone()[0] == -1


def test_failed_theft_compensates_target_and_allows_debt_to_minus_100(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    set_points(db, "小偷", 21)
    set_points(db, "目标", 0)
    db.set_display_name("目标", "目标老板")
    rolls = iter([100, 100, 100])
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: next(rolls))

    reply = CommandRouter(db).handle({"sender": "小偷", "text": "/偷窃目标"}).replies[0]

    assert "赔偿 100 功德点" in reply
    assert "目标老板" in reply
    assert "{'id':" not in reply
    assert db.get_user("小偷")["points"] == -79
    assert db.get_user("目标")["points"] == 100


def test_theft_daily_limit_is_two_attempts(tmp_path):
    db = make_db(tmp_path)
    actor = set_points(db, "小偷", 200)
    target = set_points(db, "目标", 200)

    assert db.resolve_theft(actor, target, 1, True)["ok"]
    assert db.resolve_theft(actor, target, 1, True)["ok"]
    blocked = db.resolve_theft(actor, target, 1, True)

    assert not blocked["ok"]
    assert blocked["reason"] == "daily_limit"
    assert db.count_theft_attempts_today(actor) == 2


def test_target_cannot_be_stolen_below_minus_10(tmp_path):
    db = make_db(tmp_path)
    actor = set_points(db, "小偷", 100)
    target = set_points(db, "目标", 3)

    result = db.resolve_theft(actor, target, 100, True)

    assert result["amount"] == 13
    assert db.get_user("目标")["points"] == -10
    assert db.get_user("小偷")["points"] == 112


def test_single_defense_coupon_blocks_once_and_is_consumed(tmp_path):
    db = make_db(tmp_path)
    db.ensure_theft_shop_items()
    actor = set_points(db, "小偷", 100)
    set_points(db, "目标", 100)
    db.purchase_item("目标", THEFT_SINGLE_DEFENSE_ITEM)
    target_before = db.get_user("目标")["points"]

    result = db.resolve_theft(actor, db.get_user("目标"), 30, True)

    assert result["outcome"] == "protected"
    assert result["protection"]["item"] == THEFT_SINGLE_DEFENSE_ITEM
    assert db.get_user("小偷")["points"] == 100
    assert db.get_user("目标")["points"] == target_before
    assert not db.get_inventory("目标")


def test_multi_defense_coupon_blocks_exactly_five_times(tmp_path):
    db = make_db(tmp_path)
    db.ensure_theft_shop_items()
    target = set_points(db, "目标", 300)
    db.purchase_item("目标", THEFT_MULTI_DEFENSE_ITEM)
    remaining = []
    for index in range(5):
        actor = set_points(db, f"小偷{index}", 100)
        result = db.resolve_theft(actor, target, 10, True)
        remaining.append(result["protection"]["remaining"])

    assert remaining == [4, 3, 2, 1, 0]
    assert not db.get_inventory("目标")


def test_absolute_theft_item_is_special_and_executes_through_use_command(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    db.ensure_theft_shop_items()
    set_points(db, "小偷", 200)
    set_points(db, "目标", 200)
    db.purchase_item("小偷", THEFT_ABSOLUTE_ITEM)
    rolls = iter([50, 50, 60])
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: next(rolls))

    reply = CommandRouter(db).handle({"sender": "小偷", "text": "/对目标使用物品1"}).replies[0]

    assert "绝对掠夺" in reply
    assert "偷得 60 功德点" in reply
    assert "值班修女收取 6 功德点" in reply
    assert "实际获得 54 功德点" in reply
    assert db.get_user("小偷")["points"] == 214
    assert db.get_user("目标")["points"] == 140
    assert not db.get_inventory("小偷")
    item = db.conn.execute("select * from shop_items where name=?", (THEFT_ABSOLUTE_ITEM,)).fetchone()
    assert item["item_category"] == "special"


def test_absolute_theft_and_defense_are_both_consumed(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    db.ensure_theft_shop_items()
    set_points(db, "小偷", 200)
    set_points(db, "目标", 200)
    db.purchase_item("小偷", THEFT_ABSOLUTE_ITEM)
    db.purchase_item("目标", THEFT_SINGLE_DEFENSE_ITEM)
    actor_before = db.get_user("小偷")["points"]
    target_before = db.get_user("目标")["points"]
    rolls = iter([50, 50, 60])
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: next(rolls))

    reply = CommandRouter(db).handle({"sender": "小偷", "text": "/对目标使用物品1"}).replies[0]

    assert "同时消耗" in reply
    assert db.get_user("小偷")["points"] == actor_before
    assert db.get_user("目标")["points"] == target_before
    assert not db.get_inventory("小偷")
    assert not db.get_inventory("目标")


def test_renaming_special_item_keeps_inventory_and_mechanism(tmp_path):
    db = make_db(tmp_path)
    db.ensure_theft_shop_items()
    actor = set_points(db, "小偷", 100)
    set_points(db, "目标", 300)
    db.purchase_item("目标", THEFT_MULTI_DEFENSE_ITEM)
    item = dict(db.conn.execute("select * from shop_items where name=?", (THEFT_MULTI_DEFENSE_ITEM,)).fetchone())
    item["name"] = "财神的五重金光券"

    db.upsert_shop_item(item)
    result = db.resolve_theft(actor, db.get_user("目标"), 20, True)

    inventory = db.get_inventory("目标")
    assert inventory[0]["item_name"] == "财神的五重金光券"
    assert inventory[0]["special_kind"] == "theft_multi_defense"
    assert result["outcome"] == "protected"
    assert result["protection"]["remaining"] == 4


def test_absolute_theft_does_not_count_toward_or_obey_daily_limit(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    db.ensure_theft_shop_items()
    actor = set_points(db, "小偷", 500)
    target = set_points(db, "目标", 500)
    assert db.resolve_theft(actor, target, 1, True)["ok"]
    assert db.resolve_theft(actor, target, 1, True)["ok"]
    db.purchase_item("小偷", THEFT_ABSOLUTE_ITEM)
    rolls = iter([50, 50, 60])
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: next(rolls))

    special_reply = CommandRouter(db).handle({"sender": "小偷", "text": "/对目标使用物品1"}).replies[0]
    ordinary_after_special = db.resolve_theft(db.get_user("小偷"), db.get_user("目标"), 1, True)

    assert "绝对掠夺" in special_reply
    assert db.count_theft_attempts_today("小偷") == 2
    assert db.conn.execute("select count(*) from theft_attempts where special_item=1").fetchone()[0] == 1
    assert not ordinary_after_special["ok"]
    assert ordinary_after_special["reason"] == "daily_limit"


def test_absolute_theft_can_be_used_while_actor_has_negative_points(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    db.ensure_theft_shop_items()
    set_points(db, "小偷", 100)
    set_points(db, "目标", 200)
    db.purchase_item("小偷", THEFT_ABSOLUTE_ITEM)
    set_points(db, "小偷", -50)
    rolls = iter([50, 50, 60])
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: next(rolls))

    reply = CommandRouter(db).handle({"sender": "小偷", "text": "/对目标使用物品1"}).replies[0]

    assert "绝对掠夺" in reply
    assert db.get_user("小偷")["points"] == 4
    assert db.get_user("目标")["points"] == 140


@pytest.mark.parametrize(
    ("stolen_amount", "bribe_amount", "net_amount"),
    [(1, 0, 1), (10, 0, 10), (11, 1, 10), (19, 1, 18), (20, 2, 18), (99, 9, 90), (100, 10, 90)],
)
def test_successful_theft_bribe_uses_integer_floor_and_is_destroyed(
    tmp_path, stolen_amount, bribe_amount, net_amount
):
    db = make_db(tmp_path)
    actor = set_points(db, "小偷", 500)
    target = set_points(db, "目标", 500)
    total_before = sum(row["points"] for row in db.conn.execute("select points from users"))

    result = db.resolve_theft(
        actor, target, stolen_amount, True, event_id=f"main:amount-{stolen_amount}"
    )

    assert result["amount"] == stolen_amount
    assert result["bribe_amount"] == bribe_amount
    assert result["net_amount"] == net_amount
    assert db.get_user("小偷")["points"] == 500 + net_amount
    assert db.get_user("目标")["points"] == 500 - stolen_amount
    total_after = sum(row["points"] for row in db.conn.execute("select points from users"))
    assert total_before - total_after == bribe_amount
    audit = db.conn.execute(
        "select * from theft_attempts where event_id=?", (f"main:amount-{stolen_amount}",)
    ).fetchone()
    assert audit["audit_type"] == ("偷窃贿赂/功德回收" if bribe_amount else "偷窃结算")
    assert audit["settled_amount"] == stolen_amount
    assert audit["bribe_amount"] == bribe_amount
    assert audit["net_amount"] == net_amount


def test_theft_event_is_idempotent(tmp_path):
    db = make_db(tmp_path)
    actor = set_points(db, "小偷", 500)
    target = set_points(db, "目标", 500)

    first = db.resolve_theft(actor, target, 100, True, event_id="main:same-message")
    second = db.resolve_theft(actor, target, 100, True, event_id="main:same-message")

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert db.get_user("小偷")["points"] == 590
    assert db.get_user("目标")["points"] == 400
    assert db.conn.execute(
        "select count(*) from theft_attempts where event_id='main:same-message'"
    ).fetchone()[0] == 1
    assert db.conn.execute(
        "select count(*) from transactions where reason like '%偷窃%' or reason like '%被 小偷%'"
    ).fetchone()[0] == 2


def test_theft_transaction_rolls_back_on_mid_settlement_error(tmp_path):
    db = make_db(tmp_path)
    actor = set_points(db, "小偷", 500)
    target = set_points(db, "目标", 500)
    db.conn.execute(
        """create temp trigger fail_theft_audit before insert on theft_attempts
           begin select raise(abort, 'forced theft audit failure'); end"""
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced theft audit failure"):
        db.resolve_theft(actor, target, 100, True, event_id="main:rollback")

    assert db.get_user("小偷")["points"] == 500
    assert db.get_user("目标")["points"] == 500
    assert db.conn.execute("select count(*) from transactions").fetchone()[0] == 0


def test_failed_theft_has_no_bribe(tmp_path):
    db = make_db(tmp_path)
    actor = set_points(db, "小偷", 500)
    target = set_points(db, "目标", 500)

    result = db.resolve_theft(actor, target, 100, False, event_id="main:failed")

    assert result["outcome"] == "caught"
    assert result["bribe_amount"] == 0
    assert result["net_amount"] == 0
    audit = db.conn.execute("select * from theft_attempts where event_id='main:failed'").fetchone()
    assert audit["bribe_amount"] == 0


def test_bribe_success_reply_amounts_and_line_limit(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    set_points(db, "小偷", 500)
    set_points(db, "目标", 500)
    rolls = iter([100, 100, 1])
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: next(rolls))

    reply = CommandRouter(db).handle(
        {"sender": "小偷", "text": "/偷窃 目标", "message_id": "reply-100", "group_key": "main"}
    ).replies[0]

    assert "偷得 100 功德点" in reply
    assert "值班修女收取 10 功德点" in reply
    assert "实际获得 90 功德点" in reply
    assert all(part.count("\n") + 1 <= 10 for part in prepare_outgoing_text_messages(reply))
