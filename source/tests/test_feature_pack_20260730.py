from __future__ import annotations

from app.command_router import CommandRouter
from app.database import Database


def message(user_id: str, nickname: str, text: str) -> dict:
    return {
        "platform_user_id": user_id,
        "user_id": user_id,
        "sender": nickname,
        "message_id": f"{user_id}-{text}",
        "text": text,
        "is_self": False,
    }


def make_db(tmp_path) -> Database:
    db = Database(tmp_path / "bot.db")
    db.init()
    return db


def test_newcomer_benefit_is_granted_once_for_first_real_message(tmp_path):
    db = make_db(tmp_path)

    first = db.ensure_user(message("new-user-1", "新人", "第一次发言"))
    second = db.ensure_user(message("new-user-1", "新人新昵称", "第二次发言"))

    assert first["points"] == 60
    assert second["points"] == 60
    stats = db.newcomer_benefit_stats()
    assert stats["recipient_count"] == 1
    assert stats["total_amount"] == 60
    assert db.conn.execute(
        "select count(*) from transactions where reason='新人首次发言福利'"
    ).fetchone()[0] == 1


def test_internal_user_creation_does_not_claim_newcomer_message_benefit(tmp_path):
    db = make_db(tmp_path)

    user = db.ensure_user(
        {
            "platform_user_id": "internal-user",
            "user_id": "internal-user",
            "sender": "后台创建",
        }
    )

    assert user["points"] == 0
    assert db.newcomer_benefit_stats()["recipient_count"] == 0


def test_user_lucky_bag_is_self_funded_and_admin_bag_is_system_funded(tmp_path):
    db = make_db(tmp_path)
    user = db.ensure_user(
        {"platform_user_id": "bag-user", "user_id": "bag-user", "sender": "普通用户"}
    )
    db.add_points(user, 200, "测试初始化")
    admin = db.ensure_user(
        {"platform_user_id": "bag-admin", "user_id": "bag-admin", "sender": "管理员"}
    )
    db.update_user(admin, {**admin, "is_admin": True})
    router = CommandRouter(db)

    user_result = router.handle(message("bag-user", "普通用户", "/发福袋100金币5个"))
    admin_result = router.handle(message("bag-admin", "管理员", "/管理员发福袋100金币5个"))

    assert user_result.handled
    assert admin_result.handled
    assert db.get_user(user)["points"] == 100
    assert db.get_user(admin)["points"] == 0
    packets = db.list_red_packets()
    assert {row["funding_type"] for row in packets[:2]} == {"user", "admin"}


def test_drop_pool_membership_does_not_change_shop_fields_even_after_restart(tmp_path):
    db = make_db(tmp_path)
    item_id = db.upsert_shop_item(
        {
            "name": "测试掉落物",
            "item_category": "normal",
            "price": 10,
            "stock": 8,
            "enabled": True,
            "use_enabled": True,
        }
    )

    db.upsert_drop_pool_entry(
        {
            "item_id": item_id,
            "chance_percent": 50,
            "min_quantity": 1,
            "max_quantity": 1,
            "deduct_stock": True,
            "enabled": True,
        }
    )

    item = db.conn.execute("select * from shop_items where id=?", (item_id,)).fetchone()
    assert item["item_category"] == "normal"
    assert item["enabled"] == 1
    assert item["price"] == 10
    assert item["use_enabled"] == 1
    assert item["stock"] == 8
    assert any(row["id"] == item_id for row in db.list_shop_items())

    db.conn.close()
    restarted = Database(tmp_path / "bot.db")
    restarted.init()
    item = restarted.conn.execute(
        "select * from shop_items where id=?", (item_id,)
    ).fetchone()
    assert item["item_category"] == "normal"
    assert item["enabled"] == 1
    assert item["price"] == 10
    assert item["use_enabled"] == 1
    assert item["stock"] == 8


def test_nipple_game_completed_round_counts_toward_its_own_daily_limit(
    tmp_path, monkeypatch
):
    db = make_db(tmp_path)
    user = db.ensure_user(
        {"platform_user_id": "game-user", "user_id": "game-user", "sender": "玩家"}
    )
    db.add_points(user, 200, "测试初始化")
    config = db.get_config()
    config["features"]["game_open_windows"] = ""
    config["features"]["game_daily_nipple_guess_limit"] = "1"
    db.save_config(config)
    router = CommandRouter(db, game_asset_dir=tmp_path)
    monkeypatch.setattr("app.command_router.random.random", lambda: 0.0)

    started = router.handle(message("game-user", "玩家", "/猜乳头"))
    first = router.handle(message("game-user", "玩家", "/1"))
    stopped = router.handle(message("game-user", "玩家", "/1"))
    blocked = router.handle(message("game-user", "玩家", "/猜乳头"))

    assert started.handled and not started.media_first
    assert started.media_paths[0].endswith("开局.webp")
    assert first.handled and "当前可获得" in first.replies[0]
    assert stopped.handled and db.get_user(user)["points"] == 250
    assert db.count_game_plays_today(user, ["猜乳头"]) == 1
    assert blocked.handled and "上限 1 次" in blocked.replies[0]


