from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.command_router import CommandRouter
from app.database import Database
from app.help_system import CATEGORIES, HELP_ENTRIES, validate_menu_message
from app.outgoing_text import (
    normalize_outgoing_text,
    outgoing_line_count,
    prepare_outgoing_text_sequence,
)


def make_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    config = db.get_config()
    config["features"]["newcomer_benefit_enabled"] = False
    db.save_config(config)
    return db


def message(text: str, *, user_id: str = "11111111-1111-1111-1111-111111111111") -> dict:
    return {
        "sender": "帮助测试用户",
        "platform_user_id": user_id,
        "user_id": user_id,
        "message_id": f"help-{abs(hash((text, user_id)))}",
        "group_key": "main",
        "text": text,
        "is_self": False,
    }


def assert_single_safe_menu(result) -> None:
    assert result.handled
    assert len(result.replies) == 1
    text = result.replies[0]
    assert outgoing_line_count(text) <= 10
    assert all(line.strip() for line in normalize_outgoing_text(text).split("\n"))
    assert "/下一页" not in text
    assert "/上一页" not in text
    assert "查看更多" not in text
    final = prepare_outgoing_text_sequence(result.replies)
    assert final == [normalize_outgoing_text(text)]


@pytest.mark.parametrize("command", ["/菜单", "/帮助", "/指引", "/圣殿帮助", "/教堂帮助", "/help"])
def test_root_help_aliases_are_one_real_message(tmp_path: Path, command: str) -> None:
    result = CommandRouter(make_db(tmp_path)).handle(message(command), dry_run=True)
    assert_single_safe_menu(result)
    assert "日常：" in result.replies[0]
    assert "委托：" in result.replies[0]
    assert "RP：" in result.replies[0]
    assert "管理员福袋" not in result.replies[0]


def test_direct_root_help_only_shows_private_market_entry(tmp_path: Path) -> None:
    direct = message("/帮助")
    direct.update({"source_type": "direct", "group_key": "direct:help-room", "source_group": "direct:help-room", "chatroom_id": "help-room"})

    result = CommandRouter(make_db(tmp_path)).handle(direct, dry_run=True)

    assert result.replies == ["⛪ 私聊功能菜单\n委托所：/市场帮助"]


@pytest.mark.parametrize("category", [item.key for item in CATEGORIES])
def test_every_secondary_menu_is_one_safe_message(tmp_path: Path, category: str) -> None:
    result = CommandRouter(make_db(tmp_path)).handle(message(f"/帮助 {category}"), dry_run=True)
    assert_single_safe_menu(result)


def test_menu_validator_rejects_split_pressure_blank_and_paging() -> None:
    with pytest.raises(ValueError, match="超过10行"):
        validate_menu_message("\n".join(str(index) for index in range(11)))
    with pytest.raises(ValueError, match="空白行"):
        validate_menu_message("标题\n\n内容")
    with pytest.raises(ValueError, match="翻页"):
        validate_menu_message("标题\n/下一页")


def test_primary_menu_has_exactly_eight_real_categories(tmp_path: Path) -> None:
    result = CommandRouter(make_db(tmp_path)).handle(message("/帮助"), dry_run=True)
    lines = result.replies[0].splitlines()
    assert len(CATEGORIES) == 8
    assert len(lines) == 10
    assert [line.split("：", 1)[0] for line in lines[1:9]] == [item.key for item in CATEGORIES]


def test_unified_metadata_contains_required_fields_and_unique_primary_commands() -> None:
    assert HELP_ENTRIES
    commands = [entry.command for entry in HELP_ENTRIES]
    assert len(commands) == len(set(commands))
    for entry in HELP_ENTRIES:
        assert entry.category
        assert entry.command
        assert entry.summary
        assert entry.example
        assert entry.permission
        assert entry.scope
        assert entry.order >= 0


def test_current_recommended_commands_replace_stale_main_commands(tmp_path: Path) -> None:
    router = CommandRouter(make_db(tmp_path))
    game = router.handle(message("/帮助 游戏"), dry_run=True).replies[0]
    bounty = router.handle(message("/帮助 委托"), dry_run=True).replies[0]
    assert "/裁决" in game
    assert "/六印圣裁" not in game
    assert "/需求：" in bounty
    assert "/服务：" in bounty
    assert "/发布悬赏" not in bounty
    assert "/下一页" not in bounty


def test_commission_help_uses_private_wizard_and_new_order_terms(tmp_path: Path) -> None:
    router = CommandRouter(make_db(tmp_path))
    direct = message("/委托帮助")
    direct.update({"source_type": "direct", "group_key": "direct:help-room", "source_group": "direct:help-room", "chatroom_id": "help-room"})
    result = router.handle(direct, dry_run=True)
    assert result.handled
    assert len(result.replies) == 3
    assert all(outgoing_line_count(part) <= 10 for part in result.replies)
    text = "\n".join(result.replies)
    assert "分步发布" in text
    assert "发布需求：私聊发送 /需求" in text
    assert "发布服务：私聊发送 /服务" in text
    assert "机器人将逐步询问" in text
    assert "格式：/需求：" not in text
    assert "格式：/服务：" not in text
    assert "示例：/需求：" not in text
    assert "示例：/服务：" not in text
    assert "/上一步" in text
    assert "/确认发布" in text
    assert "/取消发布" in text
    assert "/完成订单O编号" in text
    assert "/确认订单O编号" in text
    assert "原有记录保留内容" in text
    assert "/查看需求2" in text and "/查看服务2" in text
    assert "D、S、O编号" in text
    assert not router.handle(message("/悬赏帮助"), dry_run=True).handled


