from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Database


def scalar(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0] or 0)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_commission_house_migration.py DATABASE")
    path = Path(sys.argv[1]).resolve()
    before = sqlite3.connect(path)
    report = {
        "legacy_demands": scalar(before, "select count(*) from bounties where coalesce(bounty_mode,'request')='request'"),
        "legacy_service_bounties": scalar(before, "select count(*) from bounties where bounty_mode='service'"),
        "legacy_market_services": scalar(before, "select count(*) from market_listings"),
        "legacy_bounty_orders": scalar(before, "select count(*) from bounty_participants"),
        "legacy_market_orders": scalar(before, "select count(*) from market_orders"),
        "user_points": scalar(before, "select coalesce(sum(points),0) from users"),
        "transactions": scalar(before, "select count(*) from transactions"),
    }
    before.close()
    db = Database(path)
    db.init()
    report.update({
        "v2_demands": scalar(db.conn, "select count(*) from commission_demands"),
        "v2_services": scalar(db.conn, "select count(*) from commission_services"),
        "v2_orders": scalar(db.conn, "select count(*) from commission_orders_v2"),
        "user_points_after": scalar(db.conn, "select coalesce(sum(points),0) from users"),
        "transactions_after": scalar(db.conn, "select count(*) from transactions"),
        "demand_content_mismatches": scalar(db.conn, """select count(*) from commission_demands d join bounties b on d.legacy_source_type='bounty' and d.legacy_source_id=b.id where d.original_text!=b.content or d.content!=b.content"""),
        "service_content_mismatches": scalar(db.conn, """select count(*) from commission_services s join bounties b on s.legacy_source_type='bounty' and s.legacy_source_id=b.id where s.original_text!=b.content or s.description!=b.content"""),
        "market_content_mismatches": scalar(db.conn, """select count(*) from commission_services s join market_listings m on s.legacy_source_type='market_listing' and s.legacy_source_id=m.id where s.title!=m.title or s.description!=m.description"""),
        "demand_participant_count_mismatches": scalar(db.conn, """select count(*) from commission_demands d where d.legacy_source_type='bounty' and d.accepted_count!=(select count(*) from commission_orders_v2 o where o.demand_id=d.id and o.status!='cancelled')"""),
        "market_amount_mismatches": scalar(db.conn, """select count(*) from commission_orders_v2 o join market_orders m on o.legacy_source_type='market_order' and o.legacy_source_id=m.id where o.gross_amount!=m.gross_amount or o.commission_amount!=m.commission_amount or o.provider_net_amount!=m.seller_net_amount"""),
        "duplicate_public_codes": scalar(db.conn, """select count(*) from (select prefix,public_number,count(*) c from commission_public_ids group by prefix,public_number having c>1)"""),
    })
    db.close()
    report["ok"] = (
        report["legacy_demands"] == report["v2_demands"]
        and report["legacy_service_bounties"] + report["legacy_market_services"] == report["v2_services"]
        and report["legacy_bounty_orders"] + report["legacy_market_orders"] == report["v2_orders"]
        and report["user_points"] == report["user_points_after"]
        and report["transactions"] == report["transactions_after"]
        and report["demand_content_mismatches"] == 0
        and report["service_content_mismatches"] == 0
        and report["market_content_mismatches"] == 0
        and report["demand_participant_count_mismatches"] == 0
        and report["market_amount_mismatches"] == 0
        and report["duplicate_public_codes"] == 0
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
