from __future__ import annotations

import asyncio

import pytest

from app.command_router import CommandRouter, SIX_SEAL_FEATURES
from app.database import Database
from app.outgoing_text import (
    AI_MAX_OUTGOING_LINES,
    MAX_OUTGOING_CHARS,
    MAX_OUTGOING_LINES,
    normalize_outgoing_text,
    outgoing_line_count,
    prepare_outgoing_text_messages,
    prepare_outgoing_text_sequence,
)
from app.rule_engine import RuleEngine
from app.scheduler import BotScheduler


class FakeBrowser:
    page = None


class FakeAdapter:
    def __init__(self, *, fail_text_at: int | None = None, fail_image: bool = False):
        self.browser = FakeBrowser()
        self.fail_text_at = fail_text_at
        self.fail_image = fail_image
        self.sent: list[str] = []
        self.images: list[str] = []
        self.direct: list[tuple[str, str]] = []

    async def send_message(self, text: str, group_key: str = "main") -> bool:
        self.sent.append(text)
        return self.fail_text_at != len(self.sent)

    async def send_image(self, path: str, group_key: str = "main") -> bool:
        self.images.append(path)
        return not self.fail_image

    async def send_direct_message(self, chatroom_id: str, text: str) -> bool:
        self.direct.append((chatroom_id, text))
        return True


class FakeLogger:
    def __init__(self):
        self.entries: list[tuple[str, str]] = []

    def info(self, message, kind="normal"):
        self.entries.append(("info", str(message)))

    def warning(self, message, kind="normal"):
        self.entries.append(("warning", str(message)))

    def error(self, message, kind="error"):
        self.entries.append(("error", str(message)))


def make_db(tmp_path) -> Database:
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    config = db.get_config()
    config["dzmm"]["send_delay_seconds"] = 0
    config["safety"]["night_silence_enabled"] = False
    config["safety"]["max_replies_per_minute"] = 1000
    config["safety"]["max_replies_per_hour"] = 1000
    db.save_config(config)
    return db


def make_scheduler(db: Database, adapter: FakeAdapter | None = None):
    adapter = adapter or FakeAdapter()
    scheduler = BotScheduler(db, adapter, engine=None, logger=FakeLogger())
    return scheduler, adapter, db.get_config()


def message(text: str = "/测试", message_id: str = "outgoing-test") -> dict:
    return {
        "message_id": message_id,
        "platform_user_id": "outgoing-user-id",
        "user_id": "outgoing-user-id",
        "sender": "输出测试者",
        "text": text,
        "time": "12:00:00",
        "is_self": False,
        "raw_html": "",
        "group_key": "main",
    }


def send_final(
    db: Database,
    replies: list[str],
    *,
    adapter=None,
    media_paths=None,
    media_refund_inventory_id=None,
):
    scheduler, adapter, config = make_scheduler(db, adapter)
    async def run():
        await scheduler._send_replies(
            message(),
            replies,
            "输出测试",
            None,
            config,
            media_paths=media_paths,
            media_refund_inventory_id=media_refund_inventory_id,
        )
        if scheduler.media_send_tasks:
            await asyncio.gather(*list(scheduler.media_send_tasks))
    asyncio.run(run())
    return scheduler, adapter


@pytest.mark.parametrize(
    ("line_total", "message_total"),
    [(1, 1), (9, 1), (10, 2), (18, 2), (30, 2)],
)
def test_prepare_outgoing_text_boundary_counts(line_total, message_total):
    result = prepare_outgoing_text_messages(
        "\n".join(f"第{index}行" for index in range(1, line_total + 1)),
        max_lines=AI_MAX_OUTGOING_LINES,
    )
    assert len(result) == message_total
    assert all(outgoing_line_count(part) <= AI_MAX_OUTGOING_LINES for part in result)


def test_windows_newlines_and_repeated_blank_lines_are_normalized():
    text = "\r\n第一行\r\n\r\n\r\n第二行\r\n"
    assert normalize_outgoing_text(text) == "第一行\n\n第二行"
    assert prepare_outgoing_text_messages(text) == ["第一行\n\n第二行"]


