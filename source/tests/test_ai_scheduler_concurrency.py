from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.ai_character import parse_ai_command
from app.database import Database
from app.scheduler import BotScheduler


class FakeBrowser:
    page = None


class FakeAdapter:
    def __init__(self):
        self.browser = FakeBrowser()
        self.sent: list[str] = []

    async def send_message(self, text: str, group_key: str = "main") -> bool:
        self.sent.append(text)
        return True


class FakeLogger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class FakeStore:
    def __init__(self, settings: dict):
        self._settings = settings

    def settings(self):
        return dict(self._settings)


class FakeAiService:
    def __init__(self, settings: dict):
        self.store = FakeStore(settings)


def make_message(message_id: str, user_id: str, text: str = "/zz 测试") -> dict:
    return {
        "message_id": message_id,
        "platform_user_id": user_id,
        "user_id": user_id,
        "sender": user_id,
        "text": text,
        "group_key": "main",
        "source_group": "main",
    }


def make_scheduler(tmp_path, **overrides):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    config = db.get_config()
    config["dzmm"]["send_delay_seconds"] = 0
    config["safety"]["night_silence_enabled"] = False
    config["safety"]["max_replies_per_minute"] = 1000
    config["safety"]["max_replies_per_hour"] = 1000
    db.save_config(config)
    settings = {
        "normal_concurrency": 2,
        "thinking_concurrency": 1,
        "normal_thinking": False,
        "per_user_queue": 3,
        "per_group_queue": 10,
        "queue_wait_seconds": 2,
        **overrides,
    }
    scheduler = BotScheduler(
        db,
        FakeAdapter(),
        engine=None,
        logger=FakeLogger(),
        ai_service=FakeAiService(settings),
    )
    return db, scheduler, config


def run(coro):
    return asyncio.run(coro)


def test_two_users_overlap_but_same_user_stays_in_order(tmp_path):
    db, scheduler, config = make_scheduler(tmp_path, normal_concurrency=2)
    started: list[str] = []
    release_first = asyncio.Event()
    both_users_started = asyncio.Event()

    async def handle(msg, _command, _config):
        started.append(msg["message_id"])
        if {"u1-first", "u2-first"}.issubset(started):
            both_users_started.set()
        if msg["message_id"] == "u1-first":
            await release_first.wait()

    async def scenario():
        scheduler._handle_ai_request = handle
        await scheduler._queue_ai_request(make_message("u1-first", "u1"), parse_ai_command("/zz 一"), config)
        await scheduler._queue_ai_request(make_message("u1-second", "u1"), parse_ai_command("/zz 二"), config)
        await scheduler._queue_ai_request(make_message("u2-first", "u2"), parse_ai_command("/zz 三"), config)
        await asyncio.wait_for(both_users_started.wait(), 1)
        assert "u1-second" not in started
        release_first.set()
        await asyncio.gather(*list(scheduler.ai_request_tasks))

    run(scenario())
    assert started.index("u1-first") < started.index("u1-second")
    db.close()


def test_normal_and_thinking_have_independent_limits(tmp_path):
    db, scheduler, config = make_scheduler(tmp_path, normal_concurrency=1, thinking_concurrency=1)
    active = {"normal": 0, "thinking": 0}
    peaks = {"normal": 0, "thinking": 0}
    release = asyncio.Event()

    async def handle(msg, command, _config):
        mode = "thinking" if command.thinking else "normal"
        active[mode] += 1
        peaks[mode] = max(peaks[mode], active[mode])
        await release.wait()
        active[mode] -= 1

    async def scenario():
        scheduler._handle_ai_request = handle
        await scheduler._queue_ai_request(make_message("n1", "n1"), parse_ai_command("/zz 一"), config)
        await scheduler._queue_ai_request(make_message("n2", "n2"), parse_ai_command("/zz 二"), config)
        await scheduler._queue_ai_request(make_message("t1", "t1", "/zzs 一"), parse_ai_command("/zzs 一"), config)
        await scheduler._queue_ai_request(make_message("t2", "t2", "/zzs 二"), parse_ai_command("/zzs 二"), config)
        await asyncio.sleep(0.05)
        assert active == {"normal": 1, "thinking": 1}
        release.set()
        await asyncio.gather(*list(scheduler.ai_request_tasks))

    run(scenario())
    assert peaks == {"normal": 1, "thinking": 1}
    db.close()


def test_queue_full_and_timeout_do_not_create_ai_task_or_charge(tmp_path):
    db, scheduler, config = make_scheduler(
        tmp_path, normal_concurrency=1, per_user_queue=1, queue_wait_seconds=1
    )
    release = asyncio.Event()

    async def handle(_msg, _command, _config):
        await release.wait()

    async def scenario():
        scheduler._handle_ai_request = handle
        await scheduler._queue_ai_request(make_message("first", "u1"), parse_ai_command("/zz 一"), config)
        await asyncio.sleep(0)
        await scheduler._queue_ai_request(make_message("full", "u1"), parse_ai_command("/zz 二"), config)
        await scheduler._queue_ai_request(make_message("timeout", "u2"), parse_ai_command("/zz 三"), config)
        await asyncio.sleep(1.1)
        release.set()
        await asyncio.gather(*list(scheduler.ai_request_tasks))

    run(scenario())
    assert any("正在排队" in text for text in scheduler.adapter.sent)
    assert any("等待超时" in text for text in scheduler.adapter.sent)
    assert db.conn.execute("select count(*) from ai_tasks").fetchone()[0] == 0
    assert db.conn.execute("select count(*) from ai_fee_transactions").fetchone()[0] == 0
    db.close()


def test_stop_cleans_request_tasks_and_waits_for_background(tmp_path):
    db, scheduler, config = make_scheduler(tmp_path)
    request_started = asyncio.Event()
    background_release = asyncio.Event()
    background_finished = asyncio.Event()

    async def handle(_msg, _command, _config):
        request_started.set()
        await asyncio.Event().wait()

    async def background():
        await background_release.wait()
        background_finished.set()

    async def scenario():
        scheduler.running = True
        scheduler._handle_ai_request = handle
        await scheduler._queue_ai_request(make_message("stop", "u1"), parse_ai_command("/zz 一"), config)
        await request_started.wait()
        scheduler.ai_background_task = asyncio.create_task(background())
        stop_task = asyncio.create_task(scheduler.stop())
        await asyncio.sleep(0)
        assert not stop_task.done()
        background_release.set()
        await stop_task
        assert background_finished.is_set()

    run(scenario())
    assert scheduler.ai_request_tasks == set()
    assert scheduler.ai_queue_counts == {}
    assert scheduler.ai_group_queue_counts == {}
    db.close()
