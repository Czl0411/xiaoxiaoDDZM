import json

import pytest

from app.command_router import CommandRouter
from app.database import Database
from app.marketplace_ai import MarketplaceParseError, validate_ai_result


SELLER = "11111111-1111-1111-1111-111111111111"
BUYER = "22222222-2222-2222-2222-222222222222"


def msg(uid, name, text, mid):
    return {
        "platform_user_id": uid,
        "user_id": uid,
        "sender": name,
        "text": text,
        "message_id": mid,
        "group_key": "main",
        "source_group": "main",
        "is_self": False,
    }


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db")
    db.init()
    db.set_secret("deepseek_api_key", "test-key")
    return db


def fund(db, uid, name, points):
    user = db.ensure_user(msg(uid, name, "初始化", f"init:{uid}"))
    db.add_points(user, points - int(user["points"]), "市场测试初始化")
    return db.get_user(user)


class FakeAI:
    outputs = []

    def __init__(self, **_kwargs):
        pass

    def generate(self, **_kwargs):
        return type(self).outputs.pop(0)


def market_json(**changes):
    data = {
        "title": "一小时陪玩",
        "description": "陪玩一小时，成交后双方自行联系安排时间。",
        "price": 80,
        "stock": None,
        "duration_days": None,
    }
    data.update(changes)
    return json.dumps(data, ensure_ascii=False)


def test_ai_validation_requires_seller_price_and_applies_defaults():
    parsed = validate_ai_result(
        market_json(),
        minimum_price=50,
        maximum_price=100000,
        default_stock=1,
        default_duration_days=3,
    )
    assert parsed.price == 80 and parsed.stock == 1 and parsed.duration_days == 3
    with pytest.raises(MarketplaceParseError) as caught:
        validate_ai_result(
            market_json(price=None),
            minimum_price=50,
            maximum_price=100000,
            default_stock=1,
            default_duration_days=3,
        )
    assert "price" in caught.value.fields


@pytest.mark.skip(reason="旧市场群聊命令已废弃；历史内容兼容见 test_commission_house.py")
def test_market_command_draft_confirm_is_independent_from_official_shop(tmp_path):
    db = make_db(tmp_path)
    fund(db, SELLER, "卖家", 500)
    official_before = db.conn.execute("select count(*) from shop_items").fetchone()[0]
    FakeAI.outputs = [market_json()]
    router = CommandRouter(db, ai_client_factory=FakeAI)

    preview = router.handle(msg(SELLER, "卖家", "/上架市场：陪玩一小时，每份80功德", "draft-1"))
    assert preview.handled and "库存：1" in preview.replies[0] and "有效期：3天" in preview.replies[0]
    assert db.conn.execute("select count(*) from market_listings").fetchone()[0] == 0

    created = router.handle(msg(SELLER, "卖家", "/确认上架", "confirm-1"))
    assert "M0001" in created.replies[0]
    listing = db.marketplace_core.get_listing(1)
    assert listing["price"] == 80 and listing["stock_remaining"] == 1
    assert db.conn.execute("select count(*) from shop_items").fetchone()[0] == official_before


def test_immediate_purchase_commission_stock_history_and_idempotency(tmp_path):
    db = make_db(tmp_path)
    seller = fund(db, SELLER, "卖家", 100)
    buyer = fund(db, BUYER, "买家", 1000)
    seller_total_before = int(seller["total_merit"])
    db.marketplace_core.save_draft(
        msg(SELLER, "卖家", "上架", "core-draft"),
        "商品",
        {"title": "定制文字", "description": "提供一次文字定制", "price": 100, "stock": 2, "duration_days": 3},
        ttl_seconds=600,
    )
    listing = db.marketplace_core.confirm_draft(
        msg(SELLER, "卖家", "确认", "core-confirm"), mode="create", maximum_active=3
    )["listing"]
    purchase_message = msg(BUYER, "买家", "/市场购买M0001", "buy-once")
    first = db.marketplace_core.purchase(listing["id"], purchase_message, 1, commission_rate_bps=1000)
    second = db.marketplace_core.purchase(listing["id"], purchase_message, 1, commission_rate_bps=1000)

    assert first["ok"] and not first["duplicate"] and second["duplicate"]
    assert db.conn.execute("select count(*) from market_orders").fetchone()[0] == 1
    assert db.get_user(buyer)["points"] == 900
    updated_seller = db.get_user(seller)
    assert updated_seller["points"] == 190
    assert updated_seller["total_merit"] == seller_total_before + 90
    assert db.marketplace_core.get_listing(listing["id"])["stock_remaining"] == 1
    recovery = db.conn.execute("select amount,rate_bps from market_recovery_records").fetchone()
    assert tuple(recovery) == (10, 1000)


def test_purchase_rejects_self_insufficient_balance_and_excess_stock(tmp_path):
    db = make_db(tmp_path)
    seller = fund(db, SELLER, "卖家", 100)
    fund(db, BUYER, "买家", 50)
    db.marketplace_core.save_draft(
        msg(SELLER, "卖家", "上架", "limits-draft"),
        "商品",
        {"title": "限量商品", "description": "只有一份", "price": 100, "stock": 1, "duration_days": 3},
        ttl_seconds=600,
    )
    listing = db.marketplace_core.confirm_draft(
        msg(SELLER, "卖家", "确认", "limits-confirm"), mode="create", maximum_active=3
    )["listing"]
    assert db.marketplace_core.purchase(listing["id"], msg(SELLER, "卖家", "买", "self"), 1, commission_rate_bps=1000)["reason"] == "self"
    assert db.marketplace_core.purchase(listing["id"], msg(BUYER, "买家", "买", "poor"), 1, commission_rate_bps=1000)["reason"] == "balance"
    assert db.marketplace_core.purchase(listing["id"], msg(BUYER, "买家", "买", "stock"), 2, commission_rate_bps=1000)["reason"] == "stock"
    assert db.get_user(seller)["points"] == 100


