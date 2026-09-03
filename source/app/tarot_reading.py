from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.ai_interaction import AIInteractionError, DeepSeekClient
from app.fortune_today import TODAY_FORTUNE_FEATURES, normalize_fortune_output


@dataclass(frozen=True)
class TarotCommand:
    matched: bool
    topic: str = ""


class TarotReadingService:
    """塔罗牌专用业务服务；调度器负责按图片、文字、AI、结果的顺序发送。"""

    COMMAND = "/塔罗牌"
    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

    def __init__(self, db, asset_dir: str | Path, *, ai_client_factory=None, random_source=None):
        self.db = db
        self.asset_dir = Path(asset_dir).resolve()
        self.ai_client_factory = ai_client_factory or DeepSeekClient
        self.random_source = random_source or random.random

    @classmethod
    def parse_command(cls, text: str) -> TarotCommand:
        value = str(text or "").strip()
        if not value.startswith(cls.COMMAND):
            return TarotCommand(False)
        tail = value[len(cls.COMMAND) :]
        if tail and not (tail[0].isspace() or tail[0] in ":："):
            return TarotCommand(False)
        topic = tail.strip()
        if topic.startswith((":", "：")):
            topic = topic[1:].strip()
        return TarotCommand(True, topic)

    def features(self) -> dict[str, Any]:
        stored = self.db.get_config().get("features", {})
        return {**TODAY_FORTUNE_FEATURES, **stored, "fortune_commands": self.COMMAND}

    @staticmethod
    def _enabled(value: Any) -> bool:
        return value if isinstance(value, bool) else str(value).strip().lower() != "false"

    @staticmethod
    def _render(template: Any, values: dict[str, Any]) -> str:
        result = str(template or "")
        for key, value in {"newline": "\n", **values}.items():
            result = result.replace("{" + key + "}", str(value))
        return result.strip()

    def _cards(self) -> list[dict[str, str]]:
        if not self.asset_dir.is_dir():
            return []
        cards: list[dict[str, str]] = []
        for path in sorted(self.asset_dir.iterdir(), key=lambda item: item.name):
            if not path.is_file() or path.suffix.lower() not in self.IMAGE_SUFFIXES:
                continue
            parts = path.stem.split("-", 1)
            cards.append(
                {
                    "card_name": parts[0].strip(),
                    "card_character": parts[1].strip() if len(parts) > 1 else "牌阵",
                    "image_path": str(path),
                    "image_filename": path.name,
                }
            )
        return [card for card in cards if card["card_name"]]

    def prepare(self, message: dict[str, Any], command: TarotCommand) -> dict[str, Any]:
        features = self.features()
        user = self.db.ensure_user(message)
        title = self.db.display_name(user)
        currency = str(features.get("currency_name") or "功德点")
        cost = max(1, min(100000, int(features.get("fortune_cost", 20) or 20)))
        daily_limit = max(1, min(100, int(features.get("fortune_daily_limit", 1) or 1)))
        reader = str(features.get("fortune_reader_name") or "大祭司魔法追追").strip()
        values = {
            "user": title,
            "topic": command.topic,
            "cost": cost,
            "currency": currency,
            "balance": int(user.get("points") or 0),
            "daily_limit": daily_limit,
            "reader": reader,
        }
        if not self._enabled(features.get("fortune_enabled", True)):
            return {"ok": False, "reply": self._render(features["fortune_disabled_reply"], values)}
        if not command.topic:
            return {"ok": False, "reply": self._render(features["fortune_usage_reply"], values)}
        if len(command.topic) > 40:
            return {"ok": False, "reply": self._render(features["fortune_topic_too_long_reply"], values)}
        if not (user.get("platform_user_id") or user.get("user_id")):
            return {"ok": False, "reply": self._render(features["fortune_identity_invalid_reply"], values)}
        if self.db.count_today_fortune_readings(user) >= daily_limit:
            return {"ok": False, "reply": self._render(features["fortune_already_reply"], values)}
        if int(user.get("points") or 0) < cost:
            return {"ok": False, "reply": self._render(features["fortune_no_money_reply"], values)}
        if not self.db.get_secret("deepseek_api_key"):
            return {"ok": False, "reply": self._render(features["fortune_ai_not_configured_reply"], values)}
        cards = self._cards()
        if not cards:
            self.db.add_log("ERROR", "tarot", f"塔罗牌素材目录为空或不存在：{self.asset_dir}")
            return {
                "ok": False,
                "reply": "塔罗牌素材暂时无法读取，本次没有扣除任何功德，请联系管理员检查素材目录。",
            }
        card = cards[min(int(float(self.random_source()) * len(cards)), len(cards) - 1)]
        orientation = "正位" if float(self.random_source()) < 0.5 else "逆位"
        values.update(card)
        values["orientation"] = orientation
        return {
            "ok": True,
            "features": features,
            "user": user,
            "title": title,
            "currency": currency,
            "cost": cost,
            "daily_limit": daily_limit,
            "reader": reader,
            "topic": command.topic,
            "orientation": orientation,
            **card,
            "draw_reply": self._render(features["fortune_draw_reply"], values),
        }

    def generate(self, prepared: dict[str, Any]) -> str:
        features = prepared["features"]
        values = {
            "user": prepared["title"],
            "topic": prepared["topic"],
            "card_name": prepared["card_name"],
            "card_character": prepared["card_character"],
            "orientation": prepared["orientation"],
            "date": datetime.now().strftime("%Y-%m-%d"),
            "cost": prepared["cost"],
            "currency": prepared["currency"],
            "reader": prepared["reader"],
        }
        client = self.ai_client_factory(
            api_key=self.db.get_secret("deepseek_api_key"),
            base_url=str(features.get("fortune_ai_base_url") or "https://api.deepseek.com"),
            model=str(features.get("fortune_ai_model") or "deepseek-v4-flash"),
            timeout_seconds=float(features.get("fortune_ai_timeout_seconds", 40) or 40),
        )
        generation_args = {
            "system_prompt": self._render(features.get("fortune_ai_system_prompt"), values),
            "user_prompt": self._render(features.get("fortune_ai_user_prompt"), values),
            "temperature": float(features.get("fortune_ai_temperature", 0.75) or 0.75),
            "max_tokens": int(features.get("fortune_ai_max_tokens", 1000) or 1000),
            "max_output_chars": min(1000, max(80, int(features.get("fortune_ai_max_output_chars", 900) or 900))),
        }
        last_error: Exception | None = None
        generated = ""
        for attempt in range(2):
            try:
                generated = client.generate(**generation_args)
                break
            except AIInteractionError as exc:
                last_error = exc
                self.db.add_log("WARNING", "tarot", f"塔罗牌 AI 第{attempt + 1}次请求失败：{str(exc)[:500]}")
        text = normalize_fortune_output(generated)
        if not text:
            raise AIInteractionError(str(last_error or "AI输出为空"))
        required = f"{prepared['card_name']}（{prepared['orientation']}）"
        if prepared["card_name"] not in text or prepared["orientation"] not in text:
            repair_values = {**values, "original": text}
            try:
                repaired = client.generate(
                    **{
                        **generation_args,
                        "user_prompt": self._render(
                            features.get("fortune_ai_repair_prompt"), repair_values
                        ),
                    }
                )
                repaired = normalize_fortune_output(repaired)
                if prepared["card_name"] in repaired and prepared["orientation"] in repaired:
                    text = repaired
            except AIInteractionError as exc:
                self.db.add_log("WARNING", "tarot", f"塔罗牌格式整理失败，改用本地兜底：{str(exc)[:500]}")
            if prepared["card_name"] not in text or prepared["orientation"] not in text:
                text = f"🔮 你抽到的是{required}。{text}"
        host_prefix = f"🔮 {prepared['reader']}解牌："
        if not text.startswith(host_prefix):
            text = host_prefix + text
        output_limit = min(
            1000,
            max(80, int(features.get("fortune_ai_max_output_chars", 600) or 600)),
        )
        return text[:output_limit].rstrip("，；、 ")

    def error_reply(self, prepared: dict[str, Any], key: str) -> str:
        return self._render(
            prepared["features"].get(key),
            {
                "user": prepared["title"],
                "topic": prepared["topic"],
                "cost": prepared["cost"],
                "currency": prepared["currency"],
                "balance": int(prepared["user"].get("points") or 0),
                "daily_limit": prepared["daily_limit"],
                "card_name": prepared["card_name"],
                "card_character": prepared["card_character"],
                "orientation": prepared["orientation"],
                "reader": prepared["reader"],
            },
        )

    def settle(self, prepared: dict[str, Any], body: str) -> dict[str, Any]:
        return self.db.complete_fortune_reading(
            prepared["user"],
            prepared["topic"],
            body,
            cost=prepared["cost"],
            daily_limit=prepared["daily_limit"],
            card_name=prepared["card_name"],
            card_character=prepared["card_character"],
            orientation=prepared["orientation"],
            image_filename=prepared["image_filename"],
        )

    def final_text(self, prepared: dict[str, Any], body: str, balance: int) -> str:
        footer = self._render(
            prepared["features"].get("fortune_settlement_footer"),
            {
                "user": prepared["title"],
                "cost": prepared["cost"],
                "currency": prepared["currency"],
                "balance": balance,
                "topic": prepared["topic"],
                "card_name": prepared["card_name"],
                "card_character": prepared["card_character"],
                "orientation": prepared["orientation"],
                "reader": prepared["reader"],
            },
        )
        body_budget = max(1, 1000 - len(footer) - (1 if footer else 0))
        compact_body = normalize_fortune_output(body)[:body_budget].rstrip("，；、 ")
        return " ".join(part for part in (compact_body, footer) if part).strip()[:1000]
