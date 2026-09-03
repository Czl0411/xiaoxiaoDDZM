from datetime import datetime, timedelta

from app.bounty_core import BEIJING_TZ
from app.database import Database


def ref(uid: str, name: str) -> dict:
    return {
        "platform_user_id": uid,
        "user_id": uid,
        "sender": name,
        "avatar_id": f"avatar-{uid}",
    }


def funded(db: Database, uid: str, name: str, amount: int = 500) -> dict:
    user = db.ensure_user(ref(uid, name))
    db.add_points(user, amount, "测试准备")
    return db.get_user(user)


def test_old_site_origin_is_migrated_without_changing_room_ids(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    config = db.get_config()
    config["dzmm"].update(
        {
            "home_url": "https://www.ainvmei.com",
            "group_url": "https://www.ainvmei.com/chat?c=11111111-1111-1111-1111-111111111111",
            "bounty_group_url": "https://www.ainvmei.com/chat?c=22222222-2222-2222-2222-222222222222",
        }
    )
    db.save_config(config)

    migrated = db.get_config()["dzmm"]

    assert migrated["home_url"] == "https://www.aikda.com"
    assert migrated["group_url"] == "https://www.aikda.com/chat?c=11111111-1111-1111-1111-111111111111"
    assert migrated["bounty_group_url"] == "https://www.aikda.com/chat?c=22222222-2222-2222-2222-222222222222"


def test_wage_uses_verified_stored_name_when_socket_sender_is_unresolved(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    config = db.get_config()
    config["features"]["newcomer_benefit_enabled"] = False
    db.save_config(config)
    db.save_facility_wage_rule(
        {"keyword": "见习修女", "amount": 10, "enabled": True, "sort_order": 0}
    )
    user = funded(db, "user-wage", "小紫（见习修女）", 0)
    db.save_message(
        {
            **ref("user-wage", "未知用户"),
            "message_id": "unresolved-yesterday",
            "text": "昨天发言",
            "is_self": False,
        }
    )
    yesterday = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=1)
    db.conn.execute(
        "update messages set created_at=? where message_id='unresolved-yesterday'",
        (yesterday.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    db.conn.commit()

    result = db.claim_previous_day_facility_wage(ref("user-wage", "小紫（见习修女）"))

    assert result["ok"]
    assert result["amount"] == 10


def test_waiting_card_battle_timeout_refunds_every_player_once(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    first = funded(db, "card-a", "甲")
    second = funded(db, "card-b", "乙")
    game = db.create_game("炸金花", first, 50, max_players=3)
    db.join_game(second)
    old = (datetime.now() - timedelta(seconds=121)).strftime("%Y-%m-%d %H:%M:%S")
    db.conn.execute("update games set created_at=? where id=?", (old, game["game_id"]))
    db.conn.commit()

    expired = db.claim_expired_waiting_games(120)
    repeated = db.claim_expired_waiting_games(120)

    assert len(expired) == 1
    assert expired[0]["refund_count"] == 2
    assert repeated == []
    assert db.get_user(first)["points"] == 500
    assert db.get_user(second)["points"] == 500
    assert db.get_active_game() is None


def test_closing_migrated_demand_prevents_weekly_second_refund(tmp_path):
    path = tmp_path / "bot.db"
    owner_id = "aaaaaaaa-1111-4111-8111-111111111111"
    first = Database(path, allow_legacy_user_creation=True)
    first.init()
    publisher = funded(first, owner_id, "豪龙", 2000)
    bounty = first.create_bounty(
        ref(owner_id, "豪龙"), duration_type="single", duration_days=0,
        reward=1500, reward_per_person=1500, required_count=1,
        content="旧需求", source_group="main",
    )
    after_publish = first.get_user(publisher)["points"]
    first.conn.execute("delete from settings where key='commission_house_v2_migrated'")
    first.conn.commit()
    first.close()

    reopened = Database(path, allow_legacy_user_creation=True)
    reopened.init()
    demand = reopened.commission_house.resolve(f"D{bounty['id']:04d}", "demand")
    assert demand is not None
    reopened.commission_house.close_demand(demand["id"], ref(owner_id, "豪龙"))
    after_close = reopened.get_user(publisher)["points"]
    cleanup = reopened.run_weekly_bounty_cleanup(datetime(2026, 9, 7, 0, 0, tzinfo=BEIJING_TZ))

    assert after_close - after_publish == 1650
    assert cleanup["refunded_amount"] == 0
    assert reopened.get_user(publisher)["points"] == after_close
