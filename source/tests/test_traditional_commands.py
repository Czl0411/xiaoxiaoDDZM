from app.command_router import CommandRouter
from app.database import Database
from app.rule_engine import RuleEngine


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    return db


def set_points(db, user, points):
    db.conn.execute("update users set points=? where id=?", (points, user["id"]))
    db.conn.commit()


def test_system_command_accepts_traditional_chinese(tmp_path):
    db = make_db(tmp_path)
    result = CommandRouter(db).handle(
        {"sender": "繁體使用者", "text": "/領取工資"}
    )

    assert result.handled


def test_traditional_command_keeps_nickname_argument_unchanged(tmp_path):
    db = make_db(tmp_path)
    lender = db.ensure_user("臺灣主人")
    db.ensure_user("借款人")
    set_points(db, lender, 100)
    router = CommandRouter(db)

    result = router.handle(
        {
            "sender": "借款人",
            "text": "/發起奴隸契約 臺灣主人 50",
        }
    )

    assert result.handled
    pending = db.conn.execute(
        "select * from slave_contracts where status='pending'"
    ).fetchone()
    assert pending is not None
    assert pending["lender_nickname"] == "臺灣主人"


def test_custom_command_matches_simplified_and_traditional_forms(tmp_path):
    db = make_db(tmp_path)
    db.create_rule(
        db.blank_rule()
        | {
            "name": "领取说明",
            "enabled": True,
            "trigger_type": "exact",
            "trigger_value": "/领取工资",
            "reply_content": "可以领取",
        }
    )
    engine = RuleEngine(db)

    hits = engine.match_rules(
        {"sender": "繁體使用者", "text": "/領取工資", "is_self": False},
        "繁體使用者",
    )

    assert len(hits) == 1


def test_traditional_configured_command_also_accepts_simplified_form(tmp_path):
    db = make_db(tmp_path)
    config = db.get_config()
    config["features"]["balance_commands"] = "/餘額"
    db.save_config(config)

    result = CommandRouter(db).handle({"sender": "用户", "text": "/余额"})

    assert result.handled
