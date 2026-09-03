from __future__ import annotations

import asyncio
import base64
from io import BytesIO

from PIL import Image

from app.database import Database
from app.image_generation import (
    DEFAULT_IMAGE_SETTINGS,
    Image2Client,
    ImageGenerationService,
    ParsedImageCommand,
    parse_image_command,
)


USER_ID = "88888888-8888-8888-8888-888888888888"


def message(text: str, message_id: str = "image-message") -> dict:
    return {
        "platform_user_id": USER_ID,
        "user_id": USER_ID,
        "sender": "绘图用户",
        "text": text,
        "message_id": message_id,
        "group_key": "image",
        "source_group": "image",
        "is_self": False,
    }


def make_db(tmp_path) -> Database:
    db = Database(tmp_path / "bot.db")
    db.init()
    db.ensure_user(message("初始化", "init-user"))
    db.conn.execute("update users set points=100 where platform_user_id=?", (USER_ID,))
    config = db.get_config()
    config["image_generation"] = {
        **DEFAULT_IMAGE_SETTINGS,
        "cooldown_seconds": 0,
        "per_user_daily_limit": 0,
        "global_daily_limit": 0,
    }
    db.save_config(config)
    db.set_secret("image2_api_key", "test-image-key")
    return db


def test_image_commands_default_portrait_landscape_and_length_limit():
    settings = {**DEFAULT_IMAGE_SETTINGS, "max_prompt_chars": 5}
    default = parse_image_command("/sc 一只猫", settings)
    portrait = parse_image_command("/SC竖屏：人物", settings)
    landscape = parse_image_command("/SC横屏 海边", settings)
    too_long = parse_image_command("/SC 123456", settings)

    assert default.matched and default.prompt == "一只猫" and default.ratio == "3:4"
    assert portrait.matched and portrait.prompt == "人物" and portrait.ratio == "3:4"
    assert landscape.matched and landscape.prompt == "海边" and landscape.ratio == "16:9"
    assert too_long.matched and too_long.error == "too_long"


def test_image2_client_accepts_base64_and_verifies_real_image(tmp_path, monkeypatch):
    buffer = BytesIO()
    Image.new("RGB", (30, 40), "pink").save(buffer, "PNG")
    client = Image2Client("https://example.test/v1", "secret")
    monkeypatch.setattr(client, "_post", lambda payload: {"data": [{"b64_json": base64.b64encode(buffer.getvalue()).decode()}]})

    result = client.generate(prompt="cat", model="gpt-image-2", ratio="3:4", output_dir=tmp_path)

    assert result["width"] == 30 and result["height"] == 40
    assert result["format"] == "png" and result["path"].is_file()


def test_reserve_deduct_and_refund_are_transactional_and_idempotent(tmp_path):
    db = make_db(tmp_path)
    parsed = ParsedImageCommand(True, "猫", "3:4", "/SC")
    reserved = db.image_generation_core.reserve(message("/SC 猫"), parsed, db.get_config()["image_generation"])

    assert reserved["ok"] and reserved["cost"] == 20 and reserved["balance"] == 80
    first = db.image_generation_core.refund(reserved["job"]["job_id"], "测试失败")
    second = db.image_generation_core.refund(reserved["job"]["job_id"], "重复退款")
    user = db.get_user(message("检查", "inspect-user"))

    assert first["refunded"] and first["amount"] == 20
    assert second["refunded"] and second["amount"] == 20
    assert int(user["points"]) == 100
    refunds = db.conn.execute("select count(*) from transactions where reason like '图片生成退款：%'").fetchone()[0]
    assert refunds == 1


class FakeAdapter:
    def __init__(self):
        self.events = []

    async def send_message(self, text, group_key="main"):
        self.events.append(("text", group_key, text))
        return True

    async def send_image(self, path, group_key="main"):
        self.events.append(("image", group_key, path))
        return True


class FakeLogger:
    def info(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


def test_service_waits_for_image_upload_before_success_text(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    adapter = FakeAdapter()
    service = ImageGenerationService(db, adapter, FakeLogger(), tmp_path)

    def fake_generate(_self, *, prompt, model, ratio, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "result.png"
        Image.new("RGB", (300, 400), "pink").save(path, "PNG")
        return {"remote_task_id": "remote-1", "path": path, "width": 300, "height": 400, "format": "png", "file_size": path.stat().st_size}

    monkeypatch.setattr(Image2Client, "generate", fake_generate)

    async def run():
        assert await service.handle_message(message("/SC 一只可爱猫猫"))
        await asyncio.gather(*list(service.tasks.values()))

    asyncio.run(run())

    assert [event[0] for event in adapter.events] == ["text", "image", "text"]
    assert all(event[1] == "image" for event in adapter.events)
    job = db.image_generation_core.list_jobs()["items"][0]
    assert job["status"] == "completed" and job["send_success"]
    assert db.image_generation_core.get(job["job_id"])["image_path"]
