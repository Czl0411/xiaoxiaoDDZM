import json

import pytest

from app.command_router import CommandRouter
from app.database import Database


PUBLISHER = "71000000-0000-0000-0000-000000000001"
BUYER = "71000000-0000-0000-0000-000000000002"
SECOND = "71000000-0000-0000-0000-000000000003"


def message(uid, name, text, mid, group="direct:test-room"):
    return {
        "platform_user_id": uid,
        "user_id": uid,
        "sender": name,
        "text": text,
        "message_id": mid,
        "group_key": group,
        "source_group": group,
        "source_type": "direct" if group.startswith("direct:") else "group",
        "chatroom_id": group.removeprefix("direct:") if group.startswith("direct:") else "",
        "is_self": False,
    }


class FakeAI:
    outputs = []

    def __init__(self, **_kwargs):
        pass

    def generate(self, **_kwargs):
        return type(self).outputs.pop(0)


def parsed(mode="request", count=1, reward=100, content="原样委托内容", unlimited=False):
    return json.dumps(
        {
            "task_type": "single",
            "duration_days": None,
            "required_count": count,
            "reward_per_person": reward,
            "content": content,
            "bounty_mode": mode,
            "unlimited_stock": unlimited,
            "missing_fields": [],
            "parse_success": True,
        },
        ensure_ascii=False,
    )


def current_demand(content="私聊需求正文"):
    return json.dumps(
        {
            "parse_success": True,
            "missing_fields": [],
            "ambiguity_reason": "",
            "title": "私聊需求",
            "content": content,
            "fulfillment_type": "one_time",
            "fulfillment_duration_value": None,
            "fulfillment_duration_unit": None,
            "required_people": 1,
            "reward_per_person": 50,
            "recruitment_duration_days": 3,
        },
        ensure_ascii=False,
    )


def current_service(content="私聊服务正文", stock=1):
    return json.dumps(
        {
            "parse_success": True,
            "missing_fields": [],
            "ambiguity_reason": "",
            "title": "私聊服务",
            "description": content,
            "unit_label": "次",
            "unit_price": 100,
            "stock_mode": "limited",
            "stock_quantity": stock,
            "listing_duration_days": 3,
            "fulfillment_type": "one_time",
            "fulfillment_duration_value": None,
            "fulfillment_duration_unit": None,
            "max_per_buyer": None,
        },
        ensure_ascii=False,
    )


@pytest.fixture
def db(tmp_path):
    instance = Database(tmp_path / "bot.db")
    instance.init()
    instance.set_secret("deepseek_api_key", "test-key")
    yield instance
    instance.close()


def fund(db, uid, name, points):
    user = db.ensure_user(message(uid, name, "初始化", f"init:{uid}"))
    db.add_points(user, points - int(user["points"]), "委托所测试初始化")
    return db.get_user(user)


def publish(router, uid, name, command, output, mid):
    FakeAI.outputs = [output]
    preview = router.handle(message(uid, name, command, mid))
    assert preview.handled and preview.replies
    confirmed = router.handle(message(uid, name, "/确认发布", mid + ":confirm"))
    assert confirmed.handled and confirmed.deliveries
    return confirmed


def test_new_publish_commands_replace_old_commands_and_require_private_chat(db):
    fund(db, PUBLISHER, "发布者", 1000)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    FakeAI.outputs = [parsed(content="不能改写的需求正文")]
    preview = router.handle(message(PUBLISHER, "发布者", "/需求：单次找人帮忙，每人100功德", "draft"))
    assert preview.handled and "需求发布预览" in preview.replies[0]
    confirmed = router.handle(message(PUBLISHER, "发布者", "/确认发布", "confirm"))
    assert confirmed.handled and "D0001" in confirmed.replies[0]
    assert confirmed.deliveries[0]["group_key"] == "bounty"
    assert db.get_bounty(1)["content"] == "不能改写的需求正文"
    assert not router.handle(message(PUBLISHER, "发布者", "/发布悬赏 单次 100 旧命令", "old")).handled
    blocked = router.handle(message(PUBLISHER, "发布者", "/服务：单次服务100功德", "wrong", "bounty"))
    assert blocked.handled and "请私聊机器人" in blocked.replies[0]


