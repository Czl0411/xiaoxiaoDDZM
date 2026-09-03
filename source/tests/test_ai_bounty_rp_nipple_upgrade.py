from __future__ import annotations

import json
import asyncio

import pytest

from app.command_router import CommandRouter
from app.database import Database
from app.outgoing_text import prepare_outgoing_text_sequence
from app.scheduler import BotScheduler


U1 = "11111111-1111-1111-1111-111111111111"
U2 = "22222222-2222-2222-2222-222222222222"
U3 = "33333333-3333-3333-3333-333333333333"
U4 = "44444444-4444-4444-4444-444444444444"


def msg(uid, name, text, group="main", mid=""):
    return {"platform_user_id": uid, "user_id": uid, "sender": name, "text": text,
            "message_id": mid or f"{group}:{uid}:{text}", "group_key": group,
            "source_group": group, "is_self": False}


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db")
    db.init()
    db.set_secret("deepseek_api_key", "test")
    config = db.get_config()
    config["features"]["game_open_windows"] = ""
    config["dzmm"]["send_delay_seconds"] = 0
    db.save_config(config)
    return db


def funded(db, uid=U1, name="甲", points=5000):
    user = db.ensure_user(msg(uid, name, "初始化", mid=f"init:{uid}"))
    current = int(db.get_user(user)["points"])
    db.add_points(user, points - current, "临时测试初始化")
    return db.get_user(user)


class FakeAI:
    outputs = []
    calls = 0

    def __init__(self, **_kwargs):
        pass

    def generate(self, **_kwargs):
        type(self).calls += 1
        value = type(self).outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def ai_json(**changes):
    data = {"task_type": "single", "duration_days": None, "required_count": 1,
            "reward_per_person": 200, "content": "完成一次角色合照",
            "missing_fields": [], "parse_success": True}
    data.update(changes)
    return json.dumps(data, ensure_ascii=False)


def test_ai_commission_draft_confirm_is_once(tmp_path):
    db = make_db(tmp_path); funded(db)
    FakeAI.calls = 0; FakeAI.outputs = [ai_json(required_count=2)]
    router = CommandRouter(db, ai_client_factory=FakeAI)
    before = int(db.get_user(msg(U1, "甲", ""))["points"])
    preview = router.handle(msg(U1, "甲", "/需求：找两个人完成一次角色合照，每人200功德", mid="a1"))
    assert "托管：400" in preview.replies[0] and FakeAI.calls == 1
    assert db.conn.execute("select count(*) from bounties").fetchone()[0] == 0
    assert int(db.get_user(msg(U1, "甲", ""))["points"]) == before
    assert "/确认发布" in preview.replies[0]
    assert "/取消发布" in preview.replies[0]
    assert not router.handle(msg(U1, "甲", "内容正确", mid="plain-confirm")).handled
    confirmed = router.handle(msg(U1, "甲", "/确认发布", mid="c1"))
    assert confirmed.handled and "D0001" in confirmed.replies[0]
    assert db.conn.execute("select count(*) from bounties").fetchone()[0] == 1
    assert int(db.get_user(msg(U1, "甲", ""))["points"]) == before - 440
    repeated = router.handle(msg(U1, "甲", "/确认发布", mid="c2"))
    assert repeated.handled and "没有找到" in repeated.replies[0]
    assert db.conn.execute("select count(*) from bounties").fetchone()[0] == 1


