from __future__ import annotations

import sys
import re
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai_interaction import AIInteractionError
from app.command_router import CommandRouter
from app.database import Database
from app.rule_engine import RuleEngine


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    config = db.get_config()
    config["features"]["newcomer_benefit_enabled"] = False
    db.save_config(config)
    return db


def make_confirmed_user(db, nickname: str, number: int):
    return db.ensure_user(
        {
            "sender": nickname,
            "platform_user_id": f"00000000-0000-0000-0000-{number:012d}",
            "user_id": f"00000000-0000-0000-0000-{number:012d}",
            "avatar_id": f"10000000-0000-0000-0000-{number:012d}",
            "message_id": f"confirmed-user-{number}",
        }
    )


def configure_paid_interaction_loss(db, number: int):
    recipient = make_confirmed_user(db, "大祭司账户", number)
    config = db.get_config()
    config["features"]["church_theme_version"] = "1"
    config["features"]["paid_interaction_loss_amount"] = 10
    config["features"]["paid_interaction_loss_recipient_user_id"] = recipient[
        "platform_user_id"
    ]
    db.save_config(config)
    return recipient


def allow_games_all_day(db, **features):
    config = db.get_config()
    config["features"] = {
        **config.get("features", {}),
        "game_open_windows": "00:00-23:59",
        **features,
    }
    db.save_config(config)


def make_engine(tmp_path):
    db = make_db(tmp_path)
    engine = RuleEngine(db)
    return db, engine


def test_exact_command_match(tmp_path):
    db, engine = make_engine(tmp_path)
    db.create_rule(
        {
            "name": "测试",
            "trigger_type": "exact",
            "trigger_value": "/测试",
            "reply_content": "机器人在线",
            "priority": 10,
        }
    )
    hits = engine.match_rules({"sender": "张三", "text": "/测试", "is_self": False}, "张三")
    assert any(h["rule"]["name"] == "测试" for h in hits)
    assert not engine.match_rules({"sender": "张三", "text": "测试", "is_self": False}, "张三")


def test_exact_command_match_supports_multiple_triggers(tmp_path):
    db, engine = make_engine(tmp_path)
    db.create_rule(
        {
            "name": "菜单",
            "trigger_type": "exact",
            "trigger_value": "/菜单，/帮助,/教程",
            "reply_content": "圣殿菜单",
            "priority": 10,
        }
    )

    for text in ["/菜单", "/帮助", "/教程"]:
        hits = engine.match_rules({"sender": "张三", "text": text, "is_self": False}, "张三")
        assert any(h["rule"]["name"] == "菜单" for h in hits)

    assert not engine.match_rules({"sender": "张三", "text": "/菜单123", "is_self": False}, "张三")


def test_builtin_help_overrides_stale_custom_rule(tmp_path):
    db = make_db(tmp_path)
    db.create_rule(
        {
            "name": "自定义帮助",
            "trigger_type": "exact",
            "trigger_value": "/帮助",
            "reply_content": "自定义菜单",
            "priority": 10,
        }
    )
    router = CommandRouter(db)

    result = router.handle({"sender": "张三", "text": "/帮助"})

    assert result.handled
    assert result.name == "帮助"
    assert "圣堂功能菜单" in result.replies[0]
    assert "自定义菜单" not in result.replies[0]


def test_update_rule_keeps_group_when_group_omitted(tmp_path):
    db = make_db(tmp_path)
    rule_id = db.create_rule(
        {
            "name": "菜单",
            "group_name": "教堂命令",
            "trigger_type": "exact",
            "trigger_value": "/菜单",
            "reply_content": "旧菜单",
        }
    )

    db.update_rule(
        rule_id,
        {
            "name": "菜单",
            "trigger_type": "exact",
            "trigger_value": "/菜单，/帮助",
            "reply_content": "新菜单",
        },
    )

    rule = next(item for item in db.list_rules() if item["id"] == rule_id)
    assert rule["group_name"] == "教堂命令"
    assert rule["reply_content"] == "新菜单"


def test_render_reply_variables(tmp_path):
    _, engine = make_engine(tmp_path)
    text = engine.render_reply("你好，{user}{newline}{random:收到|在的}", {"user": "张三", "message": "你好", "count": 1})
    assert text.startswith("你好，张三\n")


def test_ai_status_reply_does_not_block_legacy_custom_rule_cooldown(tmp_path):
    db, engine = make_engine(tmp_path)
    rule_id = db.create_rule(
        {
            "name": "legacy-command",
            "trigger_type": "exact",
            "trigger_value": "/character",
            "reply_content": "character profile",
            "global_cooldown_seconds": 2,
        }
    )
    db.conn.execute(
        "update rules set rule_cooldown_seconds=0, global_cooldown_seconds=2 where id=?",
        (rule_id,),
    )
    db.conn.commit()
    rule = next(item for item in db.list_rules() if item["id"] == rule_id)
    message = {"message_id": "ai-request", "sender": "alice", "text": "/character"}

    db.record_reply("ai-request", None, message, "thinking status", True)
    assert engine.check_cooldown(rule, message)[0] is False

    engine.update_rule_hit(rule, message, "exact")
    assert engine.check_cooldown(rule, message)[0] is True


def test_ai_router_runs_custom_rule_after_status_reply(tmp_path):
    db = make_db(tmp_path)
    rule_id = db.create_rule(
        {
            "name": "profile-command",
            "trigger_type": "exact",
            "trigger_value": "/profile",
            "reply_content": "profile content",
            "global_cooldown_seconds": 2,
        }
    )
    db.conn.execute(
        "update rules set rule_cooldown_seconds=0, global_cooldown_seconds=2 where id=?",
        (rule_id,),
    )
    db.conn.commit()
    message = {"message_id": "ai-profile", "sender": "alice", "text": "/profile"}
    db.record_reply("ai-profile", None, message, "thinking status", True)

    result = CommandRouter(db).handle_ai_command(message)

    assert result.handled is True
    assert result.replies == ["profile content"]


