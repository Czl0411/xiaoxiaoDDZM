from pathlib import Path
from datetime import datetime, timedelta

import pytest

from app.ai_character import (
    AICharacterService,
    AICharacterStore,
    AIRequestRateLimitError,
    DEFAULT_SETTINGS,
    DEFAULT_SUPREME_SYSTEM_PROMPT,
    parse_ai_command,
    split_ai_reply,
)
from app.ai_interaction import AIInteractionError, AIInteractionResponse
from app.command_router import CommandResult, CommandRouter
from app.database import Database


class FakeRouter:
    def __init__(self):
        self.commands = []

    def handle(self, message, dry_run=False):
        if not dry_run:
            self.commands.append(message["text"])
        return CommandResult(True, [f"程序原文：{message['text']}"] , name="程序业务", reason="成功")


class DraftRouter(FakeRouter):
    def __init__(self):
        super().__init__()
        self.draft_requests = []

    def create_ai_bounty_draft(self, message, request_text, dry_run=False):
        self.draft_requests.append(request_text)
        return CommandResult(True, ["📜 悬赏草稿：1人，700功德，文斗。\n确认发布：/确认"], name="AI悬赏草稿")


class MediaRouter(FakeRouter):
    def handle(self, message, dry_run=False):
        if not dry_run:
            self.commands.append(message["text"])
        return CommandResult(
            True,
            ["游戏已开启"],
            name="图片游戏",
            media_paths=["普通图片.webp"],
            media_first=True,
            deliveries=[{"group_key": "bounty", "text": "同步通知"}],
        )


class ResponseFactory:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, **kwargs):
        factory = self

        class Client:
            def generate_response(self, **call_kwargs):
                factory.calls += 1
                if not factory.responses:
                    raise AIInteractionError("模拟失败")
                item = factory.responses.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

        return Client()


def response(content, input_tokens=10, output_tokens=5):
    return AIInteractionResponse(content, input_tokens, output_tokens, "deepseek-v4-flash")


@pytest.fixture()
def db(tmp_path: Path):
    instance = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    instance.init()
    yield instance
    instance.close()


def message(message_id="m1", text="/zz你好", user_id="uuid-1", nickname="小堇"):
    return {
        "message_id": message_id,
        "text": text,
        "sender": nickname,
        "platform_user_id": user_id,
        "user_id": user_id,
        "group_key": "main",
        "source_group": "main",
    }


def prepare_user(db, msg, points=100):
    recipient_id = DEFAULT_SETTINGS["fee_recipient_user_id"]
    if msg["platform_user_id"] != recipient_id:
        recipient = db.conn.execute(
            "select id from users where platform_user_id=?", (recipient_id,)
        ).fetchone()
        if not recipient:
            recipient = db.ensure_user(message("high-priest", "/余额", recipient_id, "大祭司"))
            db.conn.execute("update users set points=0 where id=?", (recipient["id"],))
            db.conn.commit()
    user = db.ensure_user(msg)
    db.conn.execute("update users set points=? where id=?", (points, user["id"]))
    db.conn.commit()
    return db.get_user(msg)


def test_command_parser_order_and_boundaries():
    assert parse_ai_command(" /zzs   认真分析 ").thinking is True
    assert parse_ai_command("/zzs认真分析").content == "认真分析"
    assert parse_ai_command("/zz你好").content == "你好"
    assert parse_ai_command("普通聊天 /zz 你好").matched is False
    assert parse_ai_command("/zz").content == ""


def test_success_charges_once_and_duplicate_does_not_recreate(db):
    msg = message()
    prepare_user(db, msg)
    factory = ResponseFactory([response('{"type":"reply","reply":"你好，小堇。"}', 12, 7)])
    service = AICharacterService(db, FakeRouter(), ai_client_factory=factory)
    task, created = service.begin(msg, parse_ai_command(msg["text"]))
    assert created is True
    result = service.process(msg, task)
    assert result.success is True
    assert result.fee == 10
    assert "↑12 ↓7" in result.replies[-1]
    assert db.get_user(msg)["points"] == 90
    assert db.conn.execute("select count(*) from ai_fee_transactions").fetchone()[0] == 1
    recipient = db.conn.execute(
        "select * from users where platform_user_id=?", (DEFAULT_SETTINGS["fee_recipient_user_id"],)
    ).fetchone()
    assert recipient["points"] == 2
    fee_row = db.conn.execute("select * from ai_fee_transactions").fetchone()
    assert fee_row["transaction_id"] is not None
    assert fee_row["recipient_transaction_id"] is not None
    assert fee_row["recipient_fee_snapshot"] == 2
    same_task, created = service.begin(msg, parse_ai_command(msg["text"]))
    assert created is False
    assert same_task["task_id"] == task["task_id"]
    assert factory.calls == 1
    assert db.get_user(msg)["points"] == 90