@pytest.mark.parametrize("output,needle", [
    (ai_json(parse_success=False, missing_fields=["required_count"]), "所需人数"),
    (ai_json(parse_success=False, missing_fields=["task_type"]), "单次任务还是持续任务"),
    (ai_json(parse_success=False, missing_fields=["reward_per_person"]), "每人奖励"),
    (ai_json(parse_success=False, missing_fields=["content"]), "具体任务内容"),
    ("不是JSON", "必要信息"),
    (ai_json(required_count=11), "所需人数"),
    (ai_json(task_type="duration", duration_days=11), "持续天数"),
])
def test_ai_bounty_invalid_never_saves_draft(tmp_path, output, needle):
    db = make_db(tmp_path); funded(db)
    FakeAI.outputs = [output]
    result = CommandRouter(db, ai_client_factory=FakeAI).handle(msg(U1, "甲", "/需求：自然语言测试", mid="bad"))
    assert needle in result.replies[0] and "重新编辑整条" in result.replies[0]
    assert db.conn.execute("select count(*) from bounty_ai_drafts where status='pending'").fetchone()[0] == 0
    assert db.conn.execute("select count(*) from bounties").fetchone()[0] == 0


def test_ai_bounty_cancel_group_owner_and_plain_chat_isolation(tmp_path):
    db = make_db(tmp_path); funded(db); funded(db, U2, "乙")
    FakeAI.outputs = [ai_json(), ai_json()]
    router = CommandRouter(db, ai_client_factory=FakeAI)
    router.handle(msg(U1, "甲", "/需求：找一人完成一次任务每人200功德", mid="d1"))
    assert "没有找到" in router.handle(msg(U2, "乙", "/确认发布", mid="x1")).replies[0]
    assert "大群" in router.handle(msg(U1, "甲", "/确认发布", "other", "x2")).replies[0]
    assert not router.handle(msg(U1, "甲", "内容错误（取消发布）", mid="plain-cancel")).handled
    cancelled = router.handle(msg(U1, "甲", "/取消发布", mid="x3"))
    assert cancelled.handled and db.conn.execute("select count(*) from bounties").fetchone()[0] == 0
    assert not router.handle(msg(U2, "乙", "/取消发布", mid="x4")).handled


@pytest.mark.parametrize("wording", ["单次唱一首歌", "唱一首歌", "做一个动作", "完成一次祈福"])
def test_ai_bounty_single_task_never_requires_duration(tmp_path, wording):
    db = make_db(tmp_path); funded(db)
    FakeAI.outputs = [ai_json(
        task_type="duration", duration_days=None, required_count=1,
        reward_per_person=100, content=wording,
        missing_fields=["duration_days"], parse_success=False,
    )]
    result = CommandRouter(db, ai_client_factory=FakeAI).handle(
        msg(U1, "甲", f"/需求：找1个人{wording}，每人100功德", mid=f"single:{wording}")
    )
    assert "类型：单次悬赏" in result.replies[0]
    assert "持续天数" not in result.replies[0]


def test_bounty_and_rp_custom_reply_templates_take_effect(tmp_path):
    db = make_db(tmp_path); funded(db); funded(db, U2, "乙"); funded(db, U3, "观众")
    config = db.get_config()
    config["features"].update({
        "commission_request_preview_reply": "自定义需求｜{required_count}人｜托管{escrow}｜请发/确认发布或/取消发布",
        "rp_yellow_warning_reply": "自定义黄牌 @{nickname} 第{count}次",
    })
    db.save_config(config)
    FakeAI.outputs = [ai_json(required_count=2, reward_per_person=100)]
    router = CommandRouter(db, ai_client_factory=FakeAI)
    preview = router.handle(msg(U1, "甲", "/需求：找两个人完成一次合照，每人100功德", mid="custom-bounty"))
    assert preview.replies == ["自定义需求｜2人｜托管200｜请发/确认发布或/取消发布"]
    router.handle(msg(U1, "甲", "/上皮（1/2）", mid="custom-rp-1"))
    router.handle(msg(U2, "乙", "/加入", mid="custom-rp-2"))
    warning = router.handle(msg(U3, "观众", "未加括号", mid="custom-rp-3"))
    assert warning.replies == ["自定义黄牌 @观众 第1次"]


