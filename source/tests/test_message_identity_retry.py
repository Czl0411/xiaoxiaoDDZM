import asyncio

from app.command_router import CommandResult
from app.database import Database
from app.dzmm_adapter import DzmmAdapter
from app.scheduler import BotScheduler


USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"
AVATAR_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_AVATAR_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


class FakeBrowser:
    page = None


class FakeAdapter:
    def __init__(self):
        self.browser = FakeBrowser()
        self.sent = []

    async def send_message(self, text):
        self.sent.append(text)
        return True


class FakeLogger:
    def __init__(self):
        self.entries = []

    def info(self, message, kind="normal"):
        self.entries.append(("info", kind, message))

    def warning(self, message, kind="normal"):
        self.entries.append(("warning", kind, message))

    def error(self, message, kind="error"):
        self.entries.append(("error", kind, message))


class FakeRouter:
    def __init__(self):
        self.calls = []

    def handle(self, message):
        self.calls.append(message)
        return CommandResult(True, ["已正确回复"], name="测试", reason="身份确认")


def make_message(
    message_id,
    *,
    sender="测试用户",
    user_id=USER_ID,
    avatar_id=AVATAR_ID,
    source_index="101",
):
    return {
        "message_id": message_id,
        "platform_user_id": user_id,
        "user_id": user_id,
        "avatar_id": avatar_id,
        "sender": sender,
        "text": "/测试",
        "time": "12:00:00",
        "is_self": False,
        "raw_html": "",
        "source_index": source_index,
        "source_stable": True,
    }