def test_group_commission_command_guides_known_user_in_saved_direct_room(db):
    db.upsert_direct_chat(PUBLISHER, "known-room")
    router = CommandRouter(db, ai_client_factory=FakeAI)

    result = router.handle(message(PUBLISHER, "发布者", "/查看服务", "group-guide", "main"))

    assert result.replies == ["圣喻已给你单独指引"]
    assert all(item["chatroom_id"] == "known-room" for item in result.direct_deliveries)
    guide = "\n".join(item["text"] for item in result.direct_deliveries)
    assert "/查看服务" in guide
    assert "/需求" in guide and "/服务" in guide
    assert "/确认发布" in guide and "/取消发布" in guide
    assert "/需求详情" in guide and "/服务详情" in guide
    assert "/接取需求" in guide and "/购买服务" in guide
    assert "/我的委托" in guide and "/我的订单" in guide
    assert "/关闭需求" in guide and "/下架服务" in guide
    assert "/需求：找1个人" in guide
    assert "/服务：陪聊一小时" in guide
    assert "请先发送 /市场帮助 熟悉完整指令" in guide


def test_commission_help_executes_in_direct_chat_and_group_routes_it_to_direct(db):
    db.upsert_direct_chat(PUBLISHER, "known-room")
    router = CommandRouter(db, ai_client_factory=FakeAI)

    direct = router.handle(message(PUBLISHER, "发布者", "/市场帮助", "direct-help"))
    group = router.handle(message(PUBLISHER, "发布者", "/市场帮助", "group-help", "main"))

    assert direct.name == "委托帮助"
    assert "/需求：找1个人" in "\n".join(direct.replies)
    assert group.replies == ["圣喻已给你单独指引"]
    assert "/市场帮助" in "\n".join(item["text"] for item in group.direct_deliveries)


def test_group_commission_command_without_saved_room_only_requests_private_chat(db):
    router = CommandRouter(db, ai_client_factory=FakeAI)

    result = router.handle(message(BUYER, "买家", "/查看需求", "new-user", "main"))

    assert result.replies == ["请私聊机器人使用该指令"]
    assert result.direct_deliveries == []


def test_direct_commission_query_executes_instead_of_returning_group_guidance(db):
    router = CommandRouter(db, ai_client_factory=FakeAI)

    result = router.handle(message(BUYER, "买家", "/查看服务", "direct-query"))

    assert result.name == "查看服务"
    assert "群友委托所" in result.replies[0]


def test_direct_demand_publish_confirms_privately_and_broadcasts_to_bounty(db):
    fund(db, PUBLISHER, "发布者", 500)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    FakeAI.outputs = [current_demand()]

    preview = router.handle(
        message(PUBLISHER, "发布者", "/需求：找一个人测试，每人50功德，单次", "private-draft")
    )
    confirmed = router.handle(
        message(PUBLISHER, "发布者", "/确认发布", "private-confirm")
    )

    assert "需求发布预览" in preview.replies[0]
    assert "D0001" in confirmed.replies[0]
    assert confirmed.deliveries[0]["group_key"] == "bounty"
    assert "D0001" in confirmed.deliveries[0]["text"]


def test_request_and_service_lists_are_separate_and_never_exceed_nine_lines(db):
    fund(db, PUBLISHER, "发布者", 3000)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(router, PUBLISHER, "发布者", "/需求：单次需求，每人100功德", parsed("request", 1, 100, "需求正文"), "r")
    publish(router, PUBLISHER, "发布者", "/服务：单次服务，每份100功德，名额2", parsed("service", 2, 100, "服务正文"), "s")
    requests = router.handle(message(BUYER, "买家", "/查看需求", "lr", "bounty"))
    services = router.handle(message(BUYER, "买家", "/查看服务", "ls", "bounty"))
    assert "D0001" in requests.replies[0] and "S0001" not in requests.replies[0]
    assert "S0001" in services.replies[0] and "D0001" not in services.replies[0]
    assert len(requests.replies[0].splitlines()) <= 9
    assert len(services.replies[0].splitlines()) <= 9


