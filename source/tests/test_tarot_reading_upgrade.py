from __future__ import annotations

import asyncio
from pathlib import Path

from app.database import Database
from app.scheduler import BotScheduler
from app.tarot_reading import TarotReadingService


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class FakeClient:
    calls = 0

    def __init__(self, **kwargs):
        pass

    def generate(self, **kwargs):
        type(self).calls += 1
        return "女祭司（正位）说明你目前更适合先观察和整理信息，再围绕事业目标稳步行动。" + "建议耐心核对计划。" * 160


class FakeAdapter:
    def __init__(self, *, image_ok=True):
        self.events = []
        self.image_ok = image_ok

    async def send_message(self, text, group_key="main"):
        self.events.append(("text", text))
        return True

    async def send_image(self, path, group_key="main"):
        self.events.append(("image", path))
        return self.image_ok


def make_db(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = Database(tmp_path / "bot.db")
    db.init()
    db.set_secret("deepseek_api_key", "test-key")
    return db


def make_message(db, text="/塔罗牌：事业"):
    msg = {
        "platform_user_id": "tarot-user",
        "user_id": "tarot-user",
        "sender": "测试用户",
        "message_id": "tarot-message",
        "text": text,
        "is_self": False,
        "group_key": "main",
        "source_group": "main",
        "time": "2026-08-23 12:00:00",
    }
    user = db.ensure_user(msg)
    db.add_points(user, 200, "测试初始化")
    db.save_message(msg)
    return msg, db.get_user(user)


def make_assets(tmp_path):
    assets = tmp_path / "塔罗牌素材"
    assets.mkdir()
    (assets / "女祭司-小旋风大王.png").write_bytes(b"not-an-image-needed-for-unit-test")
    return assets


def test_only_new_tarot_command_is_recognized():
    assert TarotReadingService.parse_command("/塔罗牌：事业").topic == "事业"
    assert TarotReadingService.parse_command("/塔罗牌 事业").topic == "事业"
    assert not TarotReadingService.parse_command("/今日运势：事业").matched
    assert not TarotReadingService.parse_command("/测运势：事业").matched
    assert not TarotReadingService.parse_command("/测字：事业").matched


def test_tarot_output_is_compact_card_bound_and_capped(tmp_path):
    FakeClient.calls = 0
    db = make_db(tmp_path)
    msg, _ = make_message(db)
    service = TarotReadingService(
        db, make_assets(tmp_path), ai_client_factory=FakeClient, random_source=lambda: 0
    )
    prepared = service.prepare(msg, service.parse_command(msg["text"]))
    assert prepared["ok"]
    assert prepared["orientation"] == "正位"
    assert prepared["image_path"].endswith("女祭司-小旋风大王.png")
    assert "女祭司" in prepared["draw_reply"] and "小旋风大王" in prepared["draw_reply"]
    body = service.generate(prepared)
    assert "女祭司" in body and "正位" in body
    assert "\n" not in body
    assert body.startswith("🔮 大祭司魔法追追解牌：")
    assert len(body) <= 600
    assert FakeClient.calls == 1


def test_staged_send_order_and_image_failure_never_charges(tmp_path):
    async def scenario(image_ok):
        FakeClient.calls = 0
        db = make_db(tmp_path / ("ok" if image_ok else "fail"))
        msg, user = make_message(db)
        adapter = FakeAdapter(image_ok=image_ok)
        service = TarotReadingService(
            db, make_assets(tmp_path / ("ok" if image_ok else "fail")),
            ai_client_factory=FakeClient,
            random_source=lambda: 0,
        )
        scheduler = BotScheduler(db, adapter, None, FakeLogger(), tarot_service=service)
        config = db.get_config()
        config.setdefault("dzmm", {})["send_delay_seconds"] = 0.001
        await scheduler._run_tarot_request(msg, service.parse_command(msg["text"]), config)
        balance = int(db.get_user(user)["points"])
        return adapter.events, balance, int(user["points"]), FakeClient.calls, db

    failed_events, failed_balance, failed_initial, failed_calls, _ = asyncio.run(scenario(False))
    assert [event[0] for event in failed_events[:1]] == ["image"]
    assert failed_events[-1][0] == "text"
    assert failed_balance == failed_initial
    assert failed_calls == 0

    ok_events, ok_balance, ok_initial, ok_calls, ok_db = asyncio.run(scenario(True))
    assert [event[0] for event in ok_events[:3]] == ["image", "text", "text"]
    assert ok_balance == ok_initial - 20
    assert ok_calls == 1
    row = ok_db.fortune_reading_stats()["recent"][0]
    assert row["card_name"] == "女祭司"
    assert row["orientation"] == "正位"
    stored = ok_db.conn.execute(
        "select result_text from fortune_readings where id=?", (row["id"],)
    ).fetchone()
    assert len(stored["result_text"]) <= 1000


def test_completed_reading_can_be_refunded_only_once(tmp_path):
    db = make_db(tmp_path)
    msg, user = make_message(db)
    initial = int(user["points"])
    service = TarotReadingService(
        db, make_assets(tmp_path), ai_client_factory=FakeClient, random_source=lambda: 0
    )
    prepared = service.prepare(msg, service.parse_command(msg["text"]))
    settled = service.settle(prepared, "女祭司（正位）的事业解读。")
    reading_id = settled["reading"]["id"]
    assert db.refund_fortune_reading(reading_id)
    assert not db.refund_fortune_reading(reading_id)
    assert int(db.get_user(user)["points"]) == initial
    assert db.count_today_fortune_readings(user) == 0


def test_custom_reader_identity_is_used_in_draw_prompt_and_final_prefix(tmp_path):
    db = make_db(tmp_path)
    config = db.get_config()
    config.setdefault("features", {}).update(
        {
            "fortune_reader_name": "小林（正式修女）",
            "fortune_draw_reply": "{reader}正在为{user}解读。",
            "fortune_ai_system_prompt": "你是{reader}。",
        }
    )
    db.save_config(config)
    msg, _ = make_message(db)
    service = TarotReadingService(
        db, make_assets(tmp_path), ai_client_factory=FakeClient, random_source=lambda: 0
    )

    prepared = service.prepare(msg, service.parse_command(msg["text"]))
    body = service.generate(prepared)

    assert prepared["reader"] == "小林（正式修女）"
    assert prepared["draw_reply"].startswith("小林（正式修女）正在")
    assert body.startswith("🔮 小林（正式修女）解牌：")


def test_connection_page_loads_and_binds_prompt_save_buttons():
    app_js = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert 'if (name === "connect")' in app_js
    assert "loadConnectionAiSettings()" in app_js
    assert '$("savePaidInteractionConnection").onclick' in app_js
    assert '$("saveFortuneSettingsConnection").onclick' in app_js
    assert "setConnectionAiSaveEnabled(false)" in app_js
