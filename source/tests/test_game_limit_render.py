from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.command_router import CommandRouter
from app.database import Database


def test_game_limit_reply_renders_limit_variables(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    router = CommandRouter(db)

    reply = router._render(
        "{user}，你最近 {window_minutes} 分钟内已玩了 {played} 次（上限 {max_plays} 次），请 {reset_seconds} 秒后再试。",
        "大祭司",
        "金币",
        {},
        {"window_minutes": 10, "played": 3, "max_plays": 3, "reset_seconds": 58},
    )

    assert reply == "大祭司，你最近 10 分钟内已玩了 3 次（上限 3 次），请 58 秒后再试。"
