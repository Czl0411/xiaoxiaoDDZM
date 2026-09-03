from __future__ import annotations

import asyncio

import pytest

from app.command_router import CommandRouter
from app.database import Database
from app.scheduler import BotScheduler


PUBLISHER_ID = "11111111-1111-1111-1111-111111111111"
TAKER_ID = "22222222-2222-2222-2222-222222222222"
OTHER_ID = "33333333-3333-3333-3333-333333333333"


def make_db(tmp_path) -> Database:
    db = Database(tmp_path / "bot.db")
    db.init()
    return db


def make_user(db: Database, user_id: str, nickname: str, points: int = 0):
    user = db.ensure_user(
        {
            "platform_user_id": user_id,
            "user_id": user_id,
            "sender": nickname,
        }
    )
    if points:
        db.add_points(user, points, "测试初始化")
    return db.get_user(user)


def message(user_id: str, nickname: str, text: str, group_key: str = "main") -> dict:
    return {
        "platform_user_id": user_id,
        "user_id": user_id,
        "sender": nickname,
        "message_id": f"{group_key}-{user_id}-{text}",
        "text": text,
        "is_self": False,
        "group_key": group_key,
        "source_group": group_key,
    }


@pytest.mark.skip(reason="旧悬赏命令已由群友委托所替换；新流程见 test_commission_house.py")
def test_publish_freezes_reward_mirrors_and_sends_clean_invite(tmp_path):
    db = make_db(tmp_path)
    publisher = make_user(db, PUBLISHER_ID, "大祭司", 500)
    result = CommandRouter(db).handle(
        message(
            PUBLISHER_ID,
            "大祭司",
            "/发布悬赏令 3 300 三天内每天在群里分享一首歌",
        )
    )

    assert result.handled
    assert result.name == "发布悬赏令"
    assert len(result.replies) == 3
    assert result.replies[-1] == "https://www.dzmm.ai/invite/D7ZlMdAT"
    assert result.deliveries[0]["group_key"] == "bounty"
    assert "圣光教堂悬赏令" in result.deliveries[0]["text"]
    assert db.get_user(publisher)["points"] == 170
    bounty = db.get_bounty(1)
    assert bounty["status"] == "waiting"
    assert bounty["reward"] == 300
    assert bounty["reward_escrow"] == 300
    assert bounty["fee_escrow"] == 30
    assert bounty["total_charge"] == 330
    assert bounty["source_group"] == "main"


@pytest.mark.skip(reason="旧悬赏命令已废弃")
def test_publish_in_bounty_group_does_not_repeat_invite_or_duplicate_card(tmp_path):
    db = make_db(tmp_path)
    make_user(db, PUBLISHER_ID, "发布者", 200)
    result = CommandRouter(db).handle(
        message(
            PUBLISHER_ID,
            "发布者",
            "/发布悬赏令 单次 150 在群里夸我一次",
            "bounty",
        )
    )

    assert len(result.replies) == 1
    assert result.deliveries == []
    assert "单次" in result.replies[0]


@pytest.mark.skip(reason="旧悬赏命令已废弃")
def test_list_detail_and_accept_are_bounty_group_only_and_under_ten_lines(tmp_path):
    db = make_db(tmp_path)
    make_user(db, PUBLISHER_ID, "发起人", 1000)
    make_user(db, TAKER_ID, "接取人", 0)
    router = CommandRouter(db)
    for index in range(4):
        router.handle(
            message(
                PUBLISHER_ID,
                "发起人",
                f"/发布悬赏令 1 100 第{index + 1}条悬赏",
            )
        )

    blocked = router.handle(message(TAKER_ID, "接取人", "/悬赏", "main"))
    listing = router.handle(message(TAKER_ID, "接取人", "/悬赏", "bounty"))
    detail = router.handle(
        message(TAKER_ID, "接取人", "/查看悬赏 1", "bounty")
    )
    accepted = router.handle(
        message(TAKER_ID, "接取人", "/接悬赏 0004", "bounty")
    )

    assert "仅允许" in blocked.replies[0]
    assert listing.replies[0].count("\n") <= 9
    assert "#0004" in listing.replies[0]
    assert "#0004" in detail.replies[0]
    assert accepted.handled and "已接取悬赏" in accepted.replies[0]
    assert db.get_bounty(4)["taker_user_id"] == TAKER_ID