def test_bounty_commands_accept_optional_spaces_and_fixed_replies_are_customizable(tmp_path):
    db = make_db(tmp_path); funded(db, U1, "发起人"); funded(db, U2, "接取人")
    config = db.get_config()
    config["features"].update({
        "commission_request_card_reply": "自定义卡片{number}｜发送/接取需求{number}",
        "commission_order_created_reply": "自定义接取{post_number}｜{order_number}",
        "commission_order_complete_reply": "自定义待确认{order_number}｜{confirmer}",
        "commission_order_confirm_reply": "自定义结算{order_number}｜{paid_total}",
    })
    db.save_config(config)
    FakeAI.outputs = [ai_json(required_count=1, reward_per_person=100, content="唱一首歌")]
    router = CommandRouter(db, ai_client_factory=FakeAI)
    router.handle(msg(U1, "发起人", "/需求：单次找1人唱一首歌，每人100功德", mid="compact-publish"))
    published = router.handle(msg(U1, "发起人", "/确认发布", mid="compact-confirm-publish"))
    assert published.handled and "自定义卡片D0001" in published.deliveries[0]["text"]
    detail = router.handle(msg(U2, "接取人", "/需求详情D0001", group="bounty", mid="compact-detail"))
    assert detail.handled and "自定义卡片D0001" in detail.replies[0]
    accepted = router.handle(msg(U2, "接取人", "/接取需求D0001", group="bounty", mid="compact-accept"))
    assert accepted.replies == ["自定义接取D0001｜O0001"]
    completed = router.handle(msg(U2, "接取人", "/完成订单O0001", group="bounty", mid="compact-complete"))
    assert completed.replies == ["自定义待确认O0001｜发起人"]
    confirmed = router.handle(msg(U1, "发起人", "/确认订单O0001", group="bounty", mid="compact-confirm"))
    assert confirmed.replies == ["自定义结算O0001｜100"]
    assert "格式" in router.handle(msg(U2, "接取人", "/需求详情abc", group="bounty", mid="compact-bad")).replies[0]


def test_rp_gather_join_monitor_end_and_no_auto_kick(tmp_path):
    db = make_db(tmp_path)
    for uid, name in ((U1,"甲"),(U2,"乙"),(U3,"丙"),(U4,"丁")): funded(db, uid, name)
    router = CommandRouter(db)
    assert router.handle(msg(U1,"甲","/上皮（2/3）",mid="r0")).handled
    started = router.handle(msg(U1,"甲","/上皮 (1/3)",mid="r1"))
    assert "1/3" in started.replies[0]
    assert "已经" in router.handle(msg(U1,"甲","/加入",mid="r2")).replies[0]
    assert "2/3" in router.handle(msg(U2,"乙","/加入",mid="r3")).replies[0]
    opened = router.handle(msg(U3,"丙","/加入",mid="r4"))
    assert "已集齐3位" in opened.replies[0] and "自动踢" not in opened.replies[0]
    legal = router.handle_passive(msg(U4,"丁","（合法闲聊）",mid="v0"))
    assert legal.handled and not legal.replies
    first = router.handle_passive(msg(U4,"丁","前缀（不合法）",mid="v1"))
    second = router.handle_passive(msg(U4,"丁","(混合）",mid="v2"))
    duplicate = router.handle_passive(msg(U4,"丁","(混合）",mid="v2"))
    assert "黄牌" in first.replies[0]
    assert "踢出处理通知" in second.replies[0] and "已记录并通知管理员" in second.replies[0]
    assert "已被移出群聊" not in second.replies[0]
    assert duplicate.handled and not duplicate.replies
    violation = db.list_rp_admin()["violations"][0]
    assert violation["violation_count"] == 2 and violation["handling_status"] == "pending_admin_action"
    assert not router.handle(msg(U4,"丁","/结束",mid="e1")).replies[0].startswith("⚜️")
    assert "结界已解除" in router.handle(msg(U1,"甲","/结束",mid="e2")).replies[0]
    assert db.list_rp_admin()["violations"][0]["handling_status"] == "pending_admin_action"


