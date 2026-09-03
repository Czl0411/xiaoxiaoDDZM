from __future__ import annotations

import asyncio

from app.command_router import CommandRouter
from app.database import Database
from app.scheduler import BotScheduler


UID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def message(text: str, mid: str = "m1") -> dict:
    return {
        "message_id": mid,
        "platform_user_id": UID,
        "user_id": UID,
        "sender": "测试者",
        "text": text,
        "is_self": False,
        "group_key": "main",
        "source_group": "main",
    }


def make_db(tmp_path) -> Database:
    db = Database(tmp_path / "bot.db")
    db.init()
    return db


def fund(db: Database, amount: int = 1000) -> dict:
    user = db.ensure_user(message("初始化", "init"))
    db.add_points(user, amount, "测试入账")
    return db.get_user(user)


def test_total_merit_only_increases_and_monument_uses_strict_threshold(tmp_path):
    db = make_db(tmp_path)
    initial_total = int(db.ensure_user(message("初始化", "init"))["total_merit"])
    user = fund(db, 11000)
    assert db.get_user(user)["total_merit"] == initial_total + 11000
    db.add_points(user, -1500, "测试消费")
    assert db.get_user(user)["total_merit"] == initial_total + 11000
    result = CommandRouter(db).handle(message("/功德碑", "monument"))
    assert result.handled and "测试者" in result.replies[0]
    assert f"历史 {initial_total + 11000} 功德" in result.replies[0]

    db.conn.execute("update users set total_merit=10000 where id=?", (int(user["id"]),))
    db.conn.commit()
    empty = CommandRouter(db).handle(message("/功德碑", "monument-2"))
    assert "等待第一束圣光" in empty.replies[0]


def test_total_merit_excludes_refunds_and_only_counts_six_seal_reward(tmp_path):
    db = make_db(tmp_path)
    user = fund(db, 1000)
    base = int(db.get_user(user)["total_merit"])
    db.add_points(user, 200, "欲望圣裁无人加入，解除冻结")
    db.add_points(user, 272, "欲望圣裁获胜，获得72，正常损耗18")
    db.add_points(user, 100, "猜乳头超时安全退款")
    db.add_points(user, 50, "祈福奖励")
    assert db.get_user(user)["total_merit"] == base + 72 + 50


def test_blind_box_probabilities_assets_and_accounting(tmp_path):
    db = make_db(tmp_path)
    config = db.get_config()
    config["features"]["game_daily_blind_box_limit"] = "10"
    db.save_config(config)
    user = fund(db, 1000)
    before_balance = int(db.get_user(user)["points"])
    before_total = int(db.get_user(user)["total_merit"])

    double = CommandRouter(db, random_source=lambda: 0.01).handle(message("/盲盒", "box-double"))
    assert "双人大奖" in double.replies[0] and "+500" in double.replies[0]
    assert double.media_first is False and double.media_paths[0].endswith("2660173a-8afe-4002-a9b0-c07fd40ae5aa.png")
    assert db.get_user(user)["points"] == before_balance + 400
    assert db.get_user(user)["total_merit"] == before_total + 500

    single = CommandRouter(db, random_source=lambda: 0.10).handle(message("/盲盒", "box-single"))
    assert "盲盒开出：单人" in single.replies[0] and "+200" in single.replies[0]
    assert single.media_paths[0].endswith("e9632273-e2a0-42c4-8a88-4819113a6ec8.png")

    failed = CommandRouter(db, random_source=lambda: 0.50).handle(message("/盲盒", "box-empty"))
    assert "空盒" in failed.replies[0] and "失败了喔" in failed.replies[0]
    assert failed.media_paths[0].endswith("c36d90a7-8a62-4804-aa64-d527f991c6ec.jpeg")

    config = db.get_config()
    config["features"]["blind_box_double_reply"] = "自定义双人奖｜{reward}｜{balance}"
    db.save_config(config)
    custom = CommandRouter(db, random_source=lambda: 0.01).handle(message("/盲盒", "box-custom"))
    assert custom.replies[0].startswith("自定义双人奖｜500｜")


def test_blind_box_daily_limit_defaults_to_three_and_is_configurable(tmp_path):
    db = make_db(tmp_path)
    user = fund(db, 1000)
    router = CommandRouter(db, random_source=lambda: 0.50)

    for index in range(3):
        result = router.handle(message("/盲盒", f"box-limit-{index}"))
        assert result.handled and result.reason == "抽中空盒"

    balance_after_three = int(db.get_user(user)["points"])
    blocked = router.handle(message("/盲盒", "box-limit-blocked"))
    assert blocked.handled and blocked.reason == "安全限制"
    assert "上限 3 次" in blocked.replies[0]
    assert blocked.media_paths == []
    assert int(db.get_user(user)["points"]) == balance_after_three

    config = db.get_config()
    config["features"]["game_daily_blind_box_limit"] = "4"
    db.save_config(config)
    allowed = router.handle(message("/盲盒", "box-limit-fourth"))
    assert allowed.handled and allowed.reason == "抽中空盒"


def test_batch_remove_status_is_atomic_and_charges_all_layers(tmp_path):
    db = make_db(tmp_path)
    user = fund(db, 1000)
    before_balance = int(db.get_user(user)["points"])
    now = db.now()
    for _ in range(5):
        db.conn.execute(
            """insert into user_status_effects(
                 target_user_id,target_nickname,actor_user_id,actor_nickname,
                 item_name,status_text,remove_price,active,created_at)
               values(?,?,?,?,?,?,?,1,?)""",
            (UID, "测试者", "actor", "施加者", "缎带", "被红色缎带轻轻束缚", 5, now),
        )
    db.conn.commit()

    result = CommandRouter(db).handle(message("/解除状态1*5", "remove-five"))
    assert result.handled and "×5" in result.replies[0] and "25" in result.replies[0]
    assert db.get_user(user)["points"] == before_balance - 25
    assert db.list_active_statuses(user) == []


class _Browser:
    page = None


class _Adapter:
    def __init__(self):
        self.browser = _Browser()
        self.sent = []
        self.images = []

    async def send_message(self, text, group_key="main"):
        self.sent.append(text)
        return False

    async def send_image(self, path, group_key="main"):
        self.images.append(path)
        return True


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


def test_text_first_media_never_sends_image_when_text_fails(tmp_path):
    db = make_db(tmp_path)
    config = db.get_config()
    config["dzmm"]["send_delay_seconds"] = 0
    config["safety"]["global_cooldown_seconds"] = 0
    config["safety"]["max_replies_per_minute"] = 100
    config["safety"]["max_replies_per_hour"] = 100
    adapter = _Adapter()
    scheduler = BotScheduler(db, adapter, engine=None, logger=_Logger())

    async def run():
        await scheduler._send_replies(
            message("/猜乳头", "media-order"),
            ["结算文字"],
            "猜乳头",
            None,
            config,
            media_paths=["result.webp"],
            media_first=False,
        )
        await asyncio.gather(*list(scheduler.media_send_tasks))

    asyncio.run(run())
    assert adapter.sent == ["结算文字"]
    assert adapter.images == []