def test_max_three_active_expiry_renew_and_five_per_page(tmp_path):
    db = make_db(tmp_path)
    fund(db, SELLER, "卖家", 100)
    for index in range(6):
        db.marketplace_core.save_draft(
            msg(SELLER, "卖家", "上架", f"page-draft-{index}"),
            "商品",
            {"title": f"商品{index}", "description": "测试商品", "price": 50, "stock": 1, "duration_days": 3},
            ttl_seconds=600,
        )
        maximum = 3 if index == 3 else 10
        if index == 3:
            with pytest.raises(ValueError, match="最多同时上架3件"):
                db.marketplace_core.confirm_draft(
                    msg(SELLER, "卖家", "确认", f"page-confirm-{index}"), mode="create", maximum_active=maximum
                )
            db.marketplace_core.cancel_draft(msg(SELLER, "卖家", "取消", f"page-cancel-{index}"), "create")
            continue
        db.marketplace_core.confirm_draft(
            msg(SELLER, "卖家", "确认", f"page-confirm-{index}"), mode="create", maximum_active=maximum
        )
    first_page = db.marketplace_core.list_page(1, 5)
    assert first_page["total"] == 5 and len(first_page["items"]) == 5
    listing_id = first_page["items"][0]["id"]
    db.conn.execute("update market_listings set expires_at='2000-01-01 00:00:00' where id=?", (listing_id,))
    db.conn.commit()
    assert db.marketplace_core.expire_due() == 1
    renewed = db.marketplace_core.renew(
        listing_id, msg(SELLER, "卖家", "续期", "renew"), 3, maximum_active=10
    )
    assert renewed["ok"] and renewed["listing"]["status"] == "on_sale"


@pytest.mark.skip(reason="旧市场群聊命令已废弃")
def test_market_list_and_help_commands_are_concise(tmp_path):
    db = make_db(tmp_path)
    fund(db, SELLER, "卖家", 100)
    router = CommandRouter(db, ai_client_factory=FakeAI)
    assert router.handle(msg(SELLER, "卖家", "/市场", "list")).handled
    help_result = router.handle(msg(SELLER, "卖家", "/市场帮助", "help"))
    assert "官方" not in help_result.replies[0]
    assert "/上架市场" in help_result.replies[0]
    assert len(help_result.replies[0].splitlines()) <= 10


@pytest.mark.skip(reason="旧市场命令设置已由统一委托命令设置替换")
def test_all_market_commands_can_be_renamed_and_old_defaults_stop_matching(tmp_path):
    db = make_db(tmp_path)
    fund(db, SELLER, "卖家", 500)
    config = db.get_config()
    config["features"].update({
        "market_list_commands": "/集市",
        "market_help_commands": "/集市帮助",
        "market_create_commands": "/出售",
        "market_confirm_create_commands": "/确认出售",
        "market_cancel_create_commands": "/取消出售",
        "market_edit_commands": "/改货",
        "market_confirm_edit_commands": "/确认改货",
        "market_cancel_edit_commands": "/取消改货",
        "market_detail_commands": "/货品详情",
        "market_purchase_commands": "/买货",
        "market_mine_commands": "/我的货架",
        "market_off_shelf_commands": "/撤货",
        "market_renew_commands": "/续货",
    })
    db.save_config(config)
    db.marketplace_core.save_draft(
        msg(SELLER, "卖家", "上架", "renamed-core-draft"),
        "商品",
        {"title": "测试商品", "description": "用于验证改名后的全部市场指令", "price": 80, "stock": 2, "duration_days": 3},
        ttl_seconds=600,
    )
    db.marketplace_core.confirm_draft(
        msg(SELLER, "卖家", "确认", "renamed-core-confirm"), mode="create", maximum_active=3
    )
    router = CommandRouter(db, ai_client_factory=FakeAI)

    cases = [
        ("/集市", False),
        ("/集市帮助", False),
        ("/出售：陪玩一小时，每份80功德", True),
        ("/确认出售", True),
        ("/取消出售", True),
        ("/改货M0001：改成每份90功德", True),
        ("/确认改货", True),
        ("/取消改货", True),
        ("/货品详情M0001", False),
        ("/买货M0001*2", True),
        ("/我的货架", False),
        ("/撤货M0001", True),
        ("/续货M0001*5", True),
    ]
    for index, (text, dry_run) in enumerate(cases):
        result = router.handle(msg(SELLER, "卖家", text, f"renamed-{index}"), dry_run=dry_run)
        assert result.handled, text

    help_reply = router.handle(msg(SELLER, "卖家", "/集市帮助", "renamed-help")).replies[0]
    assert "/出售" in help_reply and "/买货" in help_reply and "/续货" in help_reply
    assert not router.handle(msg(SELLER, "卖家", "/市场", "old-market-command")).handled


def test_empty_expiry_sweep_closes_implicit_sqlite_transaction(tmp_path):
    db = make_db(tmp_path)
    assert db.marketplace_core.expire_due() == 0
    db.conn.execute("begin immediate")
    db.conn.rollback()
