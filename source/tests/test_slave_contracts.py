import asyncio
from datetime import datetime, timedelta

from app.command_router import CommandRouter
from app.database import Database
from app.scheduler import BotScheduler


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    return db


def set_points(db, user, amount):
    db.conn.execute(
        "update users set points=? where id=?",
        (int(amount), int(user["id"])),
    )
    db.conn.commit()


def request(router, borrower, lender, amount):
    return router.handle(
        {
            "sender": borrower,
            "text": f"/发起奴隶契约 {lender} {amount}",
        }
    )


def test_contract_acceptance_transfers_points_and_profiles_show_both_sides(tmp_path):
    db = make_db(tmp_path)
    borrower = db.ensure_user("欠款人")
    lender = db.ensure_user("主人")
    set_points(db, lender, 100)
    router = CommandRouter(db)

    applied = request(router, "欠款人", "主人", 80)
    assert applied.handled
    assert "/同意" in applied.replies[0]
    assert db.get_user("欠款人")["points"] == 0
    assert db.get_user("主人")["points"] == 100

    accepted = router.handle({"sender": "主人", "text": "/同意"})
    assert "奴隶契约成立" in accepted.replies[0]
    assert db.get_user("欠款人")["points"] == 80
    assert db.get_user("主人")["points"] == 20

    borrower_profile = router.handle({"sender": "欠款人", "text": "/me"}).replies[0]
    lender_profile = router.handle({"sender": "主人", "text": "/我"}).replies[0]
    assert "我的主人：主人（欠款 80 功德点）" in borrower_profile
    assert "我的奴隶1：欠款人（欠款 80 功德点）" in lender_profile
    assert "奴隶契约：向 主人 借款 80 功德点" in borrower_profile


def test_lender_must_have_full_amount_when_agreeing(tmp_path):
    db = make_db(tmp_path)
    db.ensure_user("欠款人")
    lender = db.ensure_user("放款人")
    set_points(db, lender, 50)
    router = CommandRouter(db)

    request(router, "欠款人", "放款人", 80)
    rejected = router.handle({"sender": "放款人", "text": "/同意"})

    assert "余额不足" in rejected.replies[0]
    assert db.get_user("放款人")["points"] == 50
    assert db.get_user("欠款人")["points"] == 0
    assert db.conn.execute(
        "select status from slave_contracts"
    ).fetchone()[0] == "pending"


def test_master_can_initiate_and_target_can_accept(tmp_path):
    db = make_db(tmp_path)
    master = db.ensure_user("主动主人")
    db.ensure_user("预定奴隶")
    set_points(db, master, 100)
    router = CommandRouter(db)

    applied = router.handle(
        {"sender": "主动主人", "text": "/招收奴隶 预定奴隶 80"}
    )

    assert applied.handled
    assert "预定奴隶" in applied.replies[0]
    assert "/同意" in applied.replies[0]
    pending = db.conn.execute(
        "select requested_by_role, status from slave_contracts"
    ).fetchone()
    assert tuple(pending) == ("lender", "pending")

    accepted = router.handle({"sender": "预定奴隶", "text": "/同意"})

    assert "奴隶契约成立" in accepted.replies[0]
    assert db.get_user("主动主人")["points"] == 20
    assert db.get_user("预定奴隶")["points"] == 80
    assert db.slave_contract_summary("预定奴隶")["master"]["lender_title"] == "主动主人"


def test_master_cannot_initiate_without_full_amount(tmp_path):
    db = make_db(tmp_path)
    master = db.ensure_user("穷主人")
    db.ensure_user("目标")
    set_points(db, master, 30)
    router = CommandRouter(db)

    result = router.handle({"sender": "穷主人", "text": "/收奴隶 目标 80"})

    assert "当前只有 30" in result.replies[0]
    assert db.conn.execute("select count(*) from slave_contracts").fetchone()[0] == 0


def test_repayment_requires_full_balance_and_removes_contract(tmp_path):
    db = make_db(tmp_path)
    borrower = db.ensure_user("欠款人")
    lender = db.ensure_user("主人")
    set_points(db, lender, 100)
    router = CommandRouter(db)
    request(router, "欠款人", "主人", 80)
    router.handle({"sender": "主人", "text": "/同意"})
    set_points(db, borrower, 60)

    rejected = router.handle({"sender": "欠款人", "text": "/还款"})
    assert "还差 20" in rejected.replies[0]
    assert db.slave_contract_summary(borrower)["master"] is not None

    set_points(db, borrower, 80)
    repaid = router.handle({"sender": "欠款人", "text": "/还款"})
    assert "契约正式解除" in repaid.replies[0]
    assert db.get_user("欠款人")["points"] == 0
    assert db.get_user("主人")["points"] == 100
    assert db.slave_contract_summary(borrower)["master"] is None


