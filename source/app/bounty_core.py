from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any


BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


ACTIVE_PARTICIPANT_STATUSES = {"accepted", "completed", "paid"}
COMPLETED_PARTICIPANT_STATUSES = {"completed", "paid"}
ACTIVE_BOUNTY_STATUSES = {"waiting", "recruiting", "active", "awaiting_confirmation"}
TERMINAL_BOUNTY_STATUSES = {"completed", "cancelled"}
BUSINESS_STATUS_ORDER = (
    "waiting",
    "recruiting",
    "active",
    "awaiting_confirmation",
    "completed",
    "cancelled",
    "archived",
)
STATUS_LABELS = {
    "waiting": "待接取",
    "recruiting": "招募中",
    "active": "进行中",
    "awaiting_confirmation": "待确认",
    "completed": "已完成",
    "cancelled": "已取消",
    "archived": "已归档",
}
IMMUTABLE_ADMIN_FIELDS = {
    "id",
    "number",
    "publisher",
    "publisher_user_pk",
    "publisher_user_id",
    "publisher_nickname",
    "publisher_title",
    "taker_user_pk",
    "taker_user_id",
    "taker_nickname",
    "taker_title",
    "takers",
    "participants",
    "participant_ids",
    "completed_participants",
    "created_at",
    "accepted_at",
    "completion_requested_at",
    "completed_at",
    "cancelled_at",
    "refunded_at",
    "refund_amount",
    "fee_burned_at",
    "reward_escrow",
    "fee_escrow",
    "total_charge",
    "transactions",
    "payments",
}
ALLOWED_ADMIN_FIELDS = {
    "content",
    "duration_type",
    "duration_days",
    "required_count",
    "unlimited_stock",
    "reward_per_person",
    "reward",
    "status",
    "admin_note",
    "cancel_reason",
    "reason",
}


