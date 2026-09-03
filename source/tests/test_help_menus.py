import re

from app.database import Database
from app.rule_engine import RuleEngine
from scripts.upsert_help_menus import GROUP_NAME, MENUS, compact_reply, rule_payload


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    return db


def install_help_menus(db):
    for menu in MENUS:
        db.create_rule(rule_payload(menu))


def test_help_menu_has_top_level_and_all_secondary_menus(tmp_path):
    db = make_db(tmp_path)
    install_help_menus(db)
    rules = [
        rule
        for rule in db.list_rules()
        if rule["group_name"] == GROUP_NAME
        and rule["name"] in {menu["name"] for menu in MENUS}
    ]

    assert len(rules) == 12
    assert all(rule["group_name"] == "指引组" for rule in rules)


def test_help_menu_uses_church_theme_and_contains_required_sections():
    all_replies = "\n".join(menu["reply"] for menu in MENUS)
    top_reply = MENUS[0]["reply"]

    assert "dzmm" not in all_replies.casefold()
    assert "机器人" not in all_replies
    for command in (
        "/群规帮助",
        "/阵营帮助",
        "/文献帮助",
        "/忏悔洞帮助",
        "/悬赏帮助",
    ):
        assert command in top_reply
    assert "委托" not in all_replies
    for command in (
        "/群规",
        "/文献",
        "/忏悔洞",
        "/发布悬赏令",
        "/查看悬赏",
        "/接悬赏",
        "/完成悬赏",
        "/确认完成",
    ):
        assert command in all_replies


def test_secondary_help_aliases_and_traditional_chinese_are_recognized(tmp_path):
    db = make_db(tmp_path)
    install_help_menus(db)
    engine = RuleEngine(db)

    for command in (
        "/帮助",
        "/教堂帮助",
        "/个人帮助",
        "/個人幫助",
        "/忏悔洞帮助",
        "/懺悔洞幫助",
        "/悬赏令帮助",
    ):
        hits = engine.match_rules(
            {"sender": "帮助测试者", "text": command, "is_self": False},
            "帮助测试者",
        )
        assert len(hits) == 1, command


def test_help_replies_are_compact_without_blank_lines():
    for menu in MENUS:
        reply = compact_reply(menu["reply"])
        assert "\n\n" not in reply
        assert all(line == line.strip() for line in reply.splitlines())
        assert not any(
            re.match(r"^(?:[^\w/]+\s*)?/", line)
            and "｜" not in line
            and index + 1 < len(reply.splitlines())
            and not reply.splitlines()[index + 1].startswith("/")
            for index, line in enumerate(reply.splitlines())
        )