def test_legacy_global_cooldown_data_is_migrated_to_rule_scope(tmp_path):
    db = make_db(tmp_path)
    rule_id = db.create_rule(
        {
            "name": "legacy-data",
            "trigger_type": "exact",
            "trigger_value": "/legacy",
            "reply_content": "ok",
        }
    )
    db.conn.execute(
        "update rules set rule_cooldown_seconds=0, global_cooldown_seconds=2 where id=?",
        (rule_id,),
    )
    db.conn.commit()

    db._migrate_legacy_rule_cooldowns()

    row = db.conn.execute(
        "select rule_cooldown_seconds, global_cooldown_seconds from rules where id=?",
        (rule_id,),
    ).fetchone()
    assert tuple(row) == (2, 0)


def test_self_message_ignored_by_default(tmp_path):
    db, engine = make_engine(tmp_path)
    db.create_rule(
        {
            "name": "自测",
            "trigger_type": "exact",
            "trigger_value": "/测试",
            "reply_content": "ok",
        }
    )
    assert not engine.match_rules({"sender": "我", "text": "/测试", "is_self": True}, "我")


def test_checkin_command_creates_user_data(tmp_path):
    db = make_db(tmp_path)
    router = CommandRouter(db)
    result = router.handle({"sender": "张三", "text": "/签到"})
    assert result.handled
    assert "完成今日祈福" in result.replies[0]
    user = db.get_user("张三")
    assert user is not None
    assert user["points"] == 10
    assert user["total_checkins"] == 1


def test_repeat_checkin_does_not_reward_twice(tmp_path):
    db = make_db(tmp_path)
    router = CommandRouter(db)
    router.handle({"sender": "张三", "text": "/签到"})
    result = router.handle({"sender": "张三", "text": "/签到"})
    assert "已经祈福" in result.replies[0]
    assert db.get_user("张三")["points"] == 10


def test_checkin_dry_run_does_not_create_user(tmp_path):
    db = make_db(tmp_path)
    router = CommandRouter(db)
    result = router.handle({"sender": "预览用户", "text": "/签到"}, dry_run=True)
    assert result.handled
    assert "签到预览" in result.reason
    assert db.get_user("预览用户") is None


def test_shop_purchase_moves_item_to_inventory(tmp_path):
    db = make_db(tmp_path)
    db.upsert_shop_item({"name": "徽章", "description": "测试商品", "price": 5, "stock": 1, "enabled": True})
    db.add_points("李四", 10, "测试发放")
    router = CommandRouter(db)
    result = router.handle({"sender": "李四", "text": "/购买 徽章"})
    assert result.handled
    assert "神殿仓库领取" in result.replies[0]
    assert db.get_user("李四")["points"] == 5
    assert db.get_inventory("李四")[0]["item_name"] == "徽章"


def test_admin_only_rule_uses_user_admin_flag(tmp_path):
    db, engine = make_engine(tmp_path)
    db.create_rule(
        {
            "name": "管理员命令",
            "trigger_type": "exact",
            "trigger_value": "/管理",
            "reply_content": "ok",
            "require_admin": True,
            "group_name": "管理员命令",
        }
    )
    normal_id = "11111111-1111-1111-1111-111111111111"
    admin_id = "22222222-2222-2222-2222-222222222222"
    db.ensure_user({"sender": "普通用户", "user_id": normal_id})
    admin = db.ensure_user({"sender": "管理员", "user_id": admin_id})
    db.update_user(admin_id, {**admin, "is_admin": True})

    assert not engine.match_rules({"sender": "普通用户", "user_id": normal_id, "text": "/管理", "is_self": False}, "普通用户")
    assert engine.match_rules({"sender": "管理员", "user_id": admin_id, "text": "/管理", "is_self": False}, "管理员")


def test_purchase_by_shop_number(tmp_path):
    db = make_db(tmp_path)
    db.upsert_shop_item({"name": "项圈", "description": "", "price": 6, "stock": -1, "enabled": True, "sort_order": 10})
    db.add_points("张三", 10, "测试发放")
    router = CommandRouter(db)
    result = router.handle({"sender": "张三", "text": "/购买1"})
    assert result.handled
    assert "项圈" in result.replies[0]
    assert db.get_inventory("张三")[0]["item_name"] == "项圈"


def test_use_inventory_item_adds_target_status(tmp_path):
    db = make_db(tmp_path)
    db.upsert_shop_item({
        "name": "项圈",
        "price": 1,
        "stock": -1,
        "enabled": True,
        "use_reply_template": "{actor}把{item}套在了{target}的脖子上！",
        "status_template": "被{actor}套上了{item}",
        "remove_price": 5,
    })
    db.add_points("张三", 10, "测试发放")
    db.ensure_user("李四")
    db.set_display_name("李四", "大祭司")
    router = CommandRouter(db)
    router.handle({"sender": "张三", "text": "/购买1"})
    result = router.handle({"sender": "张三", "text": "/对大祭司使用物品1"})
    assert result.handled
    assert "套在了大祭司" in result.replies[0]
    status = db.list_active_statuses("李四")[0]
    assert status["status_text"] == "被张三套上了项圈"


def test_use_inventory_item_can_target_platform_nickname(tmp_path):
    db = make_db(tmp_path)
    db.upsert_shop_item({
        "name": "项圈",
        "price": 1,
        "stock": -1,
        "enabled": True,
        "use_reply_template": "{actor}把{item}套在了{target}的脖子上！",
        "status_template": "被{actor}套上了{item}",
        "remove_price": 5,
    })
    db.add_points("张三", 10, "测试发放")
    db.ensure_user("李四")
    db.set_display_name("李四", "大祭司")
    router = CommandRouter(db)

    router.handle({"sender": "张三", "text": "/购买1"})
    result = router.handle({"sender": "张三", "text": "/对李四使用物品1"})

    assert result.handled
    assert "套在了大祭司" in result.replies[0]
    status = db.list_active_statuses("李四")[0]
    assert status["status_text"] == "被张三套上了项圈"