def test_split_keeps_complete_lines_order_and_never_creates_empty_or_third_message():
    original = [f"完整句子{index}。" for index in range(1, 101)]
    result = prepare_outgoing_text_messages("\n".join(original))
    assert len(result) == 2
    assert all(result)
    assert all(outgoing_line_count(part) <= MAX_OUTGOING_LINES for part in result)
    combined = "\n".join(result)
    retained = [sentence for sentence in original if sentence in combined]
    positions = [combined.index(sentence) for sentence in retained]
    assert retained == original[:len(retained)]
    assert positions == sorted(positions)
    assert original[-1] not in combined
    assert combined.endswith("...")


def test_existing_two_part_reply_is_not_duplicated():
    assert prepare_outgoing_text_sequence(["第一条", "第二条"]) == ["第一条", "第二条"]


def test_character_and_line_limits_never_create_third_page():
    result = prepare_outgoing_text_messages(
        "很长的回复" * 600, max_lines=AI_MAX_OUTGOING_LINES
    )
    assert len(result) == 2
    assert all(len(part) <= MAX_OUTGOING_CHARS for part in result)
    assert all(outgoing_line_count(part) <= AI_MAX_OUTGOING_LINES for part in result)
    assert result[-1].endswith("...")


def test_markdown_spaces_and_repeated_symbols_are_compacted():
    normalized = normalize_outgoing_text("### 标题\n\n\n**内容**    保留 😊\n~~~~~~~")
    assert "###" not in normalized
    assert "**" not in normalized
    assert "    " not in normalized
    assert "~~~~" not in normalized
    assert "😊" in normalized


def test_standalone_link_remains_the_second_standalone_message():
    link = "https://www.dzmm.ai/invite/D7ZlMdAT"
    result = prepare_outgoing_text_sequence(
        ["\n".join(f"悬赏字段{i}" for i in range(8)), "前往悬赏群查看。", link]
    )
    assert len(result) == 2
    assert result[-1] == link


def test_scheduler_records_and_limits_each_actual_text_send(tmp_path):
    db = make_db(tmp_path)
    _, adapter = send_final(db, ["\n".join(f"行{i}" for i in range(11))])
    assert len(adapter.sent) == 2
    assert db.count_recent_replies(60) == 2
    assert all(outgoing_line_count(part) <= MAX_OUTGOING_LINES for part in adapter.sent)


def test_image_action_is_unchanged(tmp_path):
    db = make_db(tmp_path)
    _, adapter = send_final(db, ["文字说明"], media_paths=["示例.webp"])
    assert adapter.sent == ["文字说明"]
    assert adapter.images == ["示例.webp"]


def test_direct_source_reply_and_guidance_delivery_stay_in_direct_rooms(tmp_path):
    db = make_db(tmp_path)
    scheduler, adapter, config = make_scheduler(db)
    direct_message = {
        **message("/查看服务", "direct-source"),
        "source_type": "direct",
        "chatroom_id": "source-room",
        "group_key": "direct:source-room",
        "source_group": "direct:source-room",
    }

    asyncio.run(
        scheduler._send_replies(
            direct_message,
            ["私聊查询结果"],
            "查看服务",
            None,
            config,
            direct_deliveries=[{"chatroom_id": "guide-room", "text": "私聊指引"}],
        )
    )

    assert adapter.sent == []
    assert adapter.direct == [
        ("source-room", "私聊查询结果"),
        ("guide-room", "私聊指引"),
    ]


def test_failed_part_uses_existing_failure_counter_and_pause(tmp_path):
    db = make_db(tmp_path)
    adapter = FakeAdapter(fail_text_at=1)
    scheduler, _ = send_final(db, ["\n".join(f"行{i}" for i in range(11))], adapter=adapter)
    scheduler.fail_count = 2
    adapter.fail_text_at = 2
    asyncio.run(
        scheduler._send_replies(
            message(message_id="failure-test"),
            ["仍会失败"],
            "失败测试",
            None,
            db.get_config(),
        )
    )
    assert len(adapter.sent) == 2
    assert scheduler.paused is True
    assert scheduler.auto_resume_at > 0


def test_image_failure_does_not_pause_or_increment_text_counter(tmp_path):
    db = make_db(tmp_path)
    scheduler, adapter = send_final(
        db,
        ["游戏结算文字"],
        adapter=FakeAdapter(fail_image=True),
        media_paths=["失败图片.webp"],
    )
    assert adapter.images == ["失败图片.webp"]
    assert adapter.sent == ["游戏结算文字"]
    assert scheduler.image_fail_count == 1
    assert scheduler.fail_count == 0
    assert scheduler.paused is False


