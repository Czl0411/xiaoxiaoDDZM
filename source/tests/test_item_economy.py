from __future__ import annotations

import json
import zipfile
from datetime import datetime

from app.command_router import CommandRouter
from app.database import (
    ANGELICA_USER_ID,
    BRA_ITEM_NAME,
    LOYAL_DOG_MEDAL_NAME,
    PANTIES_ITEM_NAME,
    STOCKING_ITEM_NAME,
    SUPREME_STOCKING_REWARD_NAME,
    Database,
)


def make_user(db: Database, nickname: str, user_id: str, points: int = 0):
    user = db.ensure_user(
        {
            "sender": nickname,
            "user_id": user_id,
            "platform_user_id": user_id,
        }
    )
    if points:
        db.add_points(user, points, "测试初始化")
    return db.get_user({"platform_user_id": user_id})


def create_item(db: Database, name: str, price: int, stock: int = -1) -> int:
    return db.upsert_shop_item(
        {
            "name": name,
            "description": "测试商品",
            "price": price,
            "stock": stock,
            "enabled": True,
            "use_enabled": True,
            "use_target": "self",
        }
    )


def test_batch_purchase_credits_configured_owner_without_public_side_effect(tmp_path):
    db = Database(tmp_path / "bot.db")
    db.init()
    buyer = make_user(db, "购买者", "buyer-id", 1000)
    owner = make_user(db, "安洁莉卡", ANGELICA_USER_ID, 0)
    create_item(db, "【安洁莉卡的侍奉服务】", 20, 10)
    db.ensure_requested_economy_items()

    result = db.purchase_item(buyer, "【安洁莉卡的侍奉服务】", 3)

    assert result["ok"]
    assert result["quantity"] == 3
    assert result["price"] == 60
    assert db.get_user(buyer)["points"] == 940
    assert db.get_user(owner)["points"] == 60
    assert db.get_inventory(buyer)[0]["quantity"] == 3


def test_ninety_nine_stockings_require_manual_exchange_and_reward_is_usable(tmp_path):
    db = Database(tmp_path / "bot.db")
    db.init()
    user = make_user(db, "收藏者", "collector-id", 0)
    create_item(db, STOCKING_ITEM_NAME, 0, 200)
    db.ensure_requested_economy_items()
    db._grant_inventory_no_commit(user, STOCKING_ITEM_NAME, 99)
    db.conn.commit()
    inventory = {row["item_name"]: row["quantity"] for row in db.get_inventory(user)}
    assert inventory[STOCKING_ITEM_NAME] == 99

    exchanged = db.exchange_offer_by_number(user, 6)
    assert exchanged["ok"]
    inventory = {row["item_name"]: row["quantity"] for row in db.get_inventory(user)}
    assert inventory[SUPREME_STOCKING_REWARD_NAME] == 1
    assert STOCKING_ITEM_NAME not in inventory

    used = db.use_inventory_item(user, None, 1)
    assert used["ok"]
    assert used["balance"] == 1500
    inventory = {row["item_name"]: row["quantity"] for row in db.get_inventory(user)}
    assert inventory[LOYAL_DOG_MEDAL_NAME] == 1
    assert [row["title"] for row in db.list_user_titles(user)] == [
        "【超级丝袜王】",
        "【小小的绝对舔狗】",
    ]

    db._grant_inventory_no_commit(user, STOCKING_ITEM_NAME, 99)
    db.conn.commit()
    second = db.exchange_offer_by_number(user, 6)
    assert not second["ok"]
    assert second["reason"] == "limit"
    inventory = {row["item_name"]: row["quantity"] for row in db.get_inventory(user)}
    assert inventory[STOCKING_ITEM_NAME] == 99
    assert SUPREME_STOCKING_REWARD_NAME not in inventory
    history = db.conn.execute("select count(*) from exchange_history where user_pk=?", (int(user["id"]),)).fetchone()
    assert int(history[0]) == 1


def test_random_drop_uses_existing_item_and_decrements_finite_stock(tmp_path, monkeypatch):
    db = Database(tmp_path / "bot.db")
    db.init()
    user = make_user(db, "掉落者", "drop-id", 0)
    item_id = create_item(db, STOCKING_ITEM_NAME, 10, 2)
    db.upsert_drop_pool_entry({
        "item_id": item_id,
        "chance_percent": 100,
        "min_quantity": 1,
        "max_quantity": 1,
        "deduct_stock": True,
        "enabled": True,
    })
    monkeypatch.setattr("app.database.random.random", lambda: 0.0)

    drop = db.maybe_grant_random_drop(
        user,
        "checkin",
        {
            "random_item_drop_enabled": "true",
            "random_item_drop_chance_percent": 100,
            "random_item_drop_sources": ["checkin"],
        },
    )

    assert drop and drop["item"]["id"] == item_id
    assert db.get_inventory(user)[0]["quantity"] == 1
    assert db.conn.execute("select stock from shop_items where id=?", (item_id,)).fetchone()[0] == 1