def test_use_inventory_item_can_target_nickname_history(tmp_path):
    db = make_db(tmp_path)
    db.upsert_shop_item({
        "name": "项圈",
        "price": 1,
        "stock": -1,
        "enabled": True,
        "use_reply_template": "{actor}把{item}套在了{target}的脖子上！",
        "status_template": "被{actor}套上了{item}",
        "remove_price": 5,
    })
    db.add_points("张三", 10, "测试发放")
    target = db.ensure_user("新昵称")
    db.update_user("新昵称", {**target, "nickname_history": "旧昵称"})
    router = CommandRouter(db)

    router.handle({"sender": "张三", "text": "/购买1"})
    result = router.handle({"sender": "张三", "text": "/对旧昵称使用物品1"})

    assert result.handled
    assert "套在了新昵称" in result.replies[0]
    assert db.list_active_statuses("新昵称")[0]["status_text"] == "被张三套上了项圈"


def test_profile_includes_statuses(tmp_path):
    db = make_db(tmp_path)
    db.ensure_user("李四")
    db.set_display_name("李四", "大祭司")
    db.conn.execute(
        """
        insert into user_status_effects(target_nickname, actor_nickname, item_name, status_text, remove_price, active, created_at)
        values('李四', '张三', '项圈', '被张三套上了项圈', 5, 1, ?)
        """,
        (db.now(),),
    )
    db.conn.commit()
    router = CommandRouter(db)
    result = router.handle({"sender": "李四", "text": "/我"})
    assert result.handled
    assert "我的称呼：大祭司" in result.replies[0]
    assert "被张三套上了项圈" in result.replies[0]


def test_duplicate_statuses_are_grouped_but_removed_one_at_a_time(tmp_path):
    db = make_db(tmp_path)
    db.ensure_user("李四")
    for _ in range(3):
        db.conn.execute(
            """insert into user_status_effects(
                 target_nickname,actor_nickname,item_name,status_text,remove_price,active,created_at)
               values('李四','张三','魔法鞭子','被张三抽打后留下了一条鞭痕',0,1,?)""",
            (db.now(),),
        )
    db.conn.commit()
    router = CommandRouter(db)

    profile = router.handle({"sender": "李四", "text": "/我"})
    status = router.handle({"sender": "李四", "text": "/我的状态"})
    removed = router.handle({"sender": "李四", "text": "/解除状态1"})
    after = router.handle({"sender": "李四", "text": "/我的状态"})

    assert "鞭痕 ×3" in profile.replies[0]
    assert "鞭痕 ×3" in status.replies[0]
    assert "已解除状态" in removed.replies[0]
    assert len(db.list_active_statuses("李四")) == 2
    assert "鞭痕 ×2" in after.replies[0]


def test_admin_red_packet_claims_integer_amounts(tmp_path):
    db = make_db(tmp_path)
    admin = db.ensure_user("管理员")
    db.update_user("管理员", {**admin, "is_admin": True})
    router = CommandRouter(db)
    created = router.handle({"sender": "管理员", "text": "/发送10金币红包3个"})
    assert created.handled
    amounts = []
    for name in ["甲", "乙", "丙"]:
        result = router.handle({"sender": name, "text": "/抢红包"})
        assert result.handled
        amounts.append(db.get_user(name)["points"])
    assert sum(amounts) == 10
    assert "福袋已经领完" in router.handle({"sender": "丁", "text": "/抢红包"}).replies[0]


def test_admin_red_packet_supports_compact_amount_count_format(tmp_path):
    db = make_db(tmp_path)
    admin = db.ensure_user("管理员")
    db.update_user("管理员", {**admin, "is_admin": True})
    router = CommandRouter(db)

    created = router.handle({"sender": "管理员", "text": "/发红包100金币10个"})

    assert created.handled
    assert "100" in created.replies[0]
    assert "10" in created.replies[0]


def test_red_packet_send_explains_admin_only(tmp_path):
    db = make_db(tmp_path)
    router = CommandRouter(db)

    result = router.handle({"sender": "普通用户", "text": "/发红包100金币10个"})

    assert result.handled
    assert "管理员命令" in result.replies[0]


def test_admin_can_give_points_by_display_name(tmp_path):
    db = make_db(tmp_path)
    admin = db.ensure_user("管理员")
    db.update_user("管理员", {**admin, "is_admin": True})
    target = db.ensure_user("李四")
    db.set_display_name(target, "大祭司")
    router = CommandRouter(db)

    result = router.handle({"sender": "管理员", "text": "/赠送大祭司100"})

    assert result.handled
    assert "大祭司" in result.replies[0]
    assert "100" in result.replies[0]
    assert db.get_user("李四")["points"] == 100


def test_give_points_is_admin_only(tmp_path):
    db = make_db(tmp_path)
    target = db.ensure_user("李四")
    db.set_display_name(target, "大祭司")
    router = CommandRouter(db)

    result = router.handle({"sender": "普通用户", "text": "/赠送大祭司100"})

    assert result.handled
    assert "管理员命令" in result.replies[0]
    assert db.get_user("李四")["points"] == 0


def test_give_points_target_not_found(tmp_path):
    db = make_db(tmp_path)
    admin = db.ensure_user("管理员")
    db.update_user("管理员", {**admin, "is_admin": True})
    router = CommandRouter(db)

    result = router.handle({"sender": "管理员", "text": "/赠送大祭司100"})

    assert result.handled
    assert "没有找到" in result.replies[0]


