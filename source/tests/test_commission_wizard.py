import asyncio
import json

import pytest

from app.command_router import CommandRouter
from app.database import Database
from app.scheduler import BotScheduler


USER1 = "91000000-0000-0000-0000-000000000001"
USER2 = "91000000-0000-0000-0000-000000000002"


def message(uid, text, mid=None, room="wizard-room"):
    return {
        "platform_user_id": uid,
        "user_id": uid,
        "sender": "玩家一" if uid == USER1 else "玩家二",
        "text": text,
        "message_id": mid or f"{uid}:{text}",
        "group_key": f"direct:{room}",
        "source_group": f"direct:{room}",
        "source_type": "direct",
        "chatroom_id": room,
        "avatar_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" if uid == USER1 else "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "is_self": False,
    }


class FailIfCalledAI:
    def __init__(self, **_kwargs):
        raise AssertionError("分步向导不应调用AI")


class RecordingAI:
    called = 0

    def __init__(self, **_kwargs):
        pass

    def generate(self, **_kwargs):
        type(self).called += 1
        return json.dumps({
            "parse_success": True,
            "missing_fields": [],
            "ambiguity_reason": "",
            "title": "自然语言需求",
            "content": "帮忙测试",
            "fulfillment_type": "one_time",
            "fulfillment_duration_value": None,
            "fulfillment_duration_unit": None,
            "required_people": 1,
            "reward_per_person": 10,
            "recruitment_duration_days": 3,
        }, ensure_ascii=False)


@pytest.fixture
def db(tmp_path):
    instance = Database(tmp_path / "bot.db")
    instance.init()
    yield instance
    instance.close()


def test_wizard_session_round_trip_and_user_isolation(db):
    db.commission_house.start_wizard(message(USER1, "/需求"), "demand", "title")
    db.commission_house.update_wizard(
        message(USER1, "称呼任务"), "content", {"title": "称呼任务"}, ["title"]
    )

    wizard = db.commission_house.get_wizard(message(USER1, ""))
    assert wizard["values"]["title"] == "称呼任务"
    assert wizard["history"] == ["title"]
    assert db.commission_house.get_wizard(message(USER2, "", room="other-room")) is None


def test_cancel_and_complete_remove_active_wizard(db):
    db.commission_house.start_wizard(message(USER1, "/服务"), "service", "title")
    assert db.commission_house.cancel_wizard(message(USER1, ""))
    assert db.commission_house.get_wizard(message(USER1, "")) is None


def test_empty_demand_command_runs_non_ai_wizard_with_examples(db):
    result = CommandRouter(db, ai_client_factory=FailIfCalledAI).handle(message(USER1, "/需求"))

    assert "第1/6步" in result.replies[0]
    assert "示例：群聊称呼任务" in result.replies[0]
    assert "/上一步｜/取消发布" in result.replies[0]


def test_demand_wizard_validates_and_builds_existing_draft(db):
    router = CommandRouter(db, ai_client_factory=FailIfCalledAI)
    for index, text in enumerate(["/需求", "称呼任务", "在群里喊我一声主人", "1"]):
        result = router.handle(message(USER1, text, f"demand:{index}"))
    bad = router.handle(message(USER1, "四个人", "demand:bad"))
    assert "1～10" in bad.replies[0]
    for index, text in enumerate(["4", "50", "3天"], start=4):
        result = router.handle(message(USER1, text, f"demand:{index}"))

    assert "需求发布预览" in result.replies[0]
    parsed = db.commission_house.get_draft(message(USER1, ""))["parsed"]
    assert parsed["required_people"] == 4
    assert parsed["reward_per_person"] == 50
    assert parsed["recruitment_duration_days"] == 3


def test_service_wizard_supports_duration_stock_limit_and_listing(db):
    router = CommandRouter(db, ai_client_factory=FailIfCalledAI)
    inputs = ["/服务", "陪聊服务", "陪你聊天", "2", "1天", "50", "小时", "10", "2", "3天"]
    for index, text in enumerate(inputs):
        result = router.handle(message(USER1, text, f"service:{index}"))

    assert "服务发布预览" in result.replies[0]
    parsed = db.commission_house.get_draft(message(USER1, ""))["parsed"]
    assert parsed["stock_quantity"] == 10 and parsed["max_per_buyer"] == 2
    assert parsed["fulfillment_duration_value"] == 1
    assert parsed["fulfillment_duration_unit"] == "day"


def test_service_wizard_explains_the_selling_unit_with_examples(db):
    router = CommandRouter(db, ai_client_factory=FailIfCalledAI)
    for index, text in enumerate(["/服务", "陪聊服务", "陪你聊天", "2", "1天", "50"]):
        result = router.handle(message(USER1, text, f"service-unit:{index}"))

    prompt = result.replies[0]
    assert "售卖单位" in prompt
    assert "这项服务按什么单位售卖" in prompt
    assert "次、小时、天、份、张" in prompt

    invalid = router.handle(message(USER1, "3", "service-unit:invalid"))
    assert "不能只填写数字" in invalid.replies[0]