def test_stocking_is_purchasable_and_drop_does_not_consume_shop_stock(tmp_path, monkeypatch):
    db = Database(tmp_path / "bot.db")
    db.init()
    buyer = make_user(db, "丝袜购买者", "stocking-buyer", 100)
    item_id = create_item(db, STOCKING_ITEM_NAME, 10, 99)
    db.upsert_drop_pool_entry({
        "item_id": item_id,
        "chance_percent": 50,
        "min_quantity": 1,
        "max_quantity": 1,
        "deduct_stock": False,
        "enabled": True,
        "sort_order": 30,
    })
    db._grant_inventory_no_commit(buyer, STOCKING_ITEM_NAME, 7)
    db.conn.commit()

    router = CommandRouter(db)
    shop = router.handle({
        "sender": "丝袜购买者",
        "platform_user_id": "stocking-buyer",
        "user_id": "stocking-buyer",
        "text": "/商店",
    })
    assert shop.handled
    assert STOCKING_ITEM_NAME in shop.replies[0]

    shop_items = db.list_shop_items()
    number = next(index for index, item in enumerate(shop_items, 1) if item["id"] == item_id)
    purchase = router.handle({
        "sender": "丝袜购买者",
        "platform_user_id": "stocking-buyer",
        "user_id": "stocking-buyer",
        "text": f"/购买{number}",
    })
    assert purchase.handled
    assert STOCKING_ITEM_NAME in purchase.replies[0]
    assert db.get_user(buyer)["points"] == 90
    assert {row["item_name"]: row["quantity"] for row in db.get_inventory(buyer)}[STOCKING_ITEM_NAME] == 8
    assert db.conn.execute("select stock from shop_items where id=?", (item_id,)).fetchone()[0] == 98

    monkeypatch.setattr("app.database.random.random", lambda: 0.0)
    drop = db.maybe_grant_random_drop(
        buyer,
        "checkin",
        {
            "random_item_drop_enabled": "true",
            "random_item_drop_chance_percent": 100,
            "random_item_drop_sources": ["checkin"],
        },
    )
    assert drop and drop["item"]["id"] == item_id
    assert {row["item_name"]: row["quantity"] for row in db.get_inventory(buyer)}[STOCKING_ITEM_NAME] == 9
    assert db.conn.execute("select stock from shop_items where id=?", (item_id,)).fetchone()[0] == 98
    entry = db.conn.execute(
        "select * from item_drop_pool_entries where item_id=?", (item_id,)
    ).fetchone()
    assert entry["chance_percent"] == 50
    assert entry["deduct_stock"] == 0
    assert entry["enabled"] == 1


def test_event_drop_uses_twenty_percent_gate_then_fifty_thirty_twenty_weights(tmp_path, monkeypatch):
    db = Database(tmp_path / "bot.db")
    db.init()
    db.ensure_requested_economy_items()
    features = {
        "random_item_drop_enabled": "true",
        "random_item_drop_chance_percent": 20,
        "random_item_drop_sources": ["game_win"],
    }

    rolls = iter([0.1999, 0.4999, 0.0, 0.5, 0.0, 0.8, 0.2])
    monkeypatch.setattr("app.database.random.random", lambda: next(rolls))
    first = db.maybe_grant_random_drop(make_user(db, "丝袜掉落", "weighted-1"), "game_win", features)
    second = db.maybe_grant_random_drop(make_user(db, "胸罩掉落", "weighted-2"), "game_win", features)
    third = db.maybe_grant_random_drop(make_user(db, "内裤掉落", "weighted-3"), "game_win", features)
    none = db.maybe_grant_random_drop(make_user(db, "未掉落", "weighted-4"), "game_win", features)

    assert first["item"]["name"] == STOCKING_ITEM_NAME
    assert second["item"]["name"] == BRA_ITEM_NAME
    assert third["item"]["name"] == PANTIES_ITEM_NAME
    assert none is None


def test_normal_chat_drop_uses_one_percent_gate_and_equal_three_item_pool(tmp_path, monkeypatch):
    db = Database(tmp_path / "bot.db")
    db.init()
    db.ensure_requested_economy_items()
    user = make_user(db, "聊天掉落者", "normal-chat-drop-id", 0)
    monkeypatch.setattr("app.database.random.random", lambda: 0.0099)
    monkeypatch.setattr("app.database.random.choice", lambda rows: rows[1])

    drop = db.maybe_grant_normal_chat_drop(
        user,
        {
            "normal_chat_item_drop_enabled": "true",
            "normal_chat_item_drop_chance_percent": 1,
        },
    )

    assert drop and drop["item"]["name"] in {
        STOCKING_ITEM_NAME,
        BRA_ITEM_NAME,
        PANTIES_ITEM_NAME,
    }
    inventory = db.get_inventory(user)
    assert len(inventory) == 1
    assert inventory[0]["item_name"] == drop["item"]["name"]
    assert inventory[0]["quantity"] == 1

    monkeypatch.setattr("app.database.random.random", lambda: 0.01)
    assert db.maybe_grant_normal_chat_drop(
        user,
        {
            "normal_chat_item_drop_enabled": "true",
            "normal_chat_item_drop_chance_percent": 1,
        },
    ) is None


