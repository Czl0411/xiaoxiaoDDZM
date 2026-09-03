from __future__ import annotations

import random
import re
from datetime import datetime
from typing import Any

from app.chinese_text import to_simplified


TRIGGER_LABELS = {
    "exact": "完全匹配",
    "contains": "包含关键词",
    "startswith": "开头匹配",
    "endswith": "结尾匹配",
    "regex": "正则表达式",
    "any_keywords": "多关键词任意命中",
    "all_keywords": "多关键词全部命中",
}


class RuleEngine:
    def __init__(self, db):
        self.db = db

    def match_rules(self, message: dict[str, Any], user: str) -> list[dict[str, Any]]:
        results = []
        for rule in self.db.list_rules(enabled_only=True):
            matched, reason = self._match_one(rule, message, user)
            if matched:
                results.append({"rule": rule, "reason": reason})
        return results

    def test_rule(self, message: dict[str, Any], user: str) -> dict[str, Any]:
        details = []
        hits = []
        for rule in self.db.list_rules(enabled_only=False):
            matched, reason = self._match_one(rule, message, user, explain=True)
            blocked, block_reason = self.check_cooldown(rule, user, dry_run=True)
            item = {
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "enabled": bool(rule["enabled"]),
                "matched": matched,
                "reason": reason,
                "blocked": blocked,
                "block_reason": block_reason,
                "reply": "",
            }
            if matched and not blocked and rule["enabled"]:
                item["reply"] = self.render_reply(rule["reply_content"], self._context(rule, message, user))
                hits.append(item)
            details.append(item)
        return {"hits": hits, "details": details}

    def render_reply(self, template: str, context: dict[str, Any]) -> str:
        text = template
        text = text.replace("{user}", str(context.get("user", "")))
        text = text.replace("{message}", str(context.get("message", "")))
        text = text.replace("{time}", datetime.now().strftime("%H:%M"))
        text = text.replace("{date}", datetime.now().strftime("%Y-%m-%d"))
        text = text.replace("{count}", str(context.get("count", 0)))
        text = text.replace("{newline}", "\n")

        def replace_random(match: re.Match[str]) -> str:
            options = [x.strip() for x in match.group(1).split("|") if x.strip()]
            return random.choice(options) if options else ""

        return re.sub(r"\{random:([^{}]+)\}", replace_random, text)

    def pick_replies(self, rule: dict[str, Any], message: dict[str, Any]) -> list[str]:
        content = rule["reply_content"]
        mode = rule.get("reply_mode", "fixed")
        context = self._context(rule, message, message.get("sender", ""))
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if mode == "random":
            return [self.render_reply(random.choice(lines or [content]), context)]
        if mode == "sequence":
            source = lines or [content]
            index = self.db.get_sequence_index(rule["id"]) % len(source)
            self.db.set_sequence_index(rule["id"], index + 1)
            return [self.render_reply(source[index], context)]
        if mode == "multi":
            return [self.render_reply(line, context) for line in (lines or [content])]
        return [self.render_reply(content, context)]

    def check_cooldown(self, rule: dict[str, Any], user: str, dry_run: bool = False) -> tuple[bool, str]:
        daily_max = int(rule.get("daily_max_hits") or 0)
        if daily_max and self.db.get_rule_hit_count_today(rule["id"]) >= daily_max:
            return True, "已达到该规则每日最大触发次数"
        # Older rule editors copied the safety-wide interval into this field.
        # Treat that legacy value as a cooldown for this rule only, never as a
        # cooldown caused by unrelated replies such as an AI status message.
        rule_cd = max(
            int(rule.get("rule_cooldown_seconds") or 0),
            int(rule.get("global_cooldown_seconds") or 0),
        )
        if rule_cd:
            elapsed = self.db.recent_rule_hit_seconds(rule["id"])
            if elapsed is not None and elapsed < rule_cd:
                return True, f"规则冷却中，还需约 {int(rule_cd - elapsed)} 秒"
        user_cd = int(rule.get("user_cooldown_seconds") or 0)
        if user_cd:
            elapsed = self.db.recent_rule_hit_seconds(rule["id"], user)
            if elapsed is not None and elapsed < user_cd:
                return True, f"用户冷却中，还需约 {int(user_cd - elapsed)} 秒"
        return False, "未触发冷却"

    def update_rule_hit(self, rule: dict[str, Any], message: dict[str, Any], reason: str) -> None:
        self.db.record_rule_hit(rule["id"], message.get("message_id", ""), message, reason)

    def _context(self, rule: dict[str, Any], message: dict[str, Any], user: str) -> dict[str, Any]:
        return {"user": user, "message": message.get("text", ""), "count": int(rule.get("hit_count") or 0) + 1}

    def _match_one(self, rule: dict[str, Any], message: dict[str, Any], user: str, explain: bool = False) -> tuple[bool, str]:
        if not rule.get("enabled") and not explain:
            return False, "规则未启用"
        text = (message.get("text") or "").strip()
        trigger = (rule.get("trigger_value") or "").strip()
        triggers = self._split_triggers(trigger)
        normalized_text = to_simplified(text)
        normalized_triggers = [to_simplified(item) for item in triggers]
        trigger_type = rule.get("trigger_type", "exact")
        if not triggers:
            return False, "触发内容为空"
        if message.get("is_self") and not rule.get("allow_self"):
            return False, "默认不回复自己消息"
        scope_ok, scope_reason = self._check_scope(rule, user)
        if not scope_ok:
            return False, scope_reason
        if rule.get("require_admin"):
            if not self.db.is_admin_user(message):
                return False, "该命令仅管理员可用"
        try:
            if trigger_type == "exact":
                ok = any(normalized_text == item for item in normalized_triggers)
            elif trigger_type == "contains":
                ok = any(item in normalized_text for item in normalized_triggers)
            elif trigger_type == "startswith":
                ok = any(normalized_text.startswith(item) for item in normalized_triggers)
            elif trigger_type == "endswith":
                ok = any(normalized_text.endswith(item) for item in normalized_triggers)
            elif trigger_type == "regex":
                ok = (
                    re.search(trigger, text) is not None
                    or re.search(to_simplified(trigger), normalized_text) is not None
                )
            elif trigger_type == "any_keywords":
                ok = any(
                    to_simplified(k) in normalized_text
                    for k in self._split_keywords(trigger)
                )
            elif trigger_type == "all_keywords":
                ok = all(
                    to_simplified(k) in normalized_text
                    for k in self._split_keywords(trigger)
                )
            else:
                return False, f"未知触发类型：{trigger_type}"
        except re.error as exc:
            return False, f"正则表达式错误：{exc}"
        label = TRIGGER_LABELS.get(trigger_type, trigger_type)
        return (ok, f"{label}命中：{trigger}") if ok else (False, f"{label}未命中")

    def _split_triggers(self, value: str) -> list[str]:
        return [x.strip() for x in re.split(r"[,，\n]+", value or "") if x.strip()]

    def _split_keywords(self, value: str) -> list[str]:
        return [x.strip() for x in re.split(r"[,，\n]+", value) if x.strip()]

    def _check_scope(self, rule: dict[str, Any], user: str) -> tuple[bool, str]:
        if user in set(self._split_keywords(rule.get("exclude_users") or "")):
            return False, "用户在排除名单中"
        scope_type = rule.get("scope_type", "all")
        scope_value = rule.get("scope_value", "")
        if scope_type == "group_url" and scope_value:
            current = self.db.get_config().get("dzmm", {}).get("group_url", "")
            if scope_value.strip() != current.strip():
                return False, "不在指定群聊 URL 范围内"
        if scope_type == "user" and scope_value:
            if user not in set(self._split_keywords(scope_value)):
                return False, "不在指定用户范围内"
        return True, "范围允许"