def test_rp_active_spectator_commands_are_blocked_and_warned(tmp_path):
    db = make_db(tmp_path)
    for uid, name in ((U1, "甲"), (U2, "乙"), (U3, "观众")):
        funded(db, uid, name)
    router = CommandRouter(db)
    router.handle(msg(U1, "甲", "/上皮（1/2）", mid="rc1"))
    router.handle(msg(U2, "乙", "/加入", mid="rc2"))
    before = int(db.get_user(msg(U3, "观众", ""))["points"])
    prayer = router.handle(msg(U3, "观众", "/祈祷", mid="rc3"))
    join = router.handle(msg(U3, "观众", "/加入", mid="rc4"))
    assert prayer.name == "RP监控" and "黄牌" in prayer.replies[0]
    assert join.name == "RP监控" and "踢出处理通知" in join.replies[0]
    assert int(db.get_user(msg(U3, "观众", ""))["points"]) == before
    assert db.conn.execute("select count(*) from checkins where user_id=?", (U3,)).fetchone()[0] == 0


def test_rp_active_participant_commands_are_violations_and_admin_can_end_after_leave(tmp_path):
    db = make_db(tmp_path)
    for uid, name in ((U1, "发起者"), (U2, "参与者"), (U3, "旁观者"), (U4, "管理员")):
        funded(db, uid, name)
    db.conn.execute("update users set is_admin=1 where platform_user_id=?", (U4,))
    db.conn.commit()
    router = CommandRouter(db)
    router.handle(msg(U1, "发起者", "/上皮（1/2）", mid="rp-lock-1"))
    router.handle(msg(U2, "参与者", "/加入", mid="rp-lock-2"))

    blocked = router.handle(msg(U1, "发起者", "/祈福", mid="rp-lock-3"))
    assert blocked.name == "RP监控"
    assert "黄牌" in blocked.replies[0]
    assert db.conn.execute("select count(*) from checkins where user_id=?", (U1,)).fetchone()[0] == 0

    not_joined = router.handle(msg(U3, "旁观者", "/退队", mid="rp-lock-4"))
    assert not_joined.name == "RP退队"
    assert db.conn.execute("select violation_count from rp_violations where user_id=?", (U3,)).fetchone() is None

    left = router.handle(msg(U2, "参与者", "/退队", mid="rp-lock-5"))
    assert left.name == "RP退队"
    active = db.get_rp_session("main", ("active",))
    assert active and active["current_count"] == 1
    assert [participant["user_id"] for participant in active["participants"]] == [U1]
    history = db.conn.execute(
        "select left_at,leave_message_id,leave_count from rp_participants where session_id=? and user_id=?",
        (active["session_id"], U2),
    ).fetchone()
    assert history["left_at"] and history["leave_message_id"] == "rp-lock-5" and history["leave_count"] == 1

    ended = router.handle(msg(U4, "管理员", "/结束", mid="rp-lock-6"))
    assert ended.name == "RP结束"
    assert db.get_rp_session("main", ("active",)) is None


class FakeAdapter:
    def __init__(self): self.sent = []
    async def send_message(self, text, group_key="main"):
        self.sent.append((group_key, text)); return True
    async def send_image(self, path, group_key="main"): return True


class FakeEngine:
    def match_rules(self, *_args): return []


class FakeLogger:
    def info(self, *_args, **_kwargs): pass
    def warning(self, *_args, **_kwargs): pass
    def error(self, *_args, **_kwargs): pass


def test_scheduler_sends_front_yellow_and_kick_notice_for_spectator(tmp_path):
    db = make_db(tmp_path)
    for uid, name in ((U1, "甲"), (U2, "乙"), (U3, "观众")):
        funded(db, uid, name)
    router = CommandRouter(db)
    router.handle(msg(U1, "甲", "/上皮（1/2）", mid="sf1"))
    router.handle(msg(U2, "乙", "/加入", mid="sf2"))
    adapter = FakeAdapter()
    scheduler = BotScheduler(db, adapter, FakeEngine(), FakeLogger(), router)
    config = db.get_config()
    plain = msg(U3, "观众", "这个就可以开始小剧场了吗", mid="sf3")
    command = msg(U3, "观众", "/祈祷", mid="sf4")
    asyncio.run(scheduler._tick(config, [plain]))
    asyncio.run(scheduler._tick(config, [command]))
    assert "黄牌警告" in adapter.sent[0][1]
    assert "踢出处理通知" in adapter.sent[1][1]
    assert db.conn.execute("select count(*) from checkins where user_id=?", (U3,)).fetchone()[0] == 0