def test_successful_begging_can_drop_but_failed_begging_cannot(tmp_path, monkeypatch):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    item_id = create_item(db, STOCKING_ITEM_NAME, 10, 10)
    db.upsert_drop_pool_entry({
        "item_id": item_id,
        "chance_percent": 100,
        "min_quantity": 1,
        "max_quantity": 1,
        "deduct_stock": True,
        "enabled": True,
    })
    config = db.get_config()
    config["features"].update(
        {
            "random_item_drop_enabled": "true",
            "random_item_drop_chance_percent": 100,
            "random_item_drop_sources": ["beg_success"],
        }
    )
    db.save_config(config)
    router = CommandRouter(db)

    successful = db.ensure_user("成功乞讨者")
    db.conn.execute("update users set points=-100 where id=?", (successful["id"],))
    db.conn.commit()
    success_reply = router.handle({"sender": "成功乞讨者", "text": "/乞讨"}).replies[0]
    assert "意外掉落" in success_reply
    assert db.get_inventory(successful)[0]["item_name"] == STOCKING_ITEM_NAME

    db.clear_active_beggar()
    failed = db.ensure_user("失败乞讨者")
    db.conn.execute("update users set points=-10 where id=?", (failed["id"],))
    db.conn.commit()
    rolls = iter([1, 1])
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: next(rolls))
    failure_reply = router.handle({"sender": "失败乞讨者", "text": "/乞讨"}).replies[0]
    assert "意外掉落" not in failure_reply
    assert db.get_inventory(failed) == []


def test_weekly_exchange_limit_and_atomic_material_check(tmp_path):
    db = Database(tmp_path / "bot.db")
    db.init()
    user = make_user(db, "兑换者", "exchange-id", 1000)
    create_item(db, STOCKING_ITEM_NAME, 10, 100)
    db.ensure_requested_economy_items()
    db._grant_inventory_no_commit(user, STOCKING_ITEM_NAME, 60)
    db.conn.commit()

    first = db.exchange_offer_by_number(user, 1)
    second = db.exchange_offer_by_number(user, 1)
    third = db.exchange_offer_by_number(user, 1)

    assert first["ok"] and second["ok"]
    assert not third["ok"] and third["reason"] == "limit"
    assert db.get_user(user)["points"] == 1000 + 480
    assert db.get_inventory(user)[0]["quantity"] == 20

    insufficient = db.exchange_offer_by_number(user, 2)
    assert not insufficient["ok"] and insufficient["reason"] == "materials"
    assert db.get_inventory(user)[0]["quantity"] == 20


def test_exchange_shop_reply_uses_short_material_names_and_compact_lines(tmp_path):
    db = Database(tmp_path / "bot.db")
    db.init()
    user = make_user(db, "查看者", "viewer-id", 0)
    create_item(db, STOCKING_ITEM_NAME, 10, 100)
    db.ensure_requested_economy_items()
    router = CommandRouter(db)

    reply = router.handle(
        {"sender": "查看者", "user_id": "viewer-id", "text": "/兑换仓库"}
    ).replies[0]

    assert "需:丝袜×20" in reply
    assert "持有:丝袜0/20" in reply
    assert "【高洁圣女小小的无垢丝袜】" not in reply
    assert "\n\n" not in reply


def test_full_export_contains_all_settings_and_only_recent_chat_window(tmp_path):
    db = Database(tmp_path / "bot.db")
    db.init()
    db.conn.execute(
        "insert into messages(message_id,sender,text,created_at) values('old','旧消息','x','2026-07-18 12:00:00')"
    )
    db.conn.execute(
        "insert into messages(message_id,sender,text,created_at) values('recent','新消息','y','2026-07-20 12:00:00')"
    )
    db.conn.commit()
    output = tmp_path / "export.zip"

    db.export_data_zip(output, now=datetime(2026, 7, 21, 10, 0, 0))

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert "config/config.json" in names
        assert "commands/system_commands_and_settings.json" in names
        assert "commands/custom_commands.json" in names
        messages = json.loads(archive.read("database/messages.json"))
    assert [row["message_id"] for row in messages] == ["recent"]
