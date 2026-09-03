import sqlite3
from datetime import datetime, timedelta

from app.database import Database


USER_ID = "99999999-9999-9999-9999-999999999999"


def make_message(index: int, *, complete: bool = False) -> dict:
    return {
        "message_id": f"message-{index:04d}",
        "platform_user_id": USER_ID if complete else "",
        "user_id": USER_ID if complete else "",
        "avatar_id": "",
        "sender": "测试用户" if complete else "未知用户",
        "text": f"消息 {index}",
        "time": "12:00:00",
        "is_self": False,
        "raw_html": "",
    }


def test_save_message_keeps_all_messages_from_the_last_five_calendar_days(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()

    for index in range(305):
        assert db.save_message(make_message(index))

    assert db.conn.execute("select count(*) from messages").fetchone()[0] == 305
    assert db.get_message("message-0000") is not None
    assert db.get_message("message-0304") is not None


def test_init_keeps_today_and_four_preceding_calendar_days(tmp_path):
    path = tmp_path / "bot.db"
    db = Database(path, allow_legacy_user_creation=True)
    db.init()
    db.close()

    conn = sqlite3.connect(path)
    today = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    conn.executemany(
        """insert into messages(message_id, sender, text, created_at)
           values(?, ?, ?, ?)""",
        [
            ("old", "旧用户", "五天前", (today - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")),
            ("day-four", "保留用户", "四天前", (today - timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S")),
            ("day-three", "保留用户", "三天前", (today - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")),
            ("day-before", "保留用户", "前天", (today - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")),
            ("yesterday", "保留用户", "昨天", (today - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")),
            ("today", "保留用户", "今天", today.strftime("%Y-%m-%d %H:%M:%S")),
        ],
    )
    conn.commit()
    conn.close()

    reopened = Database(path, allow_legacy_user_creation=True)
    reopened.init()

    assert reopened.conn.execute("select count(*) from messages").fetchone()[0] == 5
    assert reopened.get_message("old") is None
    assert reopened.get_message("day-four") is not None
    assert reopened.get_message("day-three") is not None
    assert reopened.get_message("day-before") is not None
    assert reopened.get_message("yesterday") is not None
    assert reopened.get_message("today") is not None


def test_incomplete_observation_is_updated_without_duplicate_row(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    assert db.save_message(make_message(1))

    assert not db.save_message(make_message(1, complete=True))

    stored = db.get_message("message-0001")
    assert stored["platform_user_id"] == USER_ID
    assert stored["sender"] == "测试用户"
    assert stored["identity_status"] == "normal"
    assert db.conn.execute("select count(*) from messages").fetchone()[0] == 1


def test_init_removes_pending_users_below_20_messages(tmp_path):
    path = tmp_path / "bot.db"
    db = Database(path, allow_legacy_user_creation=True)
    db.init()
    now = db.now()
    db.conn.executemany(
        """insert into users(
               nickname, identity_status, message_count, points, first_seen_at, last_seen_at)
           values(?, ?, ?, ?, ?, ?)""",
        [
            ("待删除19", "pending", 19, 200, now, now),
            ("保留20", "pending", 20, 200, now, now),
            ("正常用户", "normal", 1, 200, now, now),
            ("冲突用户", "conflict", 1, 200, now, now),
        ],
    )
    db.conn.commit()
    db.close()

    reopened = Database(path, allow_legacy_user_creation=True)
    reopened.init()

    names = {
        row[0]
        for row in reopened.conn.execute(
            "select nickname from users where nickname in ('待删除19','保留20','正常用户','冲突用户')"
        ).fetchall()
    }
    assert names == {"保留20", "正常用户", "冲突用户"}
