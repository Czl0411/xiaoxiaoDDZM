from __future__ import annotations

import json

import pytest

import app.ai_interaction as ai_interaction
from app.ai_interaction import DeepSeekClient
from app.database import Database
from app.embedded_secrets import decode_embedded_secret, encode_secret_for_embedding


class _Response:
    def __init__(self, payload=None):
        self.payload = payload or {"choices": [{"message": {"content": "ok"}}]}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("model", ["deepseek-v4-flash", "deepseek-v4-pro"])
def test_all_supported_models_force_thinking_disabled(monkeypatch, model):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(ai_interaction, "urlopen", fake_urlopen)
    result = DeepSeekClient(
        api_key="test-key",
        model=model,
        base_url="https://example.com",
    ).generate(
        system_prompt="system",
        user_prompt="user",
    )

    assert result == "ok"
    assert captured["payload"]["model"] == model
    assert captured["payload"]["thinking"] == {"type": "disabled"}


def test_json_object_response_format_is_forwarded(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr(ai_interaction, "urlopen", fake_urlopen)
    DeepSeekClient(api_key="test-key", base_url="https://example.com").generate_response(
        system_prompt="system",
        user_prompt="user",
        response_format={"type": "json_object"},
    )

    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_official_deepseek_host_uses_direct_connection_first(monkeypatch):
    calls = []

    class _Opener:
        def open(self, request, timeout):
            calls.append(("direct", request.full_url, timeout))
            return _Response()

    monkeypatch.setattr(ai_interaction, "build_opener", lambda *_args: _Opener())
    monkeypatch.setattr(
        ai_interaction,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("系统代理不应在直连成功时使用")
        ),
    )

    result = DeepSeekClient(api_key="test-key").generate(
        system_prompt="system",
        user_prompt="user",
    )

    assert result == "ok"
    assert calls and calls[0][0] == "direct"


def test_official_deepseek_host_falls_back_to_system_proxy(monkeypatch):
    calls = []

    class _FailingOpener:
        def open(self, request, timeout):
            calls.append(("direct", request.full_url, timeout))
            raise ai_interaction.URLError("direct unavailable")

    def fake_urlopen(request, timeout):
        calls.append(("proxy", request.full_url, timeout))
        return _Response()

    monkeypatch.setattr(
        ai_interaction, "build_opener", lambda *_args: _FailingOpener()
    )
    monkeypatch.setattr(ai_interaction, "urlopen", fake_urlopen)

    result = DeepSeekClient(api_key="test-key").generate(
        system_prompt="system",
        user_prompt="user",
    )

    assert result == "ok"
    assert [call[0] for call in calls] == ["direct", "proxy"]


def test_embedded_secret_round_trip_and_tamper_rejection():
    blob = encode_secret_for_embedding("test-secret", nonce=b"0123456789abcdef")
    assert decode_embedded_secret(blob) == "test-secret"
    assert decode_embedded_secret(blob[:-2] + "AA") == ""


def test_plaintext_secret_remains_available_in_development(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.set_secret("deepseek_api_key", "development-key")
    assert db.get_secret("deepseek_api_key") == "development-key"


def test_content_block_array_and_alternate_usage_fields_are_supported(monkeypatch):
    payload = {
        "model": "deepseek-v4-pro",
        "choices": [{"message": {"content": [{"type": "text", "text": "结构化正文"}]}}],
        "usage": {"input_tokens": 21, "output_tokens": 7},
    }
    monkeypatch.setattr(ai_interaction, "urlopen", lambda *_args, **_kwargs: _Response(payload))
    result = DeepSeekClient(
        api_key="test-key", base_url="https://example.com", model="deepseek-v4-pro"
    ).generate_response(system_prompt="system", user_prompt="user")
    assert result.content == "结构化正文"
    assert result.input_tokens == 21
    assert result.output_tokens == 7
    assert result.from_reasoning is False


def test_reasoning_only_response_is_marked_for_caller_to_block(monkeypatch):
    payload = {
        "choices": [{"message": {"content": None, "reasoning_content": "内部推理文本"}}]
    }
    monkeypatch.setattr(ai_interaction, "urlopen", lambda *_args, **_kwargs: _Response(payload))
    result = DeepSeekClient(api_key="test-key", base_url="https://example.com").generate_response(
        system_prompt="system", user_prompt="user"
    )
    assert result.content == "内部推理文本"
    assert result.from_reasoning is True
