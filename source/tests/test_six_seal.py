from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

from app.command_router import CommandRouter, SIX_SEAL_FEATURES
from app.database import Database
from app.scheduler import BotScheduler


def message(name: str, user_id: str, text: str) -> dict:
    return {
        "sender": name,
        "text": text,
        "platform_user_id": user_id,
        "user_id": user_id,
        "avatar_id": f"avatar-{user_id}",
    }


def setup_game(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    config = db.get_config()
    config["features"] = {
        **config.get("features", {}),
        **SIX_SEAL_FEATURES,
        "currency_name": "功德点",
        "game_limit_enabled": "false",
    }
    db.save_config(config)
    router = CommandRouter(db)
    first = message("甲", "user-a", "")
    second = message("乙", "user-b", "")
    outsider = message("丙", "user-c", "")
    for item in (first, second, outsider):
        user = db.ensure_user(item)
        db.add_points(user, 500, "测试准备")
    db.conn.execute(
        "update users set gender='male' where platform_user_id=?",
        (outsider["platform_user_id"],),
    )
    db.conn.commit()
    return db, router, first, second, outsider


def run_command(router: CommandRouter, source: dict, text: str):
    return router.handle({**source, "text": text})


def force_active_state(db: Database, order: list[str], turn_user_id: str) -> None:
    game = db.get_active_six_seal_game()
    assert game and game["status"] == "active"
    db.conn.execute(
        """update six_seal_games
           set seal_order=?, next_index=0, current_turn_user_id=?, current_wager=base_wager
           where id=?""",
        (json.dumps(order, ensure_ascii=False), turn_user_id, int(game["id"])),
    )
    db.conn.commit()


def test_voluntary_lobby_freezes_maximum_and_starts_with_join(tmp_path):
    db, router, first, second, _ = setup_game(tmp_path)

    created = run_command(router, first, "/六印圣裁")
    assert created.handled
    assert "/加入" in created.replies[0]
    assert db.get_user(first)["points"] == 300
    waiting = db.get_active_six_seal_game()
    assert waiting and waiting["status"] == "waiting"
    assert waiting["base_wager"] == 50
    assert waiting["max_wager"] == 200

    self_join = run_command(router, first, "/加入")
    assert "不能占据第二个席位" in self_join.replies[0]
    assert db.get_user(first)["points"] == 300

    joined = run_command(router, second, "/加入")
    assert "欲望圣裁开始" in joined.replies[0]
    assert "丙" in joined.replies[0]
    assert "请选择连续按压次数 1～5" in joined.replies[0]
    assert "当前还剩 6 次" in joined.replies[0]
    assert db.get_user(second)["points"] == 300
    active = db.get_active_six_seal_game()
    assert active and active["status"] == "active"
    assert active["subject_user_id"] == "user-c"
    assert active["subject_nickname"] == "丙"
    assert active["subject_user_id"] not in {
        active["initiator_user_id"],
        active["opponent_user_id"],
    }
    seals = json.loads(active["seal_order"])
    assert len(seals) == 6
    assert seals.count("圣辉") == 5
    assert seals.count("深渊") == 1


def test_each_user_can_only_create_two_six_seal_games_per_day(tmp_path):
    db, router, first, _, _ = setup_game(tmp_path)
    config = db.get_config()
    config["features"]["game_limit_enabled"] = "true"
    config["features"]["game_open_windows"] = ""
    config["features"]["game_daily_six_seal_limit"] = "2"
    db.save_config(config)

    for _ in range(2):
        created = run_command(router, first, "/六印圣裁")
        assert "欲望圣裁招募" in created.replies[0]
        run_command(router, first, "/取消圣裁")

    blocked = run_command(router, first, "/六印圣裁")
    assert "上限 2 次" in blocked.replies[0]


def test_each_successful_turn_replaces_risk_for_the_next_player(tmp_path):
    db, router, first, second, _ = setup_game(tmp_path)
    run_command(router, first, "/六印圣裁")
    run_command(router, second, "/加入")
    force_active_state(
        db,
        ["圣辉", "圣辉", "圣辉", "圣辉", "深渊", "圣辉"],
        "user-a",
    )

    first_safe = run_command(router, first, "/3")
    assert "50 → 130" in first_safe.replies[0]
    assert db.get_active_six_seal_game()["current_wager"] == 130

    second_safe = run_command(router, second, "/1")
    assert "130 → 50" in second_safe.replies[0]
    assert db.get_active_six_seal_game()["current_wager"] == 50

    failed = run_command(router, first, "/1")
    assert "支付 50 功德点" in failed.replies[0]
    assert db.get_user(first)["points"] == 450
    assert db.get_user(second)["points"] == 550
    assert db.get_active_six_seal_game() is None


def test_five_seal_success_makes_next_players_risk_200(tmp_path):
    db, router, first, second, _ = setup_game(tmp_path)
    run_command(router, first, "/六印圣裁")
    run_command(router, second, "/加入")
    force_active_state(
        db,
        ["圣辉", "圣辉", "圣辉", "圣辉", "圣辉", "深渊"],
        "user-a",
    )

    final = run_command(router, first, "/5")
    assert "直接作出最终裁决" in final.replies[0]
    assert "支付 200 功德点" in final.replies[0]
    assert db.get_active_six_seal_game() is None
    assert db.get_user(first)["points"] == 700
    assert db.get_user(second)["points"] == 300


def test_last_certain_curse_auto_settles_from_the_latest_players_chain(tmp_path):
    db, router, first, second, _ = setup_game(tmp_path)
    run_command(router, first, "/六印圣裁")
    run_command(router, second, "/加入")
    force_active_state(
        db,
        ["圣辉", "圣辉", "圣辉", "圣辉", "圣辉", "深渊"],
        "user-a",
    )

    run_command(router, first, "/3")
    final = run_command(router, second, "/2")

    assert "直接作出最终裁决" in final.replies[0]
    assert "支付 90 功德点" in final.replies[0]
    assert db.get_user(first)["points"] == 410
    assert db.get_user(second)["points"] == 590


def test_invalid_or_outsider_turn_does_not_change_state(tmp_path):
    db, router, first, second, outsider = setup_game(tmp_path)
    run_command(router, first, "/六印圣裁")
    run_command(router, second, "/加入")
    force_active_state(db, ["圣辉"] * 5 + ["深渊"], "user-a")

    outsider_reply = run_command(router, outsider, "/1")
    assert "不是当前欲望圣裁的参与者" in outsider_reply.replies[0]
    wrong_turn = run_command(router, second, "/1")
    assert "还没有轮到你" in wrong_turn.replies[0]
    old_command = run_command(router, first, "/揭印 1")
    assert not old_command.handled
    assert db.get_active_six_seal_game()["next_index"] == 0


def test_only_one_group_game_can_exist_in_either_direction(tmp_path):
    db, router, first, second, _ = setup_game(tmp_path)
    run_command(router, first, "/六印圣裁")
    blocked_cards = db.create_game("炸金花", second, 20, max_players=2)
    assert blocked_cards == {"ok": False, "reason": "exists"}
    assert db.get_user(second)["points"] == 500

    run_command(router, first, "/取消圣裁")
    cards = db.create_game("炸金花", second, 20, max_players=2)
    assert cards["ok"]
    blocked_seals = db.create_six_seal_game(
        first,
        base_wager=50,
        max_wager=200,
        wager_step=40,
    )
    assert blocked_seals == {"ok": False, "reason": "other_game"}
    assert db.get_user(first)["points"] == 500


class Adapter:
    def __init__(self):
        self.sent = []

    async def send_message(self, text):
        self.sent.append(text)
        return True


class Logger:
    def info(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


def test_waiting_game_expires_refunds_and_sends_notice(tmp_path):
    db, router, first, _, _ = setup_game(tmp_path)
    run_command(router, first, "/六印圣裁")
    expired = (datetime.now() - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    db.conn.execute(
        "update six_seal_games set expires_at=? where status='waiting'",
        (expired,),
    )
    db.conn.commit()
    adapter = Adapter()
    scheduler = BotScheduler(db, adapter, engine=None, logger=Logger(), command_router=router)
    config = db.get_config()

    asyncio.run(scheduler._process_expired_six_seal_games(config))

    assert db.get_user(first)["points"] == 500
    assert db.get_active_six_seal_game() is None
    assert len(adapter.sent) == 1
    assert "无人加入" in adapter.sent[0]
    assert "自动取消" in adapter.sent[0]


def test_active_game_timeout_makes_current_player_forfeit(tmp_path):
    db, router, first, second, _ = setup_game(tmp_path)
    run_command(router, first, "/六印圣裁")
    run_command(router, second, "/加入")
    expired = (datetime.now() - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    db.conn.execute(
        "update six_seal_games set current_turn_user_id=?, expires_at=? where status='active'",
        (second["user_id"], expired),
    )
    db.conn.commit()
    adapter = Adapter()
    scheduler = BotScheduler(db, adapter, engine=None, logger=Logger(), command_router=router)

    asyncio.run(scheduler._process_expired_six_seal_games(db.get_config()))

    assert db.get_active_six_seal_game() is None
    assert db.get_user(second)["points"] == 450
    assert db.get_user(first)["points"] == 550
    assert len(adapter.sent) == 1
    assert "逃战" in adapter.sent[0]
    assert "乙" in adapter.sent[0]
    assert "甲" in adapter.sent[0]


def test_successful_turn_resets_active_game_timeout(tmp_path):
    db, router, first, second, _ = setup_game(tmp_path)
    config = db.get_config()
    config["features"]["six_seal_turn_timeout_seconds"] = 120
    db.save_config(config)
    run_command(router, first, "/六印圣裁")
    run_command(router, second, "/加入")
    force_active_state(db, ["圣辉"] * 5 + ["深渊"], first["user_id"])
    old_expiry = (datetime.now() + timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
    db.conn.execute(
        "update six_seal_games set expires_at=? where status='active'",
        (old_expiry,),
    )
    db.conn.commit()

    result = run_command(router, first, "/1")

    assert result.handled
    active = db.get_active_six_seal_game()
    assert active and active["status"] == "active"
    assert datetime.strptime(active["expires_at"], "%Y-%m-%d %H:%M:%S") >= datetime.now() + timedelta(seconds=115)


def test_join_is_rejected_without_an_eligible_third_male(tmp_path):
    db, router, first, second, outsider = setup_game(tmp_path)
    db.conn.execute(
        "update users set gender='female' where platform_user_id=?",
        (outsider["platform_user_id"],),
    )
    db.conn.commit()

    run_command(router, first, "/六印圣裁")
    joined = run_command(router, second, "/加入")

    assert "没有可供本场随机抽取的第三位真实男性用户" in joined.replies[0]
    assert db.get_user(second)["points"] == 500
    game = db.get_active_six_seal_game()
    assert game and game["status"] == "waiting"
    assert not game["subject_user_id"]


def test_selected_male_subject_survives_database_reopen(tmp_path):
    path = tmp_path / "bot.db"
    db, router, first, second, _ = setup_game(tmp_path)
    run_command(router, first, "/六印圣裁")
    run_command(router, second, "/加入")
    selected = db.get_active_six_seal_game()
    assert selected and selected["subject_user_id"] == "user-c"
    db.conn.close()

    reopened = Database(path, allow_legacy_user_creation=True)
    reopened.init()
    restored = reopened.get_active_six_seal_game()

    assert restored and restored["subject_user_id"] == "user-c"
    assert restored["subject_nickname"] == "丙"
    assert restored["variant"] == "normal"


def enable_high_priest_variant(db: Database) -> None:
    config = db.get_config()
    config["features"]["six_seal_high_priest_user_id"] = "user-c"
    db.save_config(config)


def add_second_male_candidate(db: Database) -> dict:
    candidate = message("丁", "user-d", "")
    user = db.ensure_user(candidate)
    db.add_points(user, 500, "测试准备")
    db.conn.execute(
        "update users set gender='male' where platform_user_id=?",
        (candidate["platform_user_id"],),
    )
    db.conn.commit()
    return candidate


def test_high_priest_has_independent_twenty_two_percent_hit_chance(
    tmp_path, monkeypatch
):
    db, router, first, second, _ = setup_game(tmp_path)
    enable_high_priest_variant(db)
    add_second_male_candidate(db)
    monkeypatch.setattr("app.database.random.random", lambda: 0.219)

    run_command(router, first, "/六印圣裁")
    run_command(router, second, "/加入")

    game = db.get_active_six_seal_game()
    assert game and game["variant"] == "high_priest"
    assert game["subject_user_id"] == "user-c"


def test_high_priest_probability_miss_selects_an_ordinary_male(
    tmp_path, monkeypatch
):
    db, router, first, second, _ = setup_game(tmp_path)
    enable_high_priest_variant(db)
    add_second_male_candidate(db)
    monkeypatch.setattr("app.database.random.random", lambda: 0.22)

    run_command(router, first, "/六印圣裁")
    run_command(router, second, "/加入")

    game = db.get_active_six_seal_game()
    assert game and game["variant"] == "normal"
    assert game["subject_user_id"] == "user-d"


def test_high_priest_subject_opens_twelve_slot_hidden_game(tmp_path):
    db, router, first, second, _ = setup_game(tmp_path)
    enable_high_priest_variant(db)

    run_command(router, first, "/六印圣裁")
    joined = run_command(router, second, "/加入")

    assert "隐藏圣谕·大祭司十二重欲望圣裁" in joined.replies[0]
    assert "基础圣契额提升至 300 功德点" in joined.replies[0]
    assert "圣契上限提升至 500 功德点" in joined.replies[0]
    assert "最低可降至 -100" in joined.replies[0]
    assert "当前还剩 12 次" in joined.replies[0]
    game = db.get_active_six_seal_game()
    assert game and game["variant"] == "high_priest"
    assert game["base_wager"] == 300
    assert game["max_wager"] == 500
    assert game["wager_step"] == 75
    assert game["reserve_amount"] == 500
    seals = json.loads(game["seal_order"])
    assert len(seals) == 12
    assert seals.count("圣辉") == 11
    assert seals.count("深渊") == 1
    assert db.get_user(first)["points"] == 0
    assert db.get_user(second)["points"] == 0


def test_high_priest_game_allows_reserve_to_negative_one_hundred(tmp_path):
    db, router, first, second, _ = setup_game(tmp_path)
    enable_high_priest_variant(db)
    db.add_points(db.get_user(first), -100, "准备负余额边界")
    db.add_points(db.get_user(second), -100, "准备负余额边界")

    run_command(router, first, "/六印圣裁")
    joined = run_command(router, second, "/加入")

    assert "隐藏圣谕" in joined.replies[0]
    assert db.get_user(first)["points"] == -100
    assert db.get_user(second)["points"] == -100


def test_high_priest_game_never_reserves_below_negative_one_hundred(tmp_path):
    db, router, first, second, _ = setup_game(tmp_path)
    enable_high_priest_variant(db)
    db.add_points(db.get_user(first), -250, "准备越界测试")
    db.add_points(db.get_user(second), -200, "准备越界测试")

    run_command(router, first, "/六印圣裁")
    joined = run_command(router, second, "/加入")

    assert "大祭司的隐藏圣谕已经降临" in joined.replies[0]
    assert "最低降至 -100" in joined.replies[0]
    assert db.get_user(first)["points"] == 50
    assert db.get_user(second)["points"] == 300
    game = db.get_active_six_seal_game()
    assert game and game["status"] == "waiting"


def test_high_priest_remaining_choices_and_twelfth_final_are_dynamic(tmp_path):
    db, router, first, second, _ = setup_game(tmp_path)
    enable_high_priest_variant(db)
    run_command(router, first, "/六印圣裁")
    run_command(router, second, "/加入")
    game = db.get_active_six_seal_game()
    assert game
    order = ["圣辉"] * 11 + ["深渊"]
    db.conn.execute(
        """update six_seal_games
           set seal_order=?, next_index=9, current_turn_user_id=?,
               current_wager=base_wager
           where id=?""",
        (json.dumps(order, ensure_ascii=False), "user-a", int(game["id"])),
    )
    db.conn.commit()

    invalid = run_command(router, first, "/5")
    assert "当前还剩 3 次" in invalid.replies[0]
    assert "/1、/2、/3" in invalid.replies[0]
    assert "/4" not in invalid.replies[0]
    final = run_command(router, first, "/2")

    assert "大祭司作出终极裁决" in final.replies[0]
    assert "支付 375 功德点" in final.replies[0]
    assert "正常损耗" not in final.replies[0]
    assert "获得全部 375" in final.replies[0]
    assert db.get_user(first)["points"] == 875
    assert db.get_user(second)["points"] == 125
    assert db.get_active_six_seal_game() is None


def test_high_priest_shared_wager_only_rises_cumulatively(tmp_path):
    db, router, first, second, _ = setup_game(tmp_path)
    enable_high_priest_variant(db)
    run_command(router, first, "/六印圣裁")
    run_command(router, second, "/加入")
    game = db.get_active_six_seal_game()
    assert game
    db.conn.execute(
        """update six_seal_games set seal_order=?,current_turn_user_id=? where id=?""",
        (json.dumps(["圣辉"] * 11 + ["深渊"], ensure_ascii=False), "user-a", int(game["id"])),
    )
    db.conn.commit()

    run_command(router, first, "/2")
    assert db.get_active_six_seal_game()["current_wager"] == 375
    run_command(router, second, "/2")
    assert db.get_active_six_seal_game()["current_wager"] == 450
    run_command(router, first, "/1")
    assert db.get_active_six_seal_game()["current_wager"] == 450


def test_user_facing_templates_avoid_modern_weapon_and_fatality_words():
    forbidden = ("枪", "子弹", "死亡", "赌")
    replies = [
        value
        for key, value in SIX_SEAL_FEATURES.items()
        if key.endswith("_reply")
    ]
    assert replies
    for reply in replies:
        assert not any(word in reply for word in forbidden)