def test_direction_aware_order_completion_and_settlement(db):
    fund(db, PUBLISHER, "服务者", 1000)
    fund(db, BUYER, "买家", 1000)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(router, PUBLISHER, "服务者", "/服务：单次服务，每份100功德，名额2", parsed("service", 2, 100, "服务正文"), "service")
    accepted = router.handle(message(BUYER, "买家", "/接取服务S0001", "accept", "bounty"))
    assert accepted.handled and "O0001" in accepted.replies[0]
    assert db.get_user(BUYER)["points"] == 890
    wrong = router.handle(message(BUYER, "买家", "/完成订单O0001", "wrong-complete", "bounty"))
    assert "not_performer" in wrong.replies[0]
    completed = router.handle(message(PUBLISHER, "服务者", "/完成订单O0001", "complete", "bounty"))
    assert "等待 买家 确认" in completed.replies[0]
    confirmed = router.handle(message(BUYER, "买家", "/确认订单O0001", "settle", "bounty"))
    assert confirmed.handled and "到账 100" in confirmed.replies[0]
    assert db.get_user(PUBLISHER)["points"] == 1100
    assert db.get_user(BUYER)["points"] == 890


def test_mutual_order_cancel_refunds_without_deleting_content(db):
    fund(db, PUBLISHER, "服务者", 500)
    fund(db, BUYER, "买家", 500)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(router, PUBLISHER, "服务者", "/服务：单次服务100功德", parsed("service", 1, 100, "原始服务内容"), "cancel-service")
    router.handle(message(BUYER, "买家", "/接取服务S0001", "take", "bounty"))
    requested = router.handle(message(BUYER, "买家", "/申请取消订单O0001", "cancel", "bounty"))
    assert "申请取消" in requested.replies[0]
    approved = router.handle(message(PUBLISHER, "服务者", "/同意取消订单O0001", "approve", "bounty"))
    assert "退还 110" in approved.replies[0]
    assert db.get_user(BUYER)["points"] == 500
    assert db.get_bounty(1)["content"] == "原始服务内容"


def test_purchase_and_accept_broadcast_and_notify_post_owner(db):
    fund(db, PUBLISHER, "发布者", 1000)
    fund(db, BUYER, "买家", 1000)
    db.upsert_direct_chat(PUBLISHER, "publisher-room")
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(router, PUBLISHER, "发布者", "/服务：单次服务，每份100功德，名额2，上架3天", current_service("服务正文", 2), "notify-service")

    bought = router.handle(message(BUYER, "买家", "/购买服务S0001", "notify-buy"))

    assert bought.deliveries == [{"group_key": "bounty", "text": bought.deliveries[0]["text"]}]
    assert "S0001" in bought.deliveries[0]["text"] and "买家" in bought.deliveries[0]["text"]
    assert bought.direct_deliveries[0]["chatroom_id"] == "publisher-room"
    assert "O0001" in bought.direct_deliveries[0]["text"]

    demand_payload = json.loads(current_demand("需求正文"))
    demand_payload["reward_per_person"] = 100
    publish(router, PUBLISHER, "发布者", "/需求：单次需求，每人100功德", json.dumps(demand_payload, ensure_ascii=False), "notify-demand")
    accepted = router.handle(message(BUYER, "买家", "/接取需求D0001", "notify-accept"))
    assert "D0001" in accepted.deliveries[0]["text"] and "买家" in accepted.deliveries[0]["text"]
    assert accepted.direct_deliveries[0]["chatroom_id"] == "publisher-room"
    assert "O0002" in accepted.direct_deliveries[0]["text"]


