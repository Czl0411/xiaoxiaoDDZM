from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.outgoing_text import MAX_OUTGOING_LINES, normalize_outgoing_text, outgoing_line_count


@dataclass(frozen=True)
class HelpEntry:
    category: str
    command: str
    aliases: tuple[str, ...]
    summary: str
    example: str
    details: tuple[str, ...]
    permission: str
    scope: str
    show: bool
    order: int
    menu_group: int
    source: str = "builtin"


@dataclass(frozen=True)
class HelpCategory:
    key: str
    title: str
    root_summary: str
    aliases: tuple[str, ...]
    order: int


@dataclass(frozen=True)
class HelpResponse:
    replies: tuple[str, ...]
    name: str
    reason: str


CATEGORIES: tuple[HelpCategory, ...] = (
    HelpCategory("日常", "✨ 日常与功德", "祈福、功德、工资、塔罗牌", ("功德", "经济"), 10),
    HelpCategory("物品", "🏛️ 商店与物品", "官方商店、背包、兑换", ("仓库", "商店"), 20),
    HelpCategory("委托", "🤝 群友委托所", "发布需求或服务、接单、完成、结算", ("群友委托所", "委托所"), 30),
    HelpCategory("互动", "🎭 AI与互动", "AI聊天、付费互动、偷窃、契约", ("AI", "契约"), 40),
    HelpCategory("RP", "⚜️ 沉浸RP", "上皮、加入、退队、括号规则、结束", ("rp", "角色扮演"), 50),
    HelpCategory("游戏", "🎲 游戏娱乐", "纸牌、圣裁、猜乳头", ("试炼",), 60),
    HelpCategory("资料", "📜 资料与排行", "个人状态、称呼、排行榜", ("个人", "排行"), 70),
    HelpCategory("规则", "📖 规则与帮助", "群规、玩法、帮助入口", ("群规", "文献"), 80),
)