def test_user_rate_limit_is_persistent_cross_group_and_excludes_confirmations(db):
    requester = message("rate-user-init", "/zz 第一次", user_id="rate-user", nickname="限流测试")
    prepare_user(db, requester)
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    for index in range(5):
        request = message(f"rate-user-{index}", f"/zz 请求{index}", user_id="rate-user", nickname="限流测试")
        task, created = service.begin(request, parse_ai_command(request["text"]))
        assert created is True
        assert task["fee_snapshot"] == 10

    blocked = message("rate-user-cross-group", "/zz 第六次", user_id="rate-user", nickname="限流测试")
    blocked["group_key"] = "bounty"
    blocked["source_group"] = "bounty"
    with pytest.raises(AIRequestRateLimitError) as error:
        service.begin(blocked, parse_ai_command(blocked["text"]))
    assert "每30分钟最多5次" in str(error.value)
    assert db.conn.execute("select count(*) from ai_tasks where user_id='rate-user'").fetchone()[0] == 5
    assert db.conn.execute("select count(*) from ai_fee_transactions").fetchone()[0] == 0

    confirmation = message("rate-user-confirm", "/zz确认", user_id="rate-user", nickname="限流测试")
    confirm_task, created = service.begin(confirmation, parse_ai_command(confirmation["text"]))
    assert created is True
    assert confirm_task["fee_snapshot"] == 0
    with pytest.raises(AIRequestRateLimitError):
        service.begin(
            message("rate-user-still-blocked", "/zz 仍应受限", user_id="rate-user", nickname="限流测试"),
            parse_ai_command("/zz 仍应受限"),
        )


def test_tool_calls_sum_all_successful_token_usage(db):
    msg = message(text="/zz看看我的余额")
    prepare_user(db, msg)
    factory = ResponseFactory([
        response('{"type":"tool","tool":"balance","arguments":{}}', 20, 8),
        response("你现在有100功德。", 30, 9),
    ])
    service = AICharacterService(db, FakeRouter(), ai_client_factory=factory)
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.token_input == 50
    assert result.token_output == 17
    assert "↑50 ↓17" in result.replies[-1]
    assert db.conn.execute("select count(*) from ai_tool_calls").fetchone()[0] == 1
    assert db.get_user(msg)["points"] == 90


def test_multiple_tool_calls_respect_limit_and_sum_every_model_call(db):
    msg = message(text="/zz比较我的余额和背包")
    prepare_user(db, msg)
    factory = ResponseFactory([
        response('{"type":"tool","tool":"balance","arguments":{}}', 10, 3),
        response('{"type":"tool","tool":"inventory","arguments":{}}', 11, 4),
        response('{"type":"reply","reply":"你有100功德，背包目前是空的。"}', 12, 5),
    ])
    service = AICharacterService(db, FakeRouter(), ai_client_factory=factory)
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert result.token_input == 33
    assert result.token_output == 12
    assert db.conn.execute("select count(*) from ai_tool_calls").fetchone()[0] == 2
    assert db.get_user(msg)["points"] == 90


def test_duplicate_tool_call_fails_without_charge(db):
    msg = message(text="/zz反复查余额")
    prepare_user(db, msg)
    duplicate = '{"type":"tool","tool":"balance","arguments":{}}'
    factory = ResponseFactory([response(duplicate), response(duplicate)])
    service = AICharacterService(db, FakeRouter(), ai_client_factory=factory)
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is False
    assert db.get_user(msg)["points"] == 100
    assert db.conn.execute("select count(*) from ai_fee_transactions").fetchone()[0] == 0