def test_user_can_own_two_slaves_and_also_be_someone_elses_slave(tmp_path):
    db = make_db(tmp_path)
    owner = db.ensure_user("双重身份")
    db.ensure_user("奴隶甲")
    db.ensure_user("奴隶乙")
    upper_lender = db.ensure_user("上级主人")
    set_points(db, owner, 200)
    set_points(db, upper_lender, 100)
    router = CommandRouter(db)

    request(router, "奴隶甲", "双重身份", 100)
    router.handle({"sender": "双重身份", "text": "/同意"})
    request(router, "奴隶乙", "双重身份", 100)
    router.handle({"sender": "双重身份", "text": "/同意"})
    set_points(db, owner, -50)  # 模拟契约成立后在纸牌游戏中输成负数

    request(router, "双重身份", "上级主人", 100)
    accepted = router.handle({"sender": "上级主人", "text": "/同意"})

    assert "奴隶契约成立" in accepted.replies[0]
    summary = db.slave_contract_summary(owner)
    assert len(summary["slaves"]) == 2
    assert summary["master"]["lender_title"] == "上级主人"
    assert db.get_user("双重身份")["points"] == 50
    profile = router.handle({"sender": "双重身份", "text": "/me"}).replies[0]
    assert "我的主人：上级主人" in profile
    assert "我的奴隶1：奴隶甲" in profile
    assert "我的奴隶2：奴隶乙" in profile


def test_master_cannot_own_a_third_slave(tmp_path):
    db = make_db(tmp_path)
    master = db.ensure_user("主人")
    set_points(db, master, 300)
    for name in ("甲", "乙", "丙"):
        db.ensure_user(name)
    router = CommandRouter(db)

    for name in ("甲", "乙"):
        request(router, name, "主人", 50)
        router.handle({"sender": "主人", "text": "/同意"})

    third = request(router, "丙", "主人", 50)

    assert "2 名奴隶" in third.replies[0]
    assert len(db.slave_contract_summary(master)["slaves"]) == 2


def test_master_slave_limit_can_be_configured(tmp_path):
    db = make_db(tmp_path)
    config = db.get_config()
    config["features"]["slave_contract_max_slaves"] = 3
    db.save_config(config)
    master = db.ensure_user("三人主人")
    set_points(db, master, 400)
    for name in ("甲", "乙", "丙", "丁"):
        db.ensure_user(name)
    router = CommandRouter(db)

    for name in ("甲", "乙", "丙"):
        requested = request(router, name, "三人主人", 50)
        assert "/同意" in requested.replies[0]
        accepted = router.handle({"sender": "三人主人", "text": "/同意"})
        assert "奴隶契约成立" in accepted.replies[0]

    blocked = request(router, "丁", "三人主人", 50)

    assert "3 名奴隶" in blocked.replies[0]
    assert len(db.slave_contract_summary(master)["slaves"]) == 3


def test_legacy_master_limit_reply_is_migrated_to_dynamic_value(tmp_path):
    db = make_db(tmp_path)
    config = db.get_config()
    config["features"]["slave_contract_lender_limit_reply"] = (
        "{lender} 已经拥有两名奴隶，不能再接受新的契约。"
    )
    db.save_config(config)

    migrated = db.get_config()

    assert migrated["features"]["slave_contract_lender_limit_reply"] == (
        "{lender} 已经拥有 {max_slaves} 名奴隶，达到当前上限，不能再接受新的契约。"
    )


def test_slave_cannot_start_a_second_contract(tmp_path):
    db = make_db(tmp_path)
    for name in ("欠款人", "主人甲", "主人乙"):
        user = db.ensure_user(name)
        set_points(db, user, 100)
    router = CommandRouter(db)
    request(router, "欠款人", "主人甲", 50)
    router.handle({"sender": "主人甲", "text": "/同意"})

    second = request(router, "欠款人", "主人乙", 50)

    assert "已经是别人的奴隶" in second.replies[0]


