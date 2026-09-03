from __future__ import annotations

import json

from app.command_router import CommandRouter
from app.database import Database
from app.random_event_ai import validate_ai_result


ADMIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
U1 = "11111111-1111-1111-1111-111111111111"
U2 = "22222222-2222-2222-2222-222222222222"


def msg(uid: str, name: str, text: str, mid: str, group: str = "main") -> dict:
    return {
        "platform_user_id": uid,
        "user_id": uid,
        "sender": name,
        "text": text,
        "message_id": mid,
        "group_key": group,
        "source_group": group,
        "is_self": False,
    }


class FakeAI:
    output = ""
    last_kwargs = {}

    def __init__(self, **_kwargs):
        pass

    def generate(self, **_kwargs):
        type(self).last_kwargs = _kwargs
        return self.output


def make_db(tmp_path) -> Database:
    db = Database(tmp_path / "bot.db")
    db.init()
    db.set_secret("deepseek_api_key", "test")
    for uid, name in ((ADMIN, "管理员"), (U1, "甲"), (U2, "乙")):
        db.ensure_user(msg(uid, name, "初始化", f"init:{uid}"))
    db.conn.execute("update users set is_admin=1 where platform_user_id=?", (ADMIN,))
    db.conn.commit()
    return db


def event_ai_json() -> str:
    return json.dumps(
        {
            "title": "深夜来客",
            "content": "深夜的修道院突然响起敲门声，修女与神秘访客需要在封闭的大门前完成一场身份试探。",
            "roles": [
                {"number": 1, "name": "正式修女", "gender": "女", "description": "看守修道院并调查访客目的"},
                {"number": 2, "name": "神秘访客", "gender": "男", "description": "隐瞒身份并尝试进入禁区"},
            ],
            "needs_clarification": False,
            "missing": [],
        },
        ensure_ascii=False,
    )


def test_complete_random_event_keeps_original_text_even_if_ai_summarizes():
    original = "第一幕里，两位角色在雨夜相遇。" * 30
    raw = json.dumps(
        {
            "title": "雨夜相遇",
            "content": "两人在雨夜相遇并展开试探。",
            "roles": [
                {"number": 1, "name": "守夜人", "gender": "不限", "description": "守住大门并查明来意"},
                {"number": 2, "name": "来访者", "gender": "不限", "description": "说明来意并争取进入"},
            ],
            "rewrite_required": False,
            "needs_clarification": False,
            "missing": [],
        },
        ensure_ascii=False,
    )

    parsed = validate_ai_result(raw, original_content=original)

    assert parsed.content == original


def test_incomplete_random_event_accepts_only_non_shorter_reconstruction():
    original = "守夜人。陌生人。门口。" * 3
    expanded = "雨夜里，守夜人发现一名陌生人站在门口。守夜人需要查明对方来意，陌生人则要说明身份并争取进入。"
    base = {
        "title": "雨夜访客",
        "roles": [
            {"number": 1, "name": "守夜人", "gender": "不限", "description": "查明陌生人的来意"},
            {"number": 2, "name": "陌生人", "gender": "不限", "description": "解释身份并争取进入"},
        ],
        "rewrite_required": True,
        "needs_clarification": False,
        "missing": [],
    }
    parsed = validate_ai_result(
        json.dumps({**base, "content": expanded}, ensure_ascii=False),
        original_content=original,
    )
    protected = validate_ai_result(
        json.dumps({**base, "content": "雨夜相遇。"}, ensure_ascii=False),
        original_content=original,
    )

    assert parsed.content == expanded
    assert protected.content == original


def test_random_event_draft_programmatically_preserves_long_complete_source(tmp_path):
    db = make_db(tmp_path)
    original = "修女与来访者在封闭的礼拜堂里逐步调查钟声来源，并根据沿途线索确认彼此身份。" * 12
    FakeAI.output = event_ai_json()
    router = CommandRouter(db, ai_client_factory=FakeAI)

    result = router.handle(msg(ADMIN, "管理员", f"/创建随机事件：{original}", "long-draft"))
    draft = db.random_event_core.get_pending_draft(msg(ADMIN, "管理员", "", "inspect"))

    assert result.handled
    assert draft is not None
    assert draft["parsed"]["content"] == original
    assert "程序强制剧情保留协议" in FakeAI.last_kwargs["system_prompt"]


