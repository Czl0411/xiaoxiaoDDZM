import json

import pytest

from app.command_router import CommandRouter
from app.commission_ai import validate_demand_result, validate_service_result
from app.database import Database
from app.help_system import resolve_help_request


SELLER = "81000000-0000-0000-0000-000000000001"
BUYER = "81000000-0000-0000-0000-000000000002"
WORKER = "81000000-0000-0000-0000-000000000003"


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


def demand_json(people=4, reward=50):
    return json.dumps({
        "parse_success": True,
        "missing_fields": [],
        "ambiguity_reason": "",
        "title": "群内称呼任务",
        "content": "分别在群里喊我一声主人",
        "fulfillment_type": "one_time",
        "fulfillment_duration_value": None,
        "fulfillment_duration_unit": None,
        "required_people": people,
        "reward_per_person": reward,
        "recruitment_duration_days": None,
    }, ensure_ascii=False)


def service_json(stock_mode="unlimited", stock=None):
    return json.dumps({
        "parse_success": True,
        "missing_fields": [],
        "ambiguity_reason": "",
        "title": "群内称呼服务",
        "description": "在群里喊你一声主人",
        "unit_label": "次",
        "unit_price": 50,
        "stock_mode": stock_mode,
        "stock_quantity": stock,
        "listing_duration_days": 3,
        "fulfillment_type": "one_time",
        "fulfillment_duration_value": None,
        "fulfillment_duration_unit": None,
        "max_per_buyer": None,
    }, ensure_ascii=False)


@pytest.fixture
def db(tmp_path):
    instance = Database(tmp_path / "bot.db")
    instance.init()
    instance.set_secret("deepseek_api_key", "test-key")
    yield instance
    instance.close()


def fund(db, uid, name, amount):
    user = db.ensure_user(message(uid, name, "初始化", "init:" + uid))
    db.add_points(user, amount - int(user["points"]), "测试初始化")
    return db.get_user(user)


def publish(router, uid, name, text, output, mid):
    FakeAI.outputs = [output]
    preview = router.handle(message(uid, name, text, mid))
    assert preview.handled and preview.replies
    result = router.handle(message(uid, name, "/确认发布", mid + ":confirm"))
    assert result.handled and result.deliveries
    return result


def test_ai_schemas_are_completely_separate():
    demand = validate_demand_result(demand_json())
    service = validate_service_result(service_json())
    assert demand.required_people == 4 and demand.reward_per_person == 50
    assert service.stock_mode == "unlimited" and service.unit_price == 50
    with pytest.raises(Exception):
        validate_demand_result(service_json())
    with pytest.raises(Exception):
        validate_service_result(demand_json())


@pytest.mark.parametrize(("unit", "expected"), [("天", "day"), ("小时", "hour")])
def test_demand_accepts_chinese_fulfillment_duration_units(unit, expected):
    payload = json.loads(demand_json(people=1, reward=100))
    payload.update({
        "fulfillment_type": "time_based",
        "fulfillment_duration_value": 1,
        "fulfillment_duration_unit": unit,
    })

    draft = validate_demand_result(json.dumps(payload, ensure_ascii=False))

    assert draft.fulfillment_duration_value == 1
    assert draft.fulfillment_duration_unit == expected


def test_legacy_demand_prompt_is_replaced_before_ai_parsing(db):
    class SchemaAwareAI:
        def __init__(self, **_kwargs):
            pass

        def generate(self, **kwargs):
            if "required_people" in kwargs["system_prompt"]:
                return demand_json()
            return json.dumps({
                "parse_success": True,
                "missing_fields": [],
                "ambiguity_reason": "",
                "title": "旧需求",
                "content": "喊主人",
                "reward_amount": 50,
                "duration_type": "one_time",
                "recruitment_duration_days": None,
            }, ensure_ascii=False)

    config = db.get_config()
    config["features"] = {
        **config.get("features", {}),
        "commission_demand_ai_system_prompt": (
            "固定字段：parse_success、missing_fields、ambiguity_reason、title、content、"
            "reward_amount、duration_type、recruitment_duration_days"
        ),
    }
    db.save_config(config)
    fund(db, SELLER, "需求方", 1000)

    result = CommandRouter(db, ai_client_factory=SchemaAwareAI).handle(
        message(SELLER, "需求方", "/需求：找4个人分别喊我一声主人，每人50功德，单次", "legacy-prompt")
    )

    assert "需求发布预览" in result.replies[0]
    assert "人数：4人" in result.replies[0]
    assert "每人奖励：50功德" in result.replies[0]


