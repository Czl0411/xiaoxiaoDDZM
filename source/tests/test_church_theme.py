from datetime import datetime, timedelta

from app.command_router import CHURCH_THEME_FEATURES, CommandRouter
from app.database import Database


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    return db


def verified(db, number, nickname, points=0):
    platform_id = f"{number:08d}-1111-4111-8111-{number:012d}"
    user = db.ensure_user({
        "platform_user_id": platform_id,
        "user_id": platform_id,
        "avatar_id": f"{number:08d}-2222-4222-8222-{number:012d}",
        "sender": nickname,
        "message_id": f"m-{number}",
    })
    db.conn.execute("update users set points=? where id=?", (points, user["id"]))
    db.conn.commit()
    return db.get_user({"platform_user_id": platform_id})


def test_prayer_streak_bonus_is_capped_at_twenty(tmp_path):
    db = make_db(tmp_path)
    user = db.ensure_user("prayer-user")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    db.conn.execute(
        "update users set streak_days=99,last_checkin_date=? where id=?",
        (yesterday, user["id"]),
    )
    db.conn.commit()

    result = db.checkin_user("prayer-user", 10, 1, 20)

    assert result["reward"] == 30
    assert result["streak"] == 100


def test_prayer_reply_uses_display_name_not_user_dict(tmp_path):
    db = make_db(tmp_path)
    user = verified(db, 9, "prayer-name", 0)
    db.set_display_name(user, "prayer-title")

    reply = CommandRouter(db).handle({
        "platform_user_id": user["platform_user_id"],
        "user_id": user["platform_user_id"],
        "avatar_id": user["avatar_id"],
        "sender": user["nickname"],
        "text": "/祈福",
    }).replies[0]

    assert "⛪ prayer-name 完成今日祈福" in reply
    assert "{'id':" not in reply


def test_removed_games_are_not_built_in_commands(tmp_path):
    router = CommandRouter(make_db(tmp_path))

    assert not router.handle({"sender": "user", "text": "/石头剪刀布 10"}).handled
    assert not router.handle({"sender": "user", "text": "/骰子比大小 10"}).handled
    assert router.handle({"sender": "user", "text": "/修女纸牌 10"}).handled


def test_failed_begging_deducts_points_and_does_not_enable_tips(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    user = db.ensure_user("beg-user")
    db.conn.execute("update users set points=-10 where id=?", (user["id"],))
    db.conn.commit()
    rolls = iter([1, 20])
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: next(rolls))

    result = CommandRouter(db).handle({"sender": "beg-user", "text": "/乞讨"})

    assert "损失 20 功德点" in result.replies[0]
    assert db.get_user("beg-user")["points"] == -30
    assert db.get_active_beggar() is None
    assert db.conn.execute("select attempt_count from beg_attempts").fetchone()[0] == 1


def test_beg_failure_reply_can_be_customized(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    user = db.ensure_user("custom-beg-user")
    db.conn.execute("update users set points=-10 where id=?", (user["id"],))
    db.conn.commit()
    config = db.get_config()
    config["features"].update(CHURCH_THEME_FEATURES)
    config["features"]["beg_failure_reply"] = "失败测试：{user}/{attempt}/{risk}/{loss}/{balance}/{currency}"
    db.save_config(config)
    rolls = iter([1, 7])
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: next(rolls))

    reply = CommandRouter(db).handle({"sender": "custom-beg-user", "text": "/乞讨"}).replies[0]

    assert reply == "失败测试：custom-beg-user/1/10/7/-17/功德点"


def test_begging_at_debt_limit_is_guaranteed_and_cannot_be_robbed(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    user = db.ensure_user("debt-user")
    db.conn.execute("update users set points=-100 where id=?", (user["id"],))
    db.conn.commit()
    monkeypatch.setattr(
        "app.command_router.random.randint",
        lambda *_: (_ for _ in ()).throw(AssertionError("-100 乞讨不应进行失败抽奖")),
    )

    result = CommandRouter(db).handle({"sender": "debt-user", "text": "/乞讨"})

    assert "诈骗风险 0%" in result.replies[0]
    assert db.get_active_beggar()["nickname"] == "debt-user"
    assert db.get_user("debt-user")["points"] == -100
    assert db.conn.execute("select count(*) from beg_attempts").fetchone()[0] == 1


def test_begging_at_minus_fifty_still_has_failure_risk(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    user = db.ensure_user("minus-fifty-user")
    db.conn.execute("update users set points=-50 where id=?", (user["id"],))
    db.conn.commit()
    rolls = iter([1, 8])
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: next(rolls))

    result = CommandRouter(db).handle({"sender": "minus-fifty-user", "text": "/乞讨"})

    assert "损失 8 功德点" in result.replies[0]
    assert db.get_user("minus-fifty-user")["points"] == -58
    assert db.get_active_beggar() is None


def test_merit_ranking_uses_verified_real_user_points(tmp_path):
    db = make_db(tmp_path)
    verified(db, 1, "first-user", 588)
    verified(db, 2, "second-user", 388)
    pending = db.ensure_user("pending-user")
    db.conn.execute("update users set points=9999 where id=?", (pending["id"],))
    db.conn.commit()

    reply = CommandRouter(db).handle({"sender": "viewer", "text": "/功德榜"}).replies[0]

    assert "第一名—first-user—588功德点—功德无量！" in reply
    assert "第二名—second-user—388功德点" in reply
    assert "pending-user" not in reply
