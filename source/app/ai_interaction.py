from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen


class AIInteractionError(RuntimeError):
    pass


def _flatten_response_text(value: Any) -> str:
    """Read provider text blocks without serializing provider metadata to chat."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "".join(part for item in value if (part := _flatten_response_text(item))).strip()
    if not isinstance(value, dict):
        return ""
    for key in ("text", "output_text", "value"):
        if isinstance(value.get(key), str):
            return str(value[key]).strip()
    for key in ("content", "parts", "delta", "message"):
        if key in value:
            text = _flatten_response_text(value.get(key))
            if text:
                return text
    return ""


def _first_response_text(data: Any) -> tuple[str, bool]:
    """Return visible answer text and whether a reasoning-only fallback was used."""
    if not isinstance(data, dict):
        return "", False
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        for value in (
            message.get("content"),
            message.get("output_text"),
            choice.get("text"),
            choice.get("content"),
        ):
            text = _flatten_response_text(value)
            if text:
                return text, False
        for value in (message.get("reasoning_content"), choice.get("reasoning_content")):
            text = _flatten_response_text(value)
            if text:
                return text, True
    for value in (data.get("output_text"), data.get("content")):
        text = _flatten_response_text(value)
        if text:
            return text, False
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            text = _flatten_response_text(item)
            if text:
                return text, False
    return "", False


def _usage_value(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


@dataclass
class DeepSeekClient:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    timeout_seconds: float = 20.0

    def generate_response(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 1.1,
        max_tokens: int = 500,
        max_output_chars: int = 800,
        thinking: bool = False,
        messages: list[dict[str, str]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> "AIInteractionResponse":
        api_key = (self.api_key or "").strip()
        if not api_key:
            raise AIInteractionError("DeepSeek API 密钥尚未配置")
        endpoint = f"{(self.base_url or 'https://api.deepseek.com').rstrip('/')}/chat/completions"
        request_messages = messages or [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        payload: dict[str, Any] = {
            "model": (self.model or "deepseek-v4-flash").strip(),
            "messages": request_messages,
            "stream": False,
            "thinking": {"type": "enabled" if thinking else "disabled"},
            "temperature": max(0.0, min(float(temperature), 2.0)),
            "max_tokens": max(32, min(int(max_tokens), 4096)),
        }
        if response_format is not None:
            payload["response_format"] = response_format
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            timeout = max(3.0, float(self.timeout_seconds))
            if urlparse(endpoint).hostname == "api.deepseek.com":
                try:
                    direct_opener = build_opener(ProxyHandler({}))
                    response_context = direct_opener.open(request, timeout=timeout)
                except HTTPError:
                    raise
                except (URLError, TimeoutError, OSError):
                    response_context = urlopen(request, timeout=timeout)
            else:
                response_context = urlopen(request, timeout=timeout)
            with response_context as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(500).decode("utf-8", errors="ignore")
            except Exception:
                pass
            raise AIInteractionError(
                f"DeepSeek 请求失败（HTTP {exc.code}）{': ' + detail if detail else ''}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise AIInteractionError(f"DeepSeek 连接失败：{exc}") from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise AIInteractionError("DeepSeek 返回了无法解析的数据") from exc

        content, from_reasoning = _first_response_text(data)
        if not content:
            raise AIInteractionError("DeepSeek 没有生成可用内容")
        limit = max(80, min(int(max_output_chars), 16000))
        usage = data.get("usage") if isinstance(data, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        prompt_tokens = _usage_value(usage, "prompt_tokens", "input_tokens", "prompt_token_count")
        completion_tokens = _usage_value(usage, "completion_tokens", "output_tokens", "completion_token_count")
        return AIInteractionResponse(
            content=content[:limit].strip(),
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            model=str(data.get("model") or payload["model"]),
            from_reasoning=from_reasoning,
        )

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 1.1,
        max_tokens: int = 500,
        max_output_chars: int = 800,
        thinking: bool = False,
        messages: list[dict[str, str]] | None = None,
    ) -> str:
        """Backward-compatible text-only wrapper used by existing features."""
        return self.generate_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            max_output_chars=max_output_chars,
            thinking=thinking,
            messages=messages,
        ).content


@dataclass(frozen=True)
class AIInteractionResponse:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    model: str
    from_reasoning: bool = False