def test_slave_status_cannot_be_removed_manually(tmp_path):
    db = make_db(tmp_path)
    db.ensure_user("欠款人")
    lender = db.ensure_user("主人")
    set_points(db, lender, 100)
    router = CommandRouter(db)
    request(router, "欠款人", "主人", 50)
    router.handle({"sender": "主人", "text": "/同意"})

    result = router.handle({"sender": "欠款人", "text": "/解除状态1"})

    assert "必须发送 /还款" in result.replies[0]
    assert db.slave_contract_summary("欠款人")["master"] is not None


def test_contract_amount_is_limited_to_one_hundred(tmp_path):
    db = make_db(tmp_path)
    db.ensure_user("欠款人")
    db.ensure_user("主人")
    router = CommandRouter(db)

    result = request(router, "欠款人", "主人", 101)

    assert "1～100" in result.replies[0]
    assert db.conn.execute("select count(*) from slave_contracts").fetchone()[0] == 0


def test_lender_can_reject_and_requester_can_apply_again(tmp_path):
    db = make_db(tmp_path)
    db.ensure_user("欠款人")
    lender = db.ensure_user("放款人")
    set_points(db, lender, 100)
    router = CommandRouter(db)
    request(router, "欠款人", "放款人", 60)

    rejected = router.handle({"sender": "放款人", "text": "/拒绝"})

    assert "拒绝了" in rejected.replies[0]
    assert db.get_user("欠款人")["points"] == 0
    assert db.get_user("放款人")["points"] == 100
    assert db.conn.execute(
        "select status from slave_contracts order by id desc limit 1"
    ).fetchone()[0] == "rejected"

    reapplied = request(router, "欠款人", "放款人", 60)
    assert "/同意" in reapplied.replies[0]


def test_reject_without_pending_request_is_safe(tmp_path):
    db = make_db(tmp_path)
    db.ensure_user("放款人")
    result = CommandRouter(db).handle({"sender": "放款人", "text": "/拒绝"})

    assert "没有需要你拒绝" in result.replies[0]


def test_public_borrower_offer_is_accepted_with_plain_agree(tmp_path):
    db = make_db(tmp_path)
    borrower = db.ensure_user("公开欠款人")
    lender = db.ensure_user("路过的主人")
    set_points(db, borrower, -80)
    set_points(db, lender, 100)
    router = CommandRouter(db)

    published = router.handle({"sender": "公开欠款人", "text": "/发起奴隶契约"})

    assert "直接发送 /同意" in published.replies[0]
    assert "80" in published.replies[0]
    accepted = router.handle({"sender": "路过的主人", "text": "/同意"})

    assert "公开奴隶契约成立" in accepted.replies[0]
    assert db.get_user("公开欠款人")["points"] == 0
    assert db.get_user("路过的主人")["points"] == 20
    contract = db.conn.execute(
        "select amount, status from slave_contracts order by id desc limit 1"
    ).fetchone()
    assert tuple(contract) == (80, "active")


def test_public_lender_offer_is_accepted_with_plain_agree(tmp_path):
    db = make_db(tmp_path)
    lender = db.ensure_user("公开招收者")
    borrower = db.ensure_user("愿意签约者")
    set_points(db, lender, 100)
    set_points(db, borrower, -60)
    router = CommandRouter(db)

    published = router.handle({"sender": "公开招收者", "text": "/招收奴隶"})

    assert "直接发送 /同意" in published.replies[0]
    accepted = router.handle({"sender": "愿意签约者", "text": "/同意"})

    assert "公开奴隶契约成立" in accepted.replies[0]
    assert db.get_user("公开招收者")["points"] == 40
    assert db.get_user("愿意签约者")["points"] == 0
    assert db.slave_contract_summary("愿意签约者")["master"]["lender_title"] == "公开招收者"


def test_positive_balance_user_gets_clear_reason_for_open_lender_offer(tmp_path):
    db = make_db(tmp_path)
    lender = db.ensure_user("公开招收主人")
    willing_user = db.ensure_user("愿意但没有负债")
    set_points(db, lender, 100)
    set_points(db, willing_user, 13)
    router = CommandRouter(db)

    router.handle({"sender": "公开招收主人", "text": "/招收奴隶"})
    result = router.handle({"sender": "愿意但没有负债", "text": "/同意"})

    assert "当前余额为 13" in result.replies[0]
    assert "只允许负债用户接受" in result.replies[0]
    assert db.conn.execute(
        "select status from slave_contract_offers order by id desc limit 1"
    ).fetchone()[0] == "open"