def test_admin_can_fine_by_original_nickname_with_extra_spaces(tmp_path):
    db = make_db(tmp_path)
    admin = db.ensure_user("管理员")
    db.update_user("管理员", {**admin, "is_admin": True})
    target = db.ensure_user("念辞槐")
    db.set_display_name(target, "大祭司")
    db.conn.execute("update users set points=20 where id=?", (target["id"],))
    db.conn.commit()
    router = CommandRouter(db)

    result = router.handle({"sender": "管理员", "text": "/罚款  念　辞 槐   5"})

    assert result.handled
    assert result.name == "罚款"
    assert "大祭司" in result.replies[0]
    assert "5" in result.replies[0]
    assert db.get_user("念辞槐")["points"] == 15


def test_admin_can_fine_by_custom_title_and_traditional_command(tmp_path):
    db = make_db(tmp_path)
    admin = db.ensure_user("管理员")
    db.update_user("管理员", {**admin, "is_admin": True})
    target = db.ensure_user("李四")
    db.set_display_name(target, "大祭司")
    db.conn.execute("update users set points=10 where id=?", (target["id"],))
    db.conn.commit()
    router = CommandRouter(db)

    result = router.handle({"sender": "管理员", "text": "/罰款  大 祭 司  5"})

    assert result.handled
    assert db.get_user("李四")["points"] == 5


def test_fine_points_is_admin_only(tmp_path):
    db = make_db(tmp_path)
    target = db.ensure_user("李四")
    db.conn.execute("update users set points=10 where id=?", (target["id"],))
    db.conn.commit()
    router = CommandRouter(db)

    result = router.handle({"sender": "普通用户", "text": "/罚款李四5"})

    assert result.handled
    assert "管理员命令" in result.replies[0]
    assert db.get_user("李四")["points"] == 10


def test_target_lookup_supports_nickname_title_history_and_unicode_whitespace(tmp_path):
    db = make_db(tmp_path)
    target = db.ensure_user("念 辞槐")
    db.set_display_name(target, "青巫妈咪的小狗")

    assert db.find_user_by_display_name(" 念　辞 槐 ")["id"] == target["id"]
    assert db.find_user_by_display_name(" 青巫妈咪 的 小狗 ")["id"] == target["id"]


def test_daily_paid_interaction_ranking_counts_targets_and_orders_ties(tmp_path):
    db = make_db(tmp_path)
    target_a = make_confirmed_user(db, "目标甲", 801)
    target_b = make_confirmed_user(db, "目标乙", 802)
    target_c = make_confirmed_user(db, "目标丙", 803)
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    def add_transaction(user, created_at, reason="发起人向目标发起AI付费互动"):
        db.conn.execute(
            "insert into transactions(user_id,nickname,change_amount,reason,balance_after,created_at) "
            "values(?,?,?,?,?,?)",
            (
                user["platform_user_id"],
                user["nickname"],
                50,
                reason,
                50,
                created_at,
            ),
        )

    add_transaction(target_a, f"{today} 09:00:00")
    add_transaction(target_a, f"{today} 10:00:00")
    add_transaction(target_b, f"{today} 09:30:00")
    add_transaction(target_b, f"{today} 11:00:00")
    add_transaction(target_c, f"{today} 08:00:00")
    for minute in range(5):
        add_transaction(target_c, f"{yesterday} 12:0{minute}:00")
    add_transaction(target_c, f"{today} 12:00:00", reason="付费互动正常损耗")
    db.conn.commit()

    for command in ("/互动排行榜", "/每日互动榜", "/互动榜"):
        result = CommandRouter(db).handle({"sender": "查看者", "text": command})
        assert result.handled
        assert result.name == "互动排行榜"
        reply = result.replies[0]
        assert f"{today}｜按今日成功被互动次数排名" in reply
        assert "1. 目标乙—2次" in reply
        assert "2. 目标甲—2次" in reply
        assert "3. 目标丙—1次" in reply
        assert "脸热" in reply
        assert "暧昧" in reply


def test_daily_paid_interaction_ranking_empty_reply(tmp_path):
    db = make_db(tmp_path)

    result = CommandRouter(db).handle(
        {"sender": "查看者", "text": "/互动排行榜"}
    )

    assert result.handled
    assert "今天还没有成功的付费互动" in result.replies[0]


