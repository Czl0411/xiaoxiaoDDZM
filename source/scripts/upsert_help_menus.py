from __future__ import annotations

import argparse
import json
import re
from urllib.request import Request, urlopen


GROUP_NAME = "指引组"

TOP_LEVEL_REPLY = """⛪ 圣殿帮助目录 ⛪

迷途的教徒，请选择需要查阅的帮助：

👤 /个人帮助
个人档案、称呼、功德、状态与身份关系

✨ /功德帮助
祈福、工资、乞讨、赠送、打赏与功德福袋

🏛️ /仓库帮助
神殿仓库、购买圣物、背包与圣物使用

🎲 /试炼帮助
修女纸牌、群体对战及其他试炼玩法

⛓️ /契约帮助
奴隶契约、公开求主、招收、同意、拒绝与还款

📜 /群规帮助
教堂群规、行为准则与违规处理

⚜️ /阵营帮助
教堂阵营、加入方式与阵营资料

📚 /文献帮助
圣殿文献、人物记录与背景故事

🕯️ /忏悔洞帮助
忏悔洞、告解室与地下惩戒场所

⚔️ /悬赏帮助
发布、查看、接取、完成与取消悬赏

🎭 /互动帮助
偷窃、状态查询、称呼及其他群内互动

🔐 付费互动（默认关闭）
/开启付费互动：允许别人向自己发起
/关闭付费互动：拒绝别人向自己发起
/付费互动 对方称呼：向已开启的教徒发起

━━━━━━━━━━━━
发送对应命令进入二级帮助
发送 /帮助 可随时返回本目录
简体字与繁体字均可正常识别

愿圣光指引你的道路。🕊️"""