def test_order_progress_notifies_counterparty_or_falls_back_to_bounty(db):
    fund(db, PUBLISHER, "服务者", 1000)
    fund(db, BUYER, "买家", 1000)
    db.upsert_direct_chat(BUYER, "buyer-room")
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(router, PUBLISHER, "服务者", "/服务：单次服务，每份100功德，名额1，上架3天", current_service("服务正文", 1), "progress-service")
    router.handle(message(BUYER, "买家", "/购买服务S0001", "progress-buy"))

    submitted = router.handle(message(PUBLISHER, "服务者", "/完成订单O0001", "progress-submit"))
    assert submitted.deliveries == []
    assert submitted.direct_deliveries[0]["chatroom_id"] == "buyer-room"
    assert "O0001" in submitted.direct_deliveries[0]["text"] and "确认" in submitted.direct_deliveries[0]["text"]

    db.conn.execute("delete from direct_chats where platform_user_id=?", (PUBLISHER.lower(),))
    db.conn.commit()
    confirmed = router.handle(message(BUYER, "买家", "/确认订单O0001", "progress-confirm"))
    assert confirmed.direct_deliveries == []
    assert confirmed.deliveries[0]["group_key"] == "bounty"
    assert "O0001" in confirmed.deliveries[0]["text"] and "已完成" in confirmed.deliveries[0]["text"]


def test_close_and_off_shelf_broadcast_to_bounty(db):
    fund(db, PUBLISHER, "发布者", 1000)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    demand_payload = json.loads(current_demand("需求正文"))
    demand_payload["reward_per_person"] = 100
    publish(router, PUBLISHER, "发布者", "/需求：单次需求，每人100功德", json.dumps(demand_payload, ensure_ascii=False), "close-demand")
    publish(router, PUBLISHER, "发布者", "/服务：单次服务，每份100功德，名额1，上架3天", current_service("服务正文", 1), "close-service")

    closed = router.handle(message(PUBLISHER, "发布者", "/关闭需求D0001", "close-demand-now"))
    off_shelf = router.handle(message(PUBLISHER, "发布者", "/下架服务S0001", "off-shelf-now"))

    assert "D0001" in closed.deliveries[0]["text"] and "已关闭" in closed.deliveries[0]["text"]
    assert "S0001" in off_shelf.deliveries[0]["text"] and "已下架" in off_shelf.deliveries[0]["text"]


def test_preserved_market_content_uses_unified_service_and_order_numbers(db):
    seller = fund(db, PUBLISHER, "旧卖家", 500)
    fund(db, BUYER, "买家", 500)
    db.marketplace_core.save_draft(
        message(PUBLISHER, "旧卖家", "旧市场", "legacy-draft"),
        "旧原文",
        {"title": "旧标题原文", "description": "旧说明原文", "price": 50, "stock": 2, "duration_days": 3},
        ttl_seconds=600,
    )
    listing = db.marketplace_core.confirm_draft(
        message(PUBLISHER, "旧卖家", "确认", "legacy-confirm"), mode="create", maximum_active=3
    )["listing"]
    router = CommandRouter(db, ai_client_factory=FakeAI)
    listed = router.handle(message(BUYER, "买家", "/查看服务", "legacy-list", "bounty"))
    detailed = router.handle(message(BUYER, "买家", "/服务详情S0001", "legacy-detail", "bounty"))
    assert "S0001" in listed.replies[0]
    assert "M0001" not in listed.replies[0]
    assert "旧标题原文" in detailed.replies[0] and "旧说明原文" in detailed.replies[0]
    bought = router.handle(message(BUYER, "买家", "/接取服务S0001", "legacy-buy", "bounty"))
    assert "O0001" in bought.replies[0]
    assert "MO0001" not in bought.replies[0]
    assert db.marketplace_core.get_listing(listing["id"])["description"] == "旧说明原文"
    assert db.conn.execute("select count(*) from market_orders").fetchone()[0] == 1
    assert not router.handle(message(PUBLISHER, "旧卖家", "/市场", "old-market")).handled
    rejected_old_number = router.handle(message(BUYER, "买家", "/服务详情M0001", "old-number", "bounty"))
    assert rejected_old_number.handled and "S0001" in rejected_old_number.replies[0]