class BountyCore:
    """现有悬赏表的业务层；所有经济修改都在调用者事务中原子完成。"""

    def __init__(self, db):
        self.db = db

    @property
    def conn(self):
        return self.db.conn

    @staticmethod
    def _uuid(value: Any) -> str:
        uid = str(value or "").strip().lower()
        if not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            uid,
        ):
            raise ValueError("悬赏业务需要有效的平台唯一 ID")
        return uid

    def _verified_user(self, user_ref: dict[str, Any]) -> dict[str, Any]:
        uid = self._uuid(user_ref.get("platform_user_id") or user_ref.get("user_id"))
        user = self.db.ensure_user(user_ref)
        self.db._assert_not_identity_conflict(user)
        stored_uid = self._uuid(user.get("platform_user_id") or user.get("user_id"))
        if stored_uid != uid:
            raise ValueError("平台唯一 ID 与用户记录不一致")
        return user

    @staticmethod
    def amounts(required_count: int, reward_per_person: int) -> tuple[int, int, int]:
        required_count = int(required_count)
        reward_per_person = int(reward_per_person)
        if not 1 <= required_count <= 10:
            raise ValueError("悬赏人数必须在 1 到 10 人之间")
        if not 1 <= reward_per_person <= 100000:
            raise ValueError("每人奖励必须在 1 到 100000 功德之间")
        reward_escrow = required_count * reward_per_person
        fee_escrow = math.floor(reward_escrow * 10 / 100)
        return reward_escrow, fee_escrow, reward_escrow + fee_escrow

    @staticmethod
    def validate_service_stock(stock: int, reward_per_item: int) -> None:
        if not 1 <= int(stock) <= 999:
            raise ValueError("服务库存必须在 1 到 999 份之间，或设置为不限库存")
        if not 1 <= int(reward_per_item) <= 100000:
            raise ValueError("每份价格必须在 1 到 100000 功德之间")

    def _participants(self, bounty_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """select bp.*,u.nickname as current_nickname,u.display_name
               from bounty_participants bp
               left join users u on u.id=bp.user_pk
               where bp.bounty_id=? order by bp.accepted_at,bp.id""",
            (int(bounty_id),),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["order_number"] = self.db.commission_public_code(
                "bounty_participant", int(item["id"]), "O"
            )
            item["display_name"] = (
                item.get("display_name")
                or item.get("current_nickname")
                or item.get("display_name_snapshot")
            )
            result.append(item)
        return result

    @staticmethod
    def _counts(participants: list[dict[str, Any]]) -> tuple[int, int]:
        accepted = sum(1 for p in participants if p["participant_status"] in ACTIVE_PARTICIPANT_STATUSES)
        completed = sum(1 for p in participants if p["participant_status"] in COMPLETED_PARTICIPANT_STATUSES)
        return accepted, completed

    @staticmethod
    def derived_status(required_count: int, accepted_count: int, completed_count: int) -> str:
        if accepted_count == 0:
            return "waiting"
        if accepted_count < required_count:
            return "recruiting"
        if completed_count == required_count:
            return "awaiting_confirmation"
        return "active"

    @staticmethod
    def _is_unlimited_service(row: Any) -> bool:
        return (
            str(row["bounty_mode"] or "request") == "service"
            and bool(int(row["unlimited_stock"] or 0))
        )

    def _derived_status_for_row(
        self, row: Any, accepted_count: int, completed_count: int
    ) -> str:
        if self._is_unlimited_service(row):
            return "waiting" if accepted_count == 0 else "recruiting"
        return self.derived_status(
            int(row["required_count"] or 1), accepted_count, completed_count
        )

    def serialize(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        participants = self._participants(int(item["id"]))
        accepted_count, completed_count = self._counts(participants)
        publisher = self.conn.execute(
            "select * from users where id=?", (int(item["publisher_user_pk"]),)
        ).fetchone()
        required_count = max(1, int(item.get("required_count") or 1))
        paid_count = sum(1 for p in participants if p["participant_status"] == "paid")
        pending_confirmation_count = sum(
            1 for p in participants if p["participant_status"] == "completed"
        )
        reward_per_person = int(item.get("reward_per_person") or item.get("reward") or 0)
        is_service = str(item.get("bounty_mode") or "request") == "service"
        unlimited_stock = is_service and bool(int(item.get("unlimited_stock") or 0))
        reward_escrow = (
            0
            if is_service
            else int(item.get("reward_escrow") or item.get("reward") or 0)
        )
        fee_escrow = int(item.get("fee_escrow") or 0)
        item.update(
            {
                "number": self.db.bounty_number(int(item["id"])),
                "commission_number": self.db.commission_public_code(
                    "bounty", int(item["id"]), "S" if is_service else "D"
                ),
                "publisher_title": (
                    self.db.display_name(dict(publisher)) if publisher else item["publisher_nickname"]
                ),
                "participants": participants,
                "participant_names": [p["display_name"] for p in participants],
                "taker_title": participants[0]["display_name"] if participants else "",
                "required_count": required_count,
                "accepted_count": accepted_count,
                "completed_count": completed_count,
                "paid_count": paid_count,
                "pending_confirmation_count": pending_confirmation_count,
                "remaining_count": max(0, required_count - accepted_count),
                "unlimited_stock": unlimited_stock,
                "reward_per_person": reward_per_person,
                "reward": reward_per_person,
                "reward_escrow": reward_escrow,
                "fee_escrow": fee_escrow,
                "total_charge": (
                    int(item.get("total_charge") or 0)
                    if is_service
                    else int(item.get("total_charge") or reward_escrow + fee_escrow)
                ),
                "business_status": "archived" if item.get("archived_at") else item["status"],
            }
        )
        return item

    def get(self, bounty_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("select * from bounties where id=?", (int(bounty_id),)).fetchone()
        return self.serialize(row) if row else None

    def _tx(self, user: Any, amount: int, reason: str, balance_after: int, now: str) -> None:
        self.conn.execute(
            """insert into transactions(
                 user_id,nickname,change_amount,reason,balance_after,created_at)
               values(?,?,?,?,?,?)""",
            (
                str(user["platform_user_id"] or user["user_id"] or ""),
                str(user["nickname"] or ""),
                int(amount),
                reason,
                int(balance_after),
                now,
            ),
        )

    def create(
        self,
        publisher_ref: dict[str, Any],
        *,
        duration_type: str,
        duration_days: int,
        reward: int | None = None,
        reward_per_person: int | None = None,
        required_count: int = 1,
        content: str,
        source_group: str,
        external_transaction: bool = False,
        bounty_mode: str = "request",
        unlimited_stock: bool = False,
    ) -> dict[str, Any]:
        publisher = self._verified_user(publisher_ref)
        bounty_mode = str(bounty_mode or "request").strip().lower()
        if bounty_mode not in {"request", "service"}:
            raise ValueError("无效的悬赏模式")
        unlimited_stock = bool(unlimited_stock) and bounty_mode == "service"
        duration_days = int(duration_days)
        if duration_type not in {"single", "days"}:
            raise ValueError("悬赏类型只能是单次或持续")
        if duration_type == "days" and not 1 <= duration_days <= 10:
            raise ValueError("悬赏天数必须在 1 到 10 天之间")
        if duration_type == "single":
            duration_days = 0
        content = str(content or "").strip()
        if not content or len(content) > 500:
            raise ValueError("悬赏内容必须为 1 到 500 个字符")
        per_person = int(reward_per_person if reward_per_person is not None else reward or 0)
        if bounty_mode == "service":
            self.validate_service_stock(1 if unlimited_stock else required_count, per_person)
            reward_escrow, fee_escrow, total_charge = 0, 0, 0
        else:
            reward_escrow, fee_escrow, total_charge = self.amounts(
                required_count, per_person
            )
        now = self.db.now()
        if not external_transaction:
            self.conn.execute("begin immediate")
        try:
            current = self.conn.execute("select * from users where id=?", (int(publisher["id"]),)).fetchone()
            balance = int(current["points"] or 0)
            if bounty_mode == "request" and balance < total_charge:
                raise ValueError(f"余额不足，发布共需 {total_charge} 功德，当前只有 {balance}")
            final_balance = balance - total_charge if bounty_mode == "request" else balance
            if bounty_mode == "request":
                self.conn.execute(
                    "update users set points=?,last_seen_at=? where id=?",
                    (final_balance, now, int(current["id"])),
                )
            cursor = self.conn.execute(
                """insert into bounties(
                     bounty_mode,publisher_user_pk,publisher_user_id,publisher_nickname,
                     duration_type,duration_days,reward,content,status,source_group,
                     created_at,required_count,unlimited_stock,reward_per_person,reward_escrow,
                     fee_escrow,total_charge,updated_at)
                   values(?,?,?,?,?,?,?,?,'waiting',?,?,?,?,?,?,?,?,?)""",
                (
                    bounty_mode,
                    int(current["id"]),
                    str(current["platform_user_id"] or current["user_id"] or ""),
                    str(current["nickname"] or ""),
                    duration_type,
                    duration_days,
                    per_person,
                    content,
                    source_group if source_group in {"main", "bounty"} else "main",
                     now,
                     int(required_count),
                     int(unlimited_stock),
                     per_person,
                    0 if bounty_mode == "service" else reward_escrow,
                    fee_escrow,
                    0 if bounty_mode == "service" else total_charge,
                    now,
                ),
            )
            bounty_id = int(cursor.lastrowid)
            if bounty_mode == "request":
                reward_balance = balance - reward_escrow
                self._tx(current, -reward_escrow, f"发布悬赏功德托管 #{self.db.bounty_number(bounty_id)}", reward_balance, now)
                if fee_escrow:
                    self._tx(current, -fee_escrow, f"发布悬赏手续费托管 #{self.db.bounty_number(bounty_id)}", final_balance, now)
            if not external_transaction:
                self.conn.commit()
        except Exception:
            if not external_transaction:
                self.conn.rollback()
            raise
        return self.get(bounty_id)

    def list_available(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """select * from bounties
               where status in ('waiting','recruiting') and archived_at is null
               order by coalesce(nullif(updated_at,''),created_at) desc,id desc"""
        ).fetchall()
        return [self.serialize(row) for row in rows]

    def list_waiting_page(self, page: int = 1, per_page: int = 3) -> dict[str, Any]:
        items = self.list_available()
        per_page = max(1, min(int(per_page), 5))
        pages = max(1, math.ceil(len(items) / per_page))
        page = max(1, min(int(page), pages))
        start = (page - 1) * per_page
        return {"items": items[start : start + per_page], "page": page, "pages": pages, "total": len(items)}

    def available_from_sequence(self, sequence: int) -> dict[str, Any] | None:
        items = self.list_available()
        sequence = int(sequence)
        return items[sequence - 1] if 1 <= sequence <= len(items) else None

    def accept(self, bounty_id: int, taker_ref: dict[str, Any]) -> dict[str, Any]:
        taker = self._verified_user(taker_ref)
        ban = self.db._active_bounty_ban(int(taker["id"]))
        if ban:
            return {"ok": False, "reason": "banned", "ban": ban}
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            row = self.conn.execute("select * from bounties where id=?", (int(bounty_id),)).fetchone()
            if not row:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            if row["archived_at"] or row["status"] not in {"waiting", "recruiting"}:
                self.conn.rollback()
                return {"ok": False, "reason": "not_waiting", "bounty": self.serialize(row)}
            if int(row["publisher_user_pk"]) == int(taker["id"]):
                self.conn.rollback()
                return {"ok": False, "reason": "self", "bounty": self.serialize(row)}
            existing = self.conn.execute(
                "select 1 from bounty_participants where bounty_id=? and (user_pk=? or user_id=?)",
                (int(bounty_id), int(taker["id"]), str(taker["platform_user_id"])),
            ).fetchone()
            if existing:
                self.conn.rollback()
                return {"ok": False, "reason": "duplicate", "bounty": self.serialize(row)}
            participants = self._participants(int(bounty_id))
            accepted_count, _ = self._counts(participants)
            required_count = int(row["required_count"] or 1)
            unlimited_service = self._is_unlimited_service(row)
            if not unlimited_service and accepted_count >= required_count:
                self.conn.rollback()
                return {"ok": False, "reason": "full", "bounty": self.serialize(row)}
            escrow_amount = 0
            escrow_fee = 0
            if str(row["bounty_mode"] or "request") == "service":
                escrow_amount = int(row["reward_per_person"] or row["reward"] or 0)
                # 服务可以拥有多个名额；每位买家的手续费都按自己的订单金额计算，
                # 不能把整条服务的潜在总手续费重复扣给每一位买家。
                escrow_fee = math.floor(escrow_amount * 10 / 100)
                total_due = escrow_amount + escrow_fee
                current_taker = self.conn.execute("select * from users where id=?", (int(taker["id"]),)).fetchone()
                taker_balance = int(current_taker["points"] or 0)
                if taker_balance < total_due:
                    self.conn.rollback()
                    return {"ok": False, "reason": "insufficient_funds", "required": total_due, "balance": taker_balance, "bounty": self.serialize(row)}
                taker_balance -= total_due
                self.conn.execute("update users set points=?,last_seen_at=? where id=?", (taker_balance, now, int(taker["id"])))
                self._tx(current_taker, -escrow_amount, f"接取服务悬赏托管 #{self.db.bounty_number(int(bounty_id))}", taker_balance + escrow_fee, now)
                if escrow_fee:
                    self._tx(current_taker, -escrow_fee, f"服务悬赏手续费托管 #{self.db.bounty_number(int(bounty_id))}", taker_balance, now)
            self.conn.execute(
                """insert into bounty_participants(
                     bounty_id,user_pk,user_id,display_name_snapshot,participant_status,accepted_at,escrow_amount,escrow_fee)
                   values(?,?,?,?, 'accepted',?,?,?)""",
                (
                    int(bounty_id), int(taker["id"]), str(taker["platform_user_id"]),
                    str(taker.get("display_name") or taker.get("nickname") or ""), now, escrow_amount, escrow_fee,
                ),
            )
            accepted_count += 1
            new_status = (
                "recruiting" if unlimited_service
                else ("active" if accepted_count == required_count else "recruiting")
            )
            deadline = row["deadline_at"]
            if not deadline and row["duration_type"] == "days":
                deadline = (datetime.now() + timedelta(days=int(row["duration_days"]))).strftime("%Y-%m-%d %H:%M:%S")
            first_taker = row["taker_user_pk"] is None
            self.conn.execute(
                """update bounties set status=?,accepted_at=coalesce(accepted_at,?),deadline_at=?,
                     taker_user_pk=case when ? then ? else taker_user_pk end,
                     taker_user_id=case when ? then ? else taker_user_id end,
                     taker_nickname=case when ? then ? else taker_nickname end,updated_at=?
                   where id=?""",
                (
                    new_status, now, deadline, int(first_taker), int(taker["id"]),
                    int(first_taker), str(taker["platform_user_id"]), int(first_taker),
                    str(taker["nickname"] or ""), now, int(bounty_id),
                ),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"ok": True, "bounty": self.get(bounty_id)}

    def request_completion(self, bounty_id: int, taker_ref: dict[str, Any]) -> dict[str, Any]:
        taker = self._verified_user(taker_ref)
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            row = self.conn.execute("select * from bounties where id=?", (int(bounty_id),)).fetchone()
            if not row:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            participant = self.conn.execute(
                "select * from bounty_participants where bounty_id=? and user_pk=?",
                (int(bounty_id), int(taker["id"])),
            ).fetchone()
            if not participant:
                self.conn.rollback()
                return {"ok": False, "reason": "not_taker", "bounty": self.serialize(row)}
            if participant["participant_status"] in COMPLETED_PARTICIPANT_STATUSES:
                self.conn.rollback()
                return {"ok": False, "reason": "already_requested", "bounty": self.serialize(row)}
            if row["status"] not in {"recruiting", "active"} or participant["participant_status"] != "accepted":
                self.conn.rollback()
                return {"ok": False, "reason": "invalid_status", "bounty": self.serialize(row)}
            self.conn.execute(
                """update bounty_participants set participant_status='completed',completed_at=?
                   where id=? and participant_status='accepted'""",
                (now, int(participant["id"])),
            )
            participants = self._participants(int(bounty_id))
            accepted_count, completed_count = self._counts(participants)
            # 多人悬赏允许每位参与者独立申请、独立确认。聚合状态不能因为
            # 某一位待确认就阻断其他人继续接取或申请完成。
            required_count = int(row["required_count"] or 1)
            new_status = self._derived_status_for_row(
                row, accepted_count, completed_count
            )
            self.conn.execute(
                """update bounties set status=?,completion_requested_at=case when ?='awaiting_confirmation' then ? else completion_requested_at end,updated_at=? where id=?""",
                (new_status, new_status, now, now, int(bounty_id)),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {
            "ok": True,
            "bounty": self.get(bounty_id),
            "all_completed": new_status == "awaiting_confirmation",
            "participant": dict(participant),
        }

    def _settle_participant_locked(self, row: Any, participant: Any, now: str) -> dict[str, Any]:
        if row["archived_at"] or row["refunded_at"] or row["status"] not in ACTIVE_BOUNTY_STATUSES:
            raise ValueError("悬赏当前不满足结算状态")
        if participant["participant_status"] != "completed":
            raise ValueError("该参与者尚未申请完成或已经结算")
        user = self.conn.execute(
            "select * from users where id=?", (int(participant["user_pk"]),)
        ).fetchone()
        if not user or str(user["platform_user_id"] or user["user_id"] or "") != str(participant["user_id"]):
            raise ValueError("参与者平台唯一 ID 校验失败")
        if str(row["bounty_mode"] or "request") == "service":
            publisher = self.conn.execute("select * from users where id=?", (int(row["publisher_user_pk"]),)).fetchone()
            per_person = int(row["reward_per_person"] or row["reward"] or 0)
            publisher_balance = int(publisher["points"] or 0) + per_person
            self.conn.execute("update users set points=?,last_seen_at=? where id=?", (publisher_balance, now, int(publisher["id"])))
            self._tx(publisher, per_person, f"完成服务悬赏收款 #{self.db.bounty_number(int(row['id']))}", publisher_balance, now)
            fee = int(participant["escrow_fee"] or 0)
            if fee:
                self.conn.execute(
                    """insert or ignore into merit_recovery_records(
                         event_type,bounty_id,amount,reason,created_at) values(?,?,?,?,?)""",
                    (
                        f"service_fee:{int(participant['id'])}", int(row["id"]), fee,
                        f"服务订单 O{int(participant['id']):04d} 完成，手续费销毁", now,
                    ),
                )
            updated = self.conn.execute("update bounty_participants set participant_status='paid',confirmed_at=? where id=? and participant_status='completed'", (now, int(participant["id"])))
            if updated.rowcount != 1:
                raise ValueError("该参与者已经结算，请勿重复确认")
            participants = self._participants(int(row["id"]))
            accepted_count, _ = self._counts(participants)
            paid_count = sum(1 for item in participants if item["participant_status"] == "paid")
            required_count = int(row["required_count"] or 1)
            unlimited_service = self._is_unlimited_service(row)
            all_settled = False if unlimited_service else paid_count >= required_count
            new_status = (
                "completed" if all_settled
                else (
                    "recruiting" if unlimited_service or accepted_count < required_count
                    else "active"
                )
            )
            self.conn.execute(
                """update bounties set status=?,completed_at=?,
                     fee_burned_at=case when ? then coalesce(fee_burned_at,?) else fee_burned_at end,
                     updated_at=? where id=?""",
                (
                    new_status, now if all_settled else None, int(bool(fee)), now,
                    now, int(row["id"]),
                ),
            )
            return {
                "paid_total": per_person,
                "fee_burned": fee,
                "balance": publisher_balance,
                "participant_id": int(participant["id"]),
                "participant_name": (
                    participant.get("display_name") if isinstance(participant, dict) else ""
                ) or participant["display_name_snapshot"],
                "all_settled": all_settled,
            }
        per_person = int(row["reward_per_person"] or row["reward"])
        balance = int(user["points"] or 0) + per_person
        self.conn.execute(
            "update users set points=?,last_seen_at=? where id=?",
            (balance, now, int(user["id"])),
        )
        self._tx(
            user,
            per_person,
            f"完成悬赏结算 #{self.db.bounty_number(int(row['id']))} 参与者#{int(participant['id'])}",
            balance,
            now,
        )
        updated = self.conn.execute(
            """update bounty_participants set participant_status='paid',confirmed_at=?
               where id=? and participant_status='completed'""",
            (now, int(participant["id"])),
        )
        if updated.rowcount != 1:
            raise ValueError("该参与者已经结算，请勿重复确认")

        participants = self._participants(int(row["id"]))
        required_count = int(row["required_count"] or 1)
        accepted_count, _ = self._counts(participants)
        paid_count = sum(1 for item in participants if item["participant_status"] == "paid")
        fee = int(row["fee_escrow"] or 0)
        finished = paid_count == required_count
        fee_burned = 0
        if finished:
            if fee and not row["fee_burned_at"]:
                self.conn.execute(
                    """insert into merit_recovery_records(event_type,bounty_id,amount,reason,created_at)
                       values('bounty_fee',?,?,?,?)""",
                    (int(row["id"]), fee, "悬赏完成，10% 手续费正式销毁", now),
                )
                fee_burned = fee
            self.conn.execute(
                """update bounties set status='completed',completed_at=?,fee_burned_at=?,updated_at=?
                   where id=?""",
                (now, now if fee else None, now, int(row["id"])),
            )
        else:
            new_status = "recruiting" if accepted_count < required_count else "active"
            self.conn.execute(
                "update bounties set status=?,updated_at=? where id=?",
                (new_status, now, int(row["id"])),
            )
        return {
            "paid_total": per_person,
            "fee_burned": fee_burned,
            "balance": balance,
            "participant_id": int(participant["id"]),
            "participant_name": (
                participant.get("display_name") if isinstance(participant, dict) else ""
            ) or participant["display_name_snapshot"],
            "all_settled": finished,
        }

    def _settle_locked(self, row: Any, now: str) -> dict[str, Any]:
        if row["status"] != "awaiting_confirmation" or row["archived_at"] or row["refunded_at"]:
            raise ValueError("悬赏当前不满足结算状态")
        participants = self._participants(int(row["id"]))
        accepted_count, completed_count = self._counts(participants)
        required_count = int(row["required_count"] or 1)
        if accepted_count != required_count or completed_count != required_count:
            raise ValueError("必须名额已满且所有参与者均已完成才能结算")
        per_person = int(row["reward_per_person"] or row["reward"])
        reward_escrow = int(row["reward_escrow"] or row["reward"])
        if per_person * required_count != reward_escrow:
            raise ValueError("功德托管金额与参与人数不一致")
        pending = [p for p in participants if p["participant_status"] == "completed"]
        paid_total = 0
        balances: dict[str, int] = {}
        fee_burned = 0
        for participant in pending:
            current_row = self.conn.execute("select * from bounties where id=?", (int(row["id"]),)).fetchone()
            settlement = self._settle_participant_locked(current_row, participant, now)
            paid_total += int(settlement["paid_total"])
            balances[str(participant["user_id"])] = int(settlement["balance"])
            fee_burned += int(settlement["fee_burned"])
        if paid_total != per_person * len(pending):
            raise ValueError("结算总额与功德托管总额不一致")
        return {"paid_total": paid_total, "fee_burned": fee_burned, "balances": balances}

    def confirm(
        self, bounty_id: int, publisher_ref: dict[str, Any], participant_sequence: int | None = None
    ) -> dict[str, Any]:
        publisher = self._verified_user(publisher_ref)
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            row = self.conn.execute("select * from bounties where id=?", (int(bounty_id),)).fetchone()
            if not row:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            if int(row["publisher_user_pk"]) != int(publisher["id"]):
                self.conn.rollback()
                return {"ok": False, "reason": "not_publisher", "bounty": self.serialize(row)}
            if row["status"] not in ACTIVE_BOUNTY_STATUSES:
                self.conn.rollback()
                return {"ok": False, "reason": "invalid_status", "bounty": self.serialize(row)}
            pending = [
                item for item in self._participants(int(bounty_id))
                if item["participant_status"] == "completed"
            ]
            if not pending:
                self.conn.rollback()
                return {"ok": False, "reason": "invalid_status", "bounty": self.serialize(row)}
            sequence = int(participant_sequence or 1)
            if sequence < 1 or sequence > len(pending):
                self.conn.rollback()
                return {
                    "ok": False,
                    "reason": "participant_not_found",
                    "bounty": self.serialize(row),
                    "pending": pending,
                }
            settlement = self._settle_participant_locked(row, pending[sequence - 1], now)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"ok": True, "bounty": self.get(bounty_id), **settlement}

    def get_order(self, order_id: int) -> dict[str, Any] | None:
        participant = self.conn.execute(
            "select * from bounty_participants where id=?", (int(order_id),)
        ).fetchone()
        if not participant:
            return None
        item = dict(participant)
        item["order_number"] = self.db.commission_public_code(
            "bounty_participant", int(item["id"]), "O"
        )
        bounty = self.get(int(item["bounty_id"]))
        item["bounty"] = bounty
        item["direction"] = str((bounty or {}).get("bounty_mode") or "request")
        cancellation = self.conn.execute(
            """select * from commission_order_cancellations
               where participant_id=? order by id desc limit 1""",
            (int(order_id),),
        ).fetchone()
        item["cancellation"] = dict(cancellation) if cancellation else None
        return item

    def request_order_completion(
        self, order_id: int, actor_ref: dict[str, Any]
    ) -> dict[str, Any]:
        """Mark one unified order complete using direction-aware authorization."""
        actor = self._verified_user(actor_ref)
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            participant = self.conn.execute(
                "select * from bounty_participants where id=?", (int(order_id),)
            ).fetchone()
            if not participant:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            row = self.conn.execute(
                "select * from bounties where id=?", (int(participant["bounty_id"]),)
            ).fetchone()
            is_service = str(row["bounty_mode"] or "request") == "service"
            performer_pk = int(row["publisher_user_pk"]) if is_service else int(participant["user_pk"])
            if int(actor["id"]) != performer_pk:
                self.conn.rollback()
                return {"ok": False, "reason": "not_performer", "order": self.get_order(order_id)}
            if participant["participant_status"] in COMPLETED_PARTICIPANT_STATUSES:
                self.conn.rollback()
                return {"ok": False, "reason": "already_requested", "order": self.get_order(order_id)}
            if participant["participant_status"] != "accepted" or row["status"] not in ACTIVE_BOUNTY_STATUSES:
                self.conn.rollback()
                return {"ok": False, "reason": "invalid_status", "order": self.get_order(order_id)}
            pending_cancel = self.conn.execute(
                """select 1 from commission_order_cancellations
                   where participant_id=? and status='pending'""",
                (int(order_id),),
            ).fetchone()
            if pending_cancel:
                self.conn.rollback()
                return {"ok": False, "reason": "cancellation_pending", "order": self.get_order(order_id)}
            self.conn.execute(
                """update bounty_participants set participant_status='completed',completed_at=?
                   where id=? and participant_status='accepted'""",
                (now, int(order_id)),
            )
            participants = self._participants(int(row["id"]))
            accepted_count, completed_count = self._counts(participants)
            required_count = int(row["required_count"] or 1)
            new_status = self._derived_status_for_row(
                row, accepted_count, completed_count
            )
            self.conn.execute(
                """update bounties set status=?,
                     completion_requested_at=case when ?='awaiting_confirmation' then ? else completion_requested_at end,
                     updated_at=? where id=?""",
                (new_status, new_status, now, now, int(row["id"])),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"ok": True, "order": self.get_order(order_id)}

    def confirm_order_completion(
        self, order_id: int, actor_ref: dict[str, Any]
    ) -> dict[str, Any]:
        """Settle one order. Demand publishers confirm; service buyers confirm."""
        actor = self._verified_user(actor_ref)
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            participant = self.conn.execute(
                "select * from bounty_participants where id=?", (int(order_id),)
            ).fetchone()
            if not participant:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            row = self.conn.execute(
                "select * from bounties where id=?", (int(participant["bounty_id"]),)
            ).fetchone()
            is_service = str(row["bounty_mode"] or "request") == "service"
            confirmer_pk = int(participant["user_pk"]) if is_service else int(row["publisher_user_pk"])
            if int(actor["id"]) != confirmer_pk:
                self.conn.rollback()
                return {"ok": False, "reason": "not_confirmer", "order": self.get_order(order_id)}
            if participant["participant_status"] != "completed":
                self.conn.rollback()
                return {"ok": False, "reason": "invalid_status", "order": self.get_order(order_id)}
            pending_cancel = self.conn.execute(
                """select 1 from commission_order_cancellations
                   where participant_id=? and status='pending'""",
                (int(order_id),),
            ).fetchone()
            if pending_cancel:
                self.conn.rollback()
                return {"ok": False, "reason": "cancellation_pending", "order": self.get_order(order_id)}
            settlement = self._settle_participant_locked(row, participant, now)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"ok": True, "order": self.get_order(order_id), **settlement}

    def request_order_cancellation(
        self, order_id: int, actor_ref: dict[str, Any]
    ) -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            participant = self.conn.execute(
                "select * from bounty_participants where id=?", (int(order_id),)
            ).fetchone()
            if not participant:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            row = self.conn.execute(
                "select * from bounties where id=?", (int(participant["bounty_id"]),)
            ).fetchone()
            parties = {int(row["publisher_user_pk"]), int(participant["user_pk"])}
            if int(actor["id"]) not in parties:
                self.conn.rollback()
                return {"ok": False, "reason": "not_party"}
            if participant["participant_status"] not in {"accepted", "completed"}:
                self.conn.rollback()
                return {"ok": False, "reason": "invalid_status"}
            pending = self.conn.execute(
                """select * from commission_order_cancellations
                   where participant_id=? and status='pending' order by id desc limit 1""",
                (int(order_id),),
            ).fetchone()
            if pending:
                self.conn.rollback()
                return {"ok": False, "reason": "already_pending", "request": dict(pending)}
            cursor = self.conn.execute(
                """insert into commission_order_cancellations(
                     participant_id,bounty_id,requester_user_pk,requester_user_id,status,created_at)
                   values(?,?,?,?, 'pending',?)""",
                (
                    int(order_id), int(row["id"]), int(actor["id"]),
                    str(actor["platform_user_id"] or actor["user_id"] or ""), now,
                ),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"ok": True, "request_id": int(cursor.lastrowid), "order": self.get_order(order_id)}

    def respond_order_cancellation(
        self, order_id: int, actor_ref: dict[str, Any], *, approve: bool
    ) -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            request = self.conn.execute(
                """select * from commission_order_cancellations
                   where participant_id=? and status='pending' order by id desc limit 1""",
                (int(order_id),),
            ).fetchone()
            if not request:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            participant = self.conn.execute(
                "select * from bounty_participants where id=?", (int(order_id),)
            ).fetchone()
            row = self.conn.execute(
                "select * from bounties where id=?", (int(participant["bounty_id"]),)
            ).fetchone()
            parties = {int(row["publisher_user_pk"]), int(participant["user_pk"])}
            if int(actor["id"]) not in parties or int(actor["id"]) == int(request["requester_user_pk"]):
                self.conn.rollback()
                return {"ok": False, "reason": "not_responder"}
            if not approve:
                self.conn.execute(
                    """update commission_order_cancellations
                       set status='rejected',responder_user_pk=?,resolved_at=? where id=?""",
                    (int(actor["id"]), now, int(request["id"])),
                )
                self.conn.commit()
                return {"ok": True, "approved": False, "order": self.get_order(order_id)}
            if participant["participant_status"] not in {"accepted", "completed"}:
                self.conn.rollback()
                return {"ok": False, "reason": "invalid_status"}
            is_service = str(row["bounty_mode"] or "request") == "service"
            refund = 0
            if is_service:
                payer = self.conn.execute(
                    "select * from users where id=?", (int(participant["user_pk"]),)
                ).fetchone()
                refund = int(participant["escrow_amount"] or 0) + int(participant["escrow_fee"] or 0)
                balance = int(payer["points"] or 0) + refund
                self.conn.execute(
                    "update users set points=?,last_seen_at=? where id=?",
                    (balance, now, int(payer["id"])),
                )
                self._tx(payer, refund, f"服务订单 O{int(order_id):04d} 双方取消退款", balance, now)
            else:
                payer = self.conn.execute(
                    "select * from users where id=?", (int(row["publisher_user_pk"]),)
                ).fetchone()
                per_person = int(row["reward_per_person"] or row["reward"] or 0)
                old_required = int(row["required_count"] or 1)
                old_fee = int(row["fee_escrow"] or 0)
                new_required = max(0, old_required - 1)
                new_fee = math.floor(new_required * per_person * 10 / 100)
                fee_refund = max(0, old_fee - new_fee)
                refund = per_person + fee_refund
                balance = int(payer["points"] or 0) + refund
                self.conn.execute(
                    "update users set points=?,last_seen_at=? where id=?",
                    (balance, now, int(payer["id"])),
                )
                self._tx(payer, refund, f"需求订单 O{int(order_id):04d} 双方取消退款", balance, now)
                if new_required > 0:
                    self.conn.execute(
                        """update bounties set required_count=?,reward_escrow=max(0,reward_escrow-?),
                             fee_escrow=?,total_charge=max(0,total_charge-?),updated_at=? where id=?""",
                        (
                            new_required, per_person, new_fee, refund, now, int(row["id"]),
                        ),
                    )
                else:
                    self.conn.execute(
                        """update bounties set status='cancelled',reward_escrow=0,fee_escrow=0,
                             total_charge=0,cancelled_at=?,refunded_at=?,refund_amount=refund_amount+?,
                             cancel_reason='订单双方同意取消',updated_at=? where id=?""",
                        (now, now, refund, now, int(row["id"])),
                    )
            self.conn.execute(
                """update bounty_participants set participant_status='cancelled',refunded_amount=?
                   where id=? and participant_status in ('accepted','completed')""",
                (refund, int(order_id)),
            )
            current = self.conn.execute(
                "select * from bounties where id=?", (int(row["id"]),)
            ).fetchone()
            if current["status"] != "cancelled":
                participants = self._participants(int(row["id"]))
                accepted_count, completed_count = self._counts(participants)
                new_status = self._derived_status_for_row(
                    current, accepted_count, completed_count
                )
                self.conn.execute(
                    "update bounties set status=?,updated_at=? where id=?",
                    (new_status, now, int(row["id"])),
                )
            self.conn.execute(
                """update commission_order_cancellations
                   set status='approved',responder_user_pk=?,resolved_at=?,refund_amount=? where id=?""",
                (int(actor["id"]), now, refund, int(request["id"])),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"ok": True, "approved": True, "refund": refund, "order": self.get_order(order_id)}

    def close_post(self, bounty_id: int, actor_ref: dict[str, Any]) -> dict[str, Any]:
        """Close unused capacity without disturbing already accepted orders."""
        actor = self._verified_user(actor_ref)
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            row = self.conn.execute(
                "select * from bounties where id=?", (int(bounty_id),)
            ).fetchone()
            if not row:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            if int(row["publisher_user_pk"]) != int(actor["id"]):
                self.conn.rollback()
                return {"ok": False, "reason": "not_publisher"}
            if row["status"] not in ACTIVE_BOUNTY_STATUSES:
                self.conn.rollback()
                return {"ok": False, "reason": "invalid_status"}
            participants = self._participants(int(row["id"]))
            accepted_count, completed_count = self._counts(participants)
            if accepted_count == 0:
                refund = self._cancel_locked(row, "publisher_close", now)
            else:
                old_required = int(row["required_count"] or 1)
                unlimited_service = self._is_unlimited_service(row)
                if not unlimited_service and accepted_count >= old_required:
                    self.conn.rollback()
                    return {"ok": False, "reason": "no_unused_capacity"}
                refund = 0
                is_service = str(row["bounty_mode"] or "request") == "service"
                if not is_service:
                    per_person = int(row["reward_per_person"] or row["reward"] or 0)
                    unused = old_required - accepted_count
                    reward_refund = unused * per_person
                    new_fee = math.floor(accepted_count * per_person * 10 / 100)
                    fee_refund = max(0, int(row["fee_escrow"] or 0) - new_fee)
                    refund = reward_refund + fee_refund
                    publisher = self.conn.execute(
                        "select * from users where id=?", (int(row["publisher_user_pk"]),)
                    ).fetchone()
                    balance = int(publisher["points"] or 0) + refund
                    self.conn.execute(
                        "update users set points=?,last_seen_at=? where id=?",
                        (balance, now, int(publisher["id"])),
                    )
                    self._tx(
                        publisher, refund,
                        f"关闭需求剩余 {unused} 个名额退款 #{self.db.bounty_number(int(row['id']))}",
                        balance, now,
                    )
                    self.conn.execute(
                        """update bounties set required_count=?,reward_escrow=?,fee_escrow=?,
                             total_charge=?,refund_amount=refund_amount+?,updated_at=? where id=?""",
                        (
                            accepted_count, accepted_count * per_person, new_fee,
                            accepted_count * per_person + new_fee, refund, now, int(row["id"]),
                        ),
                    )
                elif unlimited_service:
                    self.conn.execute(
                        """update bounties set unlimited_stock=0,required_count=?,updated_at=?
                           where id=?""",
                        (max(1, accepted_count), now, int(row["id"])),
                    )
                else:
                    self.conn.execute(
                        "update bounties set required_count=?,updated_at=? where id=?",
                        (accepted_count, now, int(row["id"])),
                    )
                new_status = self.derived_status(
                    accepted_count, accepted_count, completed_count
                )
                self.conn.execute(
                    "update bounties set status=?,updated_at=? where id=?",
                    (new_status, now, int(row["id"])),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"ok": True, "refund": refund, "bounty": self.get(bounty_id)}

    def list_orders(self, limit: int = 2000) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "select id from bounty_participants order by id desc limit ?",
            (max(1, min(int(limit), 5000)),),
        ).fetchall()
        return [order for row in rows if (order := self.get_order(int(row["id"]))) is not None]

    @staticmethod
    def _user_ref_from_row(user: Any) -> dict[str, Any]:
        return {
            "platform_user_id": str(user["platform_user_id"] or user["user_id"] or ""),
            "user_id": str(user["platform_user_id"] or user["user_id"] or ""),
            "sender": str(user["nickname"] or ""),
        }

    def admin_order_action(
        self,
        order_id: int,
        *,
        action: str,
        admin_identity: str,
        reason: str,
    ) -> dict[str, Any]:
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("管理员处理订单必须填写原因")
        if action not in {"mark_completed", "settle", "refund", "reopen"}:
            raise ValueError("不支持的管理员订单操作")
        before = self.get_order(order_id)
        if not before:
            raise ValueError("没有找到这个委托订单")
        bounty = before["bounty"] or {}
        participant = self.conn.execute(
            "select * from bounty_participants where id=?", (int(order_id),)
        ).fetchone()
        publisher = self.conn.execute(
            "select * from users where id=?", (int(bounty["publisher_user_pk"]),)
        ).fetchone()
        taker = self.conn.execute(
            "select * from users where id=?", (int(participant["user_pk"]),)
        ).fetchone()
        is_service = before["direction"] == "service"
        if action == "reopen":
            if participant["participant_status"] != "completed":
                raise ValueError("只有待确认订单可以恢复为进行中")
            self.conn.execute("begin immediate")
            try:
                self.conn.execute(
                    """update bounty_participants set participant_status='accepted',
                         completed_at=null where id=? and participant_status='completed'""",
                    (int(order_id),),
                )
                row = self.conn.execute(
                    "select * from bounties where id=?", (int(participant["bounty_id"]),)
                ).fetchone()
                participants = self._participants(int(row["id"]))
                accepted_count, completed_count = self._counts(participants)
                status = self._derived_status_for_row(
                    row, accepted_count, completed_count
                )
                self.conn.execute(
                    "update bounties set status=?,updated_at=? where id=?",
                    (status, self.db.now(), int(row["id"])),
                )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            result: dict[str, Any] = {"ok": True}
        else:
            if action in {"mark_completed", "settle"} and participant["participant_status"] == "accepted":
                performer = publisher if is_service else taker
                result = self.request_order_completion(
                    order_id, self._user_ref_from_row(performer)
                )
                if not result.get("ok"):
                    raise ValueError(str(result.get("reason") or "无法标记完成"))
            if action == "settle":
                confirmer = taker if is_service else publisher
                result = self.confirm_order_completion(
                    order_id, self._user_ref_from_row(confirmer)
                )
                if not result.get("ok"):
                    raise ValueError(str(result.get("reason") or "无法结算"))
            elif action == "refund":
                current = self.get_order(order_id)
                if not current or current["participant_status"] not in {"accepted", "completed"}:
                    raise ValueError("只有进行中或待确认订单可以退款取消")
                pending = current.get("cancellation") or {}
                if pending.get("status") != "pending":
                    result = self.request_order_cancellation(
                        order_id, self._user_ref_from_row(publisher)
                    )
                    if not result.get("ok"):
                        raise ValueError(str(result.get("reason") or "无法建立退款申请"))
                    responder = taker
                else:
                    responder = (
                        publisher
                        if int(pending.get("requester_user_pk") or 0) == int(taker["id"])
                        else taker
                    )
                result = self.respond_order_cancellation(
                    order_id, self._user_ref_from_row(responder), approve=True
                )
                if not result.get("ok"):
                    raise ValueError(str(result.get("reason") or "无法退款"))
            else:
                result = {"ok": True}
        after = self.get_order(order_id) or {}
        self.conn.execute(
            """insert into commission_admin_audit(
                 participant_id,admin_identity,action,before_json,after_json,reason,created_at)
               values(?,?,?,?,?,?,?)""",
            (
                int(order_id), str(admin_identity or "local-manager"), action,
                json.dumps(before, ensure_ascii=False, default=str),
                json.dumps(after, ensure_ascii=False, default=str), reason, self.db.now(),
            ),
        )
        self.conn.commit()
        return {"ok": True, "order": after, **{k: v for k, v in result.items() if k != "order"}}

    def _refund_components_locked(self, row: Any, reason_prefix: str, now: str) -> int:
        if row["refunded_at"]:
            return 0
        if str(row["bounty_mode"] or "request") == "service":
            total_refund = 0
            participants = self._participants(int(row["id"]))
            for participant in participants:
                if participant["participant_status"] not in {"accepted", "completed"} or int(participant["escrow_amount"] or 0) <= 0:
                    continue
                user = self.conn.execute("select * from users where id=?", (int(participant["user_pk"]),)).fetchone()
                amount = int(participant["escrow_amount"] or 0) + int(participant["escrow_fee"] or 0)
                balance = int(user["points"] or 0) + amount
                self.conn.execute("update users set points=?,last_seen_at=? where id=?", (balance, now, int(user["id"])))
                self._tx(user, amount, f"{reason_prefix}服务悬赏托管退款 #{self.db.bounty_number(int(row['id']))}", balance, now)
                self.conn.execute("update bounty_participants set refunded_amount=? where id=?", (amount, int(participant["id"])))
                total_refund += amount
            return total_refund
        publisher = self.conn.execute("select * from users where id=?", (int(row["publisher_user_pk"]),)).fetchone()
        if not publisher:
            raise ValueError("悬赏发布者数据不存在")
        paid_count = int(self.conn.execute(
            "select count(*) from bounty_participants where bounty_id=? and participant_status='paid'",
            (int(row["id"]),),
        ).fetchone()[0])
        per_person = int(row["reward_per_person"] or row["reward"] or 0)
        reward_refund = max(0, int(row["reward_escrow"] or row["reward"] or 0) - paid_count * per_person)
        fee_refund = int(row["fee_escrow"] or 0)
        balance = int(publisher["points"] or 0)
        if reward_refund:
            balance += reward_refund
            self._tx(publisher, reward_refund, f"{reason_prefix}功德托管 #{self.db.bounty_number(int(row['id']))}", balance, now)
        if fee_refund:
            balance += fee_refund
            self._tx(publisher, fee_refund, f"{reason_prefix}手续费 #{self.db.bounty_number(int(row['id']))}", balance, now)
        self.conn.execute("update users set points=?,last_seen_at=? where id=?", (balance, now, int(publisher["id"])))
        return reward_refund + fee_refund

    def _cancel_locked(self, row: Any, cancel_reason: str, now: str) -> int:
        if row["status"] not in ACTIVE_BOUNTY_STATUSES:
            raise ValueError("只有未完成悬赏可以取消")
        refund = self._refund_components_locked(row, "取消悬赏退款：", now)
        self.conn.execute(
            """update bounty_participants set participant_status='cancelled'
               where bounty_id=? and participant_status in ('accepted','completed')""",
            (int(row["id"]),),
        )
        self.conn.execute(
            """update bounties set status='cancelled',cancelled_at=?,cancel_reason=?,
                 refunded_at=?,refund_amount=?,publisher_compensation=0,forfeited_amount=0,updated_at=?
               where id=?""",
            (now, cancel_reason, now, refund, now, int(row["id"])),
        )
        return refund

    def cancel(self, bounty_id: int, actor_ref: dict[str, Any], **_: Any) -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        now = self.db.now()
        abandonment_count = 0
        banned_until = ""
        self.conn.execute("begin immediate")
        try:
            row = self.conn.execute("select * from bounties where id=?", (int(bounty_id),)).fetchone()
            if not row:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            participant = self.conn.execute(
                "select 1 from bounty_participants where bounty_id=? and user_pk=?",
                (int(bounty_id), int(actor["id"])),
            ).fetchone()
            is_publisher = int(row["publisher_user_pk"]) == int(actor["id"])
            if not is_publisher and not participant:
                self.conn.rollback()
                return {"ok": False, "reason": "not_party", "bounty": self.serialize(row)}
            if row["status"] not in ACTIVE_BOUNTY_STATUSES:
                self.conn.rollback()
                return {"ok": False, "reason": "invalid_status", "bounty": self.serialize(row)}
            reason = "publisher_cancel" if is_publisher else "participant_cancel"
            if not is_publisher:
                self.conn.execute(
                    """insert into bounty_abandonments(
                         bounty_id,user_pk,user_id,nickname,created_at)
                       values(?,?,?,?,?)""",
                    (
                        int(row["id"]), int(actor["id"]), str(actor["platform_user_id"]),
                        str(actor["nickname"] or ""), now,
                    ),
                )
                abandonment_count = int(
                    self.conn.execute(
                        "select count(*) from bounty_abandonments where user_pk=?",
                        (int(actor["id"]),),
                    ).fetchone()[0]
                )
                if abandonment_count % 3 == 0:
                    banned_until = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
                    self.conn.execute(
                        """insert into bounty_bans(
                             user_pk,user_id,nickname,banned_until,reason,updated_at)
                           values(?,?,?,?,?,?)
                           on conflict(user_pk) do update set user_id=excluded.user_id,
                             nickname=excluded.nickname,banned_until=excluded.banned_until,
                             reason=excluded.reason,updated_at=excluded.updated_at""",
                        (
                            int(actor["id"]), str(actor["platform_user_id"]),
                            str(actor["nickname"] or ""), banned_until,
                            "累计三次放弃进行中的悬赏", now,
                        ),
                    )
            refund = self._cancel_locked(row, reason, now)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {
            "ok": True,
            "bounty": self.get(bounty_id),
            "refund": refund,
            "taker_compensation": 0,
            "forfeited": 0,
            "abandonment_count": abandonment_count,
            "banned_until": banned_until,
        }

    def list_my(self, user_ref: dict[str, Any], limit: int = 4) -> dict[str, Any]:
        user = self._verified_user(user_ref)
        published = self.conn.execute(
            "select * from bounties where publisher_user_pk=? order by id desc limit ?",
            (int(user["id"]), int(limit)),
        ).fetchall()
        taken = self.conn.execute(
            """select b.* from bounties b join bounty_participants p on p.bounty_id=b.id
               where p.user_pk=? order by b.id desc limit ?""",
            (int(user["id"]), int(limit)),
        ).fetchall()
        return {"published": [self.serialize(r) for r in published], "taken": [self.serialize(r) for r in taken]}

    def claim_expired(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """select * from bounties where status in ('recruiting','active','awaiting_confirmation')
               and archived_at is null and deadline_at is not null and deadline_at!=''
               and deadline_at<=? and expiry_notified_at is null order by deadline_at,id""",
            (self.db.now(),),
        ).fetchall()
        return [self.serialize(row) for row in rows]

    def all_grouped(self) -> dict[str, Any]:
        groups = {
            key: {"status": key, "label": STATUS_LABELS[key], "count": 0, "items": []}
            for key in BUSINESS_STATUS_ORDER
        }
        rows = self.conn.execute(
            "select * from bounties order by coalesce(nullif(updated_at,''),created_at) desc,id desc"
        ).fetchall()
        for row in rows:
            item = self.serialize(row)
            key = item["business_status"]
            if key not in groups:
                key = item["status"] if item["status"] in groups else "cancelled"
            groups[key]["items"].append(item)
            groups[key]["count"] += 1
        return {"status_order": list(BUSINESS_STATUS_ORDER), "groups": groups, "total": len(rows)}

    def stats(self) -> dict[str, Any]:
        grouped = self.all_grouped()
        counts = {key: group["count"] for key, group in grouped["groups"].items()}
        locked = self.conn.execute(
            """select coalesce(sum(reward_escrow),0),coalesce(sum(fee_escrow),0)
               from bounties where status in ('waiting','recruiting','active','awaiting_confirmation')
               and archived_at is null and refunded_at is null"""
        ).fetchone()
        return {
            "counts": counts,
            "locked_reward": int(locked[0]),
            "locked_fee": int(locked[1]),
            "locked_total": int(locked[0]) + int(locked[1]),
            "abandonments": int(self.conn.execute("select count(*) from bounty_abandonments").fetchone()[0]),
            "active_bans": int(self.conn.execute("select count(*) from bounty_bans where banned_until>?", (self.db.now(),)).fetchone()[0]),
            "recent": [item for key in BUSINESS_STATUS_ORDER for item in grouped["groups"][key]["items"]][:100],
        }

    def delete_preview(self, bounty_id: int) -> dict[str, Any]:
        bounty = self.get(bounty_id)
        if not bounty:
            raise ValueError("没有找到这个悬赏编号")
        if bounty["business_status"] == "archived":
            action, refund = "already_archived", 0
        elif bounty["status"] in ACTIVE_BOUNTY_STATUSES:
            action, refund = "cancel_and_archive", int(bounty["total_charge"])
        else:
            action, refund = "archive_only", 0
        return {"bounty": bounty, "action": action, "refund": refund, "physical_delete": False}

    def _audit(
        self,
        bounty_id: int,
        admin_identity: str,
        before: dict[str, Any],
        after: dict[str, Any],
        reason: str,
        balance_delta: int = 0,
        reward_delta: int = 0,
        fee_delta: int = 0,
    ) -> None:
        self.conn.execute(
            """insert into bounty_admin_audit(
                 admin_identity,bounty_id,changed_at,before_json,after_json,balance_delta,
                 reward_escrow_delta,fee_escrow_delta,old_status,new_status,reason)
               values(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                admin_identity, int(bounty_id), self.db.now(),
                json.dumps(before, ensure_ascii=False, sort_keys=True, default=str),
                json.dumps(after, ensure_ascii=False, sort_keys=True, default=str),
                int(balance_delta), int(reward_delta), int(fee_delta),
                str(before.get("business_status") or before.get("status") or ""),
                str(after.get("business_status") or after.get("status") or ""), reason,
            ),
        )

    def admin_delete(self, bounty_id: int, admin_identity: str, reason: str) -> dict[str, Any]:
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("管理员取消或归档必须填写原因")
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            row = self.conn.execute("select * from bounties where id=?", (int(bounty_id),)).fetchone()
            if not row:
                raise ValueError("没有找到这个悬赏编号")
            before = self.serialize(row)
            refund = 0
            if not row["archived_at"]:
                if row["status"] in ACTIVE_BOUNTY_STATUSES:
                    refund = self._cancel_locked(row, f"admin_cancel:{reason}", now)
                self.conn.execute(
                    """update bounties set archived_at=?,archive_reason=?,updated_at=?
                       where id=? and archived_at is null""",
                    (now, f"admin:{reason}", now, int(bounty_id)),
                )
            after = self.get(bounty_id)
            self._audit(bounty_id, admin_identity, before, after, reason, balance_delta=refund)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"ok": True, "bounty": self.get(bounty_id), "refund": refund, "physical_delete": False}

    @staticmethod
    def _deadline(row: Any, duration_type: str, duration_days: int) -> str | None:
        if duration_type == "single" or not row["accepted_at"]:
            return None
        accepted = datetime.strptime(str(row["accepted_at"]), "%Y-%m-%d %H:%M:%S")
        deadline = accepted + timedelta(days=duration_days)
        created = datetime.strptime(str(row["created_at"]), "%Y-%m-%d %H:%M:%S")
        if deadline < created:
            raise ValueError("截止时间不能早于创建时间")
        return deadline.strftime("%Y-%m-%d %H:%M:%S")

    def admin_update(
        self,
        bounty_id: int,
        changes: dict[str, Any],
        admin_identity: str,
    ) -> dict[str, Any]:
        supplied = set(changes)
        forbidden = supplied & IMMUTABLE_ADMIN_FIELDS
        unknown = supplied - ALLOWED_ADMIN_FIELDS - IMMUTABLE_ADMIN_FIELDS
        if forbidden:
            raise ValueError("禁止修改人员、唯一 ID、编号、时间或历史流水字段：" + "、".join(sorted(forbidden)))
        if unknown:
            raise ValueError("不支持修改字段：" + "、".join(sorted(unknown)))
        reason = str(changes.get("reason") or changes.get("admin_note") or "").strip()
        if not reason:
            raise ValueError("后台编辑必须填写操作原因")
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            row = self.conn.execute("select * from bounties where id=?", (int(bounty_id),)).fetchone()
            if not row:
                raise ValueError("没有找到这个悬赏编号")
            before = self.serialize(row)
            if row["archived_at"] and (supplied - {"admin_note", "reason"}):
                raise ValueError("已归档悬赏只能补充管理员备注")
            terminal = row["status"] in TERMINAL_BOUNTY_STATUSES
            protected = {
                "required_count", "unlimited_stock", "reward_per_person",
                "reward", "duration_type", "duration_days",
            }
            if terminal and supplied & protected:
                raise ValueError("已完成或已取消悬赏不能修改人数、赏金、类型或时长")

            content = str(changes.get("content", row["content"])).strip()
            if not content or len(content) > 500:
                raise ValueError("悬赏内容必须为 1 到 500 个字符")
            duration_type = str(changes.get("duration_type", row["duration_type"]))
            if duration_type not in {"single", "days"}:
                raise ValueError("悬赏类型只能是 single（单次）或 days（持续）")
            duration_days = int(changes.get("duration_days", row["duration_days"] or 0))
            if duration_type == "single":
                duration_days = 0
            elif not 1 <= duration_days <= 10:
                raise ValueError("持续悬赏天数必须在 1 到 10 天之间")
            required_count = int(changes.get("required_count", row["required_count"] or 1))
            per_person = int(changes.get("reward_per_person", changes.get("reward", row["reward_per_person"] or row["reward"])))
            is_service = str(row["bounty_mode"] or "request") == "service"
            unlimited_stock = bool(changes.get("unlimited_stock", row["unlimited_stock"]))
            if unlimited_stock and not is_service:
                raise ValueError("只有服务可以设置为不限库存")
            if unlimited_stock:
                required_count = max(1, required_count)
            validation_count = 1 if unlimited_stock else required_count
            if is_service:
                self.validate_service_stock(validation_count, per_person)
                potential_reward, potential_fee, potential_total = 0, 0, 0
            else:
                potential_reward, potential_fee, potential_total = self.amounts(
                    validation_count, per_person
                )
            if is_service:
                new_reward, new_fee, new_total = 0, 0, 0
            else:
                new_reward, new_fee, new_total = (
                    potential_reward, potential_fee, potential_total
                )
            participants = self._participants(int(bounty_id))
            accepted_count, completed_count = self._counts(participants)
            paid_count = sum(1 for item in participants if item["participant_status"] == "paid")
            if paid_count and supplied & {"required_count", "unlimited_stock", "reward_per_person", "reward"}:
                raise ValueError("已有订单完成结算，不能再修改库存或每份价格")
            if not unlimited_stock and (required_count < accepted_count or required_count < completed_count):
                if is_service:
                    raise ValueError(f"服务库存不能小于已购买数量 {accepted_count} 或已完成数量 {completed_count}")
                raise ValueError(f"所需人数不能小于已接取人数 {accepted_count} 或已完成人数 {completed_count}")

            old_reward = 0 if is_service else int(row["reward_escrow"] or 0)
            old_fee = 0 if is_service else int(row["fee_escrow"] or 0)
            old_total = 0 if is_service else int(row["total_charge"] or old_reward + old_fee)
            reward_delta = new_reward - old_reward
            fee_delta = new_fee - old_fee
            total_delta = new_total - old_total
            balance_delta = -total_delta
            if total_delta and terminal:
                raise ValueError("已完成或已取消悬赏不能修改历史托管金额")
            publisher = self.conn.execute("select * from users where id=?", (int(row["publisher_user_pk"]),)).fetchone()
            if not publisher:
                raise ValueError("悬赏发布者数据不存在")
            balance = int(publisher["points"] or 0)
            if total_delta > 0 and balance < total_delta:
                raise ValueError(f"发布者余额不足，补充托管需要 {total_delta} 功德，当前只有 {balance}")
            if reward_delta:
                balance -= reward_delta
                self._tx(
                    publisher, -reward_delta,
                    ("后台增加悬赏功德托管" if reward_delta > 0 else "后台退回悬赏功德托管") + f" #{self.db.bounty_number(int(bounty_id))}",
                    balance, now,
                )
            if fee_delta:
                balance -= fee_delta
                self._tx(
                    publisher, -fee_delta,
                    ("后台增加悬赏手续费托管" if fee_delta > 0 else "后台退回悬赏手续费托管") + f" #{self.db.bounty_number(int(bounty_id))}",
                    balance, now,
                )
            if total_delta:
                self.conn.execute("update users set points=?,last_seen_at=? where id=?", (balance, now, int(publisher["id"])))

            deadline_at = self._deadline(row, duration_type, duration_days)
            status_row = dict(row)
            status_row["required_count"] = required_count
            status_row["unlimited_stock"] = int(unlimited_stock)
            derived = self._derived_status_for_row(
                status_row, accepted_count, completed_count
            )
            target_status = str(changes.get("status", derived if row["status"] in ACTIVE_BOUNTY_STATUSES else row["status"]))
            if terminal and target_status != row["status"] and target_status != "archived":
                raise ValueError("已完成或已取消悬赏不能重新激活")
            self.conn.execute(
                """update bounties set content=?,duration_type=?,duration_days=?,required_count=?,unlimited_stock=?,
                      reward=?,reward_per_person=?,reward_escrow=?,fee_escrow=?,total_charge=?,
                     deadline_at=?,admin_note=?,cancel_reason=?,updated_at=? where id=?""",
                (
                    content, duration_type, duration_days, required_count,
                    int(unlimited_stock), per_person, per_person,
                    new_reward, new_fee, new_total, deadline_at,
                    str(changes.get("admin_note", row["admin_note"] or "")),
                    str(changes.get("cancel_reason", row["cancel_reason"] or "")),
                    now, int(bounty_id),
                ),
            )
            row = self.conn.execute("select * from bounties where id=?", (int(bounty_id),)).fetchone()
            operation_balance_delta = balance_delta
            if target_status == "cancelled" and row["status"] in ACTIVE_BOUNTY_STATUSES:
                operation_balance_delta += self._cancel_locked(row, f"admin_status:{reason}", now)
            elif target_status == "completed" and row["status"] != "completed":
                if row["status"] != "awaiting_confirmation":
                    raise ValueError("只有满员且所有参与者已完成的待确认悬赏才能结算为已完成")
                self._settle_locked(row, now)
            elif target_status == "archived":
                if row["status"] in ACTIVE_BOUNTY_STATUSES:
                    operation_balance_delta += self._cancel_locked(row, f"admin_archive:{reason}", now)
                self.conn.execute(
                    "update bounties set archived_at=?,archive_reason=?,updated_at=? where id=?",
                    (now, f"admin:{reason}", now, int(bounty_id)),
                )
            elif target_status in ACTIVE_BOUNTY_STATUSES:
                if target_status != derived:
                    raise ValueError(f"参与者数据决定当前状态必须为“{STATUS_LABELS[derived]}”，不能改为“{STATUS_LABELS[target_status]}”")
                self.conn.execute("update bounties set status=?,updated_at=? where id=?", (derived, now, int(bounty_id)))
            elif target_status not in TERMINAL_BOUNTY_STATUSES:
                raise ValueError("未知的悬赏状态")
            after = self.get(bounty_id)
            self._audit(
                bounty_id, admin_identity, before, after, reason,
                balance_delta=operation_balance_delta, reward_delta=reward_delta, fee_delta=fee_delta,
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"ok": True, "bounty": self.get(bounty_id), "balance_delta": operation_balance_delta}

    def run_weekly_cleanup(self, now_beijing: datetime | None = None) -> dict[str, Any]:
        local_now = now_beijing or datetime.now(BEIJING_TZ)
        if local_now.tzinfo is None:
            local_now = local_now.replace(tzinfo=BEIJING_TZ)
        monday = (local_now - timedelta(days=local_now.weekday())).date()
        week_key = monday.isoformat()
        existing = self.conn.execute(
            "select * from bounty_weekly_cleanup_runs where week_key=?", (week_key,)
        ).fetchone()
        if existing:
            return {"ran": False, "week_key": week_key, **dict(existing)}
        now = local_now.strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute("begin immediate")
        try:
            existing = self.conn.execute(
                "select * from bounty_weekly_cleanup_runs where week_key=?", (week_key,)
            ).fetchone()
            if existing:
                self.conn.rollback()
                return {"ran": False, "week_key": week_key, **dict(existing)}
            waiting = self.conn.execute(
                """select b.* from bounties b
                   where b.status='waiting' and b.archived_at is null and b.refunded_at is null
                     and not exists(select 1 from bounty_participants p where p.bounty_id=b.id)"""
            ).fetchall()
            refunded = 0
            for row in waiting:
                refunded += self._cancel_locked(row, f"weekly_cleanup:{week_key}", now)
            completed = self.conn.execute(
                "select id from bounties where status='completed' and archived_at is null"
            ).fetchall()
            self.conn.execute(
                """update bounties set archived_at=?,archive_reason=?,updated_at=?
                   where status='completed' and archived_at is null""",
                (now, f"weekly_cleanup:{week_key}", now),
            )
            self.conn.execute(
                """insert into bounty_weekly_cleanup_runs(
                     week_key,run_at,cancelled_count,archived_count,refunded_amount)
                   values(?,?,?,?,?)""",
                (week_key, now, len(waiting), len(completed), refunded),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {
            "ran": True,
            "week_key": week_key,
            "run_at": now,
            "cancelled_count": len(waiting),
            "archived_count": len(completed),
            "refunded_amount": refunded,
        }