MENUS = [
    {
        "name": "圣殿帮助目录",
        "triggers": "/帮助,/菜单,/指引,/圣殿帮助,/教堂帮助,/help",
        "reply": TOP_LEVEL_REPLY,
        "priority": 100,
        "note": "一级帮助菜单，集中展示全部二级帮助入口。",
        "top_level": True,
    },
    {
        "name": "个人帮助",
        "triggers": "/个人帮助,/个人指引,/我的帮助,/档案帮助",
        "reply": """👤 个人帮助

/我 或 /me
查看个人档案、功德点、状态与契约关系

/功德点
查看当前功德点

/我的称呼
查看当前称呼

/自定义称呼 新称呼
修改自己的显示称呼

/我的状态
查看当前全部状态

/称呼的状态
查看其他教徒的状态，例如：/圣女的状态

/解除状态编号
解除允许主动移除的状态，例如：/解除状态1

/功德榜
查看圣·功德榜

发送 /帮助 返回圣殿帮助目录。""",
        "priority": 95,
        "note": "个人档案、称呼、状态与排行榜帮助。",
    },
    {
        "name": "功德帮助",
        "triggers": "/功德帮助,/功德指引,/经济帮助,/金币帮助",
        "reply": """✨ 功德帮助

/祈福
每日祈福并领取功德点

/功德点
查看当前功德点

/领取工资
领取昨天符合规则的工资

/乞讨
负债时尝试获得功德点

/打赏 金额
打赏最近一次成功乞讨的教徒

/赠送 对方称呼 金额
向指定教徒赠送功德点

/罚款 对方昵称或称呼 金额
管理员扣除指定教徒的功德点，例如：/罚款大祭司5

/付费互动 对方昵称或称呼
向已经开启接受功能的教徒支付固定功德点并发起互动

/开启付费互动
允许其他教徒向自己发起付费互动；所有人默认关闭

/关闭付费互动
关闭自己的付费互动接受功能

/发福袋 总额 份数
发布功德福袋

/领福袋
领取当前可用的功德福袋

/偷窃 对方称呼
尝试进行每日偷窃互动

发送 /帮助 返回圣殿帮助目录。""",
        "priority": 94,
        "note": "功德点获取、赠送、工资与福袋帮助。",
    },
    {
        "name": "仓库帮助",
        "triggers": "/仓库帮助,/仓库指引,/商店帮助,/圣物帮助",
        "reply": """🏛️ 仓库帮助

/神殿仓库
查看当前可领取的圣物

/购买编号
按仓库编号购买圣物，例如：/购买1

/购买 圣物名称
按名称购买指定圣物

/背包
查看已经持有的物品

/使用物品编号
对自己使用背包物品，例如：/使用物品1

/对称呼使用物品编号
对指定教徒使用物品，例如：/对圣女使用物品1

/使用物品
查看已有的物品使用说明

发送 /帮助 返回圣殿帮助目录。""",
        "priority": 93,
        "note": "神殿仓库、背包、购买与物品使用帮助。",
    },
    {
        "name": "试炼帮助",
        "triggers": "/试炼帮助,/试炼指引,/游戏帮助,/玩法帮助",
        "reply": """🎲 试炼帮助

/游戏
查看当前开放的试炼玩法

/玩法
查看群内玩法总览

/修女纸牌 金额
参加单人修女纸牌试炼

/发起修女纸牌对战 金额
发起多人纸牌试炼

/加入
加入当前等待中的多人试炼

试炼可能产生功德点得失，请在参加前确认下注金额。

发送 /帮助 返回圣殿帮助目录。""",
        "priority": 92,
        "note": "修女纸牌与群体试炼帮助。",
    },
    {
        "name": "契约帮助",
        "triggers": "/契约帮助,/契约指引,/奴隶契约帮助,/奴隶帮助",
        "reply": """⛓️ 契约帮助

/发起奴隶契约
负债者公开寻找愿意代偿的主人

/发起奴隶契约 主人称呼 金额
向指定主人发起借款契约

/招收奴隶
公开招收一名负债奴隶

/招收奴隶 对方称呼 金额
向指定教徒发起契约邀请

/同意
接受当前可处理的契约申请或公开悬赏

/拒绝
拒绝当前待确认的契约申请

/还款
一次性偿还欠款并解除契约

奴隶只能拥有一名主人；主人可拥有的奴隶数量以后台设置为准。

发送 /帮助 返回圣殿帮助目录。""",
        "priority": 91,
        "note": "奴隶契约、公开悬赏、同意与还款帮助。",
    },
    {
        "name": "群规帮助",
        "triggers": "/群规帮助,/群规指引,/教堂群规,/查看群规",
        "reply": """📜 群规帮助

/群规
查阅完整教堂群规与行为准则

进入教堂即视为愿意遵守群规。若规则内容发生更新，请以 /群规 显示的最新版本为准。

发送 /帮助 返回圣殿帮助目录。""",
        "priority": 90,
        "note": "教堂群规入口帮助。",
    },
    {
        "name": "阵营帮助",
        "triggers": "/阵营帮助,/阵营指引,/阵营说明,/教堂阵营",
        "reply": """⚜️ 阵营帮助

/加入阵营
查看阵营加入方式与当前可选阵营

/深渊教团
查阅深渊教团相关资料

其他阵营资料开放后也会收录在本页。

发送 /帮助 返回圣殿帮助目录。""",
        "priority": 89,
        "note": "阵营说明、加入方式与阵营资料帮助。",
    },
    {
        "name": "文献帮助",
        "triggers": "/文献帮助,/文献指引,/文献目录,/教堂文献",
        "reply": """📚 文献帮助

/文献
查看当前收录的圣殿文献目录

/【圣女的手抄本】001卷
查阅圣女手抄本文献第一卷

/【圣女的手抄本】002卷
查阅圣女手抄本文献第二卷

/淫光大教堂
查阅教堂背景故事

人物档案可直接发送人物对应命令查阅，例如：/圣女、/大祭司。

发送 /帮助 返回圣殿帮助目录。""",
        "priority": 88,
        "note": "圣殿文献、背景故事与人物记录帮助。",
    },
    {
        "name": "忏悔洞帮助",
        "triggers": "/忏悔洞帮助,/忏悔洞指引,/忏悔帮助,/告解帮助",
        "reply": """🕯️ 忏悔洞帮助

/忏悔洞
查看忏悔洞玩法与相关规则

/告解室
进入告解室相关内容

/地下惩戒所
查看地下惩戒场所相关内容

请先阅读对应场所说明，再参与相关互动。

发送 /帮助 返回圣殿帮助目录。""",
        "priority": 87,
        "note": "忏悔洞、告解室与地下惩戒场所帮助。",
    },
    {
        "name": "悬赏帮助",
        "triggers": "/悬赏帮助,/悬赏指引,/悬赏令帮助,/圣殿悬赏帮助",
        "reply": """⚔️ 悬赏帮助

/发布悬赏令 天数 功德 内容
在主群或悬赏群发布；天数也可写“单次”

/悬赏
仅在悬赏群查看等待接取列表

/下一页
翻到下一页悬赏

/查看悬赏 序号
查看当前页对应序号的详情

/接悬赏 编号
按真实编号接取，例如：/接悬赏 0012

/我的悬赏
查看自己发布和接取的记录

/完成悬赏 编号
由接取人申请完成

/确认完成 编号
由发起人确认并结算赏金

/取消悬赏 编号
按当前状态执行退款、补偿或跑单处罚

发送 /帮助 返回圣殿帮助目录。""",
        "priority": 86,
        "note": "圣光教堂悬赏系统完整命令帮助。",
    },
    {
        "name": "互动帮助",
        "triggers": "/互动帮助,/互动指引,/群聊互动帮助,/其他玩法帮助",
        "reply": """🎭 互动帮助

/偷窃 对方称呼
尝试进行每日偷窃互动

/开启付费互动
允许别人向自己发起付费互动；默认关闭

/关闭付费互动
停止接受别人发起的付费互动

/付费互动 对方称呼
向已经开启接受功能的教徒发起付费互动

/称呼的状态
查看指定教徒的当前状态

/自定义称呼 新称呼
修改自己的显示称呼

/感谢
查看教堂名人堂与感谢记录

/还愿模版
查看还愿内容模版

/夕夕公演
查看夕夕公演相关内容

更多世界观内容可发送 /文献帮助 查阅。

发送 /帮助 返回圣殿帮助目录。""",
        "priority": 84,
        "note": "状态、称呼、偷窃和群内互动帮助。",
    },
]


