from __future__ import annotations

from app.database import Database


def test_paid_interaction_mojibake_is_repaired_losslessly_and_idempotently(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    config = db.get_config()
    original = "本次互动生成失败，未扣除任何 {currency}，请稍后再试。"
    custom_prompt = "保留我的自定义提示词：{user} 与 {target}"
    config["features"]["paid_interaction_ai_error_reply"] = (
        original.encode("utf-8").decode("latin-1")
    )
    config["features"]["paid_interaction_ai_system_prompt"] = (
        custom_prompt.encode("utf-8").decode("latin-1")
    )
    config["features"]["unrelated_text"] = (
        "不应处理".encode("utf-8").decode("latin-1")
    )
    db.save_config(config)

    repaired = db.repair_paid_interaction_mojibake()
    loaded = db.get_config()

    assert set(repaired) == {
        "paid_interaction_ai_error_reply",
        "paid_interaction_ai_system_prompt",
    }
    assert loaded["features"]["paid_interaction_ai_error_reply"] == original
    assert loaded["features"]["paid_interaction_ai_system_prompt"] == custom_prompt
    assert loaded["features"]["unrelated_text"] != "不应处理"
    assert db.repair_paid_interaction_mojibake() == []


def test_paid_interaction_repair_ignores_normal_unicode(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    config = db.get_config()
    config["features"]["paid_interaction_ai_error_reply"] = "正常中文回复"
    db.save_config(config)

    assert db.repair_paid_interaction_mojibake() == []
    assert db.get_config()["features"]["paid_interaction_ai_error_reply"] == "正常中文回复"