def test_model_failure_does_not_charge(db):
    msg = message()
    prepare_user(db, msg)
    factory = ResponseFactory([])
    service = AICharacterService(db, FakeRouter(), ai_client_factory=factory)
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is False
    assert db.get_user(msg)["points"] == 100
    assert db.conn.execute("select count(*) from ai_fee_transactions").fetchone()[0] == 0
    task_row = db.conn.execute("select * from ai_tasks where task_id=?", (task["task_id"],)).fetchone()
    assert task_row["fee_status"] == "not_charged"


def test_ai_fee_cannot_cross_negative_one_hundred_floor(db):
    msg = message("debt-floor", "/zz 测试负债下限", "debt-floor-user", "负债测试")
    prepare_user(db, msg, points=-99)
    factory = ResponseFactory([response('{"type":"reply","reply":"不应调用模型"}')])
    service = AICharacterService(db, FakeRouter(), ai_client_factory=factory)
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))

    result = service.process(msg, task)

    assert result.success is False
    assert factory.calls == 0
    assert db.get_user(msg)["points"] == -99
    assert db.conn.execute("select count(*) from ai_fee_transactions").fetchone()[0] == 0


def test_action_requires_confirmation_and_program_reply_is_not_rewritten(db):
    msg = message(text="/zz买第一个商品")
    prepare_user(db, msg)
    router = FakeRouter()
    factory = ResponseFactory([response('{"type":"action","command":"/购买1"}')])
    service = AICharacterService(db, router, ai_client_factory=factory)
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    draft = service.process(msg, task)
    assert draft.success is True
    assert "待确认操作" in draft.replies[0]
    assert router.commands == []

    confirm_msg = message("m2", "/zz 确认")
    confirm_task, _ = service.begin(confirm_msg, parse_ai_command(confirm_msg["text"]))
    confirmed = service.process(confirm_msg, confirm_task)
    assert confirmed.direct_program is True
    assert router.commands == ["/购买1"]
    assert confirmed.replies[0].startswith("程序原文：/购买1")
    assert db.get_user(msg)["points"] == 90
    again_msg = message("m3", "/zz 确认")
    again_task, _ = service.begin(again_msg, parse_ai_command(again_msg["text"]))
    again = service.process(again_msg, again_task)
    assert again.success is False
    assert router.commands == ["/购买1"]
    assert db.get_user(msg)["points"] == 90


def test_contract_relationship_is_authoritative_and_deactivates(db):
    borrower_msg = message("b1", "/余额", "borrower-id", "小堇")
    lender_msg = message("l1", "/余额", "lender-id", "大祭司")
    borrower = prepare_user(db, borrower_msg)
    lender = prepare_user(db, lender_msg)
    now = db.now()
    db.conn.execute(
        """insert into slave_contracts(borrower_user_pk,borrower_user_id,borrower_nickname,lender_user_pk,
           lender_user_id,lender_nickname,amount,status,requested_at,activated_at) values(?,?,?,?,?,?,10,'active',?,?)""",
        (borrower["id"], "borrower-id", "小堇", lender["id"], "lender-id", "大祭司", now, now),
    )
    db.conn.commit()
    store = AICharacterStore(db)
    store.sync_relationships("main")
    relation = db.conn.execute("select * from ai_relationships where source_type='slave_contract'").fetchone()
    assert relation["confidence"] == "verified"
    assert relation["locked"] == 1
    assert relation["forward_relation"] == "奴隶"
    db.conn.execute("update slave_contracts set status='repaid'")
    db.conn.commit()
    store.sync_relationships("main")
    assert db.conn.execute("select active from ai_relationships where id=?", (relation["id"],)).fetchone()[0] == 0


def test_user_memory_keeps_admin_correction_and_is_group_scoped(db):
    msg = message()
    user = prepare_user(db, msg)
    store = AICharacterStore(db)
    saved = store.save_user_memory(user["id"], {"admin_correction": "这是管理员确认事实", "auto_summary": "旧摘要"})
    assert saved["admin_correction"] == "这是管理员确认事实"
    updated = store.save_user_memory(user["id"], {"auto_summary": "新摘要"})
    assert updated["admin_correction"] == "这是管理员确认事实"
    other = store.user_memory(user["id"], "bounty")
    assert other["auto_summary"] == ""


