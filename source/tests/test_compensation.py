from app.database import Database


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    return db


def test_compensation_includes_normal_pending_and_conflict_users(tmp_path):
    db = make_db(tmp_path)
    normal = db.ensure_user(
        {
            "platform_user_id": "11111111-1111-1111-1111-111111111111",
            "sender": "正常用户",
            "avatar_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        }
    )
    pending = db.ensure_user("待校准用户")
    conflict = db.ensure_user(
        {
            "platform_user_id": "22222222-2222-2222-2222-222222222222",
            "sender": "冲突用户",
            "avatar_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        }
    )
    db.conn.execute(
        "update users set points=10 where id=?",
        (int(normal["id"]),),
    )
    db.conn.execute(
        "update users set identity_status='conflict', points=20 where id=?",
        (int(conflict["id"]),),
    )
    db.conn.commit()

    preview = db.compensation_preview()
    assert preview == {
        "recipient_count": 3,
        "normal_count": 1,
        "pending_count": 1,
        "conflict_count": 1,
    }

    batch = db.grant_compensation("request-123", 50, "更新补偿")
    assert batch["recipient_count"] == 3
    assert batch["total_amount"] == 150
    assert batch["duplicate"] is False
    assert db.conn.execute(
        "select points from users where id=?",
        (int(normal["id"]),),
    ).fetchone()[0] == 60
    assert db.conn.execute(
        "select points from users where id=?",
        (int(pending["id"]),),
    ).fetchone()[0] == 50
    assert db.conn.execute(
        "select points from users where id=?",
        (int(conflict["id"]),),
    ).fetchone()[0] == 70
    assert db.conn.execute(
        "select count(*) from transactions where reason like '全员补偿：%'"
    ).fetchone()[0] == 3


def test_compensation_request_id_prevents_duplicate_grant(tmp_path):
    db = make_db(tmp_path)
    user = db.ensure_user("待校准用户")

    first = db.grant_compensation("same-request", 30, "更新补偿")
    second = db.grant_compensation("same-request", 30, "更新补偿")

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert db.conn.execute(
        "select points from users where id=?",
        (int(user["id"]),),
    ).fetchone()[0] == 30
    assert db.conn.execute(
        "select count(*) from compensation_recipients"
    ).fetchone()[0] == 1


def test_compensation_excludes_non_user_placeholder_rows(tmp_path):
    db = make_db(tmp_path)
    db.ensure_user("真实用户")
    db.conn.execute(
        """insert into users(
             nickname, identity_status, first_seen_at, last_seen_at)
           values('我', 'pending', ?, ?)""",
        (db.now(), db.now()),
    )
    db.conn.commit()

    assert db.compensation_preview()["recipient_count"] == 1
