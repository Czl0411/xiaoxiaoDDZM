from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import Database  # noqa: E402


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def safe_pairs(conn: sqlite3.Connection) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    verified = rows(conn, "select * from users where platform_user_id!=''")
    pending = rows(conn, "select * from users where platform_user_id=''")
    result: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for old in pending:
        candidates = [
            user
            for user in verified
            if user["nickname"] == old["nickname"]
            or (
                old.get("avatar_id")
                and user.get("avatar_id")
                and old["avatar_id"] == user["avatar_id"]
            )
        ]
        candidate_ids = {user["id"] for user in candidates}
        if len(candidate_ids) == 1:
            result.append((old, candidates[0]))
    return result


def append_history(*values: str) -> str:
    names: list[str] = []
    for value in values:
        for name in (value or "").split(","):
            name = name.strip()
            if name and name not in names:
                names.append(name)
    return ",".join(names[-20:])


def identity_match(column: str, nickname_column: str, old: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    avatar_id = (old.get("avatar_id") or "").strip()
    if avatar_id:
        return (
            f"(({column}='' or {column}=?) and {nickname_column}=?)",
            (avatar_id, old["nickname"]),
        )
    return f"({column}='' and {nickname_column}=?)", (old["nickname"],)


def archive_pending(conn: sqlite3.Connection, old: dict[str, Any], normal: dict[str, Any]) -> None:
    snapshot = {
        "repair": "identity-duplicate-20260717",
        "pending_user": old,
        "merged_into": {
            "id": normal["id"],
            "platform_user_id": normal["platform_user_id"],
            "nickname": normal["nickname"],
        },
    }
    conn.execute(
        """insert into deleted_user_archives(
             user_pk, platform_user_id, nickname, snapshot_json, deleted_at)
           values(?, '', ?, ?, ?)""",
        (
            old["id"],
            old["nickname"],
            json.dumps(snapshot, ensure_ascii=False),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


def migrate_pair(conn: sqlite3.Connection, old: dict[str, Any], normal: dict[str, Any]) -> None:
    uid = normal["platform_user_id"]
    nickname = normal["nickname"]

    # Tables whose user identity is stored in user_id/nickname.
    for table in ("transactions", "game_plays"):
        where, params = identity_match("user_id", "nickname", old)
        conn.execute(
            f"update {table} set user_id=?, nickname=? where {where}",
            (uid, nickname, *params),
        )

    # Check-ins and inventory have identity-scoped unique indexes and need merging.
    where, params = identity_match("user_id", "nickname", old)
    for checkin in rows(conn, f"select * from checkins where {where}", params):
        existing = conn.execute(
            "select * from checkins where user_id=? and checkin_date=? and id!=?",
            (uid, checkin["checkin_date"], checkin["id"]),
        ).fetchone()
        if existing:
            conn.execute(
                """update checkins set reward=max(reward, ?),
                     streak_days=max(streak_days, ?) where id=?""",
                (checkin["reward"], checkin["streak_days"], existing["id"]),
            )
            conn.execute("delete from checkins where id=?", (checkin["id"],))
        else:
            conn.execute(
                "update checkins set user_id=?, nickname=? where id=?",
                (uid, nickname, checkin["id"]),
            )

    for inventory in rows(conn, f"select * from inventory where {where}", params):
        existing = conn.execute(
            "select * from inventory where user_id=? and item_name=? and id!=?",
            (uid, inventory["item_name"], inventory["id"]),
        ).fetchone()
        if existing:
            conn.execute(
                """update inventory set quantity=quantity+?,
                     active_uses=max(active_uses, ?), updated_at=? where id=?""",
                (
                    inventory["quantity"],
                    inventory["active_uses"],
                    max(existing["updated_at"], inventory["updated_at"]),
                    existing["id"],
                ),
            )
            conn.execute("delete from inventory where id=?", (inventory["id"],))
        else:
            conn.execute(
                "update inventory set user_id=?, nickname=? where id=?",
                (uid, nickname, inventory["id"]),
            )

    # Game players are unique by game and verified UUID.
    for player in rows(conn, f"select * from game_players where {where}", params):
        existing = conn.execute(
            "select * from game_players where game_id=? and user_id=? and id!=?",
            (player["game_id"], uid, player["id"]),
        ).fetchone()
        if existing:
            conn.execute(
                """update game_players set is_winner=max(is_winner, ?),
                     hand_cards=coalesce(hand_cards, ?), hand_type=coalesce(hand_type, ?)
                   where id=?""",
                (player["is_winner"], player["hand_cards"], player["hand_type"], existing["id"]),
            )
            conn.execute("delete from game_players where id=?", (player["id"],))
        else:
            conn.execute(
                "update game_players set user_id=?, nickname=? where id=?",
                (uid, nickname, player["id"]),
            )

    # Sender/actor/target identity columns.
    for table, id_col, nick_col in (
        ("replies", "user_id", "sender"),
        ("rule_hits", "user_id", "sender"),
        ("red_packet_claims", "user_id", "nickname"),
    ):
        where, params = identity_match(id_col, nick_col, old)
        conn.execute(
            f"update or ignore {table} set {id_col}=?, {nick_col}=? where {where}",
            (uid, nickname, *params),
        )

    for table, id_col, nick_col in (
        ("theft_attempts", "actor_user_id", "actor_nickname"),
        ("theft_attempts", "target_user_id", "target_nickname"),
        ("user_status_effects", "actor_user_id", "actor_nickname"),
        ("user_status_effects", "target_user_id", "target_nickname"),
    ):
        where, params = identity_match(id_col, nick_col, old)
        conn.execute(
            f"update {table} set {id_col}=?, {nick_col}=? where {where}",
            (uid, nickname, *params),
        )

    where, params = identity_match("sender_user_id", "sender_nickname", old)
    conn.execute(
        f"update red_packets set sender_user_id=?, sender_nickname=? where {where}",
        (uid, nickname, *params),
    )
    where, params = identity_match("initiator_user_id", "initiator_nickname", old)
    conn.execute(
        f"update games set initiator_user_id=?, initiator_nickname=? where {where}",
        (uid, nickname, *params),
    )

    # Begging tables.
    where, params = identity_match("user_id", "nickname", old)
    conn.execute(
        f"update beg_sessions set user_id=?, nickname=? where {where}",
        (uid, nickname, *params),
    )
    for attempt in rows(conn, f"select * from beg_attempts where {where}", params):
        existing = conn.execute(
            """select * from beg_attempts
               where user_id=? and nickname=? and attempt_date=? and id!=?""",
            (uid, nickname, attempt["attempt_date"], attempt["id"]),
        ).fetchone()
        if existing:
            conn.execute(
                "update beg_attempts set attempt_count=attempt_count+? where id=?",
                (attempt["attempt_count"], existing["id"]),
            )
            conn.execute("delete from beg_attempts where id=?", (attempt["id"],))
        else:
            conn.execute(
                "update beg_attempts set user_id=?, nickname=? where id=?",
                (uid, nickname, attempt["id"]),
            )

    # Only avatar-backed legacy messages can be assigned safely.
    if old.get("avatar_id"):
        conn.execute(
            """update messages set user_id=?, platform_user_id=?,
                 identity_status='normal', sender=?
               where platform_user_id='' and avatar_id=?""",
            (uid, uid, nickname, old["avatar_id"]),
        )

    # Preserve identity observations and user statistics.
    for history in rows(conn, "select * from user_identity_history where user_pk=?", (old["id"],)):
        conn.execute(
            """insert or ignore into user_identity_history(
                 user_pk, platform_user_id, nickname, avatar_id, source_message_id, observed_at)
               values(?, ?, ?, ?, ?, ?)""",
            (
                normal["id"],
                history["platform_user_id"],
                history["nickname"],
                history["avatar_id"],
                history["source_message_id"],
                history["observed_at"],
            ),
        )
    conn.execute("delete from user_identity_history where user_pk=?", (old["id"],))

    history = append_history(
        old.get("nickname_history") or "",
        old["nickname"],
        normal.get("nickname_history") or "",
        nickname,
    )
    first_seen = min(
        [value for value in (old.get("first_seen_at"), normal.get("first_seen_at")) if value]
        or [None]
    )
    last_seen = max(
        [value for value in (old.get("last_seen_at"), normal.get("last_seen_at")) if value]
        or [None]
    )
    checkin_stats = conn.execute(
        """select count(*) as total, max(checkin_date) as last_date,
             coalesce(max(streak_days), 0) as max_streak
           from checkins where user_id=?""",
        (uid,),
    ).fetchone()
    display_name = normal.get("display_name") or nickname
    if display_name in ("未知用户", "我"):
        display_name = old.get("display_name") or nickname
    conn.execute(
        """update users set display_name=?, nickname_history=?,
             is_admin=max(is_admin, ?), message_count=message_count+?,
             hit_count=hit_count+?, total_checkins=?, streak_days=?,
             last_checkin_date=?, first_seen_at=?, last_seen_at=?,
             identity_status='normal', identity_conflict_reason=''
           where id=?""",
        (
            display_name,
            history,
            old.get("is_admin") or 0,
            old.get("message_count") or 0,
            old.get("hit_count") or 0,
            checkin_stats["total"],
            max(
                checkin_stats["max_streak"],
                old.get("streak_days") or 0,
                normal.get("streak_days") or 0,
            ),
            checkin_stats["last_date"],
            first_seen,
            last_seen,
            normal["id"],
        ),
    )
    archive_pending(conn, old, normal)
    conn.execute("delete from users where id=?", (old["id"],))


def repair_group_payout_balances(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    verified_by_name: dict[str, list[dict[str, Any]]] = {}
    for user in rows(conn, "select * from users where platform_user_id!=''"):
        verified_by_name.setdefault(user["nickname"], []).append(user)

    starts: dict[str, int] = {}
    for tx in rows(conn, "select * from transactions where user_id='' order by id"):
        matches = verified_by_name.get(tx["nickname"], [])
        if len(matches) != 1 or tx["reason"] != "群对战获胜":
            continue
        uid = matches[0]["platform_user_id"]
        previous = conn.execute(
            """select * from transactions where id<?
               and (user_id=? or (user_id='' and nickname=?))
               order by id desc limit 1""",
            (tx["id"], uid, tx["nickname"]),
        ).fetchone()
        if not previous:
            continue
        implied_prior = int(tx["balance_after"]) - int(tx["change_amount"])
        if implied_prior != int(previous["balance_after"]):
            starts[uid] = min(starts.get(uid, tx["id"]), tx["id"])

    repairs: list[dict[str, Any]] = []
    for uid, first_id in starts.items():
        user = dict(
            conn.execute("select * from users where platform_user_id=?", (uid,)).fetchone()
        )
        previous = conn.execute(
            """select * from transactions where id<?
               and (user_id=? or (user_id='' and nickname=?))
               order by id desc limit 1""",
            (first_id, uid, user["nickname"]),
        ).fetchone()
        running = int(previous["balance_after"])
        before = int(user["points"])
        affected = rows(
            conn,
            """select * from transactions where id>=?
               and (user_id=? or (user_id='' and nickname=?)) order by id""",
            (first_id, uid, user["nickname"]),
        )
        for tx in affected:
            running += int(tx["change_amount"])
            conn.execute(
                "update transactions set user_id=?, nickname=?, balance_after=? where id=?",
                (uid, user["nickname"], running, tx["id"]),
            )
        conn.execute("update users set points=? where id=?", (running, user["id"]))
        repairs.append(
            {
                "user_id": uid,
                "nickname": user["nickname"],
                "before": before,
                "after": running,
                "first_transaction_id": first_id,
                "transaction_count": len(affected),
            }
        )
    return repairs


def sync_merged_balances(conn: sqlite3.Connection, merged_ids: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for uid in merged_ids:
        user = conn.execute("select * from users where platform_user_id=?", (uid,)).fetchone()
        latest = conn.execute(
            "select balance_after from transactions where user_id=? order by id desc limit 1",
            (uid,),
        ).fetchone()
        if not user or not latest or int(user["points"]) == int(latest["balance_after"]):
            continue
        before = int(user["points"])
        after = int(latest["balance_after"])
        conn.execute("update users set points=? where id=?", (after, user["id"]))
        result.append(
            {
                "user_id": uid,
                "nickname": user["nickname"],
                "before": before,
                "after": after,
                "reason": "merged_legacy_ledger",
            }
        )
    return result


def mark_remaining_verified_collisions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    collisions: dict[int, set[int]] = {}
    verified = rows(conn, "select * from users where platform_user_id!=''")
    for user in verified:
        for other in verified:
            if user["id"] == other["id"]:
                continue
            same_nickname = user["nickname"] == other["nickname"]
            same_avatar = (
                user.get("avatar_id")
                and other.get("avatar_id")
                and user["avatar_id"] == other["avatar_id"]
            )
            if same_nickname or same_avatar:
                collisions.setdefault(user["id"], set()).add(other["id"])

    result: list[dict[str, Any]] = []
    for user_pk, candidate_ids in collisions.items():
        user = dict(conn.execute("select * from users where id=?", (user_pk,)).fetchone())
        reason = "多个真实主页ID使用相同昵称或头像，必须人工确认"
        conn.execute(
            """update users set identity_status='conflict',
                 identity_conflict_reason=? where id=?""",
            (reason, user_pk),
        )
        candidate_text = ",".join(str(value) for value in sorted(candidate_ids))
        exists = conn.execute(
            """select id from identity_conflicts
               where status='open' and platform_user_id=? and reason=?""",
            (user["platform_user_id"], reason),
        ).fetchone()
        if not exists:
            conn.execute(
                """insert into identity_conflicts(
                     platform_user_id, nickname, avatar_id, candidate_user_ids,
                     reason, status, source_message_id, created_at)
                   values(?, ?, ?, ?, ?, 'open', '', ?)""",
                (
                    user["platform_user_id"],
                    user["nickname"],
                    user["avatar_id"],
                    candidate_text,
                    reason,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
        result.append(
            {
                "user_pk": user_pk,
                "platform_user_id": user["platform_user_id"],
                "nickname": user["nickname"],
                "candidate_user_ids": sorted(candidate_ids),
            }
        )
    return result


def execute(db_path: Path, apply: bool) -> dict[str, Any]:
    db = Database(db_path)
    if apply:
        db.init()
    conn = db.conn
    conn.row_factory = sqlite3.Row
    pairs = safe_pairs(conn)
    plan = {
        "safe_merges": [
            {
                "pending_pk": old["id"],
                "pending_nickname": old["nickname"],
                "verified_pk": normal["id"],
                "verified_nickname": normal["nickname"],
                "platform_user_id": normal["platform_user_id"],
                "same_avatar": bool(
                    old.get("avatar_id")
                    and old.get("avatar_id") == normal.get("avatar_id")
                ),
            }
            for old, normal in pairs
        ]
    }
    if not apply:
        db.conn.close()
        return plan

    conn.execute(
        """create table if not exists identity_repair_audits(
             id integer primary key autoincrement,
             repair_kind text not null,
             platform_user_id text not null default '',
             nickname text not null default '',
             before_json text not null,
             after_json text not null,
             created_at text not null)"""
    )
    conn.execute("begin immediate")
    try:
        # Repair broken group-payout ledgers while the UUID-less payout rows
        # are still distinguishable from ordinary verified transactions.
        balance_repairs = repair_group_payout_balances(conn)
        merged_ids: list[str] = []
        for old, normal in pairs:
            migrate_pair(conn, old, normal)
            merged_ids.append(normal["platform_user_id"])
            conn.execute(
                """insert into identity_repair_audits(
                     repair_kind, platform_user_id, nickname,
                     before_json, after_json, created_at)
                   values('merge_pending_duplicate', ?, ?, ?, ?, ?)""",
                (
                    normal["platform_user_id"],
                    normal["nickname"],
                    json.dumps(old, ensure_ascii=False),
                    json.dumps(
                        {"kept_user_pk": normal["id"], "deleted_pending_pk": old["id"]},
                        ensure_ascii=False,
                    ),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )

        balance_repairs.extend(sync_merged_balances(conn, merged_ids))
        for repair in balance_repairs:
            conn.execute(
                """insert into identity_repair_audits(
                     repair_kind, platform_user_id, nickname,
                     before_json, after_json, created_at)
                   values('restore_balance', ?, ?, ?, ?, ?)""",
                (
                    repair["user_id"],
                    repair["nickname"],
                    json.dumps({"points": repair["before"]}, ensure_ascii=False),
                    json.dumps(repair, ensure_ascii=False),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )

        conflicts = mark_remaining_verified_collisions(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    result = {
        **plan,
        "balance_repairs": balance_repairs,
        "remaining_conflicts": conflicts,
        "users": conn.execute("select count(*) from users").fetchone()[0],
        "duplicate_nicknames": conn.execute(
            """select count(*) from (
                 select nickname from users group by nickname having count(*)>1)"""
        ).fetchone()[0],
        "integrity": conn.execute("pragma integrity_check").fetchone()[0],
    }
    conn.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "bot.db")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db_path = args.db.resolve()
    if args.apply:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = db_path.parent / "backups" / f"bot-before-repair-apply-{stamp}.db"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_path, backup)
        print(json.dumps({"safety_backup": str(backup)}, ensure_ascii=False))
    print(json.dumps(execute(db_path, args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