def test_request_context_does_not_run_full_relationship_sync(db):
    msg = message()
    prepare_user(db, msg)
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    service.store.sync_relationships = lambda _group_id: (_ for _ in ()).throw(
        AssertionError("普通请求不应执行全群关系同步")
    )
    context = service.store.context(task)
    assert context["user"]["nickname"] == "小堇"


def test_named_member_context_includes_stable_profile_and_admin_memory(db):
    requester_msg = message("ask-xiaoxiao", "/zz小小是谁？")
    prepare_user(db, requester_msg)
    xiaoxiao_msg = message(
        "xiaoxiao-profile", "/余额", "6833a4c2-bb4b-42ce-9fad-b100a762afef", "小小"
    )
    xiaoxiao = prepare_user(db, xiaoxiao_msg)
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    service.store.backfill_basic_user_memories()

    task, _ = service.begin(requester_msg, parse_ai_command(requester_msg["text"]))
    context = service.store.context(task)

    assert len(context["referenced_users"]) == 1
    referenced = context["referenced_users"][0]
    assert referenced["stable_user_id"] == xiaoxiao_msg["platform_user_id"]
    assert referenced["profile"]["display_name"] == "小小"
    assert "圣女、群主" in referenced["memory"]["admin_correction"]
    assert xiaoxiao["id"] != db.get_user(requester_msg)["id"]


def test_planner_keeps_fifty_recent_messages_and_structured_identity_context(db):
    requester_msg = message("long-context", "/zz小小是谁？")
    prepare_user(db, requester_msg)
    prepare_user(
        db,
        message("xiaoxiao-user", "/余额", "6833a4c2-bb4b-42ce-9fad-b100a762afef", "小小"),
    )
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    service.store.backfill_basic_user_memories()
    long_text = "完整群聊内容" + ("甲" * 3000)
    for index in range(55):
        db.save_message(message(f"recent-{index:02d}", f"{long_text}{index}", f"member-{index}", f"成员{index}"))

    task, _ = service.begin(requester_msg, parse_ai_command(requester_msg["text"]))
    context = service.store.context(task)
    _, user_prompt = service._planner_prompt(task)

    assert len(context["recent_messages"]) == 50
    assert context["referenced_users"][0]["profile"]["display_name"] == "小小"
    assert "圣女、群主" in user_prompt
    assert context["recent_messages"][0]["text"] in user_prompt
    assert context["recent_messages"][-1]["text"] in user_prompt


def test_group_history_chunks_and_cumulative_summary_are_permanent_context(db):
    actor = message("history-user", "/余额", "history-user", "历史成员")
    prepare_user(db, actor)
    db.save_message({**actor, "message_id": "history-1", "text": "第一条历史消息"})
    db.save_message({**actor, "message_id": "history-2", "text": "第二条历史消息"})
    factory = ResponseFactory([
        response('{"chunk_summary":"本批历史摘要","cumulative_summary":"长期累计群摘要"}')
    ])
    service = AICharacterService(db, FakeRouter(), ai_client_factory=factory)

    result = service._update_group_history("main", service.store.settings())
    query_msg = message("history-query", "/zz群里以前发生过什么", "history-user", "历史成员")
    task, _ = service.begin(query_msg, parse_ai_command(query_msg["text"]))
    context = service.store.context(task)

    assert result == {"updated": True, "messages": 2}
    assert db.conn.execute("select count(*) from ai_group_summary_chunks").fetchone()[0] == 1
    assert context["long_term_group_summary"] == "长期累计群摘要"
    assert context["long_term_group_message_count"] == 2


def test_user_lookup_uses_indexed_identity_history(db):
    msg = message()
    user = prepare_user(db, msg)
    db.conn.execute(
        "insert into user_identity_history(user_pk,platform_user_id,nickname,avatar_id,source_message_id,observed_at) values(?,?,?,?,?,?)",
        (user["id"], msg["platform_user_id"], "旧昵称", "", "history-1", db.now()),
    )
    db.conn.commit()
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service._tool(task, "user_lookup", {"name": "旧昵称"})
    assert len(result["matches"]) == 1
    assert result["matches"][0]["nickname"] == "小堇"
    indexes = {row[1] for row in db.conn.execute("pragma index_list(user_identity_history)").fetchall()}
    assert "idx_identity_history_ai_nickname" in indexes


