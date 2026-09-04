from app.database import Database
from app.command_router import CommandRouter


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db")
    db.init()
    return db


def user(db, uid, name):
    return db.ensure_user({"platform_user_id": uid, "user_id": uid, "sender": name})


def message(uid, name, mid, text="祈福"):
    return {
        "platform_user_id": uid,
        "user_id": uid,
        "sender": name,
        "message_id": mid,
        "text": text,
        "source_group": "main",
        "group_key": "main",
    }


def test_third_distinct_message_rewards_inviter_and_affection_once(tmp_path):
    db = make_db(tmp_path)
    inviter = user(db, "inviter-id", "紫苑")
    db.referral_core.record_join({
        "message_id": "join-1", "group_key": "main", "chatroom_id": "room-1",
        "newcomer_name": "鸿鸿鸿", "inviter_name": "紫苑",
        "sent_at": "2026-09-04T01:19:00Z",
    })

    assert db.referral_core.observe_message(message("new-id", "鸿鸿鸿", "m1")) is None
    assert db.referral_core.observe_message(message("new-id", "鸿鸿鸿", "m2")) is None
    result = db.referral_core.observe_message(message("new-id", "鸿鸿鸿", "m3"))
    duplicate = db.referral_core.observe_message(message("new-id", "鸿鸿鸿", "m3"))

    updated = db.get_user(inviter)
    assert result.reward_amount == 40
    assert duplicate is None
    assert updated["points"] == 40
    assert updated["total_merit"] == 40
    assert updated["saintess_affection"] == 1
    assert "迷途的羔羊 鸿鸿鸿 顺着 紫苑 的传送门" in result.announcement
    assert "发放了 40 功德奖励" in result.announcement
    assert db.conn.execute("select count(*) from transactions where reason='传送门拉新奖励'").fetchone()[0] == 1


def test_reward_zero_still_adds_one_affection(tmp_path):
    db = make_db(tmp_path)
    inviter = user(db, "inviter-id", "紫苑")
    config = db.get_config()
    config["features"]["referral_reward_amount"] = 0
    db.save_config(config)
    db.referral_core.record_join({"message_id": "join-1", "group_key": "main", "newcomer_name": "新人", "inviter_name": "紫苑"})
    for index in range(1, 4):
        outcome = db.referral_core.observe_message(message("new-id", "新人", f"m{index}"))
    updated = db.get_user(inviter)
    assert outcome.reward_amount == 0
    assert updated["points"] == 0
    assert updated["saintess_affection"] == 1


def test_ambiguous_inviter_nickname_is_not_guessed(tmp_path):
    db = make_db(tmp_path)
    user(db, "inviter-a", "同名")
    user(db, "inviter-b", "同名")
    db.referral_core.record_join({"message_id": "join-1", "group_key": "main", "newcomer_name": "新人", "inviter_name": "同名"})
    for index in range(1, 4):
        assert db.referral_core.observe_message(message("new-id", "新人", f"m{index}")) is None
    row = db.conn.execute("select status,failure_reason from referral_invites").fetchone()
    assert row["status"] == "needs_review"
    assert row["failure_reason"] == "邀请人昵称不唯一"


def test_admin_can_set_reward_and_profile_shows_affection(tmp_path):
    db = make_db(tmp_path)
    admin = user(db, "admin-id", "管理员")
    db.update_user("admin-id", {**admin, "is_admin": True})
    router = CommandRouter(db)

    changed = router.handle(message("admin-id", "管理员", "set-1", "/设置拉新奖励 88"))
    profile = router.handle(message("admin-id", "管理员", "profile-1", "/我"))

    assert changed.handled and "88" in changed.replies[0]
    assert db.get_config()["features"]["referral_reward_amount"] == 88
    assert "圣女好感度：0" in profile.replies[0]


def test_non_admin_cannot_set_referral_reward(tmp_path):
    db = make_db(tmp_path)
    user(db, "user-id", "普通人")
    result = CommandRouter(db).handle(message("user-id", "普通人", "set-1", "/设置拉新奖励 88"))
    assert result.handled and "仅限管理员" in result.replies[0]
    assert db.get_config()["features"].get("referral_reward_amount", 40) == 40
