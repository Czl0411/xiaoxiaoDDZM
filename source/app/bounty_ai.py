from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


SYSTEM_PROMPT = """你是群友委托所的自然语言解析器，只能输出一个JSON对象，不得解释、不得调用工具。
字段固定为task_type、duration_days、required_count、unlimited_stock、reward_per_person、content、missing_fields、parse_success。
task_type只能是single或duration。持续任务天数1到10；需求所需人数1到10；服务库存可限制1到999份，也可不限库存；每人奖励或每份价格为正整数。
服务原文中的“商品数量”“数量”“库存”“限N人”都表示可售库存。原文明示“不限人数”“不限名额”“数量不限”“无限库存”“任何人都可以买”等意思时，必须输出unlimited_stock=true、required_count=1，且不得把required_count列为缺失。其他情况输出unlimited_stock=false。
原文出现“单次”“做一次”“完成一次”，或明确只做一件一次性事情（如唱一首歌、做一个动作），且没有持续/连续/每天/N天时，必须输出task_type=single、duration_days=null；单次任务绝不能把duration_days列为缺失。
严禁猜测缺失信息；总额与每人金额不明确时必须失败并把reward_per_person列入missing_fields。
content只保留参与者要完成的事，不扩写、不改变原意。任何重要缺失或歧义都令parse_success=false。"""


FIELD_LABELS = {
    "required_count": "所需人数",
    "task_type": "任务类型",
    "duration_days": "持续天数",
    "reward_per_person": "每人奖励",
    "content": "具体任务内容",
    "bounty_mode": "悬赏类型",
}


@dataclass(frozen=True)
class BountyDraftData:
    task_type: str
    duration_days: int | None
    required_count: int
    reward_per_person: int
    content: str
    bounty_mode: str = "request"
    unlimited_stock: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "duration_days": self.duration_days,
            "required_count": self.required_count,
            "reward_per_person": self.reward_per_person,
            "content": self.content,
            "bounty_mode": self.bounty_mode,
            "unlimited_stock": self.unlimited_stock,
            "missing_fields": [],
            "parse_success": True,
        }


class BountyParseError(ValueError):
    def __init__(self, missing_fields: list[str] | None = None, *, ambiguity: bool = False):
        self.missing_fields = list(dict.fromkeys(missing_fields or []))
        self.ambiguity = ambiguity
        super().__init__(self.reply())

    def reply(self) -> str:
        if self.ambiguity:
            return "悬赏暂时无法建立：无法确定功德是总金额还是每人奖励。请重新编辑整条悬赏内容，明确写出“每人多少功德”后再次发送。"
        if self.missing_fields == ["task_type"] or set(self.missing_fields) == {"task_type", "duration_days"}:
            return "悬赏暂时无法建立：无法确定这是单次任务还是持续任务。请重新编辑整条悬赏内容，写明“单次”或“持续几天”后再次发送。"
        labels = [FIELD_LABELS.get(field, field) for field in self.missing_fields]
        missing = "、".join(labels) if labels else "必要信息"
        return f"悬赏暂时无法建立：缺少{missing}。请重新编辑整条悬赏内容，补全后再次发送。"


def _extract_json(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        raise BountyParseError()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.I | re.S)
    candidate = fenced.group(1) if fenced else ""
    if not candidate:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise BountyParseError()
        candidate = text[start : end + 1]
    try:
        value = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BountyParseError() from exc
    if not isinstance(value, dict):
        raise BountyParseError()
    return value


def validate_ai_result(
    raw: str, *, explicit_single: bool = False, explicit_unlimited: bool = False,
    expected_mode: str | None = None,
) -> BountyDraftData:
    value = _extract_json(raw)
    if expected_mode in {"request", "service"}:
        value["bounty_mode"] = expected_mode
    missing = value.get("missing_fields")
    if not isinstance(missing, list) or any(not isinstance(item, str) for item in missing):
        missing = []
    if explicit_single:
        value["task_type"] = "single"
        value["duration_days"] = None
        missing = [field for field in missing if field not in {"task_type", "duration_days"}]
        value["missing_fields"] = missing
        if not missing:
            value["parse_success"] = True
    if explicit_unlimited:
        value["unlimited_stock"] = True
        value["required_count"] = 1
        missing = [field for field in missing if field != "required_count"]
        value["missing_fields"] = missing
        if not missing:
            value["parse_success"] = True
    if value.get("parse_success") is not True:
        ambiguity = bool(value.get("amount_ambiguous")) or (
            "reward_per_person" in missing and "总" in str(value.get("content") or "")
        )
        raise BountyParseError(missing, ambiguity=ambiguity)
    task_type = value.get("task_type")
    duration = value.get("duration_days")
    mode = str(value.get("bounty_mode") or "request").strip().lower()
    unlimited_stock = value.get("unlimited_stock") is True
    if unlimited_stock and mode != "service":
        raise BountyParseError(["required_count"])
    count = 1 if unlimited_stock else value.get("required_count")
    reward = value.get("reward_per_person")
    content = value.get("content")
    invalid: list[str] = []
    if task_type not in {"single", "duration"}:
        invalid.append("task_type")
    maximum_count = 999 if mode == "service" else 10
    if type(count) is not int or not 1 <= count <= maximum_count:
        invalid.append("required_count")
    if type(reward) is not int or not 1 <= reward <= 100000:
        invalid.append("reward_per_person")
    if not isinstance(content, str) or not content.strip() or len(content.strip()) > 500:
        invalid.append("content")
    if task_type == "duration":
        if type(duration) is not int or not 1 <= duration <= 10:
            invalid.append("duration_days")
    elif duration not in {None, 0}:
        invalid.append("duration_days")
    if invalid:
        raise BountyParseError(invalid)
    if mode not in {"request", "service"}:
        raise BountyParseError(["bounty_mode"])
    return BountyDraftData(
        task_type, duration if task_type == "duration" else None, count,
        reward, content.strip(), mode, unlimited_stock,
    )


def user_prompt(original: str) -> str:
    return "解析下面完整悬赏原文并只返回固定JSON：\n" + str(original or "").strip()