def test_back_help_and_cancel_alias_preserve_expected_state(db):
    router = CommandRouter(db, ai_client_factory=FailIfCalledAI)
    router.handle(message(USER1, "/需求", "nav:0"))
    router.handle(message(USER1, "称呼任务", "nav:1"))
    help_result = router.handle(message(USER1, "/市场帮助", "nav:help"))
    assert help_result.name == "委托帮助"
    blocked = router.handle(message(USER1, "/余额", "nav:blocked"))
    assert "先完成或取消" in blocked.replies[0]
    back = router.handle(message(USER1, "/上一步", "nav:back"))
    assert "需求标题" in back.replies[0]
    cancelled = router.handle(message(USER1, "/取消发布草稿", "nav:cancel"))
    assert "已取消" in cancelled.replies[0]
    assert db.commission_house.get_wizard(message(USER1, "")) is None


def test_natural_language_publish_still_uses_ai(db):
    db.set_secret("deepseek_api_key", "test-key")
    RecordingAI.called = 0
    result = CommandRouter(db, ai_client_factory=RecordingAI).handle(
        message(USER1, "/需求：找一个人帮忙测试，每人10功德，单次", "compat:ai")
    )

    assert RecordingAI.called == 1
    assert "需求发布预览" in result.replies[0]


def test_group_text_does_not_advance_private_wizard(db):
    router = CommandRouter(db, ai_client_factory=FailIfCalledAI)
    router.handle(message(USER1, "/需求", "isolation:start"))
    group_message = message(USER1, "这只是群聊内容", "isolation:group")
    group_message.update({"source_type": "group", "group_key": "main", "source_group": "main", "chatroom_id": ""})

    result = router.handle(group_message)

    assert not result.handled
    assert db.commission_house.get_wizard(message(USER1, ""))["current_step"] == "title"


def test_completed_wizard_uses_existing_confirm_and_broadcast_flow(db):
    router = CommandRouter(db, ai_client_factory=FailIfCalledAI)
    inputs = ["/需求", "测试需求", "帮忙测试", "1", "1", "10", "3天"]
    for index, text in enumerate(inputs):
        router.handle(message(USER1, text, f"confirm:{index}"))

    confirmed = router.handle(message(USER1, "/确认发布", "confirm:publish"))

    assert "D0001" in confirmed.replies[0]
    assert confirmed.deliveries[0]["group_key"] == "bounty"
    assert "D0001" in confirmed.deliveries[0]["text"]


def test_scheduler_routes_non_slash_direct_text_into_active_wizard(db):
    class Adapter:
        def __init__(self):
            self.sent = []

        async def send_message(self, text, *_args):
            self.sent.append(text)
            return True

        async def send_direct_message(self, _room, text):
            self.sent.append(text)
            return True

    class Logger:
        def info(self, *_args, **_kwargs): pass
        def warning(self, *_args, **_kwargs): pass
        def error(self, *_args, **_kwargs): pass

    router = CommandRouter(db, ai_client_factory=FailIfCalledAI)
    router.handle(message(USER1, "/需求", "scheduler:start"))
    adapter = Adapter()
    scheduler = BotScheduler(db, adapter, engine=None, logger=Logger(), command_router=router)
    config = db.get_config()
    config["dzmm"]["send_delay_seconds"] = 0
    incoming = message(USER1, "收小狗", "scheduler:title")
    incoming.update({"time": "12:00:00", "source_stable": False})

    asyncio.run(scheduler._tick(config, [incoming], group_key="direct:wizard-room"))

    assert any("需求内容" in text for text in adapter.sent), (adapter.sent, db.get_message("scheduler:title"), incoming)
    assert db.commission_house.get_wizard(message(USER1, ""))["current_step"] == "content"


def test_scheduler_allows_preview_reply_after_final_non_slash_wizard_step(db):
    class Adapter:
        def __init__(self): self.sent = []
        async def send_message(self, text, *_args): self.sent.append(text); return True
        async def send_direct_message(self, _room, text): self.sent.append(text); return True

    class Logger:
        def info(self, *_args, **_kwargs): pass
        def warning(self, *_args, **_kwargs): pass
        def error(self, *_args, **_kwargs): pass

    router = CommandRouter(db, ai_client_factory=FailIfCalledAI)
    router.handle(message(USER1, "/需求", "final:start"))
    adapter = Adapter()
    scheduler = BotScheduler(db, adapter, engine=None, logger=Logger(), command_router=router)
    config = db.get_config()
    config["dzmm"]["send_delay_seconds"] = 0
    for index, text in enumerate(["测试需求", "帮忙测试", "1", "1", "10", "1天"]):
        incoming = message(USER1, text, f"final:{index}")
        incoming.update({"time": "12:00:00", "source_stable": False})
        asyncio.run(scheduler._tick(config, [incoming], group_key="direct:wizard-room"))

    assert any("需求发布预览" in text for text in adapter.sent)
    assert db.commission_house.get_draft(message(USER1, "")) is not None

    db.commission_house.start_wizard(message(USER1, "/服务"), "service", "title")
    assert db.commission_house.complete_wizard(message(USER1, ""))
    assert db.commission_house.get_wizard(message(USER1, "")) is None