@pytest.mark.skip(reason="旧悬赏命令已废弃")
def test_complete_requires_taker_then_publisher_and_pays_escrow(tmp_path):
    db = make_db(tmp_path)
    publisher = make_user(db, PUBLISHER_ID, "发布者", 300)
    taker = make_user(db, TAKER_ID, "接取者", 10)
    router = CommandRouter(db)
    router.handle(
        message(PUBLISHER_ID, "发布者", "/发布悬赏令 1 200 完成测试")
    )
    router.handle(message(TAKER_ID, "接取者", "/接悬赏 0001", "bounty"))

    requested = router.handle(
        message(TAKER_ID, "接取者", "/完成悬赏 0001", "main")
    )
    confirmed = router.handle(
        message(PUBLISHER_ID, "发布者", "/确认完成 0001", "main")
    )

    assert "可发送 /确认完成" in requested.replies[0]
    assert "发放 200功德" in confirmed.replies[0]
    assert db.get_user(publisher)["points"] == 80
    assert db.get_user(taker)["points"] == 210
    assert db.get_bounty(1)["status"] == "completed"


@pytest.mark.skip(reason="旧悬赏命令已废弃")
def test_multi_bounty_list_shows_each_participant_and_independent_settlement(tmp_path):
    db = make_db(tmp_path)
    make_user(db, PUBLISHER_ID, "发布者", 500)
    make_user(db, TAKER_ID, "甲", 0)
    second_id = "00000000-0000-0000-0000-000000000099"
    make_user(db, second_id, "乙", 0)
    router = CommandRouter(db)
    router.handle(message(PUBLISHER_ID, "发布者", "/发布悬赏令 单次 2人 100 多人测试"))
    router.handle(message(TAKER_ID, "甲", "/接悬赏0001", "bounty"))
    router.handle(message(second_id, "乙", "/接悬赏0001", "bounty"))
    router.handle(message(TAKER_ID, "甲", "/完成悬赏0001"))

    before = router.handle(message(PUBLISHER_ID, "发布者", "/我的悬赏"))
    paid = router.handle(message(PUBLISHER_ID, "发布者", "/确认完成0001"))
    after = router.handle(message(PUBLISHER_ID, "发布者", "/我的悬赏"))

    assert "👥 多人悬赏（独立结算）" in before.replies[0]
    assert "甲·待确认" in before.replies[0]
    assert "乙·进行中" in before.replies[0]
    assert "甲" in paid.replies[0] and "100功德" in paid.replies[0]
    assert "甲·已结算" in after.replies[0]
    first = dict(db.conn.execute("select * from users where platform_user_id=?", (TAKER_ID,)).fetchone())
    second = dict(db.conn.execute("select * from users where platform_user_id=?", (second_id,)).fetchone())
    assert first["points"] == 100
    assert second["points"] == 0
    assert db.get_bounty(1)["status"] == "active"


@pytest.mark.skip(reason="旧单方取消规则已由订单双方取消替换")
def test_waiting_and_active_cancel_refund_reward_and_fee(tmp_path):
    db = make_db(tmp_path)
    publisher = make_user(db, PUBLISHER_ID, "发布者", 500)
    taker = make_user(db, TAKER_ID, "接取者", 0)
    router = CommandRouter(db)
    router.handle(message(PUBLISHER_ID, "发布者", "/发布悬赏令 单次 100 等待取消"))
    waiting_cancel = router.handle(
        message(PUBLISHER_ID, "发布者", "/取消悬赏 0001")
    )
    router.handle(message(PUBLISHER_ID, "发布者", "/发布悬赏令 1 200 进行中取消"))
    router.handle(message(TAKER_ID, "接取者", "/接悬赏 0002", "bounty"))
    active_cancel = router.handle(
        message(PUBLISHER_ID, "发布者", "/取消悬赏 0002")
    )

    assert "全额退回" in waiting_cancel.replies[0]
    assert "220功德已全额退回" in active_cancel.replies[0]
    assert db.get_user(publisher)["points"] == 500
    assert db.get_user(taker)["points"] == 0
    assert db.get_bounty(2)["forfeited_amount"] == 0