def test_failed_inventory_image_send_restores_consumed_item(tmp_path):
    db = make_db(tmp_path)
    user = db.ensure_user(message())
    db._grant_inventory_no_commit(user, "测试图库物品", 1)
    db.conn.commit()
    inventory = db.conn.execute(
        "select id from inventory where user_id=? and item_name=?",
        ("outgoing-user-id", "测试图库物品"),
    ).fetchone()
    inventory_id = int(inventory["id"])
    db.conn.execute("update inventory set quantity=0 where id=?", (inventory_id,))
    db.conn.commit()

    send_final(
        db,
        ["图库物品说明"],
        adapter=FakeAdapter(fail_image=True),
        media_paths=["失败图片.webp"],
        media_refund_inventory_id=inventory_id,
    )

    quantity = db.conn.execute(
        "select quantity from inventory where id=?", (inventory_id,)
    ).fetchone()["quantity"]
    assert quantity == 1


def test_temporary_text_pause_can_resume_automatically(tmp_path):
    db = make_db(tmp_path)
    scheduler, _, _ = make_scheduler(db)
    scheduler.pause("测试自动恢复", auto_resume_seconds=5)
    scheduler.auto_resume_at = 0.1
    scheduler._resume_if_due()
    assert scheduler.paused is False
    assert db.get_config()["dzmm"]["bot_enabled"] is True


def test_actual_command_outputs_reach_platform_within_limit(tmp_path):
    db = make_db(tmp_path)
    for index in range(1, 16):
        db.upsert_shop_item(
            {
                "name": f"测试商品{index}",
                "description": "紧凑说明",
                "price": index,
                "stock": 99,
                "enabled": True,
                "sort_order": index,
            }
        )
    router = CommandRouter(db)
    db.create_rule(
        {
            "name": "测试菜单",
            "trigger_type": "exact",
            "trigger_value": "/菜单",
            "reply_content": "\n".join(f"菜单项目{index}" for index in range(1, 22)),
            "priority": 100,
        }
    )
    engine = RuleEngine(db)
    menu_message = message("/菜单", "menu-command")
    hit = engine.match_rules(menu_message, menu_message["sender"])[0]
    _, adapter = send_final(db, engine.pick_replies(hit["rule"], menu_message))
    assert len(adapter.sent) == 2
    assert all(outgoing_line_count(part) <= MAX_OUTGOING_LINES for part in adapter.sent)

    commands = ["/神殿仓库", "/兑换仓库", "/背包", "/我的状态"]
    for index, command in enumerate(commands):
        result = router.handle(message(command, f"command-{index}"), dry_run=True)
        assert result.handled, command
        _, adapter = send_final(db, result.replies)
        assert 1 <= len(adapter.sent) <= 2, command
        assert all(outgoing_line_count(part) <= MAX_OUTGOING_LINES for part in adapter.sent), command

    bounty_message = {**message("/查看需求", "bounty-list"), "group_key": "bounty"}
    bounty = router.handle(bounty_message, dry_run=False)
    _, adapter = send_final(db, bounty.replies)
    assert 1 <= len(adapter.sent) <= 2
    assert all(outgoing_line_count(part) <= MAX_OUTGOING_LINES for part in adapter.sent)


def test_six_seal_start_and_ai_long_reply_final_output(tmp_path):
    db = make_db(tmp_path)
    config = db.get_config()
    config["features"] = {
        **config.get("features", {}),
        **SIX_SEAL_FEATURES,
        "currency_name": "功德点",
        "game_limit_enabled": "false",
    }
    db.save_config(config)
    actor = message("/六印圣裁", "six-seal")
    user = db.ensure_user(actor)
    db.add_points(user, 500, "测试准备")
    router = CommandRouter(db)
    result = router.handle(actor)
    _, adapter = send_final(db, result.replies)
    assert "/加入" in "\n".join(adapter.sent)
    assert all(outgoing_line_count(part) <= MAX_OUTGOING_LINES for part in adapter.sent)

    ai_reply = "\n".join(f"AI完整句子{index}。" for index in range(1, 31))
    _, adapter = send_final(db, [ai_reply])
    assert len(adapter.sent) == 2
    assert all(outgoing_line_count(part) <= MAX_OUTGOING_LINES for part in adapter.sent)
    combined = "\n".join(adapter.sent)
    assert "AI完整句子1。" in combined
    assert "AI完整句子30。" not in combined
    assert combined.endswith("...")