def test_background_tick_uses_separate_database_connection(db):
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    service.store.save_settings(
        {"memory_enabled": False, "group_memory_enabled": False, "proactive_enabled": False}
    )
    assert service.background_tick_isolated() == []
    assert db.conn.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_rankings_are_structured_read_tools(db):
    msg = message()
    prepare_user(db, msg)
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    merit = service._tool(task, "merit_ranking", {"limit": 5})
    interaction = service._tool(task, "interaction_ranking", {"limit": 5})
    assert merit["ranking"][0]["display_name"] == "小堇"
    assert merit["ranking"][0]["points"] == 100
    assert interaction["ranking"] == []


def test_status_messages_rotate_without_immediate_repeat(db):
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    first = service.status_text(False)
    second = service.status_text(False)
    assert first != second
    assert "追追" in first
    assert "追追" in second


def test_direct_daily_action_runs_without_confirmation(db):
    msg = message(text="/zz帮我祈福")
    prepare_user(db, msg)
    router = FakeRouter()
    service = AICharacterService(
        db, router, ai_client_factory=ResponseFactory([response('{"type":"action","command":"/祈福"}')])
    )
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert result.direct_program is True
    assert router.commands == ["/祈福"]
    assert "待确认操作" not in result.replies[0]


def test_red_packet_draft_accepts_send_confirmation_once(db):
    msg = message(text="/zz发一个100功德10份的红包")
    prepare_user(db, msg)
    router = FakeRouter()
    service = AICharacterService(
        db, router, ai_client_factory=ResponseFactory([response('{"type":"action","command":"/发福袋100功德点10个"}')])
    )
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    draft = service.process(msg, task)
    assert draft.success is True
    assert "待确认操作" in draft.replies[0]
    assert router.commands == []

    send_msg = message("send-1", "/zz 发送")
    send_task, _ = service.begin(send_msg, parse_ai_command(send_msg["text"]))
    sent = service.process(send_msg, send_task)
    assert sent.direct_program is True
    assert router.commands == ["/发福袋100功德点10个"]

    duplicate_msg = message("send-2", "/zz 确认发送")
    duplicate_task, _ = service.begin(duplicate_msg, parse_ai_command(duplicate_msg["text"]))
    duplicate = service.process(duplicate_msg, duplicate_task)
    assert duplicate.success is False
    assert router.commands == ["/发福袋100功德点10个"]


def test_supreme_prompt_is_first_and_strong_title_is_filtered(db):
    msg = message()
    prepare_user(db, msg)
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    service.store.save_settings({"system_rules": "普通系统规则"})
    service.store.save_profile({"persona_prompt": "角色人格规则"})
    system, _ = service._planner_prompt(task)
    assert system.startswith(DEFAULT_SUPREME_SYSTEM_PROMPT)
    assert system.index(DEFAULT_SUPREME_SYSTEM_PROMPT) < system.index("普通系统规则")
    assert system.index("普通系统规则") < system.index("角色人格规则")
    assert service._sanitize_direct_titles("主人，你好。\n小主人！", task) == "小堇，你好。\n小堇！"


def test_disabled_ai_keeps_memory_switches_but_stops_proactive_chat(db):
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    settings = service.store.save_settings({
        "enabled": False,
        "memory_enabled": True,
        "group_memory_enabled": True,
        "proactive_enabled": True,
        "proactive_groups": {"main": True},
    })
    assert settings["memory_enabled"] is True
    assert settings["group_memory_enabled"] is True
    assert service._proactive_for_group("main", settings) is None


def test_proactive_chat_is_time_based_and_uses_recent_group_context(db):
    db.save_message(message("proactive-recent", "群里正在讨论的内容", user_id="proactive-user"))
    factory = ResponseFactory([response("主动聊天回复")])
    service = AICharacterService(db, FakeRouter(), ai_client_factory=factory)
    settings = service.store.save_settings({
        "proactive_enabled": True,
        "proactive_groups": {"main": True, "bounty": False},
        "proactive_min_messages": 999,
        "proactive_quiet_start": "",
        "proactive_quiet_end": "",
    })
    due_at = (datetime.now().astimezone() - timedelta(seconds=1)).isoformat(timespec="seconds")
    db.conn.execute(
        "insert into ai_group_memories(group_id,status,next_proactive_at) values('main','idle',?)",
        (due_at,),
    )
    db.conn.commit()

    outputs = service.proactive_tick()

    assert factory.calls == 1
    assert outputs[0]["text"].startswith("主动聊天回复")
    next_at = db.conn.execute(
        "select next_proactive_at from ai_group_memories where group_id='main'"
    ).fetchone()[0]
    delay = datetime.fromisoformat(next_at) - datetime.now().astimezone()
    assert timedelta(minutes=9, seconds=50) <= delay <= timedelta(minutes=15, seconds=5)


