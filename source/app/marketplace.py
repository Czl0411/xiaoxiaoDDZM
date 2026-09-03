from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timedelta
from typing import Any


ACTIVE_LISTING_STATUS = "on_sale"
LISTING_STATUSES = {"on_sale", "sold_out", "expired", "off_shelf", "suspended", "archived"}


class MarketplaceCore:
    """群友市场独立业务层；不读取或修改官方商店、背包和悬赏表。"""

    def __init__(self, db):
        self.db = db

    @property
    def conn(self):
        return self.db.conn

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            create table if not exists market_listings (
              id integer primary key autoincrement,
              seller_user_pk integer not null,
              seller_user_id text not null,
              seller_nickname text not null,
              title text not null,
              description text not null,
              price integer not null,
              stock_total integer not null default 1,
              stock_remaining integer not null default 1,
              duration_days integer not null default 3,
              status text not null default 'on_sale',
              pin_rank integer not null default 0,
              sort_order integer not null default 0,
              created_at text not null,
              updated_at text not null,
              expires_at text not null,
              archived_at text,
              admin_note text not null default '',
              foreign key(seller_user_pk) references users(id)
            );
            create index if not exists idx_market_listings_active
              on market_listings(status, pin_rank, sort_order, expires_at, id);
            create unique index if not exists idx_market_listings_pin_rank
              on market_listings(pin_rank) where pin_rank between 1 and 3 and status='on_sale';
            create table if not exists market_orders (
              id integer primary key autoincrement,
              source_message_id text not null default '',
              listing_id integer not null,
              listing_title text not null,
              buyer_user_pk integer not null,
              buyer_user_id text not null,
              buyer_nickname text not null,
              seller_user_pk integer not null,
              seller_user_id text not null,
              seller_nickname text not null,
              quantity integer not null,
              unit_price integer not null,
              gross_amount integer not null,
              commission_rate_bps integer not null,
              commission_amount integer not null,
              seller_net_amount integer not null,
              buyer_balance_after integer not null,
              seller_balance_after integer not null,
              stock_after integer not null,
              status text not null default 'completed',
              created_at text not null,
              foreign key(listing_id) references market_listings(id),
              foreign key(buyer_user_pk) references users(id),
              foreign key(seller_user_pk) references users(id)
            );
            create unique index if not exists idx_market_orders_message
              on market_orders(source_message_id) where source_message_id!='';
            create index if not exists idx_market_orders_created
              on market_orders(created_at desc, id desc);
            create table if not exists market_drafts (
              id integer primary key autoincrement,
              draft_id text not null unique,
              seller_user_pk integer not null,
              seller_user_id text not null,
              seller_nickname text not null,
              group_id text not null,
              mode text not null default 'create',
              listing_id integer,
              original_text text not null,
              parsed_json text not null,
              status text not null default 'pending',
              idempotency_key text not null unique,
              created_at text not null,
              expires_at text not null,
              completed_at text,
              confirm_message_id text not null default '',
              foreign key(seller_user_pk) references users(id),
              foreign key(listing_id) references market_listings(id)
            );
            create unique index if not exists idx_market_drafts_pending
              on market_drafts(seller_user_id, group_id)
              where status='pending';
            create table if not exists market_recovery_records (
              id integer primary key autoincrement,
              order_id integer not null unique,
              amount integer not null,
              rate_bps integer not null,
              reason text not null,
              created_at text not null,
              foreign key(order_id) references market_orders(id)
            );
            create table if not exists market_admin_audit (
              id integer primary key autoincrement,
              listing_id integer not null,
              admin_identity text not null,
              action text not null,
              before_json text not null,
              after_json text not null,
              reason text not null,
              created_at text not null,
              foreign key(listing_id) references market_listings(id)
            );
            """
        )
        self.conn.commit()

    @staticmethod
    def listing_number(listing_id: int) -> str:
        return f"M{int(listing_id):04d}"

    @staticmethod
    def order_number(order_id: int) -> str:
        return f"O{int(order_id):04d}"

    @staticmethod
    def parse_number(value: Any, prefix: str = "M") -> int:
        text = str(value or "").strip().upper()
        match = re.fullmatch(rf"{re.escape(prefix.upper())}?0*(\d+)", text)
        if not match or int(match.group(1)) <= 0:
            raise ValueError("编号格式不正确")
        return int(match.group(1))

    @staticmethod
    def _uuid(value: Any) -> str:
        uid = str(value or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", uid):
            raise ValueError("群友市场需要有效的主页唯一ID")
        return uid

    def _verified_user(self, user_ref: dict[str, Any]) -> dict[str, Any]:
        uid = self._uuid(user_ref.get("platform_user_id") or user_ref.get("user_id"))
        user = self.db.ensure_user(user_ref)
        self.db._assert_not_identity_conflict(user)
        if self._uuid(user.get("platform_user_id") or user.get("user_id")) != uid:
            raise ValueError("主页唯一ID与用户记录不一致")
        return user

    def expire_due(self) -> int:
        changed = self.conn.execute(
            """update market_listings set status='expired',pin_rank=0,updated_at=?
               where status='on_sale' and expires_at<=?""",
            (self.db.now(), self.db.now()),
        ).rowcount
        # 即使没有命中过期商品，UPDATE 也会开启 SQLite 隐式事务；必须始终提交，
        # 否则下一轮契约/悬赏维护的 begin immediate 会报“事务内再次开始事务”。
        self.conn.commit()
        return int(changed)

    def _serialize(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        seller = self.conn.execute("select * from users where id=?", (int(item["seller_user_pk"]),)).fetchone()
        item["number"] = self.listing_number(int(item["id"]))
        item["seller_title"] = self.db.display_name(dict(seller)) if seller else item["seller_nickname"]
        item["sales_count"] = int(
            self.conn.execute("select coalesce(sum(quantity),0) from market_orders where listing_id=? and status='completed'", (int(item["id"]),)).fetchone()[0]
        )
        item["sales_amount"] = int(
            self.conn.execute("select coalesce(sum(gross_amount),0) from market_orders where listing_id=? and status='completed'", (int(item["id"]),)).fetchone()[0]
        )
        return item

    def get_listing(self, listing_id: int) -> dict[str, Any] | None:
        self.expire_due()
        row = self.conn.execute("select * from market_listings where id=?", (int(listing_id),)).fetchone()
        return self._serialize(row) if row else None

    def list_page(self, page: int = 1, per_page: int = 5) -> dict[str, Any]:
        self.expire_due()
        per_page = max(1, min(int(per_page), 10))
        total = int(self.conn.execute("select count(*) from market_listings where status='on_sale' and stock_remaining>0 and expires_at>?", (self.db.now(),)).fetchone()[0])
        pages = max(1, math.ceil(total / per_page))
        page = max(1, min(int(page), pages))
        rows = self.conn.execute(
            """select * from market_listings
               where status='on_sale' and stock_remaining>0 and expires_at>?
               order by case when pin_rank between 1 and 3 then 0 else 1 end,
                        pin_rank asc,sort_order desc,updated_at desc,id desc
               limit ? offset ?""",
            (self.db.now(), per_page, (page - 1) * per_page),
        ).fetchall()
        return {"items": [self._serialize(row) for row in rows], "page": page, "pages": pages, "total": total}

    def list_all(self, limit: int = 500) -> list[dict[str, Any]]:
        self.expire_due()
        rows = self.conn.execute("select * from market_listings order by updated_at desc,id desc limit ?", (max(1, min(int(limit), 2000)),)).fetchall()
        return [self._serialize(row) for row in rows]

    def list_orders(self, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.conn.execute("select * from market_orders order by id desc limit ?", (max(1, min(int(limit), 2000)),)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["number"] = self.order_number(int(item["id"]))
            item["listing_number"] = self.listing_number(int(item["listing_id"]))
            result.append(item)
        return result

    def save_draft(
        self,
        message: dict[str, Any],
        original_text: str,
        parsed: dict[str, Any],
        *,
        ttl_seconds: int,
        mode: str = "create",
        listing_id: int | None = None,
    ) -> dict[str, Any]:
        seller = self._verified_user(message)
        group_id = self.db._message_group_id(message)
        now_dt = datetime.now()
        now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        expires = (now_dt + timedelta(seconds=max(60, min(int(ttl_seconds), 3600)))).strftime("%Y-%m-%d %H:%M:%S")
        message_id = str(message.get("message_id") or "")
        idem = f"market-draft:{mode}:{message_id}" if message_id else f"market-draft:{uuid.uuid4().hex}"
        self.conn.execute("begin immediate")
        try:
            existing = self.conn.execute(
                "select * from market_drafts where idempotency_key=?", (idem,)
            ).fetchone()
            if existing:
                self.conn.rollback()
                return dict(existing)
            self.conn.execute("update market_drafts set status='superseded',completed_at=? where seller_user_id=? and group_id=? and status='pending'", (now, str(seller["platform_user_id"]), group_id))
            cursor = self.conn.execute(
                """insert into market_drafts(
                     draft_id,seller_user_pk,seller_user_id,seller_nickname,group_id,mode,
                     listing_id,original_text,parsed_json,status,idempotency_key,created_at,expires_at)
                   values(?,?,?,?,?,?,?,?,?,'pending',?,?,?)""",
                (uuid.uuid4().hex, int(seller["id"]), str(seller["platform_user_id"]), str(seller["nickname"]), group_id, mode, listing_id, str(original_text)[:1000], json.dumps(parsed, ensure_ascii=False), idem, now, expires),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return dict(self.conn.execute("select * from market_drafts where id=?", (int(cursor.lastrowid),)).fetchone())

    def get_draft(self, message: dict[str, Any], mode: str | None = None) -> dict[str, Any] | None:
        user = self._verified_user(message)
        group_id = self.db._message_group_id(message)
        sql = "select * from market_drafts where seller_user_id=? and group_id=? and status='pending'"
        args: list[Any] = [str(user["platform_user_id"]), group_id]
        if mode:
            sql += " and mode=?"
            args.append(mode)
        sql += " order by id desc limit 1"
        row = self.conn.execute(sql, args).fetchone()
        if not row:
            return None
        if str(row["expires_at"]) <= self.db.now():
            self.conn.execute("update market_drafts set status='expired',completed_at=? where id=?", (self.db.now(), int(row["id"])))
            self.conn.commit()
            return None
        item = dict(row)
        item["parsed"] = json.loads(item["parsed_json"])
        return item

    def cancel_draft(self, message: dict[str, Any], mode: str | None = None) -> bool:
        draft = self.get_draft(message, mode)
        if not draft:
            return False
        changed = self.conn.execute("update market_drafts set status='cancelled',completed_at=? where id=? and status='pending'", (self.db.now(), int(draft["id"]))).rowcount
        self.conn.commit()
        return bool(changed)

    def _active_count(self, seller_pk: int) -> int:
        self.expire_due()
        return int(self.conn.execute("select count(*) from market_listings where seller_user_pk=? and status='on_sale'", (int(seller_pk),)).fetchone()[0])

    def confirm_draft(self, message: dict[str, Any], *, mode: str, maximum_active: int) -> dict[str, Any]:
        seller = self._verified_user(message)
        draft = self.get_draft(message, mode)
        if not draft:
            return {"ok": False, "reason": "missing"}
        parsed = dict(draft["parsed"])
        now_dt = datetime.now()
        now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        expires = (now_dt + timedelta(days=int(parsed["duration_days"]))).strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute("begin immediate")
        try:
            row = self.conn.execute("select * from market_drafts where id=? and status='pending'", (int(draft["id"]),)).fetchone()
            if not row:
                self.conn.rollback()
                return {"ok": False, "reason": "duplicate"}
            if mode == "create":
                active = int(self.conn.execute("select count(*) from market_listings where seller_user_pk=? and status='on_sale' and expires_at>?", (int(seller["id"]), now)).fetchone()[0])
                if active >= int(maximum_active):
                    raise ValueError(f"每人最多同时上架{maximum_active}件商品")
                cursor = self.conn.execute(
                    """insert into market_listings(
                         seller_user_pk,seller_user_id,seller_nickname,title,description,price,
                         stock_total,stock_remaining,duration_days,status,created_at,updated_at,expires_at)
                       values(?,?,?,?,?,?,?,?,?,'on_sale',?,?,?)""",
                    (int(seller["id"]), str(seller["platform_user_id"]), str(seller["nickname"]), parsed["title"], parsed["description"], int(parsed["price"]), int(parsed["stock"]), int(parsed["stock"]), int(parsed["duration_days"]), now, now, expires),
                )
                listing_id = int(cursor.lastrowid)
            else:
                listing_id = int(draft["listing_id"] or 0)
                listing = self.conn.execute("select * from market_listings where id=?", (listing_id,)).fetchone()
                if not listing or int(listing["seller_user_pk"]) != int(seller["id"]):
                    raise ValueError("没有找到本人可以修改的市场商品")
                status = "on_sale" if int(parsed["stock"]) > 0 else "sold_out"
                if listing["status"] != "on_sale" and status == "on_sale":
                    active = int(
                        self.conn.execute(
                            "select count(*) from market_listings where seller_user_pk=? and status='on_sale' and expires_at>? and id<>?",
                            (int(seller["id"]), now, listing_id),
                        ).fetchone()[0]
                    )
                    if active >= int(maximum_active):
                        raise ValueError(f"每人最多同时上架{maximum_active}件商品")
                self.conn.execute(
                    """update market_listings set title=?,description=?,price=?,stock_total=?,
                         stock_remaining=?,duration_days=?,status=?,pin_rank=case when ?='on_sale' then pin_rank else 0 end,
                         updated_at=?,expires_at=? where id=?""",
                    (parsed["title"], parsed["description"], int(parsed["price"]), int(parsed["stock"]), int(parsed["stock"]), int(parsed["duration_days"]), status, status, now, expires, listing_id),
                )
            updated = self.conn.execute("update market_drafts set status='published',completed_at=?,confirm_message_id=? where id=? and status='pending'", (now, str(message.get("message_id") or ""), int(draft["id"]))).rowcount
            if updated != 1:
                raise ValueError("市场草稿已经处理，请勿重复确认")
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"ok": True, "listing": self.get_listing(listing_id)}

    def purchase(self, listing_id: int, buyer_ref: dict[str, Any], quantity: int, *, commission_rate_bps: int) -> dict[str, Any]:
        buyer = self._verified_user(buyer_ref)
        quantity = int(quantity)
        if not 1 <= quantity <= 999:
            raise ValueError("购买数量必须在1到999之间")
        message_id = str(buyer_ref.get("message_id") or "")
        self.conn.execute("begin immediate")
        try:
            if message_id:
                old = self.conn.execute("select * from market_orders where source_message_id=?", (message_id,)).fetchone()
                if old:
                    self.conn.rollback()
                    item = dict(old)
                    item["number"] = self.order_number(int(item["id"]))
                    return {"ok": True, "duplicate": True, "order": item, "listing": self.get_listing(int(item["listing_id"]))}
            row = self.conn.execute("select * from market_listings where id=?", (int(listing_id),)).fetchone()
            if not row:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            if row["status"] != "on_sale" or str(row["expires_at"]) <= self.db.now():
                if row["status"] == "on_sale" and str(row["expires_at"]) <= self.db.now():
                    self.conn.execute("update market_listings set status='expired',pin_rank=0,updated_at=? where id=?", (self.db.now(), int(row["id"])))
                    self.conn.commit()
                else:
                    self.conn.rollback()
                return {"ok": False, "reason": "unavailable"}
            if int(row["seller_user_pk"]) == int(buyer["id"]):
                self.conn.rollback()
                return {"ok": False, "reason": "self"}
            if int(row["stock_remaining"]) < quantity:
                self.conn.rollback()
                return {"ok": False, "reason": "stock", "stock": int(row["stock_remaining"])}
            seller = self.conn.execute("select * from users where id=?", (int(row["seller_user_pk"]),)).fetchone()
            current_buyer = self.conn.execute("select * from users where id=?", (int(buyer["id"]),)).fetchone()
            if not seller or not current_buyer:
                raise ValueError("买家或卖家用户数据不存在")
            gross = int(row["price"]) * quantity
            buyer_balance = int(current_buyer["points"] or 0)
            if buyer_balance < gross:
                self.conn.rollback()
                return {"ok": False, "reason": "balance", "required": gross, "balance": buyer_balance}
            rate = max(0, min(int(commission_rate_bps), 10000))
            commission = gross * rate // 10000
            seller_net = gross - commission
            buyer_after = buyer_balance - gross
            seller_after = int(seller["points"] or 0) + seller_net
            stock_after = int(row["stock_remaining"]) - quantity
            now = self.db.now()
            self.conn.execute("update users set points=?,last_seen_at=? where id=?", (buyer_after, now, int(current_buyer["id"])))
            self.conn.execute("update users set points=?,last_seen_at=? where id=?", (seller_after, now, int(seller["id"])))
            self.conn.execute(
                "insert into transactions(user_id,nickname,change_amount,reason,balance_after,created_at) values(?,?,?,?,?,?)",
                (str(current_buyer["platform_user_id"] or current_buyer["user_id"] or ""), str(current_buyer["nickname"]), -gross, f"群友市场购买 {self.listing_number(int(row['id']))} x{quantity}", buyer_after, now),
            )
            self.conn.execute(
                "insert into transactions(user_id,nickname,change_amount,reason,balance_after,created_at) values(?,?,?,?,?,?)",
                (str(seller["platform_user_id"] or seller["user_id"] or ""), str(seller["nickname"]), seller_net, f"群友市场收入 {self.listing_number(int(row['id']))} x{quantity}", seller_after, now),
            )
            cursor = self.conn.execute(
                """insert into market_orders(
                     source_message_id,listing_id,listing_title,buyer_user_pk,buyer_user_id,buyer_nickname,
                     seller_user_pk,seller_user_id,seller_nickname,quantity,unit_price,gross_amount,
                     commission_rate_bps,commission_amount,seller_net_amount,buyer_balance_after,
                     seller_balance_after,stock_after,status,created_at)
                   values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'completed',?)""",
                (message_id, int(row["id"]), str(row["title"]), int(current_buyer["id"]), str(current_buyer["platform_user_id"] or current_buyer["user_id"] or ""), str(current_buyer["nickname"]), int(seller["id"]), str(seller["platform_user_id"] or seller["user_id"] or ""), str(seller["nickname"]), quantity, int(row["price"]), gross, rate, commission, seller_net, buyer_after, seller_after, stock_after, now),
            )
            order_id = int(cursor.lastrowid)
            if commission:
                self.conn.execute("insert into market_recovery_records(order_id,amount,rate_bps,reason,created_at) values(?,?,?,?,?)", (order_id, commission, rate, "群友市场系统抽成回收", now))
            status = "sold_out" if stock_after == 0 else "on_sale"
            self.conn.execute("update market_listings set stock_remaining=?,status=?,pin_rank=case when ?='on_sale' then pin_rank else 0 end,updated_at=? where id=?", (stock_after, status, status, now, int(row["id"])))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        order = dict(self.conn.execute("select * from market_orders where id=?", (order_id,)).fetchone())
        order["number"] = self.order_number(order_id)
        return {"ok": True, "duplicate": False, "order": order, "listing": self.get_listing(int(row["id"]))}

    def my_market(self, user_ref: dict[str, Any], limit: int = 10) -> dict[str, Any]:
        user = self._verified_user(user_ref)
        self.expire_due()
        listings = [self._serialize(row) for row in self.conn.execute("select * from market_listings where seller_user_pk=? order by id desc limit ?", (int(user["id"]), int(limit))).fetchall()]
        orders = []
        for row in self.conn.execute("select * from market_orders where buyer_user_pk=? order by id desc limit ?", (int(user["id"]), int(limit))).fetchall():
            item = dict(row)
            item["number"] = self.order_number(int(item["id"]))
            item["listing_number"] = self.listing_number(int(item["listing_id"]))
            orders.append(item)
        return {"listings": listings, "orders": orders}

    def off_shelf(self, listing_id: int, seller_ref: dict[str, Any]) -> dict[str, Any]:
        seller = self._verified_user(seller_ref)
        row = self.conn.execute("select * from market_listings where id=?", (int(listing_id),)).fetchone()
        if not row or int(row["seller_user_pk"]) != int(seller["id"]):
            return {"ok": False, "reason": "not_found"}
        if row["status"] in {"archived", "off_shelf"}:
            return {"ok": False, "reason": "unavailable", "listing": self._serialize(row)}
        self.conn.execute("update market_listings set status='off_shelf',pin_rank=0,updated_at=? where id=?", (self.db.now(), int(listing_id)))
        self.conn.commit()
        return {"ok": True, "listing": self.get_listing(listing_id)}

    def renew(
        self,
        listing_id: int,
        seller_ref: dict[str, Any],
        days: int,
        *,
        maximum_active: int = 3,
    ) -> dict[str, Any]:
        seller = self._verified_user(seller_ref)
        row = self.conn.execute("select * from market_listings where id=?", (int(listing_id),)).fetchone()
        if not row or int(row["seller_user_pk"]) != int(seller["id"]):
            return {"ok": False, "reason": "not_found"}
        if row["status"] in {"suspended", "archived"}:
            return {"ok": False, "reason": "unavailable"}
        if row["status"] != "on_sale" and int(row["stock_remaining"]) > 0:
            active = int(
                self.conn.execute(
                    "select count(*) from market_listings where seller_user_pk=? and status='on_sale' and expires_at>? and id<>?",
                    (int(seller["id"]), self.db.now(), int(listing_id)),
                ).fetchone()[0]
            )
            if active >= int(maximum_active):
                raise ValueError(f"每人最多同时上架{maximum_active}件商品")
        now_dt = datetime.now()
        try:
            old_expiry = datetime.strptime(str(row["expires_at"]), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            old_expiry = now_dt
        base = max(now_dt, old_expiry)
        expires = (base + timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d %H:%M:%S")
        status = "on_sale" if int(row["stock_remaining"]) > 0 else "sold_out"
        self.conn.execute("update market_listings set duration_days=?,expires_at=?,status=?,updated_at=? where id=?", (int(days), expires, status, self.db.now(), int(listing_id)))
        self.conn.commit()
        return {"ok": True, "listing": self.get_listing(listing_id)}

    def stats(self) -> dict[str, Any]:
        self.expire_due()
        counts = {row["status"]: int(row["count"]) for row in self.conn.execute("select status,count(*) as count from market_listings group by status")}
        sums = self.conn.execute("select count(*) as orders,coalesce(sum(gross_amount),0) as gross,coalesce(sum(commission_amount),0) as commission,coalesce(sum(seller_net_amount),0) as seller_net from market_orders where status='completed'").fetchone()
        return {"counts": counts, "orders": int(sums["orders"]), "gross": int(sums["gross"]), "commission": int(sums["commission"]), "seller_net": int(sums["seller_net"])}

    def admin_update(
        self,
        listing_id: int,
        changes: dict[str, Any],
        *,
        admin_identity: str,
        reason: str,
        minimum_price: int = 50,
    ) -> dict[str, Any]:
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("后台修改市场商品必须填写原因")
        before = self.get_listing(listing_id)
        if not before:
            raise ValueError("没有找到市场商品")
        allowed = {"title", "description", "price", "stock_remaining", "duration_days", "status", "pin_rank", "sort_order", "expires_at", "admin_note"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("不支持修改字段：" + "、".join(sorted(unknown)))
        title = str(changes.get("title", before["title"])).strip()
        description = str(changes.get("description", before["description"])).strip()
        price = int(changes.get("price", before["price"]))
        stock = int(changes.get("stock_remaining", before["stock_remaining"]))
        duration = int(changes.get("duration_days", before["duration_days"]))
        status = str(changes.get("status", before["status"]))
        pin = int(changes.get("pin_rank", before["pin_rank"]))
        sort_order = int(changes.get("sort_order", before["sort_order"]))
        expires = str(changes.get("expires_at", before["expires_at"])).strip()
        if not 2 <= len(title) <= 30 or not 1 <= len(description) <= 160:
            raise ValueError("商品名称需2到30字，说明需1到160字")
        if price < int(minimum_price) or stock < 0 or duration < 1 or status not in LISTING_STATUSES or pin not in {0, 1, 2, 3}:
            raise ValueError("市场商品数值或状态不正确")
        try:
            datetime.strptime(expires, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError("到期时间格式必须为 YYYY-MM-DD HH:MM:SS") from exc
        self.conn.execute("begin immediate")
        try:
            if pin:
                self.conn.execute("update market_listings set pin_rank=0,updated_at=? where pin_rank=? and id<>?", (self.db.now(), pin, int(listing_id)))
            if status != "on_sale":
                pin = 0
            self.conn.execute("""update market_listings set title=?,description=?,price=?,stock_total=max(stock_total,?),stock_remaining=?,duration_days=?,status=?,pin_rank=?,sort_order=?,expires_at=?,admin_note=?,updated_at=? where id=?""", (title, description, price, stock, stock, duration, status, pin, sort_order, expires, str(changes.get("admin_note", before.get("admin_note") or ""))[:500], self.db.now(), int(listing_id)))
            after_row = self.conn.execute("select * from market_listings where id=?", (int(listing_id),)).fetchone()
            self.conn.execute("insert into market_admin_audit(listing_id,admin_identity,action,before_json,after_json,reason,created_at) values(?,?,?,?,?,?,?)", (int(listing_id), admin_identity, "update", json.dumps(before, ensure_ascii=False, default=str), json.dumps(dict(after_row), ensure_ascii=False, default=str), reason, self.db.now()))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"ok": True, "listing": self.get_listing(listing_id)}