HELP_ENTRIES: tuple[HelpEntry, ...] = (
    HelpEntry("日常", "/祈福", ("/签到", "/qd", "/祈祷", "/qf"), "领取每日奖励", "/祈福", (), "user", "main", True, 10, 10),
    HelpEntry("日常", "/功德点", ("/余额", "/金币", "/积分", "/我的积分", "/功德"), "查看余额", "/功德点", (), "user", "main", True, 20, 20),
    HelpEntry("日常", "/领取工资", ("/领工资",), "领取设施工资", "/领取工资", (), "user", "main", True, 30, 20),
    HelpEntry("日常", "/塔罗牌：事项", (), "抽牌占卜指定事项", "/塔罗牌：事业", (), "user", "main", True, 40, 30),
    HelpEntry("日常", "/乞讨", ("/要饭",), "尝试获得功德", "/乞讨", (), "user", "main", True, 50, 40),
    HelpEntry("日常", "/打赏 金额", ("/赏",), "打赏当前乞讨者", "/打赏 10", (), "user", "main", True, 60, 40),
    HelpEntry("日常", "/发福袋总额功德点份数个", (), "发布用户福袋", "/发福袋100功德点10个", (), "user", "main", True, 70, 50),
    HelpEntry("日常", "/领福袋", ("/抢红包",), "领取当前福袋", "/领福袋", (), "user", "main", True, 80, 50),

    HelpEntry("物品", "/神殿仓库", ("/商店", "/shop", "/仓库", "/sd", "/ck"), "查看商品和库存", "/神殿仓库", (), "user", "main", True, 10, 10),
    HelpEntry("物品", "/购买编号×数量", ("/买", "/buy"), "购买商品", "/购买1×2", (), "user", "main", True, 20, 20),
    HelpEntry("物品", "/背包", ("/库存", "/inventory"), "查看物品编号", "/背包", (), "user", "main", True, 30, 30),
    HelpEntry("物品", "/对称呼使用物品编号", (), "对他人使用", "/对大祭司使用物品1", (), "user", "main", True, 40, 40),
    HelpEntry("物品", "/使用物品编号", (), "对自己使用", "/使用物品1", (), "user", "main", True, 50, 50),
    HelpEntry("物品", "/兑换仓库", ("/兑换商店",), "查看兑换项目", "/兑换仓库", (), "user", "main", True, 60, 60),
    HelpEntry("物品", "/兑换编号", (), "按当前项目兑换", "/兑换1", (), "user", "main", True, 70, 70),
    HelpEntry("委托", "/需求：完整内容", (), "私聊分步发布需求", "/需求", (), "user", "direct", True, 10, 10),
    HelpEntry("委托", "/服务：完整内容", (), "私聊分步发布服务", "/服务", (), "user", "direct", True, 20, 10),
    HelpEntry("委托", "/确认发布｜/取消发布", (), "私聊确认或放弃当前草稿", "/确认发布", (), "user", "direct", True, 30, 20),
    HelpEntry("委托", "/查看需求｜/查看服务", (), "分别浏览两类委托，可在末尾加页码", "/查看服务2", (), "user", "bounty", True, 40, 30),
    HelpEntry("委托", "/需求详情D编号｜/服务详情S编号", (), "查看完整内容", "/需求详情D0001", (), "user", "bounty", True, 50, 30),
    HelpEntry("委托", "/接取需求D编号｜/购买服务S编号*数量", (), "接取需求或购买服务后生成O订单", "/购买服务S0001*2", (), "user", "bounty", True, 60, 40),
    HelpEntry("委托", "/我的订单｜/订单详情O编号", (), "在悬赏群查看本人订单", "/我的订单", (), "user", "bounty", True, 70, 40),
    HelpEntry("委托", "/完成订单O编号｜/确认订单O编号", (), "履约方完成、委托方确认", "/完成订单O0001", (), "user", "bounty", True, 80, 50),
    HelpEntry("委托", "/申请取消订单O编号", (), "申请双方取消并退款", "/申请取消订单O0001", (), "user", "bounty", True, 90, 60),
    HelpEntry("委托", "/同意取消订单O编号｜/拒绝取消订单O编号", (), "回应取消申请", "/同意取消订单O0001", (), "user", "bounty", True, 100, 60),
    HelpEntry("委托", "/我的委托｜/我的需求｜/我的服务", (), "私聊查看本人发布", "/我的服务", (), "user", "direct", True, 105, 65),
    HelpEntry("委托", "/关闭需求D编号｜/下架服务S编号", (), "私聊停止招募或出售", "/关闭需求D0001", (), "user", "direct", True, 110, 70),
    HelpEntry("委托", "/删除需求D编号｜/删除服务S编号", (), "私聊删除已结束且无未完成订单的发布", "/删除服务S0001", (), "user", "direct", True, 115, 70),
    HelpEntry("委托", "/补充库存S编号*数量｜/续期服务S编号*天数", (), "私聊管理库存和上架期限", "/补充库存S0001*5", (), "user", "direct", True, 120, 70),

    HelpEntry("互动", "/zz 内容", ("/zzs 内容",), "召唤当前AI角色；zzs为思考模式", "/zz 你好", ("普通模式使用/zz，复杂分析使用/zzs。", "空命令不调用AI也不收费。", "同一用户每30分钟最多5次；确认或取消业务草稿不计入。"), "user", "main", True, 10, 10),
    HelpEntry("互动", "/对称呼发起互动：事情", (), "发起付费互动", "/对小小发起互动：唱一首歌", (), "user", "main", True, 20, 20),
    HelpEntry("互动", "/开启付费互动", (), "允许他人互动", "/开启付费互动", (), "user", "main", True, 30, 30),
    HelpEntry("互动", "/关闭付费互动", (), "停止接收互动", "/关闭付费互动", (), "user", "main", True, 40, 30),
    HelpEntry("互动", "/偷窃 称呼", (), "按当前概率尝试偷窃", "/偷窃 大祭司", (), "user", "main", True, 50, 40),
    HelpEntry("互动", "/发起奴隶契约", (), "公开求主人或定向申请", "/发起奴隶契约 对方称呼 金额", (), "user", "main", True, 60, 50),
    HelpEntry("互动", "/招收奴隶", ("/收奴隶",), "公开招收或定向邀请", "/招收奴隶 对方称呼 金额", (), "user", "main", True, 70, 50),
    HelpEntry("互动", "/同意", (), "接受当前契约", "/同意", (), "user", "main", True, 80, 60),
    HelpEntry("互动", "/拒绝", (), "拒绝当前契约", "/拒绝", (), "user", "main", True, 90, 60),
    HelpEntry("互动", "/还款", (), "偿还当前债务", "/还款", (), "user", "main", True, 100, 60),

    HelpEntry("RP", "/上皮（1/总人数）", (), "发起5分钟集结", "/上皮（1/3）", (), "user", "main", True, 10, 10),
    HelpEntry("RP", "/加入", (), "加入当前RP集结", "/加入", (), "user", "main", True, 20, 20),
    HelpEntry("RP", "/退队", (), "单独退出当前RP结界", "/退队", (), "participant", "main", True, 30, 30),
    HelpEntry("RP", "/结束", (), "参与者或管理员结束RP", "/结束", (), "participant,admin", "main", True, 40, 30),

    HelpEntry("游戏", "/修女纸牌 金额", ("/zjh",), "单人纸牌", "/修女纸牌 10", (), "user", "main", True, 10, 10),
    HelpEntry("游戏", "/发起修女纸牌对战 金额", (), "发起多人纸牌", "/发起修女纸牌对战 10", (), "user", "main", True, 20, 20),
    HelpEntry("游戏", "/裁决", (), "发起六印圣裁", "/裁决", (), "user", "main", True, 30, 30),
    HelpEntry("游戏", "/圣裁状态", (), "查看当前圣裁", "/圣裁状态", (), "user", "main", True, 40, 40),
    HelpEntry("游戏", "/取消圣裁", (), "等待期由发起者取消", "/取消圣裁", (), "user", "main", True, 50, 40),
    HelpEntry("游戏", "/猜乳头", (), "成年虚构角色概率游戏", "/猜乳头", (), "user", "main", True, 60, 50),

    HelpEntry("资料", "/我", ("/me",), "查看个人资料", "/我", (), "user", "main", True, 10, 10),
    HelpEntry("资料", "/我的状态", (), "查看本人状态", "/我的状态", (), "user", "main", True, 20, 20),
    HelpEntry("资料", "/称呼的状态", (), "查看他人状态", "/大祭司的状态", (), "user", "main", True, 30, 20),
    HelpEntry("资料", "/我的称呼", (), "查看自定义称呼", "/我的称呼", (), "user", "main", True, 40, 30),
    HelpEntry("资料", "/自定义称呼 新称呼", ("/自定义昵称", "/自定义名称"), "修改称呼", "/自定义称呼 小祭司", (), "user", "main", True, 50, 30),
    HelpEntry("资料", "/功德榜", (), "查看功德排行", "/功德榜", (), "user", "main", True, 60, 40),
    HelpEntry("资料", "/互动排行榜", ("/每日互动榜", "/互动榜"), "查看互动排行", "/互动排行榜", (), "user", "main", True, 70, 40),
    HelpEntry("资料", "/公共设施", (), "查看当前设施与债务", "/公共设施", (), "user", "main", True, 80, 50),

    HelpEntry("规则", "/群规", (), "查看当前群规", "/群规", (), "user", "main", True, 10, 10, "rule"),
    HelpEntry("规则", "/玩法", (), "查看玩法总览", "/玩法", (), "user", "main", True, 20, 20),
    HelpEntry("规则", "/文献帮助", ("/文献指引", "/文献目录", "/教堂文献"), "查看资料入口", "/文献帮助", (), "user", "main", True, 30, 30, "rule"),
)