@pytest.mark.skip(reason="旧跑单取消命令已由订单双方取消替换")
def test_three_taker_abandonments_create_seven_day_ban(tmp_path):
    db = make_db(tmp_path)
    make_user(db, PUBLISHER_ID, "发布者", 1000)
    make_user(db, TAKER_ID, "跑单人", 0)
    router = CommandRouter(db)
    for number in range(1, 4):
        router.handle(
            message(
                PUBLISHER_ID,
                "发布者",
                f"/发布悬赏令 1 100 跑单测试{number}",
            )
        )
        router.handle(
            message(TAKER_ID, "跑单人", f"/接悬赏 {number:04d}", "bounty")
        )
        cancelled = router.handle(
            message(TAKER_ID, "跑单人", f"/取消悬赏 {number:04d}")
        )

    assert "暂停接取" in cancelled.replies[0]
    router.handle(message(PUBLISHER_ID, "发布者", "/发布悬赏令 1 100 禁用测试"))
    blocked = router.handle(
        message(TAKER_ID, "跑单人", "/接悬赏 0004", "bounty")
    )
    assert "解禁时间" in blocked.replies[0]


class FakeBrowser:
    page = None


class FakeAdapter:
    def __init__(self):
        self.browser = FakeBrowser()
        self.sent: list[tuple[str, str]] = []
        self.read_groups: list[str] = []

    async def send_message(self, text: str, group_key: str = "main") -> bool:
        self.sent.append((group_key, text))
        return True

    async def send_image(self, path: str, group_key: str = "main") -> bool:
        return True

    async def read_recent_messages(self, group_key: str = "main"):
        self.read_groups.append(group_key)
        return []


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


@pytest.mark.skip(reason="旧悬赏发布命令已废弃；新流程投递由统一委托测试覆盖")
def test_scheduler_keeps_link_message_clean_and_routes_mirror_to_bounty(tmp_path):
    db = make_db(tmp_path)
    make_user(db, PUBLISHER_ID, "发布者", 200)
    config = db.get_config()
    config["dzmm"]["send_delay_seconds"] = 0
    adapter = FakeAdapter()
    scheduler = BotScheduler(
        db, adapter, engine=None, logger=FakeLogger(), command_router=CommandRouter(db)
    )
    msg = message(
        PUBLISHER_ID,
        "发布者",
        "/发布悬赏令 单次 100 路由测试",
        "main",
    )
    msg.update({"time": "12:00:00", "raw_html": "", "source_index": "1"})

    asyncio.run(scheduler._tick(config, [msg], group_key="main"))

    assert adapter.sent[-1][0] == "bounty"
    main_messages = [text for group, text in adapter.sent if group == "main"]
    assert main_messages[-1] == "https://www.dzmm.ai/invite/D7ZlMdAT"
    assert main_messages[-1].strip() == main_messages[-1]


def test_scheduler_scans_main_and_bounty_groups_independently(tmp_path):
    db = make_db(tmp_path)
    config = db.get_config()
    config["dzmm"]["bot_enabled"] = True
    config["dzmm"]["bounty_group_url"] = (
        "https://www.ainvmei.com/chat?c=7dd8c7ee-f782-4426-95e9-137db51c2027"
    )
    adapter = FakeAdapter()
    scheduler = BotScheduler(
        db, adapter, engine=None, logger=FakeLogger(), command_router=CommandRouter(db)
    )
    scheduler.paused = False
    scheduler.primed_groups = {"main", "bounty"}

    asyncio.run(scheduler._run_cycle(config))

    assert adapter.read_groups == ["main", "bounty"]