def test_random_event_ai_draft_numbered_join_rp_end_and_admin_reward(tmp_path):
    db = make_db(tmp_path)
    FakeAI.output = event_ai_json()
    router = CommandRouter(db, ai_client_factory=FakeAI)

    preview = router.handle(msg(ADMIN, "管理员", "/创建随机事件：深夜修道院双人剧情", "draft"))
    assert preview.handled and "深夜来客" in preview.replies[0] and "2人" in preview.replies[0]
    assert db.conn.execute("select count(*) from random_event_templates").fetchone()[0] == 0

    confirmed = router.handle(msg(ADMIN, "管理员", "/确认创建事件", "confirm"))
    assert "RE0001" in confirmed.replies[0]
    assert db.conn.execute("select count(*) from random_event_templates").fetchone()[0] == 1

    launched = router.handle(msg(ADMIN, "管理员", "/发起随机事件", "launch"))
    assert "招募进度：0/2" in launched.replies[0]
    session = db.random_event_core.get_current_session("main")
    assert session and session["current_count"] == 0
    assert session["started_by_user_id"] == ADMIN
    assert not session["participants"]

    joined_two = router.handle(msg(U1, "甲", "/加入2", "join2"))
    assert "神秘访客" in joined_two.replies[0] and "1/2" in joined_two.replies[0]
    taken = router.handle(msg(U2, "乙", "/加入2", "join2-taken"))
    assert "已经被其他群友选择" in taken.replies[0]

    opened = router.handle(msg(U2, "乙", "/加入", "join1"))
    assert opened.handled and "RP结界已自动开启" in opened.replies[0]
    session = db.random_event_core.get_current_session("main")
    assert session and session["status"] == "active" and session["rp_session_id"]
    rp = db.get_rp_session("main", ("active",))
    assert rp and rp["current_count"] == 2

    before = {uid: int(db.get_user(msg(uid, name, "", f"before:{uid}"))["points"]) for uid, name in ((U1, "甲"), (U2, "乙"))}
    ended = router.handle(msg(U1, "甲", "/结束", "end"))
    assert "管理员可发送 /奖励" in ended.replies[0]
    assert db.random_event_core.get_current_session("main") is None
    assert db.get_rp_session("main", ("active",)) is None
    assert {uid: int(db.get_user(msg(uid, name, "", f"after-end:{uid}"))["points"]) for uid, name in ((U1, "甲"), (U2, "乙"))} == before

    not_admin = router.handle(msg(U1, "甲", "/奖励100", "reward-no"))
    assert "仅限管理员" in not_admin.replies[0]
    rewarded = router.handle(msg(ADMIN, "管理员", "/奖励100", "reward"))
    assert "每人获得 100 功德" in rewarded.replies[0]
    for uid, name in ((U1, "甲"), (U2, "乙")):
        user = db.get_user(msg(uid, name, "", f"after-reward:{uid}"))
        assert int(user["points"]) == before[uid] + 100
        assert int(user["total_merit"]) >= 100
    duplicate = router.handle(msg(ADMIN, "管理员", "/奖励100", "reward-again"))
    assert "已经奖励过" in duplicate.replies[0]


def test_random_event_invalid_ai_never_saves_and_manual_library_edit(tmp_path):
    db = make_db(tmp_path)
    FakeAI.output = json.dumps({"needs_clarification": True, "missing": ["角色人数"]}, ensure_ascii=False)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    result = router.handle(msg(ADMIN, "管理员", "/创建随机事件：随便玩玩", "bad"))
    assert "还需要补充：角色人数" in result.replies[0]
    assert db.conn.execute("select count(*) from random_event_drafts").fetchone()[0] == 0

    template = db.random_event_core.save_template({
        "title": "后台事件",
        "content": "这是一段可以直接从后台创建并在群聊中发起的完整随机事件剧情。",
        "enabled": True,
        "roles": [
            {"name": "角色甲", "gender": "不限", "description": "完成第一部分剧情"},
            {"name": "角色乙", "gender": "不限", "description": "完成第二部分剧情"},
        ],
    })
    assert template["event_number"] == "RE0001" and template["role_count"] == 2


def test_random_event_schedule_and_regular_rp_remain_separate(tmp_path):
    db = make_db(tmp_path)
    assert db.random_event_core.schedule_times({
        "random_event_auto_times": "22:30,12:30,18:00",
        "random_event_auto_daily_count": 2,
    }) == ["12:30", "18:00"]
    router = CommandRouter(db)
    ordinary = router.handle(msg(U1, "甲", "/上皮（1/2）", "rp-start"))
    assert ordinary.handled and "1/2" in ordinary.replies[0]
    joined = router.handle(msg(U2, "乙", "/加入", "rp-join"))
    assert joined.handled and "RP结界" in joined.name
    assert db.random_event_core.get_current_session("main") is None