ROOT_HELP_ALIASES = frozenset({"/帮助", "/菜单", "/指引", "/圣殿帮助", "/教堂帮助", "/help"})
LEGACY_HELP_ALIASES: dict[str, str] = {
    "/个人帮助": "资料", "/个人指引": "资料", "/我的帮助": "资料", "/档案帮助": "资料",
    "/功德帮助": "日常", "/功德指引": "日常", "/经济帮助": "日常", "/金币帮助": "日常",
    "/仓库帮助": "物品", "/仓库指引": "物品", "/商店帮助": "物品", "/圣物帮助": "物品",
    "/试炼帮助": "游戏", "/试炼指引": "游戏", "/游戏帮助": "游戏", "/玩法帮助": "游戏",
    "/契约帮助": "互动", "/契约指引": "互动", "/奴隶契约帮助": "互动", "/奴隶帮助": "互动",
    "/群规帮助": "规则", "/群规指引": "规则", "/教堂群规": "规则", "/查看群规": "规则",
    "/阵营帮助": "规则", "/阵营指引": "规则", "/阵营说明": "规则", "/教堂阵营": "规则",
    "/文献帮助": "规则", "/文献指引": "规则", "/文献目录": "规则", "/教堂文献": "规则",
    "/忏悔洞帮助": "规则", "/忏悔洞指引": "规则", "/忏悔帮助": "规则", "/告解帮助": "规则",
    "/互动帮助": "互动", "/互动指引": "互动", "/群聊互动帮助": "互动", "/其他玩法帮助": "互动",
}
DETAILED_HELP_ALIASES: dict[str, str] = {
    "/RP帮助": "RP", "/rp帮助": "RP",
    "/塔罗牌帮助": "塔罗牌",
    "/猜乳头帮助": "猜乳头",
    "/偷窃帮助": "偷窃",
}


