from __future__ import annotations

import math
import json
import re
from datetime import datetime, timedelta
from typing import Any


ACTIVE_ORDER_STATUSES = {"accepted", "submitted", "cancel_requested"}
TERMINAL_ORDER_STATUSES = {"completed", "cancelled"}


class CommissionHouseCore:
    """群友委托所独立业务层。

    需求、服务、订单分别保存；旧悬赏和旧市场表只作为迁移来源，不再承担新业务。
    """

    def __init__(self, db):
        self.db = db

    @property
    def conn(self):
        return self.db.conn

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            create table if not exists commission_demands (
              id integer primary key autoincrement,
              legacy_source_type text not null default '',
              legacy_source_id integer,
              publisher_user_pk integer not null,
              publisher_user_id text not null,
              publisher_nickname text not null,
              original_text text not null,
              title text not null,
              content text not null,
              fulfillment_type text not null default 'one_time',
              fulfillment_duration_value integer,
              fulfillment_duration_unit text,
              required_people integer not null,
              reward_per_person integer not null,
              recruitment_duration_days integer not null default 7,
              recruitment_expires_at text,
              fee_percent integer not null default 10,
              reward_escrow_remaining integer not null default 0,
              fee_escrow_remaining integer not null default 0,
              accepted_count integer not null default 0,
              completed_count integer not null default 0,
              status text not null default 'recruiting',
              created_message_id text not null default '',
              created_at text not null,
              updated_at text not null,
              closed_at text,
              close_reason text not null default '',
              unique(legacy_source_type,legacy_source_id),
              foreign key(publisher_user_pk) references users(id)
            );
            create index if not exists idx_commission_demands_status_created
              on commission_demands(status,created_at desc);
            create unique index if not exists idx_commission_demands_message
              on commission_demands(created_message_id) where created_message_id!='';

            create table if not exists commission_services (
              id integer primary key autoincrement,
              legacy_source_type text not null default '',
              legacy_source_id integer,
              seller_user_pk integer not null,
              seller_user_id text not null,
              seller_nickname text not null,
              original_text text not null,
              title text not null,
              description text not null,
              unit_label text not null default '次',
              unit_price integer not null,
              stock_mode text not null default 'limited',
              stock_total integer,
              stock_remaining integer,
              listing_duration_days integer not null default 3,
              listing_expires_at text not null,
              fulfillment_type text not null default 'one_time',
              fulfillment_duration_value integer,
              fulfillment_duration_unit text,
              max_per_buyer integer,
              commission_percent integer not null default 10,
              sold_quantity integer not null default 0,
              status text not null default 'on_sale',
              created_message_id text not null default '',
              created_at text not null,
              updated_at text not null,
              off_shelf_at text,
              off_shelf_reason text not null default '',
              unique(legacy_source_type,legacy_source_id),
              foreign key(seller_user_pk) references users(id)
            );
            create index if not exists idx_commission_services_status_expiry
              on commission_services(status,listing_expires_at,created_at desc);
            create unique index if not exists idx_commission_services_message
              on commission_services(created_message_id) where created_message_id!='';

            create table if not exists commission_orders_v2 (
              id integer primary key autoincrement,
              legacy_source_type text not null default '',
              legacy_source_id integer,
              order_kind text not null,
              demand_id integer,
              service_id integer,
              client_user_pk integer not null,
              client_user_id text not null,
              client_nickname text not null,
              provider_user_pk integer not null,
              provider_user_id text not null,
              provider_nickname text not null,
              quantity integer not null default 1,
              unit_price integer not null,
              gross_amount integer not null,
              commission_percent integer not null default 0,
              commission_amount integer not null default 0,
              provider_net_amount integer not null,
              escrow_amount integer not null,
              fee_mode text not null default 'seller_deducted',
              content_snapshot text not null,
              status text not null default 'accepted',
              accepted_message_id text not null default '',
              accepted_at text not null,
              fulfillment_due_at text,
              submitted_at text,
              completed_at text,
              cancelled_at text,
              cancel_requester_user_pk integer,
              cancel_reason text not null default '',
              cancel_requested_at text,
              updated_at text not null,
              unique(legacy_source_type,legacy_source_id),
              foreign key(demand_id) references commission_demands(id),
              foreign key(service_id) references commission_services(id),
              foreign key(client_user_pk) references users(id),
              foreign key(provider_user_pk) references users(id)
            );
            create index if not exists idx_commission_orders_v2_status
              on commission_orders_v2(status,accepted_at desc);
            create index if not exists idx_commission_orders_v2_people
              on commission_orders_v2(client_user_pk,provider_user_pk,status);
            create unique index if not exists idx_commission_orders_v2_message
              on commission_orders_v2(accepted_message_id) where accepted_message_id!='';

            create table if not exists commission_drafts_v2 (
              id integer primary key autoincrement,
              publisher_user_pk integer not null,
              group_id text not null,
              draft_kind text not null,
              original_text text not null,
              parsed_json text not null,
              prompt_version text not null default 'v2',
              status text not null default 'pending',
              created_at text not null,
              expires_at text not null,
              completed_at text,
              foreign key(publisher_user_pk) references users(id)
            );

            create table if not exists commission_wizard_sessions (
              id integer primary key autoincrement,
              publisher_user_pk integer not null,
              group_id text not null,
              wizard_kind text not null,
              current_step text not null,
              values_json text not null default '{}',
              history_json text not null default '[]',
              status text not null default 'active',
              created_at text not null,
              updated_at text not null,
              expires_at text not null,
              completed_at text,
              foreign key(publisher_user_pk) references users(id)
            );
            create unique index if not exists idx_commission_wizard_active
              on commission_wizard_sessions(publisher_user_pk,group_id)
              where status='active';

            create table if not exists commission_admin_audit_v2 (
              id integer primary key autoincrement,
              object_type text not null,
              object_id integer not null,
              action text not null,
              admin_identity text not null,
              reason text not null,
              detail text not null default '',
              created_at text not null
            );

            create table if not exists commission_prompt_revisions_v2 (
              id integer primary key autoincrement,
              prompt_key text not null,
              prompt_value text not null,
              value_sha256 text not null,
              operator text not null default 'local-manager',
              created_at text not null
            );
            create index if not exists idx_commission_prompt_revisions_key
              on commission_prompt_revisions_v2(prompt_key,id desc);
            """
        )
        self._migrate_draft_status_constraint()
        self.conn.commit()
        self._migrate_legacy_once()

    def _migrate_draft_status_constraint(self) -> None:
        row = self.conn.execute(
            "select sql from sqlite_master where type='table' and name='commission_drafts_v2'"
        ).fetchone()
        table_sql = re.sub(r"\s+", "", str(row["sql"] or "").lower()) if row else ""
        if "unique(publisher_user_pk,group_id,status)" in table_sql:
            self.conn.executescript(
                """
                create table commission_drafts_v2_new (
                  id integer primary key autoincrement,
                  publisher_user_pk integer not null,
                  group_id text not null,
                  draft_kind text not null,
                  original_text text not null,
                  parsed_json text not null,
                  prompt_version text not null default 'v2',
                  status text not null default 'pending',
                  created_at text not null,
                  expires_at text not null,
                  completed_at text,
                  foreign key(publisher_user_pk) references users(id)
                );
                insert into commission_drafts_v2_new(
                  id,publisher_user_pk,group_id,draft_kind,original_text,parsed_json,
                  prompt_version,status,created_at,expires_at,completed_at
                )
                select id,publisher_user_pk,group_id,draft_kind,original_text,parsed_json,
                       prompt_version,status,created_at,expires_at,completed_at
                from commission_drafts_v2;
                drop table commission_drafts_v2;
                alter table commission_drafts_v2_new rename to commission_drafts_v2;
                """
            )
        self.conn.execute(
            """create unique index if not exists idx_commission_drafts_v2_pending
               on commission_drafts_v2(publisher_user_pk,group_id)
               where status='pending'"""
        )

    @staticmethod
    def _plus_days(value: str, days: int) -> str:
        try:
            base = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            base = datetime.now()
        return (base + timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _legacy_post_status(value: str, kind: str) -> str:
        status = str(value or "")
        if kind == "service":
            return {"completed": "sold_out", "cancelled": "off_shelf", "archived": "off_shelf"}.get(status, "on_sale")
        return {"completed": "completed", "cancelled": "closed", "archived": "closed"}.get(status, "recruiting")

    def _migrate_legacy_once(self) -> None:
        marker = self.conn.execute(
            "select value from settings where key='commission_house_v2_migrated'"
        ).fetchone()
        if marker:
            return
        self.conn.execute("begin immediate")
        try:
            for row in self.conn.execute("select * from bounties order by id").fetchall():
                data = dict(row)
                kind = "service" if str(data.get("bounty_mode") or "request") == "service" else "demand"
                created = str(data.get("created_at") or self.db.now())
                days = max(1, int(data.get("duration_days") or (3 if kind == "service" else 7)))
                if kind == "demand":
                    self.conn.execute(
                        """insert or ignore into commission_demands(
                           legacy_source_type,legacy_source_id,publisher_user_pk,publisher_user_id,publisher_nickname,
                           original_text,title,content,fulfillment_type,fulfillment_duration_value,
                           fulfillment_duration_unit,required_people,reward_per_person,recruitment_duration_days,
                           recruitment_expires_at,fee_percent,reward_escrow_remaining,fee_escrow_remaining,
                           status,created_at,updated_at,closed_at,close_reason)
                           values('bounty',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            int(data["id"]), int(data["publisher_user_pk"]), str(data.get("publisher_user_id") or ""),
                            str(data.get("publisher_nickname") or ""), str(data.get("content") or ""),
                            str(data.get("content") or "")[:40], str(data.get("content") or ""),
                            "one_time" if str(data.get("duration_type")) == "single" else "time_based",
                            None if str(data.get("duration_type")) == "single" else days,
                            None if str(data.get("duration_type")) == "single" else "day",
                            max(1, int(data.get("required_count") or 1)), int(data.get("reward_per_person") or data.get("reward") or 0),
                            7, self._plus_days(created, 7), 10,
                            int(data.get("reward_escrow") or 0), int(data.get("fee_escrow") or 0),
                            self._legacy_post_status(str(data.get("status")), kind), created,
                            str(data.get("updated_at") or created), data.get("cancelled_at") or data.get("completed_at"),
                            str(data.get("cancel_reason") or ""),
                        ),
                    )
                else:
                    unlimited = bool(int(data.get("unlimited_stock") or 0))
                    count = max(1, int(data.get("required_count") or 1))
                    accepted = self.conn.execute(
                        "select count(*) from bounty_participants where bounty_id=? and participant_status!='cancelled'",
                        (int(data["id"]),),
                    ).fetchone()[0]
                    self.conn.execute(
                        """insert or ignore into commission_services(
                           legacy_source_type,legacy_source_id,seller_user_pk,seller_user_id,seller_nickname,
                           original_text,title,description,unit_label,unit_price,stock_mode,stock_total,stock_remaining,
                           listing_duration_days,listing_expires_at,fulfillment_type,fulfillment_duration_value,
                           fulfillment_duration_unit,commission_percent,sold_quantity,status,created_at,updated_at,
                           off_shelf_at,off_shelf_reason)
                           values('bounty',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            int(data["id"]), int(data["publisher_user_pk"]), str(data.get("publisher_user_id") or ""),
                            str(data.get("publisher_nickname") or ""), str(data.get("content") or ""),
                            str(data.get("content") or "")[:40], str(data.get("content") or ""), "份",
                            int(data.get("reward_per_person") or data.get("reward") or 0),
                            "unlimited" if unlimited else "limited", None if unlimited else count,
                            None if unlimited else max(0, count - int(accepted)), days, self._plus_days(created, days),
                            "one_time" if str(data.get("duration_type")) == "single" else "time_based",
                            None if str(data.get("duration_type")) == "single" else days,
                            None if str(data.get("duration_type")) == "single" else "day", 10, int(accepted),
                            self._legacy_post_status(str(data.get("status")), kind), created,
                            str(data.get("updated_at") or created), data.get("cancelled_at"), str(data.get("cancel_reason") or ""),
                        ),
                    )

            for row in self.conn.execute("select * from market_listings order by id").fetchall():
                data = dict(row)
                self.conn.execute(
                    """insert or ignore into commission_services(
                       legacy_source_type,legacy_source_id,seller_user_pk,seller_user_id,seller_nickname,
                       original_text,title,description,unit_label,unit_price,stock_mode,stock_total,stock_remaining,
                       listing_duration_days,listing_expires_at,fulfillment_type,commission_percent,sold_quantity,
                       status,created_at,updated_at,off_shelf_at,off_shelf_reason)
                       values('market_listing',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        int(data["id"]), int(data["seller_user_pk"]), str(data.get("seller_user_id") or ""),
                        str(data.get("seller_nickname") or ""), str(data.get("original_text") or data.get("description") or ""),
                        str(data.get("title") or ""), str(data.get("description") or ""), "份", int(data.get("price") or 0),
                        "limited", int(data.get("stock_total") or 1), int(data.get("stock_remaining") or 0),
                        int(data.get("duration_days") or 3), str(data.get("expires_at") or self._plus_days(data.get("created_at"), 3)),
                        "one_time", int(data.get("commission_percent") or 10),
                        max(0, int(data.get("stock_total") or 1) - int(data.get("stock_remaining") or 0)),
                        str(data.get("status") or "on_sale"), str(data.get("created_at") or self.db.now()),
                        str(data.get("updated_at") or data.get("created_at") or self.db.now()), data.get("off_shelf_at"), "",
                    ),
                )

            self._migrate_legacy_orders()
            # 旧需求的参与人数来自独立参与表，不能沿用新表默认的0；否则迁移后会错误开放重复名额。
            self.conn.execute(
                """update commission_demands
                   set accepted_count=(select count(*) from commission_orders_v2 o where o.demand_id=commission_demands.id and o.status!='cancelled'),
                       completed_count=(select count(*) from commission_orders_v2 o where o.demand_id=commission_demands.id and o.status='completed')
                   where legacy_source_type='bounty'"""
            )
            self.conn.execute(
                """update commission_demands
                   set status=case
                     when status in ('closed','completed') then status
                     when completed_count>=required_people then 'completed'
                     when accepted_count>=required_people then 'filled'
                     else 'recruiting' end
                   where legacy_source_type='bounty'"""
            )
            self.conn.execute(
                "insert or replace into settings(key,value) values('commission_house_v2_migrated',?)",
                (self.db.now(),),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _migrate_legacy_orders(self) -> None:
        rows = self.conn.execute(
            """select bp.*,b.bounty_mode,b.publisher_user_pk,b.publisher_user_id,b.publisher_nickname,
                      b.content,b.reward_per_person,b.duration_type,b.duration_days
               from bounty_participants bp join bounties b on b.id=bp.bounty_id order by bp.id"""
        ).fetchall()
        for row in rows:
            data = dict(row)
            is_service = str(data.get("bounty_mode") or "request") == "service"
            parent = self.conn.execute(
                ("select id from commission_services where legacy_source_type='bounty' and legacy_source_id=?" if is_service
                 else "select id from commission_demands where legacy_source_type='bounty' and legacy_source_id=?"),
                (int(data["bounty_id"]),),
            ).fetchone()
            if not parent:
                continue
            price = int(data.get("reward_per_person") or 0)
            fee = int(data.get("escrow_fee") or 0)
            status = {"paid": "completed", "completed": "submitted", "cancelled": "cancelled"}.get(str(data.get("participant_status")), "accepted")
            client_pk = int(data["user_pk"] if is_service else data["publisher_user_pk"])
            provider_pk = int(data["publisher_user_pk"] if is_service else data["user_pk"])
            client_uid = str(data.get("user_id") if is_service else data.get("publisher_user_id") or "")
            provider_uid = str(data.get("publisher_user_id") if is_service else data.get("user_id") or "")
            client_name = str(data.get("nickname") if is_service else data.get("publisher_nickname") or "")
            provider_name = str(data.get("publisher_nickname") if is_service else data.get("nickname") or "")
            self.conn.execute(
                """insert or ignore into commission_orders_v2(
                   legacy_source_type,legacy_source_id,order_kind,demand_id,service_id,client_user_pk,client_user_id,
                   client_nickname,provider_user_pk,provider_user_id,provider_nickname,quantity,unit_price,gross_amount,
                   commission_percent,commission_amount,provider_net_amount,escrow_amount,fee_mode,content_snapshot,
                   status,accepted_at,submitted_at,completed_at,cancelled_at,updated_at)
                   values('bounty_participant',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(data["id"]), "service" if is_service else "demand",
                    None if is_service else int(parent["id"]), int(parent["id"]) if is_service else None,
                    client_pk, client_uid, client_name, provider_pk, provider_uid, provider_name, 1, price, price,
                    0 if is_service else 0, fee if is_service else 0, price, int(data.get("escrow_amount") or price) + (fee if is_service else 0),
                    "buyer_surcharge_legacy" if is_service else "demand_prepaid", str(data.get("content") or ""), status,
                    str(data.get("accepted_at") or self.db.now()), data.get("completed_at"), data.get("confirmed_at"),
                    data.get("cancelled_at"), str(data.get("confirmed_at") or data.get("completed_at") or data.get("accepted_at") or self.db.now()),
                ),
            )
        for row in self.conn.execute("select * from market_orders order by id").fetchall():
            data = dict(row)
            service = self.conn.execute(
                "select id from commission_services where legacy_source_type='market_listing' and legacy_source_id=?",
                (int(data["listing_id"]),),
            ).fetchone()
            if not service:
                continue
            seller = self.conn.execute("select * from commission_services where id=?", (int(service["id"]),)).fetchone()
            self.conn.execute(
                """insert or ignore into commission_orders_v2(
                   legacy_source_type,legacy_source_id,order_kind,service_id,client_user_pk,client_user_id,client_nickname,
                   provider_user_pk,provider_user_id,provider_nickname,quantity,unit_price,gross_amount,commission_percent,
                   commission_amount,provider_net_amount,escrow_amount,fee_mode,content_snapshot,status,accepted_at,
                   completed_at,updated_at)
                   values('market_order',?,'service',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'completed',?,?,?)""",
                (
                    int(data["id"]), int(service["id"]), int(data["buyer_user_pk"]), str(data.get("buyer_user_id") or ""),
                    str(data.get("buyer_nickname") or ""), int(seller["seller_user_pk"]), str(seller["seller_user_id"]),
                    str(seller["seller_nickname"]), int(data.get("quantity") or 1), int(data.get("unit_price") or 0),
                    int(data.get("gross_amount") or 0), int(data.get("commission_percent") or 10),
                    int(data.get("commission_amount") or 0), int(data.get("seller_net_amount") or 0), 0,
                    "seller_deducted", str(data.get("listing_title") or ""), str(data.get("created_at") or self.db.now()),
                    str(data.get("created_at") or self.db.now()), str(data.get("created_at") or self.db.now()),
                ),
            )

    def _verified_user(self, ref: dict[str, Any]) -> dict[str, Any]:
        user = self.db.ensure_user(ref)
        self.db._assert_not_identity_conflict(user)
        uid = str(user.get("platform_user_id") or user.get("user_id") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", uid):
            raise ValueError("群友委托所需要有效的平台唯一ID")
        return user

    def save_draft(self, publisher_ref: dict[str, Any], kind: str, original_text: str, parsed: dict[str, Any], ttl_seconds: int = 600) -> dict[str, Any]:
        user = self._verified_user(publisher_ref)
        group_id = str(publisher_ref.get("group_id") or publisher_ref.get("group_key") or publisher_ref.get("source_group") or "main")
        now = datetime.now()
        created = now.strftime("%Y-%m-%d %H:%M:%S")
        expires = (now + timedelta(seconds=max(60, int(ttl_seconds)))).strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute("delete from commission_drafts_v2 where publisher_user_pk=? and group_id=? and status='pending'", (int(user["id"]), group_id))
        cur = self.conn.execute(
            """insert into commission_drafts_v2(publisher_user_pk,group_id,draft_kind,original_text,parsed_json,prompt_version,status,created_at,expires_at)
               values(?,?,?,?,?,'v2','pending',?,?)""",
            (int(user["id"]), group_id, str(kind), str(original_text), json.dumps(parsed, ensure_ascii=False), created, expires),
        )
        self.conn.commit()
        return dict(self.conn.execute("select * from commission_drafts_v2 where id=?", (cur.lastrowid,)).fetchone())

    def _wizard_identity(self, ref: dict[str, Any]) -> tuple[dict[str, Any], str]:
        user = self._verified_user(ref)
        group_id = str(ref.get("group_id") or ref.get("group_key") or ref.get("source_group") or "main")
        return user, group_id

    def start_wizard(self, ref: dict[str, Any], kind: str, step: str, expires_seconds: int = 600) -> dict[str, Any]:
        existing = self.get_wizard(ref)
        if existing:
            return existing
        user, group_id = self._wizard_identity(ref)
        now = datetime.now()
        created = now.strftime("%Y-%m-%d %H:%M:%S")
        expires = (now + timedelta(seconds=max(60, int(expires_seconds)))).strftime("%Y-%m-%d %H:%M:%S")
        cur = self.conn.execute(
            """insert into commission_wizard_sessions(
               publisher_user_pk,group_id,wizard_kind,current_step,values_json,history_json,
               status,created_at,updated_at,expires_at)
               values(?,?,?,?,?,'[]','active',?,?,?)""",
            (int(user["id"]), group_id, str(kind), str(step), "{}", created, created, expires),
        )
        self.conn.commit()
        return self.get_wizard(ref) or dict(self.conn.execute("select * from commission_wizard_sessions where id=?", (cur.lastrowid,)).fetchone())

    def get_wizard(self, ref: dict[str, Any]) -> dict[str, Any] | None:
        user, group_id = self._wizard_identity(ref)
        row = self.conn.execute(
            """select * from commission_wizard_sessions
               where publisher_user_pk=? and group_id=? and status='active'
               order by id desc limit 1""",
            (int(user["id"]), group_id),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        if str(item["expires_at"]) <= self.db.now():
            self.conn.execute(
                "update commission_wizard_sessions set status='expired',completed_at=? where id=?",
                (self.db.now(), int(item["id"])),
            )
            self.conn.commit()
            return None
        item["values"] = json.loads(item["values_json"])
        item["history"] = json.loads(item["history_json"])
        return item

    def update_wizard(self, ref: dict[str, Any], step: str, values: dict[str, Any], history: list[str], expires_seconds: int = 600) -> dict[str, Any]:
        wizard = self.get_wizard(ref)
        if not wizard:
            raise ValueError("当前没有进行中的发布向导")
        now = datetime.now()
        updated = now.strftime("%Y-%m-%d %H:%M:%S")
        expires = (now + timedelta(seconds=max(60, int(expires_seconds)))).strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            """update commission_wizard_sessions
               set current_step=?,values_json=?,history_json=?,updated_at=?,expires_at=? where id=?""",
            (str(step), json.dumps(values, ensure_ascii=False), json.dumps(history, ensure_ascii=False), updated, expires, int(wizard["id"])),
        )
        self.conn.commit()
        return self.get_wizard(ref) or {}

    def _finish_wizard(self, ref: dict[str, Any], status: str) -> bool:
        wizard = self.get_wizard(ref)
        if not wizard:
            return False
        self.conn.execute(
            "update commission_wizard_sessions set status=?,completed_at=?,updated_at=? where id=?",
            (str(status), self.db.now(), self.db.now(), int(wizard["id"])),
        )
        self.conn.commit()
        return True

    def cancel_wizard(self, ref: dict[str, Any]) -> bool:
        return self._finish_wizard(ref, "cancelled")

    def complete_wizard(self, ref: dict[str, Any]) -> bool:
        return self._finish_wizard(ref, "completed")

    def get_draft(self, publisher_ref: dict[str, Any]) -> dict[str, Any] | None:
        user = self._verified_user(publisher_ref)
        group_id = str(publisher_ref.get("group_id") or publisher_ref.get("group_key") or publisher_ref.get("source_group") or "main")
        row = self.conn.execute(
            """select * from commission_drafts_v2 where publisher_user_pk=? and group_id=? and status='pending'
               order by id desc limit 1""",
            (int(user["id"]), group_id),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        if str(item["expires_at"]) <= self.db.now():
            self.conn.execute("update commission_drafts_v2 set status='expired',completed_at=? where id=?", (self.db.now(), int(item["id"])))
            self.conn.commit()
            return None
        item["parsed"] = json.loads(item["parsed_json"])
        return item

    def cancel_draft(self, publisher_ref: dict[str, Any]) -> bool:
        draft = self.get_draft(publisher_ref)
        if not draft:
            return False
        self.conn.execute("update commission_drafts_v2 set status='cancelled',completed_at=? where id=?", (self.db.now(), int(draft["id"])))
        self.conn.commit()
        return True

    def confirm_draft(self, publisher_ref: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
        draft = self.get_draft(publisher_ref)
        if not draft:
            raise ValueError("没有找到有效的委托草稿")
        if draft["draft_kind"] == "service":
            post = self.create_service(publisher_ref, draft["parsed"], draft["original_text"], settings)
        else:
            post = self.create_demand(publisher_ref, draft["parsed"], draft["original_text"], settings)
        self.conn.execute("update commission_drafts_v2 set status='published',completed_at=? where id=?", (self.db.now(), int(draft["id"])))
        self.conn.commit()
        return {"kind": draft["draft_kind"], "post": post}

    def _adjust_points(self, user: dict[str, Any], amount: int, reason: str) -> int:
        amount = int(amount)
        current = int(self.conn.execute("select points from users where id=?", (int(user["id"]),)).fetchone()[0] or 0)
        balance = current + amount
        if amount < 0 and balance < 0:
            raise ValueError("功德不足")
        self.conn.execute("update users set points=?,last_seen_at=? where id=?", (balance, self.db.now(), int(user["id"])))
        self.conn.execute(
            "insert into transactions(user_id,nickname,change_amount,reason,balance_after,created_at) values(?,?,?,?,?,?)",
            (str(user.get("platform_user_id") or user.get("user_id") or ""), str(user.get("nickname") or ""), amount, reason, balance, self.db.now()),
        )
        return balance

    def _public_code(self, kind: str, row: dict[str, Any]) -> str:
        prefix = {"demand": "D", "service": "S", "order": "O"}[kind]
        legacy_type = str(row.get("legacy_source_type") or "")
        legacy_id = row.get("legacy_source_id")
        if legacy_type and legacy_id:
            return self.db.commission_public_code(legacy_type, int(legacy_id), prefix)
        return self.db.commission_public_code(f"commission_{kind}", int(row["id"]), prefix)

    def _serialize(self, kind: str, row: Any) -> dict[str, Any]:
        item = dict(row)
        item["commission_number"] = self._public_code(kind, item)
        return item

    def resolve(self, code: str, kind: str | None = None) -> dict[str, Any] | None:
        match = re.fullmatch(r"([DSO])(\d{1,8})", str(code or "").strip().upper())
        if not match:
            return None
        prefix, number = match.group(1), int(match.group(2))
        expected = {"D": "demand", "S": "service", "O": "order"}[prefix]
        if kind and expected != kind:
            return None
        source = self.db.resolve_commission_public_id(prefix, number)
        if not source:
            return None
        source_type, source_id = str(source["source_type"]), int(source["source_id"])
        table = {"demand": "commission_demands", "service": "commission_services", "order": "commission_orders_v2"}[expected]
        native = f"commission_{expected}"
        if source_type == native:
            row = self.conn.execute(f"select * from {table} where id=?", (source_id,)).fetchone()
        else:
            row = self.conn.execute(
                f"select * from {table} where legacy_source_type=? and legacy_source_id=?",
                (source_type, source_id),
            ).fetchone()
        return self._serialize(expected, row) if row else None

    def create_demand(self, publisher_ref: dict[str, Any], parsed: dict[str, Any], original_text: str, settings: dict[str, Any]) -> dict[str, Any]:
        user = self._verified_user(publisher_ref)
        required = int(parsed["required_people"])
        reward = int(parsed["reward_per_person"])
        if not 1 <= required <= int(settings.get("commission_demand_max_people", 10) or 10):
            raise ValueError("需求人数超出允许范围")
        if reward < int(settings.get("commission_demand_min_reward", 1) or 1):
            raise ValueError("每人奖励低于最低限制")
        fee_percent = max(0, min(100, int(settings.get("commission_demand_fee_percent", 10) or 0)))
        reward_total = required * reward
        fee_total = math.floor(reward_total * fee_percent / 100)
        days = int(parsed.get("recruitment_duration_days") or settings.get("commission_demand_default_recruitment_days", 7) or 7)
        now = self.db.now()
        message_id = str(publisher_ref.get("message_id") or "")
        self.conn.execute("begin immediate")
        try:
            if message_id:
                old = self.conn.execute("select * from commission_demands where created_message_id=?", (message_id,)).fetchone()
                if old:
                    self.conn.rollback()
                    return self._serialize("demand", old)
            self._adjust_points(user, -(reward_total + fee_total), "发布需求，托管奖励与手续费")
            cur = self.conn.execute(
                """insert into commission_demands(
                   publisher_user_pk,publisher_user_id,publisher_nickname,original_text,title,content,
                   fulfillment_type,fulfillment_duration_value,fulfillment_duration_unit,required_people,
                   reward_per_person,recruitment_duration_days,recruitment_expires_at,fee_percent,
                   reward_escrow_remaining,fee_escrow_remaining,status,created_message_id,created_at,updated_at)
                   values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(user["id"]), str(user.get("platform_user_id") or user.get("user_id") or ""), str(user.get("nickname") or ""),
                    str(original_text), str(parsed["title"]), str(parsed["content"]), str(parsed["fulfillment_type"]),
                    parsed.get("fulfillment_duration_value"), parsed.get("fulfillment_duration_unit"), required, reward, days,
                    self._plus_days(now, days), fee_percent, reward_total, fee_total, "recruiting", message_id, now, now,
                ),
            )
            row = self.conn.execute("select * from commission_demands where id=?", (cur.lastrowid,)).fetchone()
            self._public_code("demand", dict(row))
            self.conn.commit()
            return self._serialize("demand", row)
        except Exception:
            self.conn.rollback()
            raise

    def create_service(self, seller_ref: dict[str, Any], parsed: dict[str, Any], original_text: str, settings: dict[str, Any]) -> dict[str, Any]:
        user = self._verified_user(seller_ref)
        price = int(parsed["unit_price"])
        minimum = int(settings.get("commission_service_min_price", 50) or 50)
        if price < minimum:
            raise ValueError(f"服务价格不能低于{minimum}功德")
        active = self.conn.execute(
            "select count(*) from commission_services where seller_user_pk=? and status='on_sale'",
            (int(user["id"]),),
        ).fetchone()[0]
        maximum = int(settings.get("commission_service_max_active", 3) or 3)
        if int(active) >= maximum:
            raise ValueError(f"每人最多同时上架{maximum}项服务")
        stock_mode = str(parsed.get("stock_mode") or "limited")
        stock = parsed.get("stock_quantity")
        if stock_mode == "limited":
            stock = int(stock or settings.get("commission_service_default_stock", 1) or 1)
            if not 1 <= stock <= int(settings.get("commission_service_max_stock", 999) or 999):
                raise ValueError("服务库存超出允许范围")
        else:
            stock = None
        days = int(parsed.get("listing_duration_days") or settings.get("commission_service_default_listing_days", 3) or 3)
        commission = max(0, min(100, int(settings.get("commission_service_commission_percent", 10) or 0)))
        now, message_id = self.db.now(), str(seller_ref.get("message_id") or "")
        self.conn.execute("begin immediate")
        try:
            if message_id:
                old = self.conn.execute("select * from commission_services where created_message_id=?", (message_id,)).fetchone()
                if old:
                    self.conn.rollback()
                    return self._serialize("service", old)
            cur = self.conn.execute(
                """insert into commission_services(
                   seller_user_pk,seller_user_id,seller_nickname,original_text,title,description,unit_label,unit_price,
                   stock_mode,stock_total,stock_remaining,listing_duration_days,listing_expires_at,fulfillment_type,
                   fulfillment_duration_value,fulfillment_duration_unit,max_per_buyer,commission_percent,status,
                   created_message_id,created_at,updated_at)
                   values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(user["id"]), str(user.get("platform_user_id") or user.get("user_id") or ""), str(user.get("nickname") or ""),
                    str(original_text), str(parsed["title"]), str(parsed["description"]), str(parsed.get("unit_label") or "次"),
                    price, stock_mode, stock, stock, days, self._plus_days(now, days), str(parsed.get("fulfillment_type") or "one_time"),
                    parsed.get("fulfillment_duration_value"), parsed.get("fulfillment_duration_unit"), parsed.get("max_per_buyer"),
                    commission, "on_sale", message_id, now, now,
                ),
            )
            row = self.conn.execute("select * from commission_services where id=?", (cur.lastrowid,)).fetchone()
            self._public_code("service", dict(row))
            self.conn.commit()
            return self._serialize("service", row)
        except Exception:
            self.conn.rollback()
            raise

    def expire_services(self) -> int:
        now = self.db.now()
        changed = self.conn.execute(
            "update commission_services set status='expired',updated_at=? where status='on_sale' and listing_expires_at<=?",
            (now, now),
        ).rowcount
        self.conn.commit()
        return int(changed)

    def list_demands(self, *, status: str | None = None) -> list[dict[str, Any]]:
        sql = "select * from commission_demands"
        params: tuple[Any, ...] = ()
        if status:
            sql += " where status=?"
            params = (status,)
        sql += " order by created_at desc,id desc"
        return [self._serialize("demand", row) for row in self.conn.execute(sql, params).fetchall()]

    def list_services(self, *, status: str | None = None) -> list[dict[str, Any]]:
        self.expire_services()
        sql = "select * from commission_services"
        params: tuple[Any, ...] = ()
        if status:
            sql += " where status=?"
            params = (status,)
        sql += " order by created_at desc,id desc"
        return [self._serialize("service", row) for row in self.conn.execute(sql, params).fetchall()]

    def get_demand(self, demand_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("select * from commission_demands where id=?", (int(demand_id),)).fetchone()
        return self._serialize("demand", row) if row else None

    def get_service(self, service_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("select * from commission_services where id=?", (int(service_id),)).fetchone()
        return self._serialize("service", row) if row else None

    def accept_demand(self, demand_id: int, provider_ref: dict[str, Any]) -> dict[str, Any]:
        provider = self._verified_user(provider_ref)
        demand = self.get_demand(demand_id)
        if not demand or demand["status"] != "recruiting":
            raise ValueError("需求当前不可接取")
        if int(demand["publisher_user_pk"]) == int(provider["id"]):
            raise ValueError("不能接取自己发布的需求")
        duplicate = self.conn.execute(
            "select id from commission_orders_v2 where demand_id=? and provider_user_pk=? and status in ('accepted','submitted','cancel_requested','completed')",
            (int(demand_id), int(provider["id"])),
        ).fetchone()
        if duplicate:
            raise ValueError("你已经接取过这个需求")
        active = self.conn.execute(
            "select count(*) from commission_orders_v2 where demand_id=? and status in ('accepted','submitted','cancel_requested','completed')",
            (int(demand_id),),
        ).fetchone()[0]
        if int(active) >= int(demand["required_people"]):
            raise ValueError("需求名额已满")
        client = self.conn.execute("select * from users where id=?", (int(demand["publisher_user_pk"]),)).fetchone()
        return self._create_order("demand", demand, dict(client), provider, 1, provider_ref)

    def purchase_service(self, service_id: int, buyer_ref: dict[str, Any], quantity: int = 1) -> dict[str, Any]:
        buyer = self._verified_user(buyer_ref)
        self.expire_services()
        service = self.get_service(service_id)
        if not service or service["status"] != "on_sale":
            raise ValueError("服务当前不可购买")
        if int(service["seller_user_pk"]) == int(buyer["id"]):
            raise ValueError("不能购买自己发布的服务")
        quantity = int(quantity)
        if not 1 <= quantity <= 999:
            raise ValueError("购买数量必须在1到999之间")
        if service["stock_mode"] == "limited" and int(service["stock_remaining"] or 0) < quantity:
            raise ValueError("服务库存不足")
        if service.get("max_per_buyer"):
            bought = self.conn.execute(
                "select coalesce(sum(quantity),0) from commission_orders_v2 where service_id=? and client_user_pk=? and status!='cancelled'",
                (int(service_id), int(buyer["id"])),
            ).fetchone()[0]
            if int(bought) + quantity > int(service["max_per_buyer"]):
                raise ValueError("超过该服务的每位买家限购数量")
        seller = self.conn.execute("select * from users where id=?", (int(service["seller_user_pk"]),)).fetchone()
        return self._create_order("service", service, buyer, dict(seller), quantity, buyer_ref)

    def _create_order(self, kind: str, post: dict[str, Any], client: dict[str, Any], provider: dict[str, Any], quantity: int, ref: dict[str, Any]) -> dict[str, Any]:
        unit_price = int(post["reward_per_person"] if kind == "demand" else post["unit_price"])
        gross = unit_price * int(quantity)
        commission_percent = 0 if kind == "demand" else int(post.get("commission_percent") or 0)
        commission = math.floor(gross * commission_percent / 100)
        net = gross - commission
        now, message_id = self.db.now(), str(ref.get("message_id") or "")
        due = None
        value = post.get("fulfillment_duration_value")
        if value:
            hours = int(value) if post.get("fulfillment_duration_unit") == "hour" else int(value) * 24
            due = (datetime.strptime(now, "%Y-%m-%d %H:%M:%S") + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute("begin immediate")
        try:
            if message_id:
                old = self.conn.execute("select * from commission_orders_v2 where accepted_message_id=?", (message_id,)).fetchone()
                if old:
                    self.conn.rollback()
                    return self._serialize("order", old)
            if kind == "service":
                self._adjust_points(client, -gross, "购买群友服务，资金进入订单托管")
                if post["stock_mode"] == "limited":
                    changed = self.conn.execute(
                        "update commission_services set stock_remaining=stock_remaining-?,sold_quantity=sold_quantity+?,updated_at=? where id=? and stock_remaining>=?",
                        (quantity, quantity, now, int(post["id"]), quantity),
                    ).rowcount
                    if not changed:
                        raise ValueError("服务库存不足")
                else:
                    self.conn.execute("update commission_services set sold_quantity=sold_quantity+?,updated_at=? where id=?", (quantity, now, int(post["id"])))
            cur = self.conn.execute(
                """insert into commission_orders_v2(
                   order_kind,demand_id,service_id,client_user_pk,client_user_id,client_nickname,
                   provider_user_pk,provider_user_id,provider_nickname,quantity,unit_price,gross_amount,
                   commission_percent,commission_amount,provider_net_amount,escrow_amount,fee_mode,content_snapshot,
                   status,accepted_message_id,accepted_at,fulfillment_due_at,updated_at)
                   values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    kind, int(post["id"]) if kind == "demand" else None, int(post["id"]) if kind == "service" else None,
                    int(client["id"]), str(client.get("platform_user_id") or client.get("user_id") or ""), str(client.get("nickname") or ""),
                    int(provider["id"]), str(provider.get("platform_user_id") or provider.get("user_id") or ""), str(provider.get("nickname") or ""),
                    quantity, unit_price, gross, commission_percent, commission, net, gross, "demand_prepaid" if kind == "demand" else "seller_deducted",
                    str(post.get("content") if kind == "demand" else post.get("description") or ""), "accepted", message_id, now, due, now,
                ),
            )
            if kind == "demand":
                self.conn.execute("update commission_demands set accepted_count=accepted_count+1,updated_at=? where id=?", (now, int(post["id"])))
                count = self.conn.execute("select accepted_count,required_people from commission_demands where id=?", (int(post["id"]),)).fetchone()
                if int(count["accepted_count"]) >= int(count["required_people"]):
                    self.conn.execute("update commission_demands set status='filled',updated_at=? where id=?", (now, int(post["id"])))
            elif post["stock_mode"] == "limited":
                remaining = self.conn.execute("select stock_remaining from commission_services where id=?", (int(post["id"]),)).fetchone()[0]
                if int(remaining) <= 0:
                    self.conn.execute("update commission_services set status='sold_out',updated_at=? where id=?", (now, int(post["id"])))
            row = self.conn.execute("select * from commission_orders_v2 where id=?", (cur.lastrowid,)).fetchone()
            self._public_code("order", dict(row))
            self.conn.commit()
            return self._serialize("order", row)
        except Exception:
            self.conn.rollback()
            raise

    def get_order(self, order_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("select * from commission_orders_v2 where id=?", (int(order_id),)).fetchone()
        return self._serialize("order", row) if row else None

    def list_orders(self, *, user_pk: int | None = None) -> list[dict[str, Any]]:
        if user_pk is None:
            rows = self.conn.execute("select * from commission_orders_v2 order by accepted_at desc,id desc").fetchall()
        else:
            rows = self.conn.execute(
                "select * from commission_orders_v2 where client_user_pk=? or provider_user_pk=? order by accepted_at desc,id desc",
                (int(user_pk), int(user_pk)),
            ).fetchall()
        return [self._serialize("order", row) for row in rows]

    def submit_order(self, order_id: int, actor_ref: dict[str, Any]) -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        order = self.get_order(order_id)
        if not order or order["status"] != "accepted":
            raise ValueError("订单当前不能提交完成")
        if int(order["provider_user_pk"]) != int(actor["id"]):
            raise ValueError("只有履约方可以提交完成")
        now = self.db.now()
        self.conn.execute("update commission_orders_v2 set status='submitted',submitted_at=?,updated_at=? where id=?", (now, now, int(order_id)))
        self.conn.commit()
        return self.get_order(order_id) or {}

    def confirm_order(self, order_id: int, actor_ref: dict[str, Any]) -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        order = self.get_order(order_id)
        if not order or order["status"] != "submitted":
            raise ValueError("订单尚未由履约方提交完成")
        if int(order["client_user_pk"]) != int(actor["id"]):
            raise ValueError("只有委托方或买家可以确认完成")
        provider = dict(self.conn.execute("select * from users where id=?", (int(order["provider_user_pk"]),)).fetchone())
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            self._adjust_points(provider, int(order["provider_net_amount"]), "群友委托订单确认完成")
            self.conn.execute("update commission_orders_v2 set status='completed',completed_at=?,updated_at=? where id=?", (now, now, int(order_id)))
            if order["order_kind"] == "demand":
                demand = self.get_demand(int(order["demand_id"]))
                reward = int(order["gross_amount"])
                fee = math.floor(reward * int(demand.get("fee_percent") or 0) / 100) if demand else 0
                self.conn.execute(
                    """update commission_demands set completed_count=completed_count+1,
                       reward_escrow_remaining=max(0,reward_escrow_remaining-?),
                       fee_escrow_remaining=max(0,fee_escrow_remaining-?),updated_at=? where id=?""",
                    (reward, fee, now, int(order["demand_id"])),
                )
                counts = self.conn.execute("select completed_count,required_people from commission_demands where id=?", (int(order["demand_id"]),)).fetchone()
                if int(counts["completed_count"]) >= int(counts["required_people"]):
                    self.conn.execute("update commission_demands set status='completed',closed_at=?,updated_at=? where id=?", (now, now, int(order["demand_id"])))
            self.conn.commit()
            return self.get_order(order_id) or {}
        except Exception:
            self.conn.rollback()
            raise

    def request_cancel(self, order_id: int, actor_ref: dict[str, Any], reason: str = "") -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        order = self.get_order(order_id)
        if not order or order["status"] not in {"accepted", "submitted"}:
            raise ValueError("订单当前不能申请取消")
        if int(actor["id"]) not in {int(order["client_user_pk"]), int(order["provider_user_pk"])}:
            raise ValueError("你不是这笔订单的交易方")
        now = self.db.now()
        self.conn.execute(
            "update commission_orders_v2 set status='cancel_requested',cancel_requester_user_pk=?,cancel_reason=?,cancel_requested_at=?,updated_at=? where id=?",
            (int(actor["id"]), str(reason or ""), now, now, int(order_id)),
        )
        self.conn.commit()
        return self.get_order(order_id) or {}

    def respond_cancel(self, order_id: int, actor_ref: dict[str, Any], approve: bool) -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        order = self.get_order(order_id)
        if not order or order["status"] != "cancel_requested":
            raise ValueError("订单没有待处理的取消申请")
        if int(actor["id"]) not in {int(order["client_user_pk"]), int(order["provider_user_pk"])} or int(actor["id"]) == int(order["cancel_requester_user_pk"]):
            raise ValueError("只有另一方可以处理取消申请")
        now = self.db.now()
        if not approve:
            self.conn.execute("update commission_orders_v2 set status='accepted',cancel_requester_user_pk=null,cancel_requested_at=null,updated_at=? where id=?", (now, int(order_id)))
            self.conn.commit()
            return self.get_order(order_id) or {}
        client = dict(self.conn.execute("select * from users where id=?", (int(order["client_user_pk"]),)).fetchone())
        self.conn.execute("begin immediate")
        try:
            if order["order_kind"] == "service":
                self._adjust_points(client, int(order["escrow_amount"]), "群友服务订单双方同意取消退款")
                service = self.get_service(int(order["service_id"]))
                if service and service["stock_mode"] == "limited":
                    self.conn.execute(
                        "update commission_services set stock_remaining=stock_remaining-0+?,sold_quantity=max(0,sold_quantity-?),status=case when status='sold_out' then 'on_sale' else status end,updated_at=? where id=?",
                        (int(order["quantity"]), int(order["quantity"]), now, int(order["service_id"])),
                    )
            else:
                self.conn.execute(
                    "update commission_demands set accepted_count=max(0,accepted_count-1),status=case when status='filled' then 'recruiting' else status end,updated_at=? where id=?",
                    (now, int(order["demand_id"])),
                )
            self.conn.execute("update commission_orders_v2 set status='cancelled',cancelled_at=?,updated_at=? where id=?", (now, now, int(order_id)))
            self.conn.commit()
            return self.get_order(order_id) or {}
        except Exception:
            self.conn.rollback()
            raise

    def close_demand(self, demand_id: int, actor_ref: dict[str, Any]) -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        demand = self.get_demand(demand_id)
        if not demand or demand["status"] not in {"recruiting", "filled"}:
            raise ValueError("需求当前不能关闭")
        if int(actor["id"]) != int(demand["publisher_user_pk"]):
            raise ValueError("只有发布者可以关闭需求")
        active = self.conn.execute(
            "select count(*) from commission_orders_v2 where demand_id=? and status in ('accepted','submitted','cancel_requested')",
            (int(demand_id),),
        ).fetchone()[0]
        unused = max(0, int(demand["required_people"]) - int(active) - int(demand["completed_count"]))
        reward_refund = unused * int(demand["reward_per_person"])
        fee_refund = math.floor(reward_refund * int(demand["fee_percent"]) / 100)
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            if reward_refund + fee_refund:
                self._adjust_points(actor, reward_refund + fee_refund, "关闭需求，退还未使用托管")
            self.conn.execute(
                """update commission_demands set status='closed',closed_at=?,close_reason='发布者主动关闭',
                   reward_escrow_remaining=max(0,reward_escrow_remaining-?),fee_escrow_remaining=max(0,fee_escrow_remaining-?),updated_at=? where id=?""",
                (now, reward_refund, fee_refund, now, int(demand_id)),
            )
            if str(demand.get("legacy_source_type") or "") == "bounty" and demand.get("legacy_source_id"):
                self.conn.execute(
                    """update bounties
                       set status='cancelled',cancelled_at=coalesce(cancelled_at,?),
                           refunded_at=coalesce(refunded_at,?),refund_amount=max(refund_amount,total_charge),
                           cancel_reason='commission_v2_close',updated_at=?
                       where id=? and refunded_at is null""",
                    (now, now, now, int(demand["legacy_source_id"])),
                )
            self.conn.commit()
            return {**(self.get_demand(demand_id) or {}), "refund": reward_refund + fee_refund}
        except Exception:
            self.conn.rollback()
            raise

    def off_shelf_service(self, service_id: int, actor_ref: dict[str, Any]) -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        service = self.get_service(service_id)
        if not service or service["status"] not in {"on_sale", "sold_out", "expired"}:
            raise ValueError("服务当前不能下架")
        if int(actor["id"]) != int(service["seller_user_pk"]):
            raise ValueError("只有服务发布者可以下架")
        now = self.db.now()
        self.conn.execute("update commission_services set status='off_shelf',off_shelf_at=?,off_shelf_reason='卖家主动下架',updated_at=? where id=?", (now, now, int(service_id)))
        self.conn.commit()
        return self.get_service(service_id) or {}

    def delete_service(self, service_id: int, actor_ref: dict[str, Any]) -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        service = self.get_service(service_id)
        if not service:
            raise ValueError("没有找到服务")
        if int(actor["id"]) != int(service["seller_user_pk"]):
            raise ValueError("只有服务发布者可以删除服务")
        if service["status"] != "off_shelf":
            raise ValueError("请先下架服务，再执行删除")
        active = self.conn.execute(
            "select count(*) from commission_orders_v2 where service_id=? and status in ('accepted','submitted','cancel_requested')",
            (int(service_id),),
        ).fetchone()[0]
        if int(active):
            raise ValueError("服务仍有未结束订单，暂时不能删除")
        self.conn.execute(
            "update commission_services set status='deleted',updated_at=? where id=?",
            (self.db.now(), int(service_id)),
        )
        self.conn.commit()
        return self.get_service(service_id) or {}

    def delete_demand(self, demand_id: int, actor_ref: dict[str, Any]) -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        demand = self.get_demand(demand_id)
        if not demand:
            raise ValueError("没有找到需求")
        if int(actor["id"]) != int(demand["publisher_user_pk"]):
            raise ValueError("只有需求发布者可以删除需求")
        if demand["status"] not in {"closed", "completed"}:
            raise ValueError("只能删除已关闭或已完成的需求")
        active = self.conn.execute(
            "select count(*) from commission_orders_v2 where demand_id=? and status in ('accepted','submitted','cancel_requested')",
            (int(demand_id),),
        ).fetchone()[0]
        if int(active):
            raise ValueError("需求仍有未结束订单，暂时不能删除")
        self.conn.execute(
            "update commission_demands set status='deleted',updated_at=? where id=?",
            (self.db.now(), int(demand_id)),
        )
        self.conn.commit()
        return self.get_demand(demand_id) or {}

    def restock(self, service_id: int, actor_ref: dict[str, Any], quantity: int) -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        service = self.get_service(service_id)
        if not service or service["stock_mode"] != "limited":
            raise ValueError("只有有限库存服务可以补充库存")
        if int(actor["id"]) != int(service["seller_user_pk"]):
            raise ValueError("只有服务发布者可以补充库存")
        quantity = int(quantity)
        if not 1 <= quantity <= 999:
            raise ValueError("补充数量必须在1到999之间")
        if int(service.get("stock_total") or 0) + quantity > 999:
            raise ValueError("服务总库存不能超过999")
        now = self.db.now()
        self.conn.execute(
            "update commission_services set stock_total=stock_total+?,stock_remaining=stock_remaining+?,status=case when status='sold_out' then 'on_sale' else status end,updated_at=? where id=?",
            (quantity, quantity, now, int(service_id)),
        )
        self.conn.commit()
        return self.get_service(service_id) or {}

    def renew(self, service_id: int, actor_ref: dict[str, Any], days: int) -> dict[str, Any]:
        actor = self._verified_user(actor_ref)
        service = self.get_service(service_id)
        if not service:
            raise ValueError("没有找到服务")
        if int(actor["id"]) != int(service["seller_user_pk"]):
            raise ValueError("只有服务发布者可以续期")
        days = int(days)
        if not 1 <= days <= 365:
            raise ValueError("续期天数必须在1到365之间")
        base = max(datetime.now(), datetime.strptime(str(service["listing_expires_at"]), "%Y-%m-%d %H:%M:%S"))
        expires = (base + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        status = "on_sale" if service["status"] in {"expired", "off_shelf"} and (service["stock_mode"] == "unlimited" or int(service["stock_remaining"] or 0) > 0) else service["status"]
        self.conn.execute("update commission_services set listing_expires_at=?,listing_duration_days=listing_duration_days+?,status=?,updated_at=? where id=?", (expires, days, status, self.db.now(), int(service_id)))
        self.conn.commit()
        return self.get_service(service_id) or {}

    def list_my_posts(self, user_ref: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        user = self._verified_user(user_ref)
        demands = [self._serialize("demand", row) for row in self.conn.execute("select * from commission_demands where publisher_user_pk=? and status!='deleted' order by created_at desc", (int(user["id"]),)).fetchall()]
        services = [self._serialize("service", row) for row in self.conn.execute("select * from commission_services where seller_user_pk=? and status!='deleted' order by created_at desc", (int(user["id"]),)).fetchall()]
        return {"demands": demands, "services": services}

    def admin_overview(self) -> dict[str, Any]:
        return {
            "demands": self.list_demands(),
            "services": self.list_services(),
            "orders": self.list_orders(),
            "counts": {
                "active_demands": self.conn.execute("select count(*) from commission_demands where status in ('recruiting','filled')").fetchone()[0],
                "active_services": self.conn.execute("select count(*) from commission_services where status='on_sale'").fetchone()[0],
                "active_orders": self.conn.execute("select count(*) from commission_orders_v2 where status in ('accepted','submitted','cancel_requested')").fetchone()[0],
                "escrow": self.conn.execute("select coalesce(sum(escrow_amount),0) from commission_orders_v2 where status in ('accepted','submitted','cancel_requested')").fetchone()[0],
            },
        }

    def _audit(self, object_type: str, object_id: int, action: str, admin_identity: str, reason: str, detail: str = "") -> None:
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("管理员操作必须填写原因")
        self.conn.execute(
            "insert into commission_admin_audit_v2(object_type,object_id,action,admin_identity,reason,detail,created_at) values(?,?,?,?,?,?,?)",
            (object_type, int(object_id), action, str(admin_identity or "local-manager"), reason, detail, self.db.now()),
        )

    def admin_update_demand(self, demand_id: int, changes: dict[str, Any], admin_identity: str) -> dict[str, Any]:
        demand = self.get_demand(demand_id)
        if not demand:
            raise ValueError("没有找到需求")
        reason = str(changes.get("reason") or "").strip()
        title = str(changes.get("title", demand["title"]) or "").strip()
        content = str(changes.get("content", demand["content"]) or "").strip()
        required = int(changes.get("required_people", demand["required_people"]))
        reward = int(changes.get("reward_per_person", demand["reward_per_person"]))
        if not title or not content or not 1 <= required <= 10 or not 1 <= reward <= 100000:
            raise ValueError("需求标题、内容、人数或奖励不合法")
        committed = self.conn.execute(
            "select count(*) from commission_orders_v2 where demand_id=? and status in ('accepted','submitted','cancel_requested','completed')",
            (int(demand_id),),
        ).fetchone()[0]
        if required < int(committed):
            raise ValueError(f"需求人数不能小于已有订单数{int(committed)}")
        old_open = max(0, int(demand["required_people"]) - int(committed))
        new_open = max(0, required - int(committed))
        old_open_reward = old_open * int(demand["reward_per_person"])
        new_open_reward = new_open * reward
        percent = int(demand["fee_percent"])
        delta = (new_open_reward + math.floor(new_open_reward * percent / 100)) - (old_open_reward + math.floor(old_open_reward * percent / 100))
        publisher = dict(self.conn.execute("select * from users where id=?", (int(demand["publisher_user_pk"]),)).fetchone())
        expiry = str(changes.get("recruitment_expires_at", demand["recruitment_expires_at"]) or "").strip()
        if expiry:
            try:
                datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S")
            except ValueError as exc:
                raise ValueError("招募截止时间格式必须是 YYYY-MM-DD HH:MM:SS") from exc
        requested_status = str(changes.get("status", demand["status"]))
        if requested_status not in {"recruiting", "filled", "completed", "closed"}:
            raise ValueError("需求状态不合法")
        if requested_status == "completed" and int(committed) < required:
            raise ValueError("仍有未完成名额，不能直接标记需求完成")
        if str(demand["status"]) in {"closed", "completed"} and requested_status != str(demand["status"]):
            raise ValueError("已结束需求不能通过普通编辑重新开放")
        if requested_status in {"recruiting", "filled"}:
            requested_status = "filled" if int(committed) >= required else "recruiting"
        close_reward = new_open_reward if requested_status == "closed" and str(demand["status"]) != "closed" else 0
        close_fee = math.floor(new_open_reward * percent / 100) if close_reward else 0
        self.conn.execute("begin immediate")
        try:
            if delta:
                self._adjust_points(publisher, -delta, "管理员调整需求未接名额托管")
            if close_reward + close_fee:
                self._adjust_points(publisher, close_reward + close_fee, "管理员关闭需求，退还未接名额托管")
            reward_delta = new_open_reward - old_open_reward
            fee_delta = math.floor(new_open_reward * percent / 100) - math.floor(old_open_reward * percent / 100)
            self.conn.execute(
                """update commission_demands set title=?,content=?,required_people=?,reward_per_person=?,
                   recruitment_expires_at=?,status=?,reward_escrow_remaining=reward_escrow_remaining+?,
                   fee_escrow_remaining=fee_escrow_remaining+?,closed_at=case when ?='closed' then ? else closed_at end,
                   close_reason=case when ?='closed' then '管理员关闭' else close_reason end,updated_at=? where id=?""",
                (title, content, required, reward, expiry, requested_status,
                 reward_delta - close_reward, fee_delta - close_fee, requested_status, self.db.now(), requested_status,
                 self.db.now(), int(demand_id)),
            )
            self._audit("demand", demand_id, "update", admin_identity, reason, f"余额净调整:{-delta + close_reward + close_fee}")
            self.conn.commit()
            return self.get_demand(demand_id) or {}
        except Exception:
            self.conn.rollback()
            raise

    def admin_update_service(self, service_id: int, changes: dict[str, Any], admin_identity: str) -> dict[str, Any]:
        service = self.get_service(service_id)
        if not service:
            raise ValueError("没有找到服务")
        reason = str(changes.get("reason") or "").strip()
        title = str(changes.get("title", service["title"]) or "").strip()
        description = str(changes.get("description", service["description"]) or "").strip()
        price = int(changes.get("unit_price", service["unit_price"]))
        stock_mode = str(changes.get("stock_mode", service["stock_mode"]))
        status = str(changes.get("status", service["status"]))
        if not title or not description or not 1 <= price <= 100000 or stock_mode not in {"limited", "unlimited"}:
            raise ValueError("服务名称、内容、价格或库存模式不合法")
        if status not in {"on_sale", "sold_out", "expired", "off_shelf"}:
            raise ValueError("服务状态不合法")
        stock_total = None if stock_mode == "unlimited" else int(changes.get("stock_total", service["stock_total"] or 1))
        stock_remaining = None if stock_mode == "unlimited" else int(changes.get("stock_remaining", service["stock_remaining"] or 0))
        if stock_mode == "limited" and (not 0 <= stock_remaining <= stock_total <= 999):
            raise ValueError("有限库存必须满足0≤剩余库存≤总库存≤999")
        expiry = str(changes.get("listing_expires_at", service["listing_expires_at"]) or "").strip()
        try:
            datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError("上架截止时间格式必须是 YYYY-MM-DD HH:MM:SS") from exc
        if stock_mode == "limited" and stock_remaining == 0 and status == "on_sale":
            status = "sold_out"
        self.conn.execute("begin immediate")
        try:
            self.conn.execute(
                """update commission_services set title=?,description=?,unit_label=?,unit_price=?,stock_mode=?,
                   stock_total=?,stock_remaining=?,listing_expires_at=?,commission_percent=?,status=?,updated_at=? where id=?""",
                (title, description, str(changes.get("unit_label", service["unit_label"]) or "次")[:8], price, stock_mode,
                 stock_total, stock_remaining, expiry,
                 max(0, min(100, int(changes.get("commission_percent", service["commission_percent"])))), status, self.db.now(), int(service_id)),
            )
            self._audit("service", service_id, "update", admin_identity, reason)
            self.conn.commit()
            return self.get_service(service_id) or {}
        except Exception:
            self.conn.rollback()
            raise

    def admin_order_action(self, order_id: int, action: str, admin_identity: str, reason: str) -> dict[str, Any]:
        order = self.get_order(order_id)
        if not order:
            raise ValueError("没有找到订单")
        action = str(action or "").strip()
        now = self.db.now()
        self.conn.execute("begin immediate")
        try:
            if action == "mark_submitted" and order["status"] == "accepted":
                self.conn.execute("update commission_orders_v2 set status='submitted',submitted_at=?,updated_at=? where id=?", (now, now, int(order_id)))
            elif action == "reopen" and order["status"] in {"submitted", "cancel_requested"}:
                self.conn.execute("update commission_orders_v2 set status='accepted',cancel_requester_user_pk=null,cancel_requested_at=null,updated_at=? where id=?", (now, int(order_id)))
            elif action == "settle" and order["status"] in {"accepted", "submitted", "cancel_requested"}:
                provider = dict(self.conn.execute("select * from users where id=?", (int(order["provider_user_pk"]),)).fetchone())
                self._adjust_points(provider, int(order["provider_net_amount"]), "管理员确认委托订单完成")
                self.conn.execute("update commission_orders_v2 set status='completed',completed_at=?,updated_at=? where id=?", (now, now, int(order_id)))
                if order["order_kind"] == "demand":
                    demand = self.get_demand(int(order["demand_id"]))
                    fee = math.floor(int(order["gross_amount"]) * int(demand["fee_percent"]) / 100)
                    self.conn.execute("update commission_demands set completed_count=completed_count+1,reward_escrow_remaining=max(0,reward_escrow_remaining-?),fee_escrow_remaining=max(0,fee_escrow_remaining-?),updated_at=? where id=?", (int(order["gross_amount"]), fee, now, int(order["demand_id"])))
                    counts = self.conn.execute("select completed_count,required_people,status from commission_demands where id=?", (int(order["demand_id"]),)).fetchone()
                    if counts and int(counts["completed_count"]) >= int(counts["required_people"]) and str(counts["status"]) != "closed":
                        self.conn.execute("update commission_demands set status='completed',closed_at=?,updated_at=? where id=?", (now, now, int(order["demand_id"])))
            elif action == "refund" and order["status"] in {"accepted", "submitted", "cancel_requested"}:
                client = dict(self.conn.execute("select * from users where id=?", (int(order["client_user_pk"]),)).fetchone())
                if order["order_kind"] == "service":
                    self._adjust_points(client, int(order["escrow_amount"]), "管理员取消服务订单退款")
                    service = self.get_service(int(order["service_id"]))
                    if service and service["stock_mode"] == "limited":
                        self.conn.execute("update commission_services set stock_remaining=stock_remaining+?,sold_quantity=max(0,sold_quantity-?),status=case when status='sold_out' then 'on_sale' else status end,updated_at=? where id=?", (int(order["quantity"]), int(order["quantity"]), now, int(order["service_id"])))
                else:
                    self.conn.execute("update commission_demands set accepted_count=max(0,accepted_count-1),status=case when status='filled' then 'recruiting' else status end,updated_at=? where id=?", (now, int(order["demand_id"])))
                self.conn.execute("update commission_orders_v2 set status='cancelled',cancelled_at=?,updated_at=? where id=?", (now, now, int(order_id)))
            else:
                raise ValueError("当前订单状态不支持该管理员操作")
            self._audit("order", order_id, action, admin_identity, reason)
            self.conn.commit()
            return self.get_order(order_id) or {}
        except Exception:
            self.conn.rollback()
            raise

    def record_prompt_revision(self, prompt_key: str, prompt_value: str, operator: str = "local-manager") -> int:
        """在配置覆盖前保存旧提示词，避免刷新或误保存造成不可恢复的丢失。"""
        import hashlib

        value = str(prompt_value or "")
        if not value.strip():
            return 0
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        last = self.conn.execute(
            "select id,value_sha256 from commission_prompt_revisions_v2 where prompt_key=? order by id desc limit 1",
            (str(prompt_key),),
        ).fetchone()
        if last and str(last["value_sha256"]) == digest:
            return int(last["id"])
        cursor = self.conn.execute(
            "insert into commission_prompt_revisions_v2(prompt_key,prompt_value,value_sha256,operator,created_at) values(?,?,?,?,?)",
            (str(prompt_key), value, digest, str(operator or "local-manager"), self.db.now()),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def list_prompt_revisions(self, limit: int = 40) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "select id,prompt_key,value_sha256,operator,created_at,length(prompt_value) as value_length "
            "from commission_prompt_revisions_v2 order by id desc limit ?",
            (max(1, min(200, int(limit))),),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_prompt_revision(self, revision_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "select * from commission_prompt_revisions_v2 where id=?",
            (int(revision_id),),
        ).fetchone()
        return dict(row) if row else None