def test_proactive_chat_reschedules_stale_plan_without_catch_up(db):
    db.save_message(message("proactive-stale", "这条消息不该触发补发", user_id="proactive-user"))
    factory = ResponseFactory([response("不应调用")])
    service = AICharacterService(db, FakeRouter(), ai_client_factory=factory)
    service.store.save_settings({
        "proactive_enabled": True,
        "proactive_groups": {"main": True, "bounty": False},
        "proactive_quiet_start": "",
        "proactive_quiet_end": "",
    })
    stale_at = (datetime.now().astimezone() - timedelta(hours=2)).isoformat(timespec="seconds")
    db.conn.execute(
        "insert into ai_group_memories(group_id,status,next_proactive_at) values('main','idle',?)",
        (stale_at,),
    )
    db.conn.commit()

    assert service.proactive_tick() == []
    assert factory.calls == 0
    next_at = datetime.fromisoformat(db.conn.execute(
        "select next_proactive_at from ai_group_memories where group_id='main'"
    ).fetchone()[0])
    assert next_at > datetime.now().astimezone()


def test_missing_fee_recipient_blocks_before_model_call(db):
    msg = message()
    user = db.ensure_user(msg)
    db.conn.execute("update users set points=100 where id=?", (user["id"],))
    db.conn.commit()
    factory = ResponseFactory([response('{"type":"reply","reply":"不应调用"}')])
    service = AICharacterService(db, FakeRouter(), ai_client_factory=factory)
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is False
    assert factory.calls == 0
    assert db.get_user(msg)["points"] == 100


def test_ai_reply_split_keeps_footer_only_in_last_message():
    text = "\n".join([f"第{i}行" for i in range(1, 24)] + ["📊 Token：↑10 ↓5｜🪙 5功德"])
    parts = split_ai_reply(text, 5)
    assert len(parts) == 2
    assert all(len(part.splitlines()) <= 9 for part in parts)
    assert sum("📊 Token" in part for part in parts) == 1
    assert "📊 Token" in parts[-1]
    assert "第23行" not in "\n".join(parts)
    assert "..." in parts[-1]


def test_natural_language_group_game_is_canonicalized_and_runs_directly(db):
    msg = message(text="/zz 帮我开启10功德的修女纸牌群对战")
    prepare_user(db, msg)
    router = FakeRouter()
    service = AICharacterService(
        db,
        router,
        ai_client_factory=ResponseFactory([
            response('{"type":"game","command":"开启修女纸牌群对战 10功德"}')
        ]),
    )
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert result.direct_program is True
    assert router.commands == ["/发起修女纸牌对战 10"]


def test_direct_game_preserves_program_media_and_deliveries(db):
    msg = message(text="/zz 开始猜乳头")
    prepare_user(db, msg)
    router = MediaRouter()
    service = AICharacterService(
        db,
        router,
        ai_client_factory=ResponseFactory([response('{"type":"game","command":"/猜乳头"}')]),
    )
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert result.media_paths == ["普通图片.webp"]
    assert result.media_first is True
    assert result.deliveries == [{"group_key": "bounty", "text": "同步通知"}]


def test_system_battle_phrase_stays_single_player_and_wrong_model_type_is_corrected(db):
    msg = message(text="/zz 我要玩一把修女纸牌和系统对战的100功德")
    prepare_user(db, msg)
    router = FakeRouter()
    service = AICharacterService(
        db,
        router,
        ai_client_factory=ResponseFactory([
            response('{"type":"action","command":"修女纸牌和系统对战100功德"}')
        ]),
    )
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert result.direct_program is True
    assert router.commands == ["/修女纸牌 100"]