def test_rp_help_is_latest_flow_and_never_claims_auto_kick(tmp_path: Path) -> None:
    text = CommandRouter(make_db(tmp_path)).handle(message("/帮助 RP"), dry_run=True).replies[0]
    assert "/上皮（1/总人数）" in text
    assert "/加入" in text
    assert "/上皮（2/3）" not in text
    assert "第二次记录并通知管理员" in text
    assert "不会自动踢人" in text


def test_fortune_help_uses_current_command_and_dynamic_cost_limit(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    config = db.get_config()
    config["features"]["fortune_cost"] = 37
    config["features"]["fortune_daily_limit"] = 4
    db.save_config(config)
    text = CommandRouter(db).handle(message("/帮助 塔罗牌"), dry_run=True).replies[0]
    assert "/塔罗牌：你想占卜的内容" in text
    assert "每次消耗37功德" in text
    assert "每日最多4次" in text
    assert "玄奥" not in text


def test_nipple_help_reads_current_bet_and_calculates_all_rewards(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    config = db.get_config()
    config["features"]["nipple_guess_base_bet"] = 201
    db.save_config(config)
    text = CommandRouter(db).handle(message("/帮助 猜乳头"), dry_run=True).replies[0]
    assert "基础下注201功德" in text
    assert "返还总额301功德" in text
    assert "返还总额603功德" in text
    assert "成功概率1/2" in text
    assert "成功概率1/3" in text


def test_theft_help_reads_current_rate_and_explains_bribe_destruction(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    config = db.get_config()
    config["features"]["theft_daily_limit"] = 3
    config["features"]["theft_success_rate"] = 41
    db.save_config(config)
    text = CommandRouter(db).handle(message("/帮助 偷窃"), dry_run=True).replies[0]
    assert "成功率41%" in text
    assert "每天最多尝试3次" in text
    assert "不超过10功德：不收贿赂" in text
    assert "超过10功德：收取10%，向下取整" in text
    assert "贿赂直接销毁" in text


def test_item_help_has_real_quantity_syntax_and_current_stocking_guidance(tmp_path: Path) -> None:
    text = CommandRouter(make_db(tmp_path)).handle(message("/帮助 物品"), dry_run=True).replies[0]
    assert "/购买编号×数量" in text
    assert "/兑换仓库" in text
    assert "丝袜可购买或掉落" in text
    assert "99个兑换内容" in text


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ("/功德帮助", "日常与功德"),
        ("/仓库帮助", "商店与物品"),
        ("/试炼帮助", "游戏娱乐"),
        ("/契约帮助", "AI与互动"),
        ("/群规帮助", "规则与帮助"),
        ("/互动帮助", "AI与互动"),
    ],
)
def test_legacy_help_aliases_are_compatibility_entries(tmp_path: Path, legacy: str, expected: str) -> None:
    result = CommandRouter(make_db(tmp_path)).handle(message(legacy), dry_run=True)
    assert_single_safe_menu(result)
    assert expected in result.replies[0]


def test_unknown_help_and_latest_error_examples(tmp_path: Path) -> None:
    router = CommandRouter(make_db(tmp_path))
    unknown = router.handle(message("/帮助 不存在"), dry_run=True)
    assert unknown.replies == ["没有找到该帮助分类，请发送 /帮助 查看当前菜单。"]
    rp_error = router.handle(message("/上皮（2/3）"), dry_run=True)
    assert "发起RP结界请从1开始" in rp_error.replies[0]
    assert "/加入" in rp_error.replies[0]
    tarot_error = router.handle(message("/塔罗牌"), dry_run=True)
    assert "/塔罗牌：" in tarot_error.replies[0]


def test_admin_help_is_hidden_from_users_and_visible_to_admin(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    router = CommandRouter(db)
    normal = router.handle(message("/帮助 管理员"), dry_run=True)
    assert "没有找到该帮助分类" in normal.replies[0]
    admin_id = "22222222-2222-2222-2222-222222222222"
    db.ensure_user(message("/帮助", user_id=admin_id))
    db.conn.execute("update users set is_admin=1 where platform_user_id=?", (admin_id,))
    db.conn.commit()
    admin = router.handle(message("/帮助 管理员", user_id=admin_id), dry_run=True)
    assert_single_safe_menu(admin)
    assert "/管理员福袋" in admin.replies[0]
    assert "RP" in admin.replies[0]


def test_help_routes_do_not_create_users_or_change_balances(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    before_users = db.conn.execute("select count(*) from users").fetchone()[0]
    before_transactions = db.conn.execute("select count(*) from transactions").fetchone()[0]
    router = CommandRouter(db)
    for command in ("/帮助", "/帮助 悬赏", "/帮助 RP", "/帮助 猜乳头"):
        assert router.handle(message(command), dry_run=False).handled
    assert db.conn.execute("select count(*) from users").fetchone()[0] == before_users
    assert db.conn.execute("select count(*) from transactions").fetchone()[0] == before_transactions