def test_plain_agree_uses_the_latest_compatible_public_offer(tmp_path):
    db = make_db(tmp_path)
    first = db.ensure_user("先发布的人")
    latest = db.ensure_user("后发布的人")
    lender = db.ensure_user("接受者")
    set_points(db, first, -30)
    set_points(db, latest, -40)
    set_points(db, lender, 100)
    router = CommandRouter(db)

    router.handle({"sender": "先发布的人", "text": "/发起奴隶契约"})
    router.handle({"sender": "后发布的人", "text": "/发起奴隶契约"})
    accepted = router.handle({"sender": "接受者", "text": "/同意"})

    assert "后发布的人" in accepted.replies[0]
    assert db.get_user("后发布的人")["points"] == 0
    assert db.get_user("先发布的人")["points"] == -30


def test_public_offer_stays_open_when_accepting_lender_cannot_cover_debt(tmp_path):
    db = make_db(tmp_path)
    borrower = db.ensure_user("高额欠款人")
    lender = db.ensure_user("余额不足者")
    set_points(db, borrower, -80)
    set_points(db, lender, 30)
    router = CommandRouter(db)

    router.handle({"sender": "高额欠款人", "text": "/发起奴隶契约"})
    rejected = router.handle({"sender": "余额不足者", "text": "/同意"})

    assert "余额不足" in rejected.replies[0]
    assert db.get_user("高额欠款人")["points"] == -80
    assert db.get_user("余额不足者")["points"] == 30
    assert db.conn.execute(
        "select status from slave_contract_offers order by id desc limit 1"
    ).fetchone()[0] == "open"


def test_only_one_public_lender_bounty_can_exist_at_a_time(tmp_path):
    db = make_db(tmp_path)
    first = db.ensure_user("第一位招收者")
    second = db.ensure_user("第二位招收者")
    set_points(db, first, 100)
    set_points(db, second, 100)
    router = CommandRouter(db)

    created = router.handle({"sender": "第一位招收者", "text": "/招收奴隶"})
    blocked = router.handle({"sender": "第二位招收者", "text": "/招收奴隶"})

    assert "5 分钟" in created.replies[0]
    assert "全群同一时间只能存在一条" in blocked.replies[0]
    assert "第一位招收者" in blocked.replies[0]
    assert db.conn.execute(
        "select count(*) from slave_contract_offers where offer_type='lender_open' and status='open'"
    ).fetchone()[0] == 1


def test_lender_bounty_expires_after_five_minutes_and_is_claimed_once(tmp_path):
    db = make_db(tmp_path)
    lender = db.ensure_user("超时招收者")
    set_points(db, lender, 100)
    router = CommandRouter(db)
    router.handle({"sender": "超时招收者", "text": "/招收奴隶"})
    expired_at = (datetime.now() - timedelta(minutes=6)).strftime("%Y-%m-%d %H:%M:%S")
    db.conn.execute(
        "update slave_contract_offers set created_at=? where creator_user_pk=?",
        (expired_at, lender["id"]),
    )
    db.conn.commit()

    claimed = db.claim_expired_lender_offers()

    assert len(claimed) == 1
    assert claimed[0]["creator_nickname"] == "超时招收者"
    assert db.conn.execute(
        "select status from slave_contract_offers where id=?",
        (claimed[0]["id"],),
    ).fetchone()[0] == "expired"
    db.finish_expired_lender_offer_notification(claimed[0]["id"], True)
    assert db.claim_expired_lender_offers() == []


def test_scheduler_sends_lender_bounty_cancellation_notice(tmp_path):
    class Adapter:
        def __init__(self):
            self.sent = []

        async def send_message(self, text):
            self.sent.append(text)
            return True

    class Logger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    db = make_db(tmp_path)
    lender = db.ensure_user("等待超时的主人")
    set_points(db, lender, 100)
    router = CommandRouter(db)
    router.handle({"sender": "等待超时的主人", "text": "/招收奴隶"})
    db.conn.execute(
        "update slave_contract_offers set created_at=?",
        ((datetime.now() - timedelta(minutes=6)).strftime("%Y-%m-%d %H:%M:%S"),),
    )
    db.conn.commit()
    adapter = Adapter()
    scheduler = BotScheduler(db, adapter, engine=None, logger=Logger(), command_router=router)
    config = db.get_config()
    config["dzmm"]["send_delay_seconds"] = 0.001

    asyncio.run(scheduler._process_expired_slave_contract_offers(config))

    assert len(adapter.sent) == 1
    assert "等待超时的主人" in adapter.sent[0]
    assert "5 分钟无人回应" in adapter.sent[0]
    assert "自动取消" in adapter.sent[0]