def test_rp_groups_one_person_timeout_and_admin_status(tmp_path):
    db = make_db(tmp_path); funded(db); funded(db,U2,"乙")
    router = CommandRouter(db)
    assert "已集齐1位" in router.handle(msg(U1,"甲","/上皮（1/1）","g1","one")).replies[0]
    assert router.handle(msg(U2,"乙","/加入","g2","none")).name != "RP加入"
    db.admin_close_rp("g1")
    router.handle(msg(U1,"甲","/上皮（1/5）","g2","five"))
    db.conn.execute("update rp_sessions set expires_at='2000-01-01 00:00:00' where group_id='g2'"); db.conn.commit()
    expired = db.expire_rp_gatherings()
    assert len(expired) == 1 and db.get_rp_session("g2") is None


class SequenceRandom:
    def __init__(self, *values): self.values = iter(values)
    def __call__(self): return next(self.values)


def test_nipple_base_bet_rewards_sides_and_settlement(tmp_path):
    db = make_db(tmp_path); user = funded(db, points=1000)
    config = db.get_config(); config["features"]["nipple_guess_base_bet"] = 200; db.save_config(config)
    router = CommandRouter(db, random_source=SequenceRandom(0.1, 0.9))
    start = router.handle(msg(U1,"甲","/猜乳头",mid="n0"))
    assert "200" in start.replies[0] and db.get_user(user)["points"] == 800
    first = router.handle(msg(U1,"甲","/1",mid="n1"))
    session = db.get_active_nipple_guess(user)
    assert "左" in first.replies[0] and session["other_side"] == "right" and session["first_reward"] == 300
    config = db.get_config(); config["features"]["nipple_guess_base_bet"] = 999; db.save_config(config)
    second = router.handle(msg(U1,"甲","/2",mid="n2"))
    assert "右" in second.replies[0] and "300" in second.replies[0]
    assert db.get_user(user)["points"] == 800
    assert db.conn.execute("select count(*) from transactions where reason='猜乳头第二轮获胜'").fetchone()[0] == 0


@pytest.mark.parametrize("first_random,action,second_random,expected", [
    (0.9, None, None, 900),
    (0.1, "/1", None, 1050),
    (0.1, "/2", 0.2, 1200),
])
def test_nipple_exact_net_results(tmp_path, first_random, action, second_random, expected):
    db = make_db(tmp_path); user = funded(db, points=1000)
    values = [first_random] + ([second_random, 0.9] if second_random is not None else [])
    router = CommandRouter(db, random_source=SequenceRandom(*values))
    router.handle(msg(U1,"甲","/猜乳头",mid="s"))
    router.handle(msg(U1,"甲","/2",mid="f"))
    if action:
        router.handle(msg(U1,"甲",action,mid="a"))
    assert db.get_user(user)["points"] == expected


def test_nipple_timeout_refunds_and_all_new_replies_fit_sender(tmp_path):
    db = make_db(tmp_path); user = funded(db, points=1000)
    router = CommandRouter(db)
    replies = [router.handle(msg(U1,"甲","/猜乳头",mid="t0")).replies[0], router._rp_announcement(10)]
    db.conn.execute("update nipple_guess_sessions set updated_at='2000-01-01 00:00:00'"); db.conn.commit()
    assert db.expire_nipple_guess_sessions(60)[0]["refund"] == 100
    assert db.get_user(user)["points"] == 1000
    for reply in replies:
        prepared = prepare_outgoing_text_sequence([reply])
        assert len(prepared) <= 2
        assert all(len(part.splitlines()) <= 10 for part in prepared)