def test_paid_interaction_calls_ai_then_transfers_fixed_amount(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    sender = make_confirmed_user(db, "发起者", 1)
    target = make_confirmed_user(db, "念辞槐", 2)
    loss_recipient = configure_paid_interaction_loss(db, 901)
    db.set_display_name(target, "圣女")
    db.set_paid_interaction_enabled(target, True)
    db.set_secret("deepseek_api_key", "test-key")
    config = db.get_config()
    config["features"]["church_theme_version"] = "1"
    config["features"]["paid_interaction_amount"] = 60
    db.save_config(config)
    monkeypatch.setattr(
        "app.command_router.DeepSeekClient.generate",
        lambda self, **kwargs: "AI 生成的互动正文",
    )
    router = CommandRouter(db)

    result = router.handle(
        {"sender": "发起者", "text": "/对圣　女发起互动：唱一首歌"}
    )

    assert result.handled
    assert result.name == "付费互动"
    assert result.replies[0].startswith("AI 生成的互动正文")
    assert "圣女" in result.replies[0]
    assert "60" in result.replies[0]
    assert "正常损耗 10" in result.replies[0]
    assert "实际到账 50" in result.replies[0]
    assert db.get_user(sender)["points"] == -60
    assert db.get_user(target)["points"] == 50
    assert db.get_user(loss_recipient)["points"] == 10
    rows = db.conn.execute(
        "select change_amount,reason from transactions order by id"
    ).fetchall()
    assert [row["change_amount"] for row in rows] == [-60, 50, 10]
    assert rows[-1]["reason"] == "付费互动正常损耗"


def test_paid_interaction_limit_is_checked_before_ai_and_footer_is_editable(
    tmp_path, monkeypatch
):
    db = make_db(tmp_path)
    sender = make_confirmed_user(db, "发起者", 3)
    target = make_confirmed_user(db, "目标", 4)
    loss_recipient = configure_paid_interaction_loss(db, 902)
    db.set_paid_interaction_enabled(target, True)
    db.set_secret("deepseek_api_key", "test-key")
    db.conn.execute("update users set points=-50 where id=?", (sender["id"],))
    db.conn.commit()
    config = db.get_config()
    config["features"]["church_theme_version"] = "1"
    config["features"]["paid_interaction_settlement_footer"] = (
        "|结算：{user}->{target}，支付{amount}，双方余额{balance}/{target_balance}"
    )
    db.save_config(config)
    calls = []

    def generate(self, **kwargs):
        calls.append(kwargs)
        return "AI正文"

    monkeypatch.setattr("app.command_router.DeepSeekClient.generate", generate)
    router = CommandRouter(db)

    blocked = router.handle(
        {"sender": "发起者", "text": "/对目标发起互动:唱一首歌"}
    )

    assert blocked.handled
    assert "不能低于 -100" in blocked.replies[0]
    assert calls == []
    assert db.get_user(sender)["points"] == -50
    assert db.get_user(target)["points"] == 0
    assert db.conn.execute("select count(*) from transactions").fetchone()[0] == 0

    db.conn.execute("update users set points=50 where id=?", (sender["id"],))
    db.conn.commit()
    success = router.handle(
        {"sender": "发起者", "text": "/对目标发起互动：唱一首歌"}
    )
    assert len(calls) == 1
    assert success.replies == ["AI正文|结算：发起者->目标，支付100，双方余额-50/90"]
    assert db.get_user(loss_recipient)["points"] == 10


def test_paid_interaction_rejects_self_target(tmp_path):
    db = make_db(tmp_path)
    user = make_confirmed_user(db, "同一个人", 5)
    db.conn.execute("update users set points=100 where id=?", (user["id"],))
    db.conn.commit()
    router = CommandRouter(db)

    result = router.handle(
        {"sender": "同一个人", "text": "/对同 一个人发起互动：唱歌"}
    )

    assert result.handled
    assert "不能对自己" in result.replies[0]
    assert db.get_user(user)["points"] == 100
    assert db.conn.execute("select count(*) from transactions").fetchone()[0] == 0


def test_paid_interaction_is_disabled_by_default_and_user_can_toggle(
    tmp_path, monkeypatch
):
    db = make_db(tmp_path)
    sender = make_confirmed_user(db, "发起者", 6)
    target = make_confirmed_user(db, "目标", 7)
    loss_recipient = configure_paid_interaction_loss(db, 903)
    db.set_secret("deepseek_api_key", "test-key")
    monkeypatch.setattr(
        "app.command_router.DeepSeekClient.generate",
        lambda self, **kwargs: "AI正文",
    )
    router = CommandRouter(db)

    blocked = router.handle(
        {"sender": "发起者", "text": "/对目标发起互动：唱一首歌"}
    )
    assert blocked.handled
    assert "尚未开启" in blocked.replies[0]
    assert db.get_user(sender)["points"] == 0
    assert db.get_user(target)["points"] == 0

    enabled = router.handle({"sender": "目标", "text": "/開啟付費互動"})
    assert enabled.handled
    assert "已开启" in enabled.replies[0]
    assert db.get_user(target)["paid_interaction_enabled"] == 1

    success = router.handle(
        {"sender": "发起者", "text": "/对目标发起互动：唱一首歌"}
    )
    assert success.handled
    assert db.get_user(sender)["points"] == -100
    assert db.get_user(target)["points"] == 90
    assert db.get_user(loss_recipient)["points"] == 10

    disabled = router.handle({"sender": "目标", "text": "/關閉付費互動"})
    assert disabled.handled
    assert "已关闭" in disabled.replies[0]
    assert db.get_user(target)["paid_interaction_enabled"] == 0


def test_paid_interaction_uses_one_system_and_one_user_prompt(
    tmp_path, monkeypatch
):
    db = make_db(tmp_path)
    sender = make_confirmed_user(db, "发起者", 8)
    target = make_confirmed_user(db, "目标", 9)
    configure_paid_interaction_loss(db, 904)
    db.set_paid_interaction_enabled(target, True)
    db.set_secret("deepseek_api_key", "test-key")
    config = db.get_config()
    config["features"]["church_theme_version"] = "1"
    config["features"].update(
        {
            "paid_interaction_ai_system_prompt": "唯一系统提示词",
            "paid_interaction_ai_user_prompt": (
                "发起={user}({user_gender})；目标={target}({target_gender})；"
                "要求={action}；金额={amount}{currency}"
            ),
        }
    )
    db.save_config(config)
    prompts = []

    def generate(self, **kwargs):
        prompts.append((kwargs["system_prompt"], kwargs["user_prompt"]))
        return "AI正文"

    monkeypatch.setattr("app.command_router.DeepSeekClient.generate", generate)
    router = CommandRouter(db)

    db.conn.execute(
        "update users set points=1000, gender='male' where id=?", (sender["id"],)
    )
    db.conn.execute(
        "update users set points=0, gender='female' where id=?", (target["id"],)
    )
    db.conn.commit()
    router.handle(
        {"sender": "发起者", "text": "/对目标发起互动：十分疯狂地挠脚底十分钟"}
    )

    assert prompts == [
        (
            "唯一系统提示词",
            "发起=发起者(男)；目标=目标(女)；要求=十分疯狂地挠脚底十分钟；金额=100金币",
        )
    ]


def test_paid_interaction_ai_failure_does_not_transfer_points(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    sender = make_confirmed_user(db, "发起者", 10)
    target = make_confirmed_user(db, "目标", 11)
    loss_recipient = configure_paid_interaction_loss(db, 905)
    db.set_paid_interaction_enabled(target, True)
    db.set_secret("deepseek_api_key", "test-key")

    calls = []

    def fail(self, **kwargs):
        calls.append(kwargs)
        raise AIInteractionError("测试失败")

    monkeypatch.setattr("app.command_router.DeepSeekClient.generate", fail)
    result = CommandRouter(db).handle(
        {"sender": "发起者", "text": "/对目标发起互动：唱一首歌"}
    )

    assert result.handled
    assert "未扣除" in result.replies[0]
    assert db.get_user(sender)["points"] == 0
    assert db.get_user(target)["points"] == 0
    assert db.get_user(loss_recipient)["points"] == 0
    assert db.conn.execute("select count(*) from transactions").fetchone()[0] == 0
    assert len(calls) == 2
    logs = db.conn.execute(
        "select level,kind,message from logs where kind='paid_interaction' order by id"
    ).fetchall()
    assert [row["level"] for row in logs] == ["WARNING", "ERROR"]
    assert "测试失败" in logs[-1]["message"]


def test_paid_interaction_retries_once_then_transfers_on_success(
    tmp_path, monkeypatch
):
    db = make_db(tmp_path)
    sender = make_confirmed_user(db, "发起者", 12)
    target = make_confirmed_user(db, "目标", 13)
    loss_recipient = configure_paid_interaction_loss(db, 906)
    db.set_paid_interaction_enabled(target, True)
    db.set_secret("deepseek_api_key", "test-key")
    calls = []

    def fail_once(self, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise AIInteractionError("临时上游错误")
        return "重试成功正文"

    monkeypatch.setattr(
        "app.command_router.DeepSeekClient.generate",
        fail_once,
    )

    result = CommandRouter(db).handle(
        {"sender": "发起者", "text": "/对目标发起互动：唱一首歌"}
    )

    assert len(calls) == 2
    assert result.replies[0].startswith("重试成功正文")
    assert db.get_user(sender)["points"] == -100
    assert db.get_user(target)["points"] == 90
    assert db.get_user(loss_recipient)["points"] == 10
    logs = db.conn.execute(
        "select level,message from logs where kind='paid_interaction' order by id"
    ).fetchall()
    assert len(logs) == 1
    assert logs[0]["level"] == "WARNING"
    assert "临时上游错误" in logs[0]["message"]


def test_paid_interaction_loss_recipient_can_also_be_target(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    sender = make_confirmed_user(db, "发起者", 14)
    target = make_confirmed_user(db, "大祭司", 15)
    db.set_paid_interaction_enabled(target, True)
    db.set_secret("deepseek_api_key", "test-key")
    config = db.get_config()
    config["features"]["church_theme_version"] = "1"
    config["features"]["paid_interaction_amount"] = 60
    config["features"]["paid_interaction_loss_amount"] = 10
    config["features"]["paid_interaction_loss_recipient_user_id"] = target[
        "platform_user_id"
    ]
    db.save_config(config)
    monkeypatch.setattr(
        "app.command_router.DeepSeekClient.generate",
        lambda self, **kwargs: "AI正文",
    )

    result = CommandRouter(db).handle(
        {"sender": "发起者", "text": "/对大祭司发起互动：唱歌"}
    )

    assert result.handled
    assert db.get_user(sender)["points"] == -60
    assert db.get_user(target)["points"] == 60
    rows = db.conn.execute(
        "select change_amount,reason from transactions order by id"
    ).fetchall()
    assert [row["change_amount"] for row in rows] == [-60, 50, 10]
    assert rows[-1]["reason"] == "付费互动正常损耗"


def test_paid_interaction_rejects_unconfirmed_identity_before_ai(
    tmp_path, monkeypatch
):
    db = make_db(tmp_path)
    sender = make_confirmed_user(db, "发起者", 12)
    target = db.ensure_user("待校准目标")
    db.set_secret("deepseek_api_key", "test-key")
    db.conn.execute(
        "update users set paid_interaction_enabled=1 where id=?", (target["id"],)
    )
    db.conn.commit()
    calls = []
    monkeypatch.setattr(
        "app.command_router.DeepSeekClient.generate",
        lambda self, **kwargs: calls.append(kwargs) or "不应生成",
    )

    result = CommandRouter(db).handle(
        {"sender": "发起者", "text": "/对待校准目标发起互动：唱歌"}
    )

    assert result.handled
    assert "主页唯一ID尚未确认" in result.replies[0]
    assert calls == []
    assert db.get_user(sender)["points"] == 0
    assert db.get_user(target)["points"] == 0


def test_old_paid_interaction_command_is_no_longer_handled(tmp_path):
    db = make_db(tmp_path)
    make_confirmed_user(db, "发起者", 13)

    result = CommandRouter(db).handle(
        {"sender": "发起者", "text": "/强制互动 对 目标 唱一首歌"}
    )

    assert not result.handled


def test_game_can_go_negative_with_debt_limit(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    allow_games_all_day(db)
    router = CommandRouter(db)
    monkeypatch.setattr("random.random", lambda: 0.9)

    result = router.handle({"sender": "赌徒", "text": "/修女纸牌 50"})

    assert result.handled
    assert db.get_user("赌徒")["points"] == -50


def test_system_card_game_uses_one_deck_without_duplicate_cards(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    allow_games_all_day(db)
    router = CommandRouter(db)
    monkeypatch.setattr("app.command_router.random.random", lambda: 0.1)
    monkeypatch.setattr("app.command_router.random.sample", lambda deck, count: list(deck)[:count])

    result = router.handle({"sender": "验牌员", "text": "/修女纸牌 10"})

    cards = re.findall(r"[♠♥♦♣](?:10|[2-9JQKA])", result.replies[0])
    assert len(cards) == 6
    assert len(set(cards)) == 6


def test_system_card_game_respects_configured_player_win_rate(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    allow_games_all_day(db)
    router = CommandRouter(db)
    winning_deal = [
        ("♠", "2"), ("♥", "4"), ("♦", "6"),
        ("♣", "A"), ("♥", "A"), ("♦", "A"),
    ]
    losing_deal = winning_deal[3:] + winning_deal[:3]

    config = db.get_config()
    config["features"] = {
        **config.get("features", {}),
        "church_theme_version": "1",
        "game_zjh_win_rate": 0,
    }
    db.save_config(config)
    monkeypatch.setattr("app.command_router.random.random", lambda: 0.0)
    monkeypatch.setattr("app.command_router.random.sample", lambda deck, count: losing_deal)
    lost = router.handle({"sender": "零胜率", "text": "/修女纸牌 10"})

    assert "试炼未通过" in lost.replies[0]
    assert db.get_user("零胜率")["points"] == -10

    config = db.get_config()
    config["features"] = {**config.get("features", {}), "game_zjh_win_rate": 100}
    db.save_config(config)
    monkeypatch.setattr("app.command_router.random.random", lambda: 0.999999)
    monkeypatch.setattr("app.command_router.random.sample", lambda deck, count: winning_deal)
    won = router.handle({"sender": "满胜率", "text": "/修女纸牌 10"})

    assert "试炼通过" in won.replies[0]
    assert db.get_user("满胜率")["points"] == 10


def test_group_card_game_uses_one_deck_for_every_player(tmp_path):
    db = make_db(tmp_path)
    game = db.create_game(
        "炸金花",
        {"platform_user_id": "card-user-1", "sender": "甲"},
        1,
        max_players=4,
        min_balance=-100,
    )
    for index, nickname in enumerate(["乙", "丙", "丁"], 2):
        joined = db.join_game(
            {"platform_user_id": f"card-user-{index}", "sender": nickname},
            min_balance=-100,
        )
        assert joined["ok"]

    result = db.reveal_game(game["game_id"])

    cards = [
        card
        for player in result["results"]
        for card in player["hand_cards"].split()
    ]
    assert len(cards) == 12
    assert len(set(cards)) == 12


def test_game_stops_at_debt_limit(tmp_path):
    db = make_db(tmp_path)
    allow_games_all_day(db)
    user = db.ensure_user("赌徒")
    db.update_user("赌徒", {**user, "points": -90})
    router = CommandRouter(db)

    result = router.handle({"sender": "赌徒", "text": "/修女纸牌 20"})

    assert result.handled
    assert "-100 下限" in result.replies[0]
    assert db.get_user("赌徒")["points"] == -90


def test_system_games_have_daily_limit(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    allow_games_all_day(db, game_daily_system_limit="3")
    router = CommandRouter(db)
    monkeypatch.setattr("random.random", lambda: 0.1)

    for _ in range(3):
        result = router.handle({"sender": "赌徒", "text": "/修女纸牌 10"})
        assert result.handled

    blocked = router.handle({"sender": "赌徒", "text": "/修女纸牌 10"})

    assert "今天已发起 3 次系统对战" in blocked.replies[0]


def test_games_are_blocked_outside_open_windows(tmp_path):
    db = make_db(tmp_path)
    config = db.get_config()
    config["features"] = {**config.get("features", {}), "game_open_windows": "00:00-00:00"}
    db.save_config(config)
    router = CommandRouter(db)

    result = router.handle({"sender": "赌徒", "text": "/修女纸牌 10"})

    assert result.handled
    assert "不在游戏开放时间" in result.replies[0]


def test_battle_create_has_daily_limit(tmp_path):
    db = make_db(tmp_path)
    allow_games_all_day(db, game_daily_battle_limit="1")
    router = CommandRouter(db)

    first = router.handle({"sender": "甲", "text": "/发起修女纸牌对战 10"})
    db.conn.execute("update games set status='finished', finished_at=? where status='waiting'", (db.now(),))
    db.conn.commit()
    second = router.handle({"sender": "甲", "text": "/发起修女纸牌对战 10"})

    assert first.handled
    assert "今天已发起 1 次群对战" in second.replies[0]


def test_debt_status_is_rendered_in_profile(tmp_path):
    db = make_db(tmp_path)
    user = db.ensure_user("欠债人")
    db.update_user("欠债人", {**user, "points": -30})
    router = CommandRouter(db)

    result = router.handle({"sender": "欠债人", "text": "/我"})

    assert result.handled
    assert "功德修补中" in result.replies[0]
    assert "30" in result.replies[0]


def test_debt_status_is_pinned_before_item_statuses(tmp_path):
    db = make_db(tmp_path)
    user = db.ensure_user("欠债人")
    db.update_user("欠债人", {**user, "points": -30})
    db.conn.execute(
        """
        insert into user_status_effects(target_nickname, actor_nickname, item_name, status_text, remove_price, active, created_at)
        values('欠债人', '张三', '项圈', '被张三套上了项圈', 5, 1, ?)
        """,
        (db.now(),),
    )
    db.conn.commit()
    router = CommandRouter(db)

    result = router.handle({"sender": "欠债人", "text": "/我"})

    assert result.handled
    assert "1. 功德修补中" in result.replies[0]
    assert "2. 被张三套上了项圈" in result.replies[0]


def test_other_status_includes_pinned_debt_status(tmp_path):
    db = make_db(tmp_path)
    user = db.ensure_user("欠债人")
    db.update_user("欠债人", {**user, "points": -30})
    db.set_display_name("欠债人", "大祭司")
    db.conn.execute(
        """
        insert into user_status_effects(target_nickname, actor_nickname, item_name, status_text, remove_price, active, created_at)
        values('欠债人', '张三', '项圈', '被张三套上了项圈', 5, 1, ?)
        """,
        (db.now(),),
    )
    db.conn.commit()
    router = CommandRouter(db)

    result = router.handle({"sender": "路人", "text": "/大祭司的状态"})

    assert result.handled
    assert "1. 功德修补中" in result.replies[0]
    assert "2. 被张三套上了项圈" in result.replies[0]


def test_remove_status_does_not_remove_pinned_debt_status(tmp_path):
    db = make_db(tmp_path)
    user = db.ensure_user("欠债人")
    db.update_user("欠债人", {**user, "points": -30})
    db.conn.execute(
        """
        insert into user_status_effects(target_nickname, actor_nickname, item_name, status_text, remove_price, active, created_at)
        values('欠债人', '张三', '项圈', '被张三套上了项圈', 0, 1, ?)
        """,
        (db.now(),),
    )
    db.conn.commit()
    router = CommandRouter(db)

    blocked = router.handle({"sender": "欠债人", "text": "/解除状态1"})
    removed = router.handle({"sender": "欠债人", "text": "/解除状态2"})

    assert "不能手动解除" in blocked.replies[0]
    assert "已解除状态" in removed.replies[0]
    assert not db.list_active_statuses("欠债人")


def test_debt_list_command_lists_negative_balance_users(tmp_path):
    db = make_db(tmp_path)
    a = db.ensure_user("甲")
    b = db.ensure_user("乙")
    c = db.ensure_user("丙")
    db.update_user("甲", {**a, "points": -30})
    db.update_user("乙", {**b, "points": 5})
    db.update_user("丙", {**c, "points": -80})
    router = CommandRouter(db)

    result = router.handle({"sender": "管理员", "text": "/欠债列表"})

    assert result.handled
    assert "当前需要补修功德的群友" in result.replies[0]
    assert "丙" in result.replies[0]
    assert "80" in result.replies[0]
    assert "甲" in result.replies[0]
    assert "乙" not in result.replies[0]
    assert result.replies[0].find("丙") < result.replies[0].find("甲")


def test_debt_list_command_handles_empty_list(tmp_path):
    db = make_db(tmp_path)
    router = CommandRouter(db)

    result = router.handle({"sender": "管理员", "text": "/欠债列表"})

    assert result.handled
    assert "无人欠功德点" in result.replies[0]


def test_beg_requires_low_balance(tmp_path):
    db = make_db(tmp_path)
    user = db.ensure_user("富人")
    db.update_user("富人", {**user, "points": 20})
    router = CommandRouter(db)

    result = router.handle({"sender": "富人", "text": "/乞讨"})

    assert result.handled
    assert "功德碗表示这活它不接" in result.replies[0]


def test_tip_transfers_points_to_active_beggar(tmp_path, monkeypatch):
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: b)
    db = make_db(tmp_path)
    beggar = db.ensure_user("穷人")
    giver = db.ensure_user("路人")
    db.update_user("穷人", {**beggar, "points": -10})
    db.update_user("路人", {**giver, "points": 50})
    router = CommandRouter(db)

    beg = router.handle({"sender": "穷人", "text": "/乞讨"})
    tip = router.handle({"sender": "路人", "text": "/打赏10"})

    assert beg.handled
    assert tip.handled
    assert db.get_user("穷人")["points"] == 0
    assert db.get_user("路人")["points"] == 40


def test_tip_can_reduce_beggar_negative_balance(tmp_path, monkeypatch):
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: b)
    db = make_db(tmp_path)
    beggar = db.ensure_user("穷人")
    giver = db.ensure_user("路人")
    db.update_user("穷人", {**beggar, "points": -80})
    db.update_user("路人", {**giver, "points": 50})
    router = CommandRouter(db)

    router.handle({"sender": "穷人", "text": "/乞讨"})
    result = router.handle({"sender": "路人", "text": "/打赏10"})

    assert result.handled
    assert db.get_user("穷人")["points"] == -70
    assert db.get_user("路人")["points"] == 40


def test_tip_rejects_self_tip(tmp_path, monkeypatch):
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: b)
    db = make_db(tmp_path)
    beggar = db.ensure_user("穷人")
    db.update_user("穷人", {**beggar, "points": -10})
    router = CommandRouter(db)

    router.handle({"sender": "穷人", "text": "/乞讨"})
    result = router.handle({"sender": "穷人", "text": "/打赏10"})

    assert result.handled
    assert "不能给自己打赏" in result.replies[0]


def test_only_one_active_beggar_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: b)
    db = make_db(tmp_path)
    first = db.ensure_user("甲")
    second = db.ensure_user("乙")
    db.update_user("甲", {**first, "points": -10})
    db.update_user("乙", {**second, "points": -10})
    router = CommandRouter(db)

    first_result = router.handle({"sender": "甲", "text": "/乞讨"})
    second_result = router.handle({"sender": "乙", "text": "/乞讨"})

    assert first_result.handled
    assert second_result.handled
    assert "甲" in second_result.replies[0]
    assert "5分钟" in second_result.replies[0]
    assert db.get_active_beggar()["nickname"] == "甲"


def test_beggar_expires_after_five_minutes(tmp_path, monkeypatch):
    monkeypatch.setattr("app.command_router.random.randint", lambda a, b: b)
    db = make_db(tmp_path)
    beggar = db.ensure_user("甲")
    giver = db.ensure_user("乙")
    next_beggar = db.ensure_user("丙")
    db.update_user("甲", {**beggar, "points": -10})
    db.update_user("乙", {**giver, "points": 50})
    db.update_user("丙", {**next_beggar, "points": -5})
    router = CommandRouter(db)

    router.handle({"sender": "甲", "text": "/乞讨"})
    db.conn.execute("update beg_sessions set created_at='2000-01-01 00:00:00' where id=1")
    db.conn.commit()

    expired_tip = router.handle({"sender": "乙", "text": "/打赏10"})
    new_beg = router.handle({"sender": "丙", "text": "/乞讨"})

    assert "没有成功摆碗" in expired_tip.replies[0]
    assert new_beg.handled
    assert db.get_active_beggar()["nickname"] == "丙"