def test_nipple_game_is_global_exclusive_and_uses_creator_display_name(
    tmp_path, monkeypatch
):
    db = make_db(tmp_path)
    creator = db.ensure_user(
        {"platform_user_id": "creator-id", "user_id": "creator-id", "sender": "原昵称"}
    )
    other = db.ensure_user(
        {"platform_user_id": "other-id", "user_id": "other-id", "sender": "其他玩家"}
    )
    db.set_display_name(creator, "自定义称呼")
    db.add_points(creator, 300, "测试初始化")
    db.add_points(other, 300, "测试初始化")
    config = db.get_config()
    config["features"]["game_open_windows"] = ""
    db.save_config(config)
    router = CommandRouter(db, game_asset_dir=tmp_path)
    monkeypatch.setattr("app.command_router.random.random", lambda: 0.0)

    started = router.handle(message("creator-id", "原昵称", "/猜乳头"))
    other_nipple = router.handle(message("other-id", "其他玩家", "/猜乳头"))
    other_single = router.handle(message("other-id", "其他玩家", "/修女纸牌 10"))
    other_battle = router.handle(
        message("other-id", "其他玩家", "/发起修女纸牌对战 10")
    )
    other_judgement = router.handle(message("other-id", "其他玩家", "/六印圣裁"))

    assert "自定义称呼" in started.replies[0]
    assert "客人" not in started.replies[0]
    for result in (other_nipple, other_single, other_battle, other_judgement):
        assert result.handled
        assert "已有一场游戏" in result.replies[0]
    assert db.get_user(other)["points"] == 300
    assert db.conn.execute(
        """select count(*) from nipple_guess_sessions
           where status in ('awaiting_first_choice','awaiting_risk_choice')"""
    ).fetchone()[0] == 1

    first = router.handle(message("creator-id", "原昵称", "/1"))
    finished = router.handle(message("creator-id", "原昵称", "/1"))
    next_started = router.handle(message("other-id", "其他玩家", "/猜乳头"))

    assert "自定义称呼" in first.replies[0]
    assert "客人" not in first.replies[0]
    assert finished.handled
    assert next_started.handled and "游戏开始" in next_started.replies[0]


def test_card_battle_join_reply_uses_each_current_joiner_name(tmp_path):
    db = make_db(tmp_path)
    config = db.get_config()
    config["features"]["game_open_windows"] = ""
    config["features"]["game_limit_enabled"] = "false"
    db.save_config(config)
    for user_id, nickname in (
        ("card-owner", "发起修女"),
        ("card-join-a", "加入甲"),
        ("card-join-b", "加入乙"),
    ):
        row = db.ensure_user(message(user_id, nickname, "初始化"))
        db.add_points(row, 100, "测试初始化")
    router = CommandRouter(db)

    created = router.handle(message("card-owner", "发起修女", "/发起修女纸牌对战 10"))
    joined_a = router.handle(message("card-join-a", "加入甲", "/加入"))
    joined_b = router.handle(message("card-join-b", "加入乙", "/加入"))

    assert created.handled
    assert "加入甲 抱着牌桌赶到了" in joined_a.replies[0]
    assert "加入乙 抱着牌桌赶到了" in joined_b.replies[0]
    assert "加入甲 抱着牌桌赶到了" not in joined_b.replies[0]
def test_nipple_game_cannot_start_while_another_persistent_game_exists(tmp_path):
    db = make_db(tmp_path)
    first = db.ensure_user(
        {"platform_user_id": "battle-a", "user_id": "battle-a", "sender": "甲"}
    )
    second = db.ensure_user(
        {"platform_user_id": "battle-b", "user_id": "battle-b", "sender": "乙"}
    )
    db.add_points(first, 300, "测试初始化")
    db.add_points(second, 300, "测试初始化")
    config = db.get_config()
    config["features"]["game_open_windows"] = ""
    db.save_config(config)
    assert db.create_game("炸金花", first, 10, max_players=2)["ok"]

    blocked = CommandRouter(db, game_asset_dir=tmp_path).handle(
        message("battle-b", "乙", "/猜乳头")
    )

    assert blocked.handled
    assert "已有一场游戏" in blocked.replies[0]
    assert db.get_active_nipple_guess() is None


def test_old_nipple_guest_word_is_migrated_to_dynamic_user_placeholder(tmp_path):
    db = make_db(tmp_path)
    config = db.get_config()
    config["features"]["nipple_guess_start_reply"] = "客人，开始。"
    config["features"]["nipple_guess_right_reply"] = "客人好会猜。"
    db.save_config(config)
    db.close()

    reopened = Database(tmp_path / "bot.db")
    reopened.init()
    features = reopened.get_config()["features"]

    assert features["nipple_guess_start_reply"] == "{user}，开始。"
    assert features["nipple_guess_right_reply"] == "{user}好会猜。"