def test_legacy_service_prompt_is_replaced_before_ai_parsing(db):
    class SchemaAwareAI:
        def __init__(self, **_kwargs):
            pass

        def generate(self, **kwargs):
            if "fulfillment_duration_value" in kwargs["system_prompt"]:
                payload = json.loads(service_json(stock_mode="limited", stock=1))
                payload.update({
                    "title": "树洞与艾草服务",
                    "description": "我可以当一天的树洞还可以艾草",
                    "unit_price": 1500,
                    "listing_duration_days": 6,
                    "fulfillment_type": "time_based",
                    "fulfillment_duration_value": 1,
                    "fulfillment_duration_unit": "天",
                })
                return json.dumps(payload, ensure_ascii=False)
            return json.dumps({
                "parse_success": True,
                "missing_fields": [],
                "ambiguity_reason": None,
                "title": "树洞与艾草服务",
                "description": "我可以当一天的树洞还可以艾草",
                "unit_price": 1500,
                "stock_quantity": None,
                "listing_duration_days": 6,
                "fulfillment_type": "time_based",
            }, ensure_ascii=False)

    config = db.get_config()
    config["features"] = {
        **config.get("features", {}),
        "commission_service_ai_system_prompt": (
            "固定字段：parse_success、missing_fields、ambiguity_reason、title、description、"
            "unit_price、stock_quantity、listing_duration_days、fulfillment_type"
        ),
    }
    db.save_config(config)
    fund(db, SELLER, "服务方", 1000)

    result = CommandRouter(db, ai_client_factory=SchemaAwareAI).handle(
        message(SELLER, "服务方", "/服务：我可以当一天的树洞还可以艾草，1500功德，上架6天", "legacy-service")
    )

    assert "服务发布预览" in result.replies[0]
    assert "1500功德" in result.replies[0]
    assert "上架6天" in result.replies[0]
    assert "购买后持续1天" in result.replies[0]


def test_manual_api_keys_override_embedded_key_and_can_be_replaced(db):
    db.set_secret("deepseek_api_key", "manual-deepseek-key-0001")
    db.set_secret("image2_api_key", "manual-image-key-0001")
    assert db.get_secret("deepseek_api_key") == "manual-deepseek-key-0001"
    assert db.secret_source("deepseek_api_key") == "manual"
    assert db.get_secret("image2_api_key") == "manual-image-key-0001"
    assert db.secret_source("image2_api_key") == "manual"

    db.set_secret("deepseek_api_key", "manual-deepseek-key-0002")
    assert db.get_secret("deepseek_api_key") == "manual-deepseek-key-0002"
    db.set_secret("deepseek_api_key", "")
    assert db.secret_source("deepseek_api_key") == "embedded"
    assert db.get_secret("deepseek_api_key") != "manual-deepseek-key-0002"

    db.set_secret("image2_api_key", "")
    assert db.get_secret("image2_api_key") == ""
    assert db.secret_source("image2_api_key") == ""


def test_demand_uses_people_and_reopens_slot_after_mutual_cancel(db):
    fund(db, SELLER, "需求方", 1000)
    fund(db, WORKER, "履约方", 100)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    published = publish(router, SELLER, "需求方", "/需求：找4个人每人在群里喊我一声主人，每人50功德，单次", demand_json(), "demand")
    assert "D0001" in published.replies[0]
    assert db.get_user(SELLER)["points"] == 780
    accepted = router.handle(message(WORKER, "履约方", "/接取需求D0001", "take", "bounty"))
    assert "O0001" in accepted.replies[0]
    router.handle(message(WORKER, "履约方", "/申请取消订单O0001", "cancel", "bounty"))
    router.handle(message(SELLER, "需求方", "/同意取消订单O0001", "approve", "bounty"))
    demand = db.commission_house.resolve("D0001", "demand")
    assert demand["required_people"] == 4
    assert demand["accepted_count"] == 0
    assert demand["status"] == "recruiting"


