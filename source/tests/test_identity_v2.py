import json

import pytest

from app.database import Database
from app.dzmm_adapter import DzmmAdapter


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    config = db.get_config()
    config["features"]["newcomer_benefit_enabled"] = False
    db.save_config(config)
    return db


def identity(platform_user_id, nickname, avatar_id, message_id="m1"):
    return {
        "platform_user_id": platform_user_id,
        "user_id": platform_user_id,
        "sender": nickname,
        "avatar_id": avatar_id,
        "message_id": message_id,
    }


def test_production_database_rejects_new_nickname_only_user(tmp_path):
    db = Database(tmp_path / "strict.db")
    db.init()

    with pytest.raises(ValueError, match="缺少主页唯一ID"):
        db.ensure_user("nickname-without-platform-id")

    assert db.conn.execute("select count(*) from users").fetchone()[0] == 0


def test_new_verified_user_uses_platform_id(tmp_path):
    db = make_db(tmp_path)
    user = db.ensure_user(identity("11111111-1111-1111-1111-111111111111", "同名", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))

    assert user["identity_status"] == "normal"
    assert user["platform_user_id"] == "11111111-1111-1111-1111-111111111111"
    assert user["avatar_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_platform_id_does_not_adopt_legacy_user_by_nickname_or_avatar(tmp_path):
    db = make_db(tmp_path)
    legacy = db.ensure_user("旧用户")
    avatar_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    platform_id = "11111111-1111-1111-1111-111111111111"
    db.conn.execute("update users set avatar_id=? where id=?", (avatar_id, legacy["id"]))
    db.conn.commit()

    verified = db.ensure_user(identity(platform_id, "旧用户", avatar_id))

    assert verified["id"] != legacy["id"]
    assert verified["identity_status"] == "normal"
    assert verified["platform_user_id"] == platform_id
    assert db.get_user({"id": legacy["id"]})["platform_user_id"] == ""


def test_legacy_partial_match_does_not_create_identity_conflict(tmp_path):
    db = make_db(tmp_path)
    legacy = db.ensure_user("同名")
    db.conn.execute(
        "update users set avatar_id=? where id=?",
        ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", legacy["id"]),
    )
    db.conn.commit()

    verified = db.ensure_user(
        identity(
            "22222222-2222-2222-2222-222222222222",
            "同名",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        )
    )
    allowed, reason, _ = db.identity_decision(
        identity(
            "22222222-2222-2222-2222-222222222222",
            "同名",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        )
    )

    assert verified["identity_status"] == "normal"
    assert allowed
    assert reason == "身份已确认"
    assert len(db.list_identity_conflicts()) == 0


def test_same_nickname_with_distinct_platform_ids_is_allowed_for_business(tmp_path):
    db = make_db(tmp_path)
    first = identity(
        "11111111-1111-1111-1111-111111111111",
        "同名用户",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "same-name-first",
    )
    second = identity(
        "22222222-2222-2222-2222-222222222222",
        "同 名 用 户",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "same-name-second",
    )
    first_user = db.ensure_user(first)
    second_user = db.ensure_user(second)

    first_allowed, first_reason, resolved_first = db.identity_decision(first)
    second_allowed, second_reason, resolved_second = db.identity_decision(second)

    assert db.has_duplicate_nickname(first_user)
    assert db.has_duplicate_nickname(second_user)
    assert first_allowed and second_allowed
    assert first_reason == second_reason == "身份已确认"
    assert resolved_first["platform_user_id"] == first["platform_user_id"]
    assert resolved_second["platform_user_id"] == second["platform_user_id"]


def test_missing_platform_id_never_passes_business_gate(tmp_path):
    db = make_db(tmp_path)
    allowed, reason, user = db.identity_decision(
        {"sender": "未确认", "avatar_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}
    )

    assert not allowed
    assert user["identity_status"] == "pending"
    assert "尚未取得主页唯一ID" in reason
    assert db.get_user("未确认") is None


def test_existing_conflict_status_recovers_from_same_platform_id(tmp_path):
    db = make_db(tmp_path)
    platform_id = "33333333-3333-3333-3333-333333333333"
    user = db.ensure_user(
        identity(platform_id, "旧昵称", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    )
    db.conn.execute(
        """update users set identity_status='conflict',
               identity_conflict_reason='旧版冲突', points=25 where id=?""",
        (user["id"],),
    )
    db.conn.commit()
    recovered = db.ensure_user(
        identity(platform_id, "新昵称", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    )

    assert recovered["id"] == user["id"]
    assert recovered["points"] == 25
    assert recovered["nickname"] == "新昵称"
    assert recovered["identity_status"] == "normal"
    assert recovered["identity_conflict_reason"] == ""


def test_trpc_message_extraction_and_order_alignment():
    payload = {
        "result": {
            "data": {
                "json": {
                    "items": [
                        {"message_id": "m1", "sent_by": "u1", "content": "重复", "sent_at": "2026-01-01T00:00:01Z"},
                        {"message_id": "m2", "sent_by": "u2", "content": "重复", "sent_at": "2026-01-01T00:00:02Z"},
                    ]
                }
            }
        }
    }
    api_messages = DzmmAdapter._extract_trpc_messages(payload)
    matches = DzmmAdapter._align_platform_messages(
        [{"text": "重复"}, {"text": "重复"}], api_messages
    )

    assert [item["message_id"] for item in matches] == ["m1", "m2"]
    assert [item["sent_by"] for item in matches] == ["u1", "u2"]


def test_reply_reference_is_extracted_and_persisted(tmp_path):
    db = make_db(tmp_path)
    original = {
        "message_id": "quoted-1",
        "sent_by": "quoted-user",
        "sender_name": "被引用者",
        "content": "被引用的真实消息",
    }
    reply = {
        "message_id": "reply-1",
        "sent_by": "reply-user",
        "content": "这是回复",
        "reply_to_message_id": "quoted-1",
    }
    reference = DzmmAdapter._reply_reference(reply, {"quoted-1": original})
    assert reference == {
        "reply_to_message_id": "quoted-1",
        "reply_to_text": "被引用的真实消息",
        "reply_to_sender": "被引用者",
    }
    db.save_message(
        {
            **identity("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "回复者", "", "reply-1"),
            "text": "这是回复",
            **reference,
        }
    )
    stored = db.conn.execute(
        "select reply_to_message_id,reply_to_text,reply_to_sender from messages where message_id='reply-1'"
    ).fetchone()
    assert dict(stored) == reference


def test_image_upload_selector_rejects_flash_and_prefers_normal_photo():
    assert DzmmAdapter._ordinary_image_input_score(
        {"ownerText": "闪照", "mode": "view-once", "accept": "image/*"}, 1
    ) is None
    normal = DzmmAdapter._ordinary_image_input_score(
        {"ownerText": "普通图片", "mode": "photo", "accept": "image/*"}, 0
    )
    unknown = DzmmAdapter._ordinary_image_input_score(
        {"ownerText": "", "accept": "image/*"}, 1
    )
    assert normal is not None and unknown is not None
    assert normal > unknown


def test_verified_user_detail_uses_related_user_id_columns(tmp_path):
    db = make_db(tmp_path)
    platform_id = "44444444-4444-4444-4444-444444444444"
    user = db.ensure_user(identity(platform_id, "detail-user", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))
    db.conn.execute(
        "insert into inventory(user_id, nickname, item_name, quantity, updated_at) values(?, ?, ?, ?, ?)",
        (platform_id, user["nickname"], "test-item", 2, db.now()),
    )
    db.conn.commit()

    detail = db.user_detail(f"pk:{user['id']}")

    assert detail["inventory"][0]["item_name"] == "test-item"
    assert detail["inventory"][0]["quantity"] == 2


def test_user_detail_includes_all_game_history_categories(tmp_path):
    db = make_db(tmp_path)
    platform_id = "45454545-4545-4545-4545-454545454545"
    msg = identity(platform_id, "game-detail-user", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    user = db.ensure_user(msg)
    db.add_points(user, 100, "游戏记录测试准备")
    db.record_game_play(user, "修女纸牌")
    db.create_game("群纸牌对战", user, 10, max_players=2)
    now = db.now()
    db.conn.execute(
        """insert into six_seal_games(
             status,initiator_user_pk,initiator_user_id,initiator_nickname,current_wager,
             base_wager,max_wager,wager_step,reserve_amount,created_at,expires_at)
           values('finished',?,?,?,?,10,100,10,100,?,?)""",
        (user["id"], platform_id, user["nickname"], 10, now, now),
    )
    db.conn.execute(
        """insert into nipple_guess_sessions(user_pk,user_id,nickname,status,created_at,updated_at)
           values(?,?,?,'finished',?,?)""",
        (user["id"], platform_id, user["nickname"], now, now),
    )
    db.conn.commit()
    detail = db.user_detail(f"pk:{user['id']}")
    assert detail["game_plays"][0]["game_type"] == "修女纸牌"
    assert detail["game_battles"][0]["game_type"] == "群纸牌对战"
    assert detail["six_seal_games"][0]["status"] == "finished"
    assert detail["nipple_guess_sessions"][0]["status"] == "finished"


def test_delete_user_archives_and_removes_active_business_data(tmp_path):
    db = make_db(tmp_path)
    platform_id = "55555555-5555-5555-5555-555555555555"
    user = db.ensure_user(identity(platform_id, "delete-user", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"))
    db.conn.execute(
        "insert into transactions(user_id, nickname, change_amount, reason, balance_after, created_at) values(?, ?, 5, 'test', 5, ?)",
        (platform_id, user["nickname"], db.now()),
    )
    db.conn.commit()

    deleted = db.delete_user(f"pk:{user['id']}")

    assert deleted["id"] == user["id"]
    assert db.conn.execute("select count(*) from users where id=?", (user["id"],)).fetchone()[0] == 0
    assert db.conn.execute("select count(*) from transactions where user_id=?", (platform_id,)).fetchone()[0] == 0
    archive = db.conn.execute("select snapshot_json from deleted_user_archives where user_pk=?", (user["id"],)).fetchone()
    assert archive is not None
    assert json.loads(archive["snapshot_json"])["user"]["platform_user_id"] == platform_id


def test_update_user_by_internal_primary_key(tmp_path):
    db = make_db(tmp_path)
    platform_id = "66666666-6666-6666-6666-666666666666"
    user = db.ensure_user(identity(platform_id, "edit-user", "cccccccc-cccc-cccc-cccc-cccccccccccc"))

    updated = db.update_user(
        f"pk:{user['id']}",
        {**user, "display_name": "edited-title", "points": 88},
    )

    assert updated["id"] == user["id"]
    assert updated["display_name"] == "edited-title"
    assert updated["points"] == 88


def test_nickname_only_lookup_reuses_verified_user_without_creating_copy(tmp_path):
    db = make_db(tmp_path)
    platform_id = "77777777-7777-7777-7777-777777777777"
    verified = db.ensure_user(
        identity(platform_id, "verified-name", "dddddddd-dddd-dddd-dddd-dddddddddddd")
    )

    resolved = db.ensure_user("verified-name")

    assert resolved["id"] == verified["id"]
    assert resolved["platform_user_id"] == platform_id
    assert db.conn.execute(
        "select count(*) from users where nickname='verified-name'"
    ).fetchone()[0] == 1


def test_nickname_only_lookup_rejects_ambiguous_identity(tmp_path):
    db = make_db(tmp_path)
    db.ensure_user(
        identity(
            "88888888-8888-8888-8888-888888888888",
            "ambiguous-name",
            "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        )
    )
    db.conn.execute(
        """insert into users(
             nickname, identity_status, display_name, nickname_history, last_seen_at)
           values('ambiguous-name', 'pending', 'pending-copy', 'ambiguous-name', ?)""",
        (db.now(),),
    )
    db.conn.commit()

    with pytest.raises(ValueError, match="昵称对应多个用户"):
        db.ensure_user("ambiguous-name")


def test_pending_user_edit_is_scoped_to_primary_key(tmp_path):
    db = make_db(tmp_path)
    normal = db.ensure_user(
        identity(
            "99999999-9999-9999-9999-999999999999",
            "same-name",
            "ffffffff-ffff-ffff-ffff-ffffffffffff",
        )
    )
    cur = db.conn.execute(
        """insert into users(
             nickname, identity_status, display_name, nickname_history, points, last_seen_at)
           values('same-name', 'pending', 'pending-title', 'same-name', 300, ?)""",
        (db.now(),),
    )
    db.conn.commit()
    pending = dict(db.conn.execute("select * from users where id=?", (cur.lastrowid,)).fetchone())

    updated = db.update_user(
        f"pk:{pending['id']}",
        {**pending, "display_name": "pending-edited", "points": 72},
    )

    assert updated["id"] == pending["id"]
    assert updated["points"] == 72
    assert db.conn.execute("select points from users where id=?", (normal["id"],)).fetchone()[0] == 0


def test_group_battle_payout_keeps_platform_id(tmp_path):
    db = make_db(tmp_path)
    platform_id = "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"
    player = db.ensure_user(
        identity(platform_id, "battle-user", "abababab-abab-abab-abab-abababababab")
    )
    db.conn.execute("update users set points=100 where id=?", (player["id"],))
    db.conn.commit()

    game = db.create_game("群纸牌对战", player, 10, max_players=1)
    result = db.reveal_game(game["game_id"])

    assert result["ok"]
    assert db.get_user({"platform_user_id": platform_id})["points"] == 100
    assert db.conn.execute(
        "select count(*) from users where nickname='battle-user'"
    ).fetchone()[0] == 1
    payout = db.conn.execute(
        "select * from transactions where user_id=? order by id desc limit 1",
        (platform_id,),
    ).fetchone()
    assert payout["change_amount"] == 10


def test_group_battle_winners_are_identified_by_player_id_not_nickname(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    first = db.ensure_user(identity(
        "aaaaaaaa-1111-2222-3333-aaaaaaaaaaaa",
        "同名玩家",
        "11111111-aaaa-aaaa-aaaa-111111111111",
    ))
    second = db.ensure_user(identity(
        "bbbbbbbb-1111-2222-3333-bbbbbbbbbbbb",
        "同名玩家",
        "22222222-bbbb-bbbb-bbbb-222222222222",
    ))
    db.conn.execute("update users set points=100 where id in (?,?)", (first["id"], second["id"]))
    db.conn.commit()
    game = db.create_game("炸金花", first, 10, max_players=2)
    assert db.join_game(second)["ok"]
    dealt = [
        ("♠", "A"), ("♥", "A"), ("♦", "A"),
        ("♠", "2"), ("♥", "5"), ("♦", "9"),
    ]
    monkeypatch.setattr("random.sample", lambda _deck, _count: dealt)

    result = db.reveal_game(game["game_id"])

    assert result["winners"] == ["同名玩家"]
    assert result["winner_user_ids"] == [first["platform_user_id"]]
    assert result["winner_player_ids"] == [result["results"][0]["player_id"]]


def test_user_list_filters_current_nickname_conflicts_by_platform_id(tmp_path):
    db = make_db(tmp_path)
    first = db.ensure_user(
        identity(
            "10101010-1010-1010-1010-101010101010",
            "同名用户",
            "11111111-aaaa-aaaa-aaaa-111111111111",
        )
    )
    second = db.ensure_user(
        identity(
            "20202020-2020-2020-2020-202020202020",
            "同 名 用 户",
            "22222222-bbbb-bbbb-bbbb-222222222222",
        )
    )
    db.ensure_user(
        identity(
            "30303030-3030-3030-3030-303030303030",
            "独立用户",
            "33333333-cccc-cccc-cccc-333333333333",
        )
    )

    all_users = db.list_users(limit=20)
    conflicts = db.list_users(limit=20, nickname_conflict=True)

    assert len(all_users) == 3
    assert {user["id"] for user in conflicts} == {first["id"], second["id"]}
    assert all(user["nickname_conflict"] for user in conflicts)
    assert db.user_detail(f"pk:{first['id']}")["user"]["nickname_conflict"] is True