def _int_feature(features: dict[str, Any], key: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(features.get(key, default)))
    except (TypeError, ValueError):
        return default


def _category_key(value: str) -> str | None:
    candidate = str(value or "").strip()
    for category in CATEGORIES:
        if candidate == category.key or candidate.lower() in {alias.lower() for alias in category.aliases}:
            return category.key
    return None


def _menu_entry_text(entry: HelpEntry) -> str:
    return f"{entry.command}｜{entry.summary}"


def _category_lines(category_key: str) -> list[str]:
    category = next(item for item in CATEGORIES if item.key == category_key)
    entries = sorted(
        (item for item in HELP_ENTRIES if item.category == category_key and item.show),
        key=lambda item: (item.menu_group, item.order),
    )
    grouped: dict[int, list[str]] = {}
    for entry in entries:
        grouped.setdefault(entry.menu_group, []).append(_menu_entry_text(entry))
    lines = [category.title]
    lines.extend("；".join(grouped[group]) for group in sorted(grouped))
    return lines


def _root_menu() -> str:
    lines = ["⛪ 圣堂功能菜单"]
    for category in sorted(CATEGORIES, key=lambda item: item.order):
        lines.append(f"{category.key}：{category.root_summary}")
    lines.append("发送 /帮助 分类名 查看详细命令")
    return validate_menu_message("\n".join(lines))


def _direct_root_menu() -> str:
    return validate_menu_message("⛪ 私聊功能菜单\n委托所：/市场帮助")


def _secondary_menu(category_key: str, features: dict[str, Any]) -> str:
    lines = _category_lines(category_key)
    if category_key == "日常":
        cost = _int_feature(features, "fortune_cost", 20)
        daily = _int_feature(features, "fortune_daily_limit", 1, 1)
        lines.append(f"塔罗牌：每次{cost}功德｜每日{daily}次")
    elif category_key == "物品":
        lines.append("丝袜可购买或掉落；99个兑换内容以上方仓库为准")
    elif category_key == "委托":
        help_command = next(
            (part.strip() for part in re.split(r"[,，\n]+", str(features.get("commission_help_commands") or "/市场帮助,/委托帮助")) if part.strip()),
            "/市场帮助",
        )
        lines.append(f"完整规则：{help_command}")
    elif category_key == "互动":
        lines.append("详细规则：/帮助 偷窃")
    elif category_key == "RP":
        timeout = _int_feature(features, "rp_gather_timeout_seconds", 300, 1)
        maximum = min(10, _int_feature(features, "rp_max_participants", 10, 1))
        lines = [
            "⚜️ 沉浸RP",
            "/上皮（1/总人数）｜第一人发起",
            "/加入｜后续参与者统一加入",
            "/退队｜单独退出当前结界",
            f"人数1～{maximum}人｜{max(1, timeout // 60)}分钟内集齐开启",
            "参与者可正常推进剧情",
            "观众闲聊须完整放在（）或()内",
            "结界开启后仅/退队和/结束可用，其他/命令按违规记录",
            "首次违规黄牌；第二次记录并通知管理员；机器人不会自动踢人",
            "/结束｜参与者或管理员解除结界",
        ]
    elif category_key == "游戏":
        lines.append("详细规则：/帮助 猜乳头")
    elif category_key == "资料":
        lines.append("规则与资料入口：/帮助 规则")
    elif category_key == "规则":
        lines.extend(("格式：/帮助 分类名（如悬赏、RP、管理员）", "管理员分类仅管理员本人可见"))
    return validate_menu_message("\n".join(lines))