def test_service_is_repeatable_product_and_commission_is_seller_deducted(db):
    fund(db, SELLER, "卖家", 500)
    fund(db, BUYER, "买家", 500)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    published = publish(router, SELLER, "卖家", "/服务：我可以喊你一声主人，50功德一次，不限人数，上架3天", service_json(), "service")
    assert "S0001" in published.replies[0]
    first = router.handle(message(BUYER, "买家", "/购买服务S0001", "buy1", "bounty"))
    second = router.handle(message(BUYER, "买家", "/购买服务S0001*3", "buy2", "bounty"))
    assert "O0001" in first.replies[0] and "O0002" in second.replies[0]
    assert db.get_user(BUYER)["points"] == 300
    router.handle(message(SELLER, "卖家", "/完成订单O0001", "done", "bounty"))
    confirmed = router.handle(message(BUYER, "买家", "/确认订单O0001", "confirm", "bounty"))
    assert "到账 45" in confirmed.replies[0] and "系统回收 5" in confirmed.replies[0]
    assert db.get_user(SELLER)["points"] == 545
    service = db.commission_house.resolve("S0001", "service")
    assert service["stock_mode"] == "unlimited" and service["status"] == "on_sale"


def test_single_service_without_explicit_stock_defaults_to_one(db):
    fund(db, SELLER, "卖家", 500)
    FakeAI.outputs = [service_json(stock_mode="unlimited", stock=None)]
    router = CommandRouter(db, ai_client_factory=FakeAI)

    preview = router.handle(
        message(SELLER, "卖家", "/服务：我可以艾草，100功德每人，上架30天，单次", "default-stock")
    )

    draft = db.commission_house.get_draft(message(SELLER, "卖家", "", "read-draft"))
    assert "库存：1次" in preview.replies[0]
    assert draft["parsed"]["stock_mode"] == "limited"
    assert draft["parsed"]["stock_quantity"] is None


def test_service_listing_duration_starts_at_publication_and_help_has_management_commands(db):
    fund(db, SELLER, "卖家", 500)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(router, SELLER, "卖家", "/服务：喊主人，50一次，不限人数，上架3天", service_json(), "expiry")
    service = db.commission_house.resolve("S0001", "service")
    assert service["listing_expires_at"] > service["created_at"]
    help_result = router.handle(message(BUYER, "买家", "/委托帮助", "help"))
    assert "/购买服务S编号*数量" in "\n".join(help_result.replies)
    mine = router.handle(message(SELLER, "卖家", "/我的委托", "mine"))
    assert "/下架服务S编号" in mine.replies[0]
    assert len(mine.replies[0].splitlines()) <= 9


def test_service_card_separates_stock_limit_and_falls_back_from_numeric_unit(db):
    fund(db, SELLER, "卖家", 500)
    payload = json.loads(service_json(stock_mode="limited", stock=3))
    payload["max_per_buyer"] = 1
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(router, SELLER, "卖家", "/服务：测试服务", json.dumps(payload, ensure_ascii=False), "stable-card")
    db.conn.execute("update commission_services set unit_label='3' where id=1")
    db.conn.commit()

    detail = router.handle(message(BUYER, "买家", "/服务详情 S0001", "stable-card-detail", "bounty"))

    assert "价格：50功德/次" in detail.replies[0]
    assert "库存：3/3｜每人限购：1次" in detail.replies[0]