def test_bounty_intent_cannot_be_changed_to_red_packet_and_gets_one_repair(db):
    msg = message(text="/zz 发布一个100功德的招募悬赏")
    prepare_user(db, msg)
    router = DraftRouter()
    service = AICharacterService(
        db,
        router,
        ai_client_factory=ResponseFactory([
            response('{"type":"command","command":"/发福袋100功德点1个"}'),
            response('{"type":"command","command":"/需求：招募一人，赏金100功德"}'),
        ]),
    )
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert router.commands == []
    assert router.draft_requests == ["/需求：招募一人，赏金100功德"]


def test_ai_can_execute_enabled_custom_command_rule(db):
    msg = message(text="/zz 帮我执行欢迎仪式")
    prepare_user(db, msg)
    db.create_rule({
        "name": "欢迎仪式",
        "trigger_type": "exact",
        "trigger_value": "/欢迎仪式",
        "reply_content": "仪式完成，欢迎{user}",
        "priority": 500,
    })
    service = AICharacterService(
        db,
        CommandRouter(db),
        ai_client_factory=ResponseFactory([
            response('{"type":"command","command":"/欢迎仪式"}')
        ]),
    )
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert result.direct_program is True
    assert "仪式完成，欢迎小堇" in "\n".join(result.replies)
    assert db.get_rule_hit_count_today(db.list_rules(enabled_only=True)[0]["id"]) == 1


def test_character_introduction_prefers_custom_rule_over_profile_tool(db):
    msg = message(text="/zz 给我看一下麻理的介绍")
    prepare_user(db, msg)
    db.create_rule({
        "name": "麻理",
        "group_name": "人物介绍",
        "trigger_type": "exact",
        "trigger_value": "/麻理",
        "reply_content": "麻理的自定义人物设定",
        "priority": 500,
    })
    factory = ResponseFactory([response('{"decoration":"人物卷宗已经展开啦📜"}')])
    service = AICharacterService(db, CommandRouter(db), ai_client_factory=factory)
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert result.direct_program is True
    assert "麻理的自定义人物设定" in "\n".join(result.replies)
    assert factory.calls == 1


def test_chinese_red_packet_request_is_canonicalized_and_requires_confirmation(db):
    msg = message(text="/zz 发红包，一百功德的5个红包")
    prepare_user(db, msg)
    router = FakeRouter()
    service = AICharacterService(db, router, ai_client_factory=ResponseFactory([]))
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert "待确认操作：/发福袋100功德点5个" in result.replies[0]
    assert router.commands == []


def test_malformed_model_red_packet_command_gets_required_points_suffix(db):
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    assert service._normalize_planned_command(
        "/发福袋50功德5个", "发红包，五十功德的5个红包", "command"
    ) == "/发福袋50功德点5个"


def test_meat_toilet_roster_maps_to_public_facility_command(db):
    msg = message(text="/zz 查询一下当前群里面的肉便器有几个？分别是谁？")
    prepare_user(db, msg)
    router = FakeRouter()
    service = AICharacterService(
        db,
        router,
        ai_client_factory=ResponseFactory([response('{"decoration":"名单已经整理好啦📜"}')]),
    )
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert result.direct_program is True
    assert router.commands == ["/公共设施"]


def test_transactions_game_history_and_named_profile_use_exact_user(db):
    requester_msg = message(text="/zz 查小林的记录")
    prepare_user(db, requester_msg)
    target_msg = message("target", "/余额", "target-user", "小林")
    target = prepare_user(db, target_msg, points=50)
    other = prepare_user(db, message("other", "/余额", "other-user", "影"), points=90)
    db.add_points(target, -12, "游戏消耗")
    db.record_game_play(target, "修女纸牌")
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    task, _ = service.begin(requester_msg, parse_ai_command(requester_msg["text"]))

    profile = service._tool(task, "profile", {"name": "小林"})
    transactions = service._tool(task, "transactions", {"name": "小林", "limit": 10})
    games = service._tool(task, "game_history", {"name": "小林", "limit": 10})
    assert profile["nickname"] == "小林"
    assert profile["points"] == 38
    assert profile["points"] != other["points"]
    assert transactions["spending"] >= 12
    assert transactions["records"][0]["reason"] == "游戏消耗"
    assert games["game_plays"][0]["game_type"] == "修女纸牌"