def test_lists_show_explicit_page_commands_and_accept_compact_or_spaced_pages(db):
    fund(db, PUBLISHER, "发布者", 5000)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    for index in range(6):
        publish(
            router,
            PUBLISHER,
            "发布者",
            f"/服务：第{index + 1}项服务，每份50功德",
            parsed("service", 1, 50, f"第{index + 1}项服务"),
            f"page-service-{index}",
        )
    first = router.handle(message(BUYER, "买家", "/查看服务", "page-1", "bounty"))
    second = router.handle(message(BUYER, "买家", "/查看服务2", "page-2", "bounty"))
    second_spaced = router.handle(message(BUYER, "买家", "/查看服务 第2页", "page-2-spaced", "bounty"))
    assert "/查看服务2" in first.replies[0]
    assert "/查看服务1" in second.replies[0]
    assert second.replies[0] == second_spaced.replies[0]
    assert len(first.replies[0].splitlines()) <= 9
    assert len(second.replies[0].splitlines()) <= 9


def test_public_numbers_are_unique_and_stable_after_database_restart(tmp_path):
    path = tmp_path / "stable.db"
    first = Database(path)
    first.init()
    fund(first, PUBLISHER, "服务者", 500)
    service = first.create_bounty(
        message(PUBLISHER, "服务者", "创建服务", "stable-service"),
        duration_type="single",
        duration_days=0,
        reward=50,
        reward_per_person=50,
        required_count=1,
        content="稳定编号服务",
        source_group="main",
        bounty_mode="service",
    )
    first.marketplace_core.save_draft(
        message(PUBLISHER, "服务者", "保留服务", "stable-listing-draft"),
        "保留服务原文",
        {"title": "保留服务", "description": "内容不变", "price": 50, "stock": 1, "duration_days": 3},
        ttl_seconds=600,
    )
    listing = first.marketplace_core.confirm_draft(
        message(PUBLISHER, "服务者", "确认", "stable-listing-confirm"), mode="create", maximum_active=3
    )["listing"]
    service_code = first.commission_public_code("bounty", service["id"], "S")
    listing_code = first.commission_public_code("market_listing", listing["id"], "S")
    assert service_code == "S0001" and listing_code == "S0002"
    first.close()

    reopened = Database(path)
    reopened.init()
    assert reopened.commission_public_code("bounty", service["id"], "S") == service_code
    assert reopened.commission_public_code("market_listing", listing["id"], "S") == listing_code
    assert reopened.resolve_commission_public_id("S", 1)["source_type"] == "bounty"
    assert reopened.resolve_commission_public_id("S", 2)["source_type"] == "market_listing"
    reopened.close()


def test_service_can_be_unlimited_and_remains_available_after_many_orders(db):
    fund(db, PUBLISHER, "服务者", 500)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    # 即使 AI 把数量标为缺失，原文明确“不限人数”时也应由程序可靠纠正为不限库存。
    ai_output = json.dumps(
        {
            "task_type": "duration",
            "duration_days": 3,
            "required_count": None,
            "unlimited_stock": False,
            "reward_per_person": 50,
            "content": "帮你把oc图片做成动态视频",
            "bounty_mode": "service",
            "missing_fields": ["required_count"],
            "parse_success": False,
        },
        ensure_ascii=False,
    )
    FakeAI.outputs = [ai_output]
    preview = router.handle(
        message(
            PUBLISHER,
            "服务者",
            "/服务 帮你把oc图片做成动态视频，一次50，不限人数，持续时间3天",
            "unlimited-draft",
        )
    )
    assert preview.handled and "服务数量：不限" in preview.replies[0]
    confirmed = router.handle(message(PUBLISHER, "服务者", "/确认发布", "unlimited-confirm"))
    assert "S0001" in confirmed.replies[0]
    assert db.get_bounty(1)["unlimited_stock"] is True

    for index in range(11):
        uid = f"72000000-0000-0000-0000-{index:012d}"
        fund(db, uid, f"买家{index + 1}", 100)
        accepted = router.handle(
            message(uid, f"买家{index + 1}", "/接取服务S0001", f"unlimited-buy-{index}", "bounty")
        )
        assert accepted.handled and f"O{index + 1:04d}" in accepted.replies[0]

    current = db.get_bounty(1)
    assert current["accepted_count"] == 11
    assert current["status"] == "recruiting"
    listed = router.handle(message(BUYER, "查看者", "/查看服务", "unlimited-list", "bounty"))
    assert "S0001" in listed.replies[0] and "库存不限" in listed.replies[0]