def test_delete_service_requires_own_off_shelf_service_without_active_orders(db):
    fund(db, SELLER, "卖家", 500)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(router, SELLER, "卖家", "/服务：测试服务", service_json(stock_mode="limited", stock=3), "delete-service")

    selling = router.handle(message(SELLER, "卖家", "/删除服务 S0001", "delete-service-selling"))
    router.handle(message(SELLER, "卖家", "/下架服务 S0001", "delete-service-off"))
    deleted = router.handle(message(SELLER, "卖家", "/删除服务 S0001", "delete-service-done"))
    mine = router.handle(message(SELLER, "卖家", "/我的服务", "delete-service-mine"))

    assert "先下架" in selling.replies[0]
    assert "已删除" in deleted.replies[0]
    assert "S0001" not in mine.replies[0]
    assert db.commission_house.resolve("S0001", "service")["status"] == "deleted"


def test_delete_service_rejects_unfinished_orders(db):
    fund(db, SELLER, "卖家", 500)
    fund(db, BUYER, "买家", 500)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(router, SELLER, "卖家", "/服务：测试服务", service_json(stock_mode="limited", stock=2), "delete-active")
    router.handle(message(BUYER, "买家", "/购买服务 S0001", "delete-active-buy", "bounty"))
    router.handle(message(SELLER, "卖家", "/下架服务 S0001", "delete-active-off"))

    rejected = router.handle(message(SELLER, "卖家", "/删除服务 S0001", "delete-active-reject"))

    assert "未结束订单" in rejected.replies[0]


def test_delete_completed_demand_hides_it_but_preserves_record(db):
    fund(db, SELLER, "发布者", 500)
    fund(db, WORKER, "履约者", 500)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(router, SELLER, "发布者", "/需求：测试需求", demand_json(people=1, reward=50), "delete-demand")
    router.handle(message(WORKER, "履约者", "/接取需求 D0001", "delete-demand-take", "bounty"))
    router.handle(message(WORKER, "履约者", "/完成订单 O0001", "delete-demand-submit", "bounty"))
    router.handle(message(SELLER, "发布者", "/确认订单 O0001", "delete-demand-confirm", "bounty"))

    deleted = router.handle(message(SELLER, "发布者", "/删除需求 D0001", "delete-demand-done"))
    mine = router.handle(message(SELLER, "发布者", "/我的需求", "delete-demand-mine"))

    assert "已删除" in deleted.replies[0]
    assert "D0001" not in mine.replies[0]
    assert db.commission_house.resolve("D0001", "demand")["status"] == "deleted"


def test_submitted_order_tells_client_exact_confirm_command_with_space(db):
    fund(db, SELLER, "卖家", 500)
    fund(db, BUYER, "买家", 500)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(router, SELLER, "卖家", "/服务：测试服务", service_json(stock_mode="limited", stock=1), "confirm-guide")
    router.handle(message(BUYER, "买家", "/购买服务 S0001", "confirm-guide-buy", "bounty"))

    submitted = router.handle(message(SELLER, "卖家", "/完成订单 O0001", "confirm-guide-submit", "bounty"))
    notices = [item["text"] for item in submitted.deliveries + submitted.direct_deliveries]

    assert any("请发送：/确认订单 O0001" in text for text in notices)


def test_same_user_can_cancel_multiple_commission_drafts(db):
    fund(db, SELLER, "发布者", 1000)
    router = CommandRouter(db, ai_client_factory=FakeAI)

    FakeAI.outputs = [demand_json()]
    router.handle(message(SELLER, "发布者", "/需求：找4个人喊主人，每人50功德，单次", "cancel-1"))
    first = router.handle(message(SELLER, "发布者", "/取消发布", "cancel-1-confirm"))

    FakeAI.outputs = [demand_json()]
    router.handle(message(SELLER, "发布者", "/需求：找4个人喊主人，每人50功德，单次", "cancel-2"))
    second = router.handle(message(SELLER, "发布者", "/取消发布", "cancel-2-confirm"))

    assert "已取消" in first.replies[0]
    assert "已取消" in second.replies[0]
    assert db.conn.execute(
        "select count(*) from commission_drafts_v2 where status='cancelled'"
    ).fetchone()[0] == 2