def request_json(base_url: str, path: str, method: str = "GET", payload=None):
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    with urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def compact_reply(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    compacted = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if (
            re.match(r"^(?:[^\w/]+\s*)?/", line)
            and index + 1 < len(lines)
            and not lines[index + 1].startswith("/")
        ):
            compacted.append(f"{line}｜{lines[index + 1]}")
            index += 2
            continue
        compacted.append(line)
        index += 1
    return "\n".join(compacted)


def rule_payload(menu: dict) -> dict:
    return {
        "name": menu["name"],
        "enabled": True,
        "priority": menu["priority"],
        "group_name": GROUP_NAME,
        "trigger_type": "exact",
        "trigger_value": menu["triggers"],
        "reply_content": compact_reply(menu["reply"]),
        "reply_mode": "fixed",
        "scope_type": "all",
        "scope_value": "",
        "exclude_users": "",
        "rule_cooldown_seconds": 0,
        "user_cooldown_seconds": 0,
        "global_cooldown_seconds": 0,
        "daily_max_hits": 0,
        "allow_self": False,
        "require_admin": False,
        "note": menu["note"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    base_url = args.base_url

    request_json(
        base_url,
        "/api/rules/groups/create",
        method="POST",
        payload={"name": GROUP_NAME},
    )
    existing_rules = request_json(base_url, "/api/rules")
    by_name = {rule["name"]: rule for rule in existing_rules}
    legacy_top = next(
        (
            rule
            for rule in existing_rules
            if rule["group_name"] == GROUP_NAME
            and "/帮助" in str(rule["trigger_value"])
        ),
        None,
    )

    results = []
    for menu in MENUS:
        existing = by_name.get(menu["name"])
        if menu.get("top_level") and not existing:
            existing = legacy_top
        payload = rule_payload(menu)
        if existing:
            request_json(
                base_url,
                f"/api/rules/{int(existing['id'])}",
                method="PUT",
                payload=payload,
            )
            results.append({"name": menu["name"], "action": "updated", "id": int(existing["id"])})
        else:
            created = request_json(
                base_url,
                "/api/rules",
                method="POST",
                payload=payload,
            )
            results.append({"name": menu["name"], "action": "created", "id": int(created["id"])})

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