def test_bounty_action_uses_safe_draft_entry_instead_of_router_publication(db):
    msg = message(text="/zz 帮我发布悬赏，需要1个人和我文斗，700功德奖励")
    prepare_user(db, msg)
    router = DraftRouter()
    service = AICharacterService(
        db,
        router,
        ai_client_factory=ResponseFactory([
            response('{"type":"action","command":"/需求：单次找1人和我文斗，每人700功德"}')
        ]),
    )
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert result.direct_program is True
    assert router.commands == []
    assert router.draft_requests == ["/需求：单次找1人和我文斗，每人700功德"]
    assert "悬赏草稿" in result.replies[0]


def test_ai_service_bounty_uses_the_same_safe_draft_entry(db):
    msg = message(text="/zz 我想提供一小时聊天服务，收费100功德")
    prepare_user(db, msg)
    router = DraftRouter()
    service = AICharacterService(
        db,
        router,
        ai_client_factory=ResponseFactory([
            response('{"type":"action","command":"/服务：陪你聊天一个小时，每次100功德"}')
        ]),
    )
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert router.commands == []
    assert router.draft_requests == ["/服务：陪你聊天一个小时，每次100功德"]


def test_double_encoded_json_is_unwrapped_but_reasoning_only_text_is_never_sent(db):
    msg = message(text="/zz Pro回复测试")
    prepare_user(db, msg)
    wrapped = '"{\\"type\\":\\"reply\\",\\"reply\\":\\"正常文字\\"}"'
    service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([response(wrapped)]))
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)
    assert result.success is True
    assert "正常文字" in result.replies[0]
    assert "{\\\"type" not in result.replies[0]

    reasoning_msg = message("reasoning", "/zz Pro推理测试")
    reasoning_response = AIInteractionResponse(
        "internal reasoning with code: print('do not send')", 8, 4, "deepseek-v4-pro", True
    )
    reasoning_service = AICharacterService(
        db, FakeRouter(), ai_client_factory=ResponseFactory([reasoning_response])
    )
    reasoning_task, _ = reasoning_service.begin(
        reasoning_msg, parse_ai_command(reasoning_msg["text"])
    )
    failed = reasoning_service.process(reasoning_msg, reasoning_task)
    assert failed.success is False
    assert all("print('do not send')" not in reply for reply in failed.replies)


def test_planner_requests_provider_json_mode(db):
    msg = message("json-mode", "/zz 说说小小是谁", "json-user", "测试用户")
    prepare_user(db, msg)
    captured = []

    def factory(**_factory_kwargs):
        class Client:
            def generate_response(self, **call_kwargs):
                captured.append(call_kwargs)
                return response('{"type":"reply","reply":"结构化回答"}')

        return Client()

    service = AICharacterService(db, FakeRouter(), ai_client_factory=factory)
    task, _ = service.begin(msg, parse_ai_command(msg["text"]))
    result = service.process(msg, task)

    assert result.success is True
    assert captured[0]["response_format"] == {"type": "json_object"}


def test_basic_memory_is_seeded_and_failed_generation_remains_retryable(db):
    role_msg = message(
        "role-user", "/余额", "6833a4c2-bb4b-42ce-9fad-b100a762afef", "小小"
    )
    role_user = prepare_user(db, role_msg)
    store = AICharacterStore(db)
    store.backfill_basic_user_memories()
    memory = store.user_memory(role_user["id"])
    assert "基础记忆" in memory["auto_summary"]
    assert "圣女、群主" in memory["admin_correction"]
    assert memory["updated_at"] is None

    retry_msg = message("retry-0", "/余额", "retry-user", "待摘要用户")
    retry_user = prepare_user(db, retry_msg)
    for index in range(25):
        db.save_message({**retry_msg, "message_id": f"retry-{index}", "text": f"真实聊天{index}"})
    failing_service = AICharacterService(db, FakeRouter(), ai_client_factory=ResponseFactory([]))
    outcome = failing_service._update_one_user_memory(failing_service.store.settings())
    assert outcome["updated"] is False
    failed_memory = failing_service.store.user_memory(retry_user["id"])
    assert failed_memory["last_error"]
    assert failed_memory["updated_at"] is None
    assert failing_service._memory_candidate(failing_service.store.settings()) is not None