def make_scheduler(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    adapter = FakeAdapter()
    logger = FakeLogger()
    router = FakeRouter()
    scheduler = BotScheduler(db, adapter, engine=None, logger=logger, command_router=router)
    config = db.get_config()
    config["dzmm"]["send_delay_seconds"] = 0
    return db, adapter, logger, router, scheduler, config


def test_platform_id_is_sufficient_even_when_nickname_is_unknown(tmp_path):
    db, adapter, logger, router, scheduler, config = make_scheduler(tmp_path)

    asyncio.run(scheduler._tick(config, [make_message("message-1", sender="未知用户")]))

    completed = db.get_message("message-1")
    assert completed["processed"] == 1
    assert completed["sender"] == "未知用户"
    assert adapter.sent == ["已正确回复"]
    assert len(router.calls) == 1


def test_missing_platform_id_never_executes_and_later_complete_observation_replies_once(tmp_path):
    db, adapter, _, router, scheduler, config = make_scheduler(tmp_path)

    asyncio.run(
        scheduler._tick(
            config,
            [make_message("temporary-dom-id", user_id="")],
        )
    )
    asyncio.run(
        scheduler._tick(
            config,
            [make_message("real-platform-message-id")],
        )
    )
    asyncio.run(
        scheduler._tick(
            config,
            [make_message("real-platform-message-id")],
        )
    )

    assert db.get_message("temporary-dom-id")["processed"] == 0
    assert db.get_message("real-platform-message-id")["processed"] == 1
    assert adapter.sent == ["已正确回复"]
    assert len(router.calls) == 1


def test_missing_id_does_not_block_identified_user_in_same_tick(tmp_path):
    db, adapter, _, router, scheduler, config = make_scheduler(tmp_path)
    missing = make_message("missing-id", user_id="", source_index="401")
    identified = make_message(
        "identified-id",
        sender="另一位用户",
        user_id=OTHER_USER_ID,
        avatar_id=OTHER_AVATAR_ID,
        source_index="402",
    )

    asyncio.run(scheduler._tick(config, [missing, identified]))

    assert db.get_message("missing-id")["processed"] == 0
    assert "missing-id" not in scheduler.seen_message_ids
    assert db.get_message("identified-id")["processed"] == 1
    assert adapter.sent == ["已正确回复"]
    assert [call["platform_user_id"] for call in router.calls] == [OTHER_USER_ID]


def test_normal_chat_without_id_is_retried_instead_of_discarded(tmp_path):
    db, adapter, _, router, scheduler, config = make_scheduler(tmp_path)
    message = make_message("normal-retry", user_id="")
    message["text"] = "普通聊天"

    asyncio.run(scheduler._tick(config, [message]))

    assert db.get_message("normal-retry")["processed"] == 0
    assert "normal-retry" not in scheduler.seen_message_ids

    message["platform_user_id"] = USER_ID
    message["user_id"] = USER_ID
    asyncio.run(scheduler._tick(config, [message]))

    assert db.get_message("normal-retry")["processed"] == 1
    assert router.calls == []
    assert adapter.sent == []


def test_same_dom_index_with_distinct_platform_message_ids_replies_twice(tmp_path):
    _, adapter, _, router, scheduler, config = make_scheduler(tmp_path)

    asyncio.run(scheduler._tick(config, [make_message("first-id", source_index="202")]))
    asyncio.run(scheduler._tick(config, [make_message("changed-id", source_index="202")]))

    assert adapter.sent == ["已正确回复", "已正确回复"]
    assert len(router.calls) == 2


def test_normal_chat_can_award_item_without_entering_command_router(tmp_path, monkeypatch):
    db, adapter, _, router, scheduler, config = make_scheduler(tmp_path)
    db.ensure_requested_economy_items()
    config["features"]["normal_chat_item_drop_enabled"] = "true"
    config["features"]["normal_chat_item_drop_chance_percent"] = 100
    monkeypatch.setattr("app.database.random.random", lambda: 0.0)
    message = make_message("normal-chat-drop")
    message["text"] = "这是一条普通聊天"

    asyncio.run(scheduler._tick(config, [message]))

    assert len(adapter.sent) == 1
    assert "已放入背包" in adapter.sent[0]
    assert router.calls == []
    assert db.get_message("normal-chat-drop")["matched_rule"] == "普通聊天掉落"
    assert db.get_inventory({"platform_user_id": USER_ID})[0]["quantity"] == 1


def test_primed_dom_message_is_not_executed_when_its_generated_id_changes(tmp_path):
    _, adapter, _, router, scheduler, config = make_scheduler(tmp_path)

    asyncio.run(
        scheduler._prime_messages(
            [make_message("baseline-incomplete", user_id="", source_index="303")]
        )
    )
    asyncio.run(
        scheduler._tick(
            config,
            [make_message("baseline-complete", source_index="303")],
        )
    )

    assert adapter.sent == []
    assert router.calls == []


def test_adapter_rejects_crossed_api_id_and_dom_identity(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    db.ensure_user(make_message("known-1"))
    db.ensure_user(
        make_message(
            "known-2",
            sender="另一位用户",
            user_id=OTHER_USER_ID,
            avatar_id=OTHER_AVATAR_ID,
        )
    )
    adapter = DzmmAdapter(FakeBrowser(), db, FakeLogger())
    dom_message = {
        "sender": "另一位用户",
        "is_self": False,
        "raw_html": f'<img src="/avatar/{OTHER_AVATAR_ID}.png">',
    }
    wrong_platform_message = {
        "message_id": "wrong",
        "sent_by": USER_ID,
        "content": "/测试",
    }
    correct_platform_message = {
        "message_id": "correct",
        "sent_by": OTHER_USER_ID,
        "content": "/测试",
    }

    assert not adapter._platform_identity_matches_dom(
        dom_message,
        wrong_platform_message,
        allow_new_user=False,
    )
    assert adapter._platform_identity_matches_dom(
        dom_message,
        correct_platform_message,
        allow_new_user=False,
    )


def test_adapter_accepts_unique_message_when_existing_user_changed_name_and_avatar(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    db.ensure_user(
        make_message(
            "old-message",
            sender="飞火",
            user_id=USER_ID,
            avatar_id="",
        )
    )
    adapter = DzmmAdapter(FakeBrowser(), db, FakeLogger())
    dom_message = {
        "sender": "飞火[信众]",
        "is_self": False,
        "raw_html": f'<img src="/avatar/{AVATAR_ID}.png">',
    }
    platform_message = {
        "message_id": "unique-message",
        "sent_by": USER_ID,
        "content": "这是一条唯一文本",
    }

    assert adapter._platform_identity_matches_dom(
        dom_message,
        platform_message,
        allow_new_user=True,
    )


def test_adapter_accepts_platform_id_immediately_for_repeated_messages(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    db.ensure_user(
        make_message(
            "old-message",
            sender="飞火",
            user_id=USER_ID,
            avatar_id=AVATAR_ID,
        )
    )
    adapter = DzmmAdapter(FakeBrowser(), db, FakeLogger())
    dom_message = {
        "sender": "飞火[信众]",
        "is_self": False,
        "raw_html": f'<img src="/avatar/{AVATAR_ID}.png">',
    }

    first = adapter._platform_identity_matches_dom(
        dom_message,
        {"message_id": "repeat-1", "sent_by": USER_ID, "content": "/签到"},
        allow_new_user=False,
    )
    second = adapter._platform_identity_matches_dom(
        dom_message,
        {"message_id": "repeat-2", "sent_by": USER_ID, "content": "/签到"},
        allow_new_user=False,
    )

    assert first
    assert second


def test_adapter_discards_duplicate_dom_identity_paired_to_different_users():
    dom_messages = [
        {
            "text": "/加入",
            "sender": "第二位群友",
            "raw_html": f'<img src="/avatar/{AVATAR_ID}.png">',
        },
        {
            "text": "/加入",
            "sender": "第二位群友",
            "raw_html": f'<img src="/avatar/{AVATAR_ID}.png">',
        },
    ]
    matches = [
        {"message_id": "join-1", "sent_by": USER_ID, "content": "/加入"},
        {"message_id": "join-2", "sent_by": OTHER_USER_ID, "content": "/加入"},
    ]

    safe = DzmmAdapter._discard_ambiguous_identity_matches(dom_messages, matches)

    assert safe == [None, None]


def test_edited_marker_is_ignored_when_aligning_platform_identity():
    dom_messages = [{"text": "今晚参加比赛（已编辑）"}]
    api_messages = [
        {
            "message_id": "edited-message-id",
            "sent_by": USER_ID,
            "content": "今晚参加比赛",
        }
    ]

    matches = DzmmAdapter._align_platform_messages(dom_messages, api_messages)

    assert matches[0]["message_id"] == "edited-message-id"


def test_dom_observation_id_survives_virtual_list_index_change(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    adapter = DzmmAdapter(FakeBrowser(), db, FakeLogger())
    first = [{
        "sender": "测试用户",
        "text": "同一条消息（已编辑）",
        "is_self": False,
        "raw_html": f'<img src="/avatar/{AVATAR_ID}.png">',
        "data_index": "1001",
    }]
    second = [{**first[0], "data_index": "1016"}]

    first_ids, first_has_new = adapter._assign_dom_observation_ids("main", first)
    second_ids, second_has_new = adapter._assign_dom_observation_ids("main", second)

    assert first_has_new
    assert not second_has_new
    assert first_ids == second_ids


def test_unique_verified_avatar_uuid_can_restore_platform_identity(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    db.ensure_user(make_message("verified-user"))
    adapter = DzmmAdapter(FakeBrowser(), db, FakeLogger())

    user, reason = adapter._resolve_avatar_fallback(AVATAR_ID)

    assert reason == "unique"
    assert user["platform_user_id"] == USER_ID


def test_duplicate_avatar_uuid_is_blocked_and_logged_once(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    db.ensure_user(make_message("verified-user"))
    db.ensure_user(
        make_message(
            "other-verified-user",
            sender="另一位用户",
            user_id=OTHER_USER_ID,
            avatar_id=AVATAR_ID,
        )
    )
    logger = FakeLogger()
    adapter = DzmmAdapter(FakeBrowser(), db, logger)

    first, first_reason = adapter._resolve_avatar_fallback(AVATAR_ID)
    second, second_reason = adapter._resolve_avatar_fallback(AVATAR_ID)

    assert first is None and second is None
    assert first_reason == second_reason == "conflict"
    assert len([entry for entry in logger.entries if "对应多个" in entry[2]]) == 1


def test_avatar_fallback_message_executes_once_using_stored_platform_id(tmp_path):
    db, adapter, logger, router, scheduler, config = make_scheduler(tmp_path)
    db.ensure_user(make_message("seed-verified"))
    fallback = make_message("avatar-fallback")
    fallback["identity_source"] = "avatar_uuid"

    asyncio.run(scheduler._tick(config, [fallback]))
    asyncio.run(scheduler._tick(config, [fallback]))

    assert len(router.calls) == 1
    assert router.calls[0]["platform_user_id"] == USER_ID
    assert any("唯一头像UUID" in entry[2] for entry in logger.entries)


def test_duplicate_nickname_with_platform_id_routes_each_account(tmp_path):
    db, adapter, _, router, scheduler, config = make_scheduler(tmp_path)
    db.ensure_user(make_message("seed-1", sender="同名", user_id=USER_ID))
    db.ensure_user(make_message("seed-2", sender="同名", user_id=OTHER_USER_ID))
    third_user_id = "33333333-3333-3333-3333-333333333333"

    asyncio.run(
        scheduler._tick(
            config,
            [
                make_message("duplicate-command", sender="同名", user_id=USER_ID),
                make_message(
                    "normal-command",
                    sender="独立昵称",
                    user_id=third_user_id,
                    source_index="502",
                ),
            ],
        )
    )

    assert adapter.sent == ["已正确回复", "已正确回复"]
    assert [call["platform_user_id"] for call in router.calls] == [USER_ID, third_user_id]
    assert db.get_message("duplicate-command")["matched_rule"] == "测试"
    assert db.get_message("normal-command")["processed"] == 1