def _bounty_detail(features: dict[str, Any]) -> tuple[str, ...]:
    def command(key: str, fallback: str) -> str:
        raw = str(features.get(key) or fallback).strip()
        commands = [part.strip() for part in re.split(r"[,，\n]+", raw) if part.strip()]
        if key == "commission_help_commands" and "/市场帮助" in commands:
            return "/市场帮助"
        return commands[0] if commands else fallback

    ttl = max(1, _int_feature(features, "bounty_ai_draft_ttl_seconds", 600, 1) // 60)
    demand_publish = command("commission_request_publish_commands", "/需求")
    service_publish = command("commission_service_publish_commands", "/服务")
    confirm = command("commission_confirm_draft_commands", "/确认发布")
    cancel_draft = command("commission_cancel_draft_commands", "/取消发布")
    demand_list = command("commission_request_list_commands", "/查看需求")
    service_list = command("commission_service_list_commands", "/查看服务")
    demand_detail = command("commission_request_detail_commands", "/需求详情")
    service_detail = command("commission_service_detail_commands", "/服务详情")
    demand_take = command("commission_request_accept_commands", "/接取需求")
    service_buy = command("commission_service_accept_commands", "/购买服务")
    complete = command("commission_order_complete_commands", "/完成订单")
    settle = command("commission_order_confirm_commands", "/确认订单")
    cancel_order = command("commission_order_cancel_commands", "/申请取消订单")
    approve = command("commission_order_cancel_approve_commands", "/同意取消订单")
    reject = command("commission_order_cancel_reject_commands", "/拒绝取消订单")
    close_demand = command("commission_close_request_commands", "/关闭需求")
    close_service = command("commission_close_service_commands", "/下架服务")
    delete_demand = command("commission_delete_request_commands", "/删除需求")
    delete_service = command("commission_delete_service_commands", "/删除服务")
    restock = command("commission_service_restock_commands", "/补充库存")
    renew = command("commission_service_renew_commands", "/续期服务")
    first = "\n".join(
        (
            "🤝 群友委托所｜私聊发布",
            f"发布需求：私聊发送 {demand_publish}，机器人将逐步询问需要填写的内容",
            f"发布服务：私聊发送 {service_publish}，机器人将逐步询问需要填写的内容",
            "分步发布：每一步直接按提示回复，例如：标题、人数、50、3天",
            "填写操作：/上一步｜/取消发布；填错不会清空已有进度",
            f"草稿保留{ttl}分钟；{confirm} 后才正式发布或托管资金",
            f"{cancel_draft} 放弃草稿，不扣款",
        )
    )
    second = "\n".join(
        (
            "🤝 群友委托所｜悬赏群任务告示栏",
            f"{demand_list} 与 {service_list} 分开显示，每条消息最多9行",
            f"翻页直接加页码：{demand_list}2｜{service_list}2",
            f"详情：{demand_detail}D编号｜{service_detail}S编号",
            f"{demand_take}D编号 或 {service_buy}S编号*数量 后生成O订单",
            f"{complete}O编号｜履约方提交完成",
            f"{settle}O编号｜委托方确认并结算",
            f"{cancel_order}O编号｜另一方用{approve}或{reject}处理",
            "/我的订单｜/订单详情O编号",
        )
    )
    third = "\n".join(
        (
            "🤝 群友委托所｜私聊管理",
            "/我的委托｜/我的需求｜/我的服务",
            f"{close_demand}D编号｜退还未接名额的托管，已有订单继续",
            f"{close_service}S编号｜停止新购买，已有订单继续",
            f"{delete_demand}D编号｜{delete_service}S编号｜仅删除已结束且无未完成订单的发布",
            f"{restock}S编号*数量｜仅有限库存服务",
            f"{renew}S编号*天数｜延长上架有效期",
            "服务可重复购买；不限人数即不限库存；抽成从卖家收入扣除",
            "原有记录保留内容，并统一使用D、S、O编号。",
        )
    )
    return validate_detail_messages((first, second, third))


def commission_help_messages(features: dict[str, Any]) -> tuple[str, ...]:
    """返回委托所的三段帮助。

    该入口专供命令路由器调用，确保后台自定义命令后，帮助文案同步更新。
    """
    return _bounty_detail(features)


def _fortune_detail(features: dict[str, Any]) -> tuple[str, ...]:
    cost = _int_feature(features, "fortune_cost", 20)
    daily = _int_feature(features, "fortune_daily_limit", 1, 1)
    text = "\n".join(
        (
            "🔮 塔罗牌占卜帮助",
            "格式：/塔罗牌：你想占卜的内容",
            "示例：/塔罗牌：事业｜感情｜近期计划",
            "中文冒号、英文冒号或空格均可识别",
            "机器人会随机抽取一张牌和正逆位，再结合牌意完成解读",
            f"当前每次消耗{cost}功德，每人每日最多{daily}次",
            "图片或AI生成失败均不扣款、不占次数",
        )
    )
    return validate_detail_messages((text,))


def _nipple_detail(features: dict[str, Any]) -> tuple[str, ...]:
    base = _int_feature(features, "nipple_guess_base_bet", 100, 1)
    first = base * 3 // 2
    second = base * 3
    text = "\n".join(
        (
            "🎀 猜乳头帮助（成年虚构角色）",
            f"/猜乳头｜开始后冻结当前基础下注{base}功德",
            "第一回合：/1 左侧｜/2 右侧；成功概率1/2",
            f"猜中后：/1 收手，返还总额{first}功德",
            "猜中后：/2 继续，改猜第一轮相反侧",
            f"第二轮成功概率1/3，成功返还总额{second}功德",
            "任一失败只结算原始冻结，不额外扣潜在奖励",
            "返还总额已包含原始下注，不会重复退还或发奖",
            "下注从后台动态读取；已开始的局不受中途改价影响",
            "/1、/2只对发送者本人的当前游戏生效",
        )
    )
    return validate_detail_messages((text,))


def _theft_detail(features: dict[str, Any]) -> tuple[str, ...]:
    daily = _int_feature(features, "theft_daily_limit", 2, 1)
    rate = min(100, _int_feature(features, "theft_success_rate", 50))
    text = "\n".join(
        (
            "🧤 偷窃帮助",
            "格式：/偷窃 对方昵称或自定义称呼",
            f"当前普通成功率{rate}%｜每天最多尝试{daily}次",
            "当前规则未设置额外时间冷却，以每日次数为准",
            "成功金额不超过10功德：不收贿赂",
            "成功金额超过10功德：收取10%，向下取整",
            "贿赂直接销毁，不进入任何用户账户",
            "偷窃者实得=成功金额-贿赂",
            "余额、保护道具和失败赔偿按当前真实规则结算",
        )
    )
    return validate_detail_messages((text,))


def _admin_help() -> str:
    return validate_menu_message(
        "\n".join(
            (
                "🛡️ 管理员帮助",
                "/管理员福袋总额功德点份数个｜系统福袋",
                "/赠送 称呼 金额｜调整奖励",
                "/罚款 称呼 金额｜执行罚款",
                "后台悬赏：按状态查看、编辑和安全取消",
                "后台RP：查看待处理违规，标记处理或忽略",
                "后台游戏：配置猜乳头基础下注",
                "后台塔罗牌：配置金额、次数、提示词和固定回复",
                "后台只允许当前真实权限，不可改参与者唯一ID",
            )
        ),
        allow_admin=True,
    )


def validate_menu_message(text: str, *, allow_admin: bool = False) -> str:
    normalized = normalize_outgoing_text(text)
    if not normalized:
        raise ValueError("菜单不能为空")
    lines = normalized.split("\n")
    if outgoing_line_count(normalized) > MAX_OUTGOING_LINES:
        raise ValueError(f"菜单超过{MAX_OUTGOING_LINES}行")
    if any(not line.strip() for line in lines):
        raise ValueError("菜单不能包含空白行")
    if any(token in normalized for token in ("/下一页", "/上一页", "查看更多")):
        raise ValueError("菜单不能使用翻页")
    if not allow_admin and any(token in normalized for token in ("/管理员福袋", "/赠送", "/罚款", "数据库维护", "系统重启")):
        raise ValueError("普通用户菜单泄露管理员能力")
    commands = re.findall(r"/[A-Za-z0-9\u4e00-\u9fff]+", normalized)
    duplicates = {command for command in commands if commands.count(command) > 1}
    if duplicates:
        raise ValueError(f"菜单存在重复命令：{','.join(sorted(duplicates))}")
    return normalized


def validate_detail_messages(messages: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(normalize_outgoing_text(message) for message in messages)
    if not 1 <= len(normalized) <= 3:
        raise ValueError("详细帮助只能发送一至三条")
    if any(not message for message in normalized):
        raise ValueError("详细帮助不能为空")
    if any(outgoing_line_count(message) > MAX_OUTGOING_LINES for message in normalized):
        raise ValueError(f"详细帮助单条超过{MAX_OUTGOING_LINES}行")
    return normalized


def resolve_help_request(text: str, features: dict[str, Any], *, is_admin: bool, is_direct: bool = False) -> HelpResponse | None:
    stripped = str(text or "").strip()
    if stripped in DETAILED_HELP_ALIASES:
        topic = DETAILED_HELP_ALIASES[stripped]
    elif stripped in LEGACY_HELP_ALIASES:
        topic = LEGACY_HELP_ALIASES[stripped]
    elif stripped == "/游戏":
        topic = "游戏"
    elif stripped == "/玩法":
        topic = "规则"
    elif stripped == "/使用物品":
        topic = "物品"
    else:
        match = re.fullmatch(r"/(?:帮助|help|菜单|指引|圣殿帮助|教堂帮助)(?:\s+(.+?))?\s*", stripped, re.I)
        if not match:
            return None
        topic = (match.group(1) or "").strip()
        if not topic:
            return HelpResponse(((_direct_root_menu() if is_direct else _root_menu()),), "帮助", "查看一级菜单")

    lowered = topic.lower()
    if lowered == "管理员":
        if not is_admin:
            return HelpResponse(("没有找到该帮助分类，请发送 /帮助 查看当前菜单。",), "帮助", "普通用户无管理员帮助权限")
        return HelpResponse((_admin_help(),), "管理员帮助", "查看管理员帮助")
    if lowered == "塔罗牌":
        return HelpResponse(_fortune_detail(features), "塔罗牌帮助", "查看详细帮助")
    if lowered == "猜乳头":
        return HelpResponse(_nipple_detail(features), "猜乳头帮助", "查看详细帮助")
    if lowered == "偷窃":
        return HelpResponse(_theft_detail(features), "偷窃帮助", "查看详细帮助")
    if topic == "委托详细":
        return HelpResponse(_bounty_detail(features), "委托帮助", "查看详细帮助")
    category = _category_key(topic)
    if category:
        return HelpResponse((_secondary_menu(category, features),), f"{category}帮助", "查看二级菜单")
    return HelpResponse(("没有找到该帮助分类，请发送 /帮助 查看当前菜单。",), "帮助", "未知帮助分类")