def test_service_count_is_presented_and_consumed_as_product_stock(db):
    fund(db, PUBLISHER, "服务者", 500)
    fund(db, BUYER, "买家", 500)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    FakeAI.outputs = [parsed("service", 3, 50, "制作三份角色图")]
    preview = router.handle(
        message(PUBLISHER, "服务者", "/服务：制作角色图，每份50功德，商品数量3", "stock-draft")
    )
    assert "服务数量：3份" in preview.replies[0]
    assert "人数" not in preview.replies[0] and "名额" not in preview.replies[0]
    router.handle(message(PUBLISHER, "服务者", "/确认发布", "stock-confirm"))
    before = router.handle(message(BUYER, "买家", "/查看服务", "stock-before", "bounty"))
    assert "库存剩3/3份" in before.replies[0]
    router.handle(message(BUYER, "买家", "/接取服务S0001", "stock-buy", "bounty"))
    after = router.handle(message(SECOND, "买家2", "/查看服务", "stock-after", "bounty"))
    assert "库存剩2/3份" in after.replies[0]


def test_admin_can_switch_service_stock_without_charging_the_seller(db):
    seller = fund(db, PUBLISHER, "服务者", 500)
    service = db.create_bounty(
        message(PUBLISHER, "服务者", "创建服务", "admin-stock"),
        duration_type="days",
        duration_days=3,
        reward=50,
        reward_per_person=50,
        required_count=1,
        unlimited_stock=True,
        content="可编辑库存的服务",
        source_group="main",
        bounty_mode="service",
    )
    result = db.admin_update_bounty(
        service["id"],
        {"unlimited_stock": False, "required_count": 25, "reason": "调整为有限库存"},
        admin_identity="test-manager",
    )
    assert result["bounty"]["unlimited_stock"] is False
    assert result["bounty"]["required_count"] == 25
    assert db.get_user(seller)["points"] == 500


def test_request_order_and_admin_settlement_are_audited(db):
    fund(db, PUBLISHER, "需求方", 500)
    fund(db, BUYER, "履约方", 500)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(
        router,
        PUBLISHER,
        "需求方",
        "/需求：单次需求，每人100功德",
        parsed("request", 1, 100, "管理员不得改写的需求正文"),
        "admin-request",
    )
    router.handle(message(BUYER, "履约方", "/接取需求D0001", "admin-take", "bounty"))
    result = db.admin_commission_order_action(
        1,
        action="settle",
        admin_identity="test-manager",
        reason="双方线下确认完成",
    )
    assert result["ok"]
    assert db.get_commission_order(1)["participant_status"] == "paid"
    assert db.get_user(BUYER)["points"] == 600
    assert db.get_bounty(1)["content"] == "管理员不得改写的需求正文"
    audit = db.conn.execute("select * from commission_admin_audit").fetchone()
    assert audit["action"] == "settle"
    assert audit["reason"] == "双方线下确认完成"


def test_admin_refund_respects_an_existing_cancel_request_from_buyer(db):
    fund(db, PUBLISHER, "服务者", 500)
    fund(db, BUYER, "买家", 500)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(
        router,
        PUBLISHER,
        "服务者",
        "/服务：单次服务，每次100功德",
        parsed("service", 1, 100, "退款时不得改写的服务正文"),
        "admin-refund-service",
    )
    router.handle(message(BUYER, "买家", "/接取服务S0001", "refund-take", "bounty"))
    router.handle(message(BUYER, "买家", "/申请取消订单O0001", "refund-request", "bounty"))
    result = db.admin_commission_order_action(
        1,
        action="refund",
        admin_identity="test-manager",
        reason="管理员核实后退款",
    )
    assert result["ok"] and result["refund"] == 110
    assert db.get_user(BUYER)["points"] == 500
    assert db.get_commission_order(1)["participant_status"] == "cancelled"
    assert db.get_bounty(1)["content"] == "退款时不得改写的服务正文"
