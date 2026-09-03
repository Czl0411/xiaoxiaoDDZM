import asyncio

from app.database import Database
from app.scheduler import BotScheduler


PLATFORM_ID = "77777777-7777-7777-7777-777777777777"
AVATAR_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


class FakeAdapter:
    def __init__(self, messages):
        self.messages = messages
        self.read_count = 0

    async def is_logged_in(self):
        return True

    async def read_recent_messages(self):
        self.read_count += 1
        return self.messages


class FakeLogger:
    def __init__(self):
        self.entries = []

    def info(self, message, kind="normal"):
        self.entries.append(("info", kind, message))

    def warning(self, message, kind="normal"):
        self.entries.append(("warning", kind, message))

    def error(self, message, kind="error"):
        self.entries.append(("error", kind, message))


def make_message(message_id="silent-1"):
    return {
        "message_id": message_id,
        "platform_user_id": PLATFORM_ID,
        "user_id": PLATFORM_ID,
        "avatar_id": AVATAR_ID,
        "sender": "silent-user",
        "text": "ordinary chat",
        "time": "2026-07-17 10:00:00",
        "is_self": False,
        "raw_html": "",
    }


def make_scheduler(tmp_path, messages):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    adapter = FakeAdapter(messages)
    logger = FakeLogger()
    scheduler = BotScheduler(db, adapter, engine=None, logger=logger)
    return db, adapter, logger, scheduler


def test_silent_calibration_defaults_to_disabled(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()

    assert db.get_config()["dzmm"]["silent_identity_calibration_enabled"] is False


def test_legacy_silent_calibration_flag_is_ignored_while_paused(tmp_path):
    db, adapter, logger, scheduler = make_scheduler(tmp_path, [make_message()])
    scheduler.paused = True
    config = db.get_config()
    config["dzmm"]["bot_enabled"] = False
    config["dzmm"]["silent_identity_calibration_enabled"] = True

    asyncio.run(scheduler._run_cycle(config))

    assert adapter.read_count == 0
    assert db.get_user({"platform_user_id": PLATFORM_ID}) is None
    assert db.get_message("silent-1") is None
    assert db.conn.execute("select count(*) from replies").fetchone()[0] == 0
    assert not any(kind == "identity" for _, kind, _ in logger.entries)


def test_business_processing_still_reads_once_when_legacy_flag_is_true(tmp_path):
    db, adapter, _, scheduler = make_scheduler(tmp_path, [make_message("silent-2")])
    scheduler.paused = False
    scheduler.primed = True
    config = db.get_config()
    config["dzmm"]["bot_enabled"] = True
    config["dzmm"]["silent_identity_calibration_enabled"] = True

    asyncio.run(scheduler._run_cycle(config))

    assert adapter.read_count == 1
    assert db.get_message("silent-2")["processed"] == 1
    assert db.conn.execute("select count(*) from replies").fetchone()[0] == 0


def test_business_processing_never_calls_legacy_calibration(tmp_path, monkeypatch):
    db, _, _, scheduler = make_scheduler(tmp_path, [make_message("silent-once")])
    scheduler.paused = False
    scheduler.primed = True
    config = db.get_config()
    config["dzmm"]["bot_enabled"] = True
    config["dzmm"]["silent_identity_calibration_enabled"] = True
    calls = []

    def counted(message):
        calls.append(message["message_id"])
        raise AssertionError("后台校准链路不应再被调用")

    monkeypatch.setattr(db, "calibrate_message_identity", counted)

    asyncio.run(scheduler._run_cycle(config))

    assert calls == []
    assert db.get_message("silent-once")["processed"] == 1


def test_seen_message_memory_is_bounded(tmp_path):
    _, _, _, scheduler = make_scheduler(tmp_path, [])

    for index in range(scheduler.MESSAGE_MEMORY_LIMIT + 25):
        scheduler._remember_seen(f"seen-{index}")

    assert len(scheduler.seen_message_ids) == scheduler.MESSAGE_MEMORY_LIMIT
    assert len(scheduler.seen_message_order) == scheduler.MESSAGE_MEMORY_LIMIT
    assert "seen-0" not in scheduler.seen_message_ids
    assert f"seen-{scheduler.MESSAGE_MEMORY_LIMIT + 24}" in scheduler.seen_message_ids


def test_business_cycle_does_not_auto_issue_facility_wages(tmp_path, monkeypatch):
    db, _, _, scheduler = make_scheduler(tmp_path, [])
    scheduler.paused = False
    scheduler.primed = True
    config = db.get_config()
    config["dzmm"]["bot_enabled"] = True
    config["dzmm"]["silent_identity_calibration_enabled"] = False
    monkeypatch.setattr(
        db,
        "run_due_facility_wages",
        lambda: (_ for _ in ()).throw(AssertionError("不应自动发放工资")),
    )

    asyncio.run(scheduler._run_cycle(config))
