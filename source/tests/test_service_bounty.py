import json

from app.command_router import CommandRouter
from app.database import Database


PUBLISHER = "11111111-1111-1111-1111-111111111111"
TAKER = "22222222-2222-2222-2222-222222222222"


class ServiceBountyAI:
    def __init__(self, **_kwargs):
        pass

    def generate(self, *, user_prompt: str, **_kwargs) -> str:
        price = 200 if "200" in user_prompt else 50 if "50" in user_prompt else 100
        days = 1 if "持续1天" in user_prompt else None
        return json.dumps({
            "task_type": "duration" if days else "single",
            "duration_days": days,
            "required_count": 1,
            "reward_per_person": price,
            "content": "陪你聊天一个小时" if not days else "陪你聊天",
            "bounty_mode": "service",
            "missing_fields": [],
            "parse_success": True,
        }, ensure_ascii=False)


def message(user_id: str, nickname: str, text: str, group_key: str = "main") -> dict:
    return {
        "platform_user_id": user_id,
        "user_id": user_id,
        "sender": nickname,
        "message_id": f"{group_key}-{user_id}-{text}",
        "text": text,
        "group_key": group_key,
        "source_group": group_key,
    }


def user(db: Database, user_id: str, nickname: str, points: int) -> dict:
    item = db.ensure_user(message(user_id, nickname, ""))
    if points:
        db.add_points(item, points, "test setup")
    return db.get_user(item)


def make_db(tmp_path) -> Database:
    db = Database(tmp_path / "bot.db")
    db.init()
    return db


def make_router(db: Database) -> CommandRouter:
    db.set_secret("deepseek_api_key", "test")
    return CommandRouter(db, ai_client_factory=ServiceBountyAI)


def test_service_bounty_escrows_taker_and_pays_provider_after_confirmation(tmp_path):
    db = make_db(tmp_path)
    publisher = user(db, PUBLISHER, "provider", 0)
    taker = user(db, TAKER, "customer", 110)
    router = make_router(db)

    published = router.handle(message(PUBLISHER, "provider", "/服务：陪你聊天一个小时，每次100功德"))
    router.handle(message(PUBLISHER, "provider", "/确认发布"))
    bounty = db.get_bounty(1)
    assert published.handled
    assert bounty["bounty_mode"] == "service"
    assert bounty["reward_escrow"] == 0
    assert bounty["total_charge"] == 0
    assert db.get_user(publisher)["points"] == 60

    accepted = router.handle(message(TAKER, "customer", "/接取服务S0001", "bounty"))
    assert accepted.handled
    assert db.get_user(taker)["points"] == 60
    negative_transactions = db.conn.execute(
        "select user_id,change_amount from transactions where change_amount<0 order by id"
    ).fetchall()
    assert {row["user_id"] for row in negative_transactions} == {TAKER}
    participant = db.get_bounty(1)["participants"][0]
    assert participant["escrow_amount"] == 100
    assert participant["escrow_fee"] == 10

    router.handle(message(PUBLISHER, "provider", "/完成订单O0001", "bounty"))
    router.handle(message(TAKER, "customer", "/确认订单O0001", "bounty"))
    assert db.get_user(publisher)["points"] == 160
    assert db.get_user(taker)["points"] == 60
    assert db.get_bounty(1)["status"] == "completed"


def test_service_bounty_parses_duration_and_uses_compact_card(tmp_path):
    db = make_db(tmp_path)
    user(db, PUBLISHER, "provider", 0)
    router = make_router(db)
    result = router.handle(message(PUBLISHER, "provider", "/服务：陪你聊天，持续1天，每次50功德"))
    router.handle(message(PUBLISHER, "provider", "/确认发布"))
    bounty = db.get_bounty(1)
    assert result.handled
    assert bounty["duration_type"] == "days"
    assert bounty["duration_days"] == 1
    assert len(result.replies[0].splitlines()) <= 9
    assert "类型：1天" in result.replies[0]
    assert "每位买家支付：55功德" in result.replies[0]


def test_service_bounty_cancel_refunds_customer_escrow(tmp_path):
    db = make_db(tmp_path)
    user(db, PUBLISHER, "provider", 0)
    taker = user(db, TAKER, "customer", 110)
    router = make_router(db)
    router.handle(message(PUBLISHER, "provider", "/服务：陪你聊天一个小时，每次100功德"))
    router.handle(message(PUBLISHER, "provider", "/确认发布"))
    router.handle(message(TAKER, "customer", "/接取服务S0001", "bounty"))
    router.handle(message(TAKER, "customer", "/申请取消订单O0001", "bounty"))
    router.handle(message(PUBLISHER, "provider", "/同意取消订单O0001", "bounty"))

    assert db.get_user(taker)["points"] == 170
    bounty = db.get_bounty(1)
    assert bounty["status"] == "waiting"
    assert bounty["refund_amount"] == 0
    assert bounty["participants"][0]["refunded_amount"] == 110


def test_service_bounty_requires_customer_to_have_price_and_fee(tmp_path):
    db = make_db(tmp_path)
    user(db, PUBLISHER, "provider", 0)
    taker = user(db, TAKER, "customer", 109)
    router = make_router(db)
    router.handle(message(PUBLISHER, "provider", "/服务：陪你聊天一个小时，每次200功德"))
    router.handle(message(PUBLISHER, "provider", "/确认发布"))
    result = router.handle(message(TAKER, "customer", "/接取服务S0001", "bounty"))

    assert result.handled
    assert db.get_user(taker)["points"] == 169
    assert db.get_bounty(1)["participants"] == []


def test_ai_service_bounty_is_drafted_then_confirmed(tmp_path):
    db = make_db(tmp_path)
    user(db, PUBLISHER, "provider", 0)
    router = make_router(db)
    draft = router.create_ai_bounty_draft(message(PUBLISHER, "provider", ""), "/服务：陪你聊天一个小时，每次100功德")
    assert draft.handled
    assert db.get_bounty_ai_draft(message(PUBLISHER, "provider", ""))

    confirmed = router.handle_ai_bounty_draft_confirmation(message(PUBLISHER, "provider", ""), confirm=True)
    assert confirmed.handled
    assert db.get_bounty(1)["bounty_mode"] == "service"