def test_same_user_can_publish_multiple_commission_drafts(db):
    fund(db, SELLER, "发布者", 2000)
    router = CommandRouter(db, ai_client_factory=FakeAI)

    first = publish(
        router, SELLER, "发布者", "/需求：找1个人喊主人，每人50功德，单次",
        demand_json(people=1, reward=50), "publish-1",
    )
    second = publish(
        router, SELLER, "发布者", "/需求：找1个人喊主人，每人50功德，单次",
        demand_json(people=1, reward=50), "publish-2",
    )

    assert "D0001" in first.replies[0]
    assert "D0002" in second.replies[0]
    assert db.conn.execute(
        "select count(*) from commission_drafts_v2 where status='published'"
    ).fetchone()[0] == 2


def test_admin_demand_editor_reconciles_escrow_and_audits(db):
    fund(db, SELLER, "需求方", 2000)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    publish(router, SELLER, "需求方", "/需求：找4个人喊主人，每人50功德，单次", demand_json(), "admin-demand")
    before = db.get_user(SELLER)["points"]
    demand = db.commission_house.resolve("D0001", "demand")
    changed = db.commission_house.admin_update_demand(demand["id"], {
        "title": "调整后的需求", "content": demand["content"], "required_people": 5,
        "reward_per_person": 60, "recruitment_expires_at": demand["recruitment_expires_at"],
        "status": "recruiting", "reason": "测试调整",
    }, "test-admin")
    assert changed["reward_escrow_remaining"] == 300
    assert changed["fee_escrow_remaining"] == 30
    assert db.get_user(SELLER)["points"] == before - 110
    closed = db.commission_house.admin_update_demand(changed["id"], {
        "status": "closed", "reason": "测试安全关闭",
    }, "test-admin")
    assert closed["reward_escrow_remaining"] == 0 and closed["fee_escrow_remaining"] == 0
    assert db.get_user(SELLER)["points"] == 2000
    assert db.conn.execute("select count(*) from commission_admin_audit_v2 where object_type='demand'").fetchone()[0] == 2


def test_prompt_revision_history_deduplicates_and_restores_value(db):
    first = db.commission_house.record_prompt_revision("commission_service_ai_system_prompt", "版本一")
    duplicate = db.commission_house.record_prompt_revision("commission_service_ai_system_prompt", "版本一")
    second = db.commission_house.record_prompt_revision("commission_service_ai_system_prompt", "版本二")
    assert first == duplicate and second != first
    assert db.commission_house.get_prompt_revision(first)["prompt_value"] == "版本一"
    assert len(db.commission_house.list_prompt_revisions()) == 2


def test_custom_commands_flow_into_cards_lists_and_help_while_old_commands_are_removed(db):
    fund(db, SELLER, "需求方", 1000)
    config = db.get_config()
    config.setdefault("features", {}).update({
        "commission_request_publish_commands": "/找人",
        "commission_confirm_draft_commands": "/正式发出",
        "commission_request_list_commands": "/需求板",
        "commission_request_accept_commands": "/接任务",
        "commission_request_detail_commands": "/看需求",
    })
    db.save_config(config)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    FakeAI.outputs = [demand_json(people=1, reward=50)]
    preview = router.handle(message(SELLER, "需求方", "/找人：请一人喊主人，每人50功德，单次", "custom"))
    assert "/正式发出" in preview.replies[0]
    published = router.handle(message(SELLER, "需求方", "/正式发出", "custom-confirm"))
    assert "/接任务D0001" in published.deliveries[0]["text"]
    listing = router.handle(message(BUYER, "买家", "/需求板", "custom-list", "bounty"))
    assert "/看需求D0001" in listing.replies[0] and "/接任务D0001" in listing.replies[0]
    assert not router.handle(message(BUYER, "买家", "/发布悬赏令 老命令", "old-command")).handled
    assert not router.handle(message(BUYER, "买家", "/市场", "old-market")).handled
    help_result = router.handle(message(BUYER, "买家", "/委托帮助", "custom-help"))
    assert "/找人" in help_result.replies[0] and "/需求板" in help_result.replies[1]
    assert all(len(reply.splitlines()) <= 9 for reply in help_result.replies)
