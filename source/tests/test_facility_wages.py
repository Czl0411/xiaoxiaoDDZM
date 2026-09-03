from datetime import datetime, timedelta

from app.command_router import CommandRouter
from app.database import Database


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    config = db.get_config()
    config["features"]["newcomer_benefit_enabled"] = False
    db.save_config(config)
    return db


def save_activity(db, message_id, platform_user_id, nickname):
    db.save_message(
        {
            "message_id": message_id,
            "platform_user_id": platform_user_id,
            "user_id": platform_user_id,
            "avatar_id": f"avatar-{platform_user_id}",
            "sender": nickname,
            "text": "今天的活跃消息",
            "time": "11:00",
            "is_self": False,
            "raw_html": "",
        }
    )
    db.conn.execute(
        "update messages set created_at=? where message_id=?",
        (noon_today().replace(hour=11).strftime("%Y-%m-%d %H:%M:%S"), message_id),
    )
    db.conn.commit()


def save_yesterday_activity(db, message_id, platform_user_id, nickname, hour=11):
    save_activity(db, message_id, platform_user_id, nickname)
    yesterday = noon_today().replace(hour=hour) - timedelta(days=1)
    db.conn.execute(
        "update messages set created_at=? where message_id=?",
        (yesterday.strftime("%Y-%m-%d %H:%M:%S"), message_id),
    )
    db.conn.commit()


def noon_today():
    now = datetime.now()
    return now.replace(hour=12, minute=0, second=0, microsecond=0)


def test_wage_only_goes_to_today_active_user_with_current_matching_nickname(tmp_path):
    db = make_db(tmp_path)
    save_activity(db, "m1", "user-1", "小旋风大王（公共设施）")
    active_plain = db.ensure_user(
        {"platform_user_id": "user-2", "sender": "普通活跃用户", "avatar_id": "avatar-user-2"}
    )
    save_activity(db, "m2", "user-2", "普通活跃用户")
    inactive = db.ensure_user(
        {"platform_user_id": "user-3", "sender": "没发言的公共设施", "avatar_id": "avatar-user-3"}
    )

    result = db.run_due_facility_wages(noon_today())

    assert result["processed"]
    assert result["active_count"] == 2
    assert result["recipient_count"] == 1
    assert result["payouts"][0]["nickname"] == "小旋风大王（公共设施）"
    assert db.get_user({"platform_user_id": "user-1"})["points"] == 10
    assert db.get_user(active_plain)["points"] == 0
    assert db.get_user(inactive)["points"] == 0


def test_any_observed_job_nickname_is_enough_for_wage_eligibility(tmp_path):
    db = make_db(tmp_path)
    save_activity(db, "m1", "user-left", "小旋风大王（公共设施）")
    save_activity(db, "m1b", "user-left", "小旋风大王")
    save_activity(db, "m2", "user-kept", "小旋风大王（公共设施）")
    save_activity(db, "m2b", "user-kept", "大旋风大王（公共设施1号）")

    result = db.run_due_facility_wages(noon_today())

    assert result["recipient_count"] == 2
    assert db.get_user({"platform_user_id": "user-left"})["points"] == 10
    assert db.get_user({"platform_user_id": "user-kept"})["points"] == 10


def test_claim_yesterday_wage_allows_temporary_nickname_change(tmp_path):
    db = make_db(tmp_path)
    save_yesterday_activity(db, "good-1", "user-good", "早班（公共设施）", 8)
    save_yesterday_activity(db, "good-2", "user-good", "晚班（公共设施1号）", 20)
    save_yesterday_activity(db, "bad-1", "user-bad", "早班（公共设施）", 8)
    save_yesterday_activity(db, "bad-2", "user-bad", "晚上摘掉后缀", 20)
    router = CommandRouter(db)

    good = router.handle({"platform_user_id": "user-good", "sender": "晚班（公共设施1号）", "text": "/领取工资"})
    bad = router.handle({"platform_user_id": "user-bad", "sender": "晚上摘掉后缀", "text": "/领取工资"})

    assert good.handled
    assert "已领取" in good.replies[0]
    assert db.get_user({"platform_user_id": "user-good"})["points"] == 10
    assert "已领取" in bad.replies[0]
    assert db.get_user({"platform_user_id": "user-bad"})["points"] == 10


def test_claim_yesterday_wage_cannot_repeat(tmp_path):
    db = make_db(tmp_path)
    save_yesterday_activity(db, "m1", "user-repeat", "值班（公共设施）")
    router = CommandRouter(db)
    message = {"platform_user_id": "user-repeat", "sender": "值班（公共设施）", "text": "/领取工资"}

    first = router.handle(message)
    second = router.handle(message)

    assert "已领取" in first.replies[0]
    assert "不能重复领取" in second.replies[0]
    assert db.get_user({"platform_user_id": "user-repeat"})["points"] == 10


def test_wage_runs_once_per_day_and_stacks_all_matching_rules(tmp_path):
    db = make_db(tmp_path)
    default_rule = db.list_facility_wage_rules()[0]
    db.save_facility_wage_rule(
        {"keyword": "公共设施1号", "amount": 30, "enabled": True, "sort_order": -10},
        default_rule["id"],
    )
    db.save_facility_wage_rule(
        {"keyword": "公共设施", "amount": 10, "enabled": True, "sort_order": 0}
    )
    save_activity(db, "m1", "user-both", "大旋风（公共设施1号）")

    first = db.run_due_facility_wages(noon_today())
    second = db.run_due_facility_wages(noon_today().replace(hour=15))

    assert first["recipient_count"] == 1
    assert first["total_amount"] == 40
    assert second["duplicate"]
    assert db.get_user({"platform_user_id": "user-both"})["points"] == 40
    assert db.conn.execute("select count(*) from facility_wage_payouts").fetchone()[0] == 1


def test_claim_yesterday_wage_stacks_matches_and_explains_breakdown(tmp_path):
    db = make_db(tmp_path)
    default_rule = db.list_facility_wage_rules()[0]
    db.save_facility_wage_rule(
        {"keyword": "公共设施", "amount": 10, "enabled": True, "sort_order": 0},
        default_rule["id"],
    )
    db.save_facility_wage_rule(
        {"keyword": "修女", "amount": 20, "enabled": True, "sort_order": 0}
    )
    save_yesterday_activity(
        db,
        "both-1",
        "user-both-claim",
        "值班修女（公共设施）",
        8,
    )
    save_yesterday_activity(
        db,
        "both-2",
        "user-both-claim",
        "夜班修女（公共设施1号）",
        20,
    )
    router = CommandRouter(db)

    result = router.handle(
        {
            "platform_user_id": "user-both-claim",
            "sender": "夜班修女（公共设施1号）",
            "text": "/领取工资",
        }
    )

    assert result.handled
    assert "公共设施 10" in result.replies[0]
    assert "修女 20" in result.replies[0]
    assert "合计 30" in result.replies[0]
    assert db.get_user({"platform_user_id": "user-both-claim"})["points"] == 30


def test_wage_does_not_run_before_noon(tmp_path):
    db = make_db(tmp_path)
    save_activity(db, "m1", "user-early", "早班公共设施")

    result = db.run_due_facility_wages(noon_today().replace(hour=11))

    assert not result["processed"]
    assert result["reason"] == "before_noon"
    assert db.get_user({"platform_user_id": "user-early"})["points"] == 0
