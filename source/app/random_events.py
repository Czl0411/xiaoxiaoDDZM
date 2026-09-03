from __future__ import annotations

import json
import random
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any


class RandomEventCore:
    def __init__(self, db):
        self.db = db

    @property
    def conn(self):
        return self.db.conn

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """
            create table if not exists random_event_templates (
              id integer primary key autoincrement,
              event_number text not null unique,
              title text not null,
              content text not null,
              role_count integer not null,
              roles_json text not null,
              enabled integer not null default 1,
              creator_user_id text not null default '',
              creator_nickname text not null default '',
              created_at text not null,
              updated_at text not null,
              start_count integer not null default 0,
              last_started_at text,
              archived_at text,
              admin_note text not null default ''
            );
            create index if not exists idx_random_event_templates_enabled
              on random_event_templates(enabled, archived_at, last_started_at);
            create table if not exists random_event_drafts (
              id integer primary key autoincrement,
              admin_user_id text not null,
              admin_nickname text not null,
              group_id text not null,
              original_text text not null,
              parsed_json text not null,
              status text not null default 'pending',
              created_at text not null,
              expires_at text not null,
              confirmed_at text
            );
            create unique index if not exists idx_random_event_draft_pending
              on random_event_drafts(admin_user_id, group_id) where status='pending';
            create table if not exists random_event_sessions (
              id integer primary key autoincrement,
              session_id text not null unique,
              event_id integer not null,
              group_id text not null,
              status text not null default 'recruiting',
              required_count integer not null,
              current_count integer not null default 0,
              started_by_user_id text not null default '',
              started_by_nickname text not null default '',
              start_source text not null default 'manual',
              created_at text not null,
              expires_at text not null,
              started_at text,
              ended_at text,
              end_reason text not null default '',
              end_message_id text not null default '',
              rp_session_id text unique,
              reward_amount integer,
              rewarded_at text,
              rewarded_by_user_id text not null default '',
              reward_message_id text not null default '',
              expiry_notified integer not null default 0,
              start_message_id text not null unique,
              foreign key(event_id) references random_event_templates(id)
            );
            create unique index if not exists idx_random_event_open_group
              on random_event_sessions(group_id) where status in ('recruiting','active');
            create table if not exists random_event_participants (
              id integer primary key autoincrement,
              session_id text not null,
              user_pk integer not null,
              user_id text not null,
              nickname_snapshot text not null,
              role_number integer not null,
              role_name text not null,
              role_gender text not null,
              role_description text not null default '',
              joined_at text not null,
              join_message_id text not null unique,
              left_at text,
              leave_message_id text not null default '',
              unique(session_id, user_id),
              unique(session_id, role_number),
              foreign key(session_id) references random_event_sessions(session_id),
              foreign key(user_pk) references users(id)
            );
            create table if not exists random_event_schedule_runs (
              id integer primary key autoincrement,
              run_key text not null unique,
              group_id text not null,
              scheduled_date text not null,
              scheduled_time text not null,
              status text not null,
              detail text not null default '',
              session_id text not null default '',
              created_at text not null,
              updated_at text not null
            );
            """
        )
        self.conn.commit()

    @staticmethod
    def _roles(row: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            value = json.loads(str(row.get("roles_json") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            value = []
        return value if isinstance(value, list) else []

    def _template_dict(self, row) -> dict[str, Any]:
        result = dict(row)
        result["roles"] = self._roles(result)
        result["enabled"] = bool(result.get("enabled"))
        return result

    @staticmethod
    def _identity(message: dict[str, Any], user: dict[str, Any]) -> tuple[str, str]:
        user_id = str(user.get("platform_user_id") or user.get("user_id") or message.get("platform_user_id") or message.get("user_id") or "")
        nickname = str(user.get("display_name") or user.get("nickname") or message.get("sender") or "未知用户")
        return user_id, nickname

    def get_template(self, template_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("select * from random_event_templates where id=?", (int(template_id),)).fetchone()
        return self._template_dict(row) if row else None

    def list_templates(self, include_archived: bool = False) -> list[dict[str, Any]]:
        where = "" if include_archived else "where archived_at is null"
        rows = self.conn.execute(
            f"select * from random_event_templates {where} order by id desc"
        ).fetchall()
        return [self._template_dict(row) for row in rows]

    def _next_event_number(self) -> str:
        value = int(self.conn.execute("select coalesce(max(id),0)+1 from random_event_templates").fetchone()[0])
        return f"RE{value:04d}"

    @staticmethod
    def validate_template(data: dict[str, Any]) -> dict[str, Any]:
        title = re.sub(r"\s+", " ", str(data.get("title") or "")).strip()
        content = re.sub(r"[ \t]+", " ", str(data.get("content") or "")).strip()
        roles = data.get("roles")
        if not 2 <= len(title) <= 30:
            raise ValueError("事件标题必须为2至30个字符")
        if not 1 <= len(content) <= 1000:
            raise ValueError("事件剧情必须为1至1000个字符")
        if not isinstance(roles, list) or not 2 <= len(roles) <= 10:
            raise ValueError("随机事件必须有2至10个角色")
        cleaned: list[dict[str, Any]] = []
        for number, role in enumerate(roles, 1):
            if not isinstance(role, dict):
                raise ValueError(f"第{number}个角色资料不正确")
            name = re.sub(r"\s+", " ", str(role.get("name") or "")).strip()
            gender = str(role.get("gender") or "不限").strip()
            description = re.sub(r"\s+", " ", str(role.get("description") or "")).strip()
            if not 1 <= len(name) <= 20 or gender not in {"男", "女", "不限"} or not 1 <= len(description) <= 120:
                raise ValueError(f"第{number}个角色需要正确填写名称、性别和说明")
            cleaned.append({"number": number, "name": name, "gender": gender, "description": description})
        return {"title": title, "content": content, "roles": cleaned, "role_count": len(cleaned)}

    def save_template(self, data: dict[str, Any], *, template_id: int | None = None, creator: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = self.validate_template(data)
        now = self.db.now()
        enabled = 1 if bool(data.get("enabled", True)) else 0
        note = str(data.get("admin_note") or "")[:500]
        if template_id:
            changed = self.conn.execute(
                """update random_event_templates set title=?,content=?,role_count=?,roles_json=?,enabled=?,
                   admin_note=?,updated_at=? where id=?""",
                (parsed["title"], parsed["content"], parsed["role_count"], json.dumps(parsed["roles"], ensure_ascii=False), enabled, note, now, int(template_id)),
            ).rowcount
            if not changed:
                raise ValueError("没有找到随机事件")
            self.conn.commit()
            return self.get_template(int(template_id)) or {}
        creator = creator or {}
        user_id = str(creator.get("platform_user_id") or creator.get("user_id") or "")
        nickname = str(creator.get("display_name") or creator.get("nickname") or "后台管理员")
        cur = self.conn.execute(
            """insert into random_event_templates(event_number,title,content,role_count,roles_json,enabled,
               creator_user_id,creator_nickname,created_at,updated_at,admin_note) values(?,?,?,?,?,?,?,?,?,?,?)""",
            (self._next_event_number(), parsed["title"], parsed["content"], parsed["role_count"], json.dumps(parsed["roles"], ensure_ascii=False), enabled, user_id, nickname, now, now, note),
        )
        self.conn.commit()
        return self.get_template(int(cur.lastrowid)) or {}

    def archive_template(self, template_id: int) -> bool:
        changed = self.conn.execute(
            "update random_event_templates set enabled=0,archived_at=?,updated_at=? where id=? and archived_at is null",
            (self.db.now(), self.db.now(), int(template_id)),
        ).rowcount
        self.conn.commit()
        return bool(changed)

    def cancel_draft(self, message: dict[str, Any]) -> bool:
        user = self.db.ensure_user(message)
        user_id, _ = self._identity(message, user)
        changed = self.conn.execute(
            "update random_event_drafts set status='cancelled' where admin_user_id=? and group_id=? and status='pending'",
            (user_id, self.db._message_group_id(message)),
        ).rowcount
        self.conn.commit()
        return bool(changed)

    def save_draft(self, message: dict[str, Any], original: str, parsed: dict[str, Any], ttl_seconds: int) -> dict[str, Any]:
        user = self.db.ensure_user(message)
        user_id, nickname = self._identity(message, user)
        group_id = self.db._message_group_id(message)
        now = self.db.now()
        expires = (datetime.now() + timedelta(seconds=max(60, int(ttl_seconds)))).strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "update random_event_drafts set status='cancelled' where admin_user_id=? and group_id=? and status='pending'",
            (user_id, group_id),
        )
        cur = self.conn.execute(
            """insert into random_event_drafts(admin_user_id,admin_nickname,group_id,original_text,parsed_json,status,created_at,expires_at)
               values(?,?,?,?,?,'pending',?,?)""",
            (user_id, nickname, group_id, original, json.dumps(parsed, ensure_ascii=False), now, expires),
        )
        self.conn.commit()
        row = self.conn.execute("select * from random_event_drafts where id=?", (int(cur.lastrowid),)).fetchone()
        return dict(row)

    def get_pending_draft(self, message: dict[str, Any]) -> dict[str, Any] | None:
        user = self.db.ensure_user(message)
        user_id, _ = self._identity(message, user)
        row = self.conn.execute(
            """select * from random_event_drafts where admin_user_id=? and group_id=? and status='pending'
               order by id desc limit 1""",
            (user_id, self.db._message_group_id(message)),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        if str(result["expires_at"]) <= self.db.now():
            self.conn.execute("update random_event_drafts set status='expired' where id=?", (int(result["id"]),))
            self.conn.commit()
            return None
        result["parsed"] = json.loads(result["parsed_json"])
        return result

    def confirm_draft(self, message: dict[str, Any]) -> dict[str, Any] | None:
        draft = self.get_pending_draft(message)
        if not draft:
            return None
        user = self.db.ensure_user(message)
        template = self.save_template(draft["parsed"], creator=user)
        self.conn.execute(
            "update random_event_drafts set status='confirmed',confirmed_at=? where id=? and status='pending'",
            (self.db.now(), int(draft["id"])),
        )
        self.conn.commit()
        return template

    def get_current_session(self, group_id: str, statuses: tuple[str, ...] = ("recruiting", "active")) -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in statuses)
        row = self.conn.execute(
            f"select * from random_event_sessions where group_id=? and status in ({placeholders}) order by id desc limit 1",
            (str(group_id), *statuses),
        ).fetchone()
        return self.get_session(int(row["id"])) if row else None

    def get_session(self, session_id: int | str) -> dict[str, Any] | None:
        if isinstance(session_id, int):
            row = self.conn.execute("select * from random_event_sessions where id=?", (session_id,)).fetchone()
        else:
            row = self.conn.execute("select * from random_event_sessions where session_id=?", (str(session_id),)).fetchone()
        if not row:
            return None
        result = dict(row)
        template = self.get_template(int(result["event_id"]))
        result["event"] = template or {}
        result["participants"] = [dict(item) for item in self.conn.execute(
            "select * from random_event_participants where session_id=? order by role_number", (result["session_id"],)
        ).fetchall()]
        return result

    def _choose_template(self) -> dict[str, Any] | None:
        rows = self.conn.execute(
            """select * from random_event_templates where enabled=1 and archived_at is null
               order by case when last_started_at is null then 0 else 1 end,last_started_at,id"""
        ).fetchall()
        if not rows:
            return None
        oldest = str(rows[0]["last_started_at"] or "")
        candidates = [row for row in rows if str(row["last_started_at"] or "") == oldest]
        return self._template_dict(random.choice(candidates))

    def launch(self, *, group_id: str, starter: dict[str, Any] | None, ttl_seconds: int, source: str, start_message_id: str) -> dict[str, Any]:
        group_id = str(group_id or "main")
        template = self._choose_template()
        if not template:
            return {"ok": False, "reason": "empty"}
        starter = starter or {}
        starter_id = str(starter.get("platform_user_id") or starter.get("user_id") or "system")
        starter_name = str(starter.get("display_name") or starter.get("nickname") or starter.get("sender") or "系统定时任务")
        now = self.db.now()
        expires = (datetime.now() + timedelta(seconds=max(60, int(ttl_seconds)))).strftime("%Y-%m-%d %H:%M:%S")
        session_uuid = str(uuid.uuid4())
        try:
            self.conn.execute("begin immediate")
            if self.conn.execute("select 1 from random_event_sessions where group_id=? and status in ('recruiting','active')", (group_id,)).fetchone():
                self.conn.rollback()
                return {"ok": False, "reason": "event_busy"}
            if self.conn.execute("select 1 from rp_sessions where group_id=? and status in ('gathering','active')", (group_id,)).fetchone():
                self.conn.rollback()
                return {"ok": False, "reason": "rp_busy"}
            cur = self.conn.execute(
                """insert into random_event_sessions(session_id,event_id,group_id,status,required_count,current_count,
                   started_by_user_id,started_by_nickname,start_source,created_at,expires_at,start_message_id)
                   values(?,?,?,'recruiting',?,0,?,?,?,?,?,?)""",
                (session_uuid, int(template["id"]), group_id, int(template["role_count"]), starter_id, starter_name, source, now, expires, str(start_message_id)),
            )
            self.conn.execute(
                "update random_event_templates set start_count=start_count+1,last_started_at=?,updated_at=? where id=?",
                (now, now, int(template["id"])),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return {"ok": False, "reason": "duplicate"}
        return {"ok": True, "session": self.get_session(int(cur.lastrowid))}

    def cancel_failed_launch(self, session_id: str) -> None:
        row = self.conn.execute(
            "select event_id from random_event_sessions where session_id=? and status='recruiting'", (str(session_id),)
        ).fetchone()
        if not row:
            return
        self.conn.execute("begin immediate")
        self.conn.execute(
            "update random_event_sessions set status='cancelled',ended_at=?,end_reason='announcement_failed' where session_id=? and status='recruiting'",
            (self.db.now(), str(session_id)),
        )
        self.conn.execute(
            "update random_event_templates set start_count=max(0,start_count-1),updated_at=? where id=?",
            (self.db.now(), int(row["event_id"])),
        )
        self.conn.commit()

    def join(self, message: dict[str, Any], role_number: int | None = None) -> dict[str, Any]:
        user = self.db.ensure_user(message)
        self.db._assert_not_identity_conflict(user)
        user_id, nickname = self._identity(message, user)
        group_id = self.db._message_group_id(message)
        now = self.db.now()
        message_id = str(message.get("message_id") or f"random-join:{uuid.uuid4()}")
        try:
            self.conn.execute("begin immediate")
            row = self.conn.execute(
                "select * from random_event_sessions where group_id=? and status='recruiting' order by id desc limit 1", (group_id,)
            ).fetchone()
            if not row:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            session = dict(row)
            if str(session["expires_at"]) <= now:
                self.conn.execute("update random_event_sessions set status='expired',ended_at=?,end_reason='timeout' where id=?", (now, int(session["id"])))
                self.conn.commit()
                return {"ok": False, "reason": "expired"}
            old = self.conn.execute(
                "select * from random_event_participants where session_id=? and user_id=?", (session["session_id"], user_id)
            ).fetchone()
            if old and old["left_at"] is None:
                self.conn.rollback()
                return {"ok": False, "reason": "duplicate", "participant": dict(old)}
            template_row = self.conn.execute("select * from random_event_templates where id=?", (int(session["event_id"]),)).fetchone()
            roles = self._roles(dict(template_row))
            occupied = {int(item[0]) for item in self.conn.execute(
                "select role_number from random_event_participants where session_id=? and left_at is null", (session["session_id"],)
            ).fetchall()}
            if role_number is None:
                role_number = next((int(role["number"]) for role in roles if int(role["number"]) not in occupied), None)
            if role_number is None or not 1 <= int(role_number) <= len(roles):
                self.conn.rollback()
                return {"ok": False, "reason": "invalid_role"}
            if int(role_number) in occupied:
                self.conn.rollback()
                return {"ok": False, "reason": "role_taken"}
            role = roles[int(role_number) - 1]
            if old:
                self.conn.execute(
                    """update random_event_participants set nickname_snapshot=?,role_number=?,role_name=?,role_gender=?,
                       role_description=?,joined_at=?,join_message_id=?,left_at=null,leave_message_id='' where id=?""",
                    (nickname, int(role_number), role["name"], role["gender"], role["description"], now, message_id, int(old["id"])),
                )
            else:
                self.conn.execute(
                    """insert into random_event_participants(session_id,user_pk,user_id,nickname_snapshot,role_number,
                       role_name,role_gender,role_description,joined_at,join_message_id) values(?,?,?,?,?,?,?,?,?,?)""",
                    (session["session_id"], int(user["id"]), user_id, nickname, int(role_number), role["name"], role["gender"], role["description"], now, message_id),
                )
            count = int(self.conn.execute(
                "select count(*) from random_event_participants where session_id=? and left_at is null", (session["session_id"],)
            ).fetchone()[0])
            opened = count >= int(session["required_count"])
            rp_session_id = None
            if opened:
                if self.conn.execute("select 1 from rp_sessions where group_id=? and status in ('gathering','active')", (group_id,)).fetchone():
                    self.conn.rollback()
                    return {"ok": False, "reason": "rp_busy"}
                rp_session_id = str(uuid.uuid4())
                participants = self.conn.execute(
                    "select * from random_event_participants where session_id=? and left_at is null order by role_number", (session["session_id"],)
                ).fetchall()
                first = participants[0]
                self.conn.execute(
                    """insert into rp_sessions(session_id,group_id,status,target_count,current_count,initiator_user_id,
                       initiator_nickname,created_at,expires_at,started_at,last_action_at,start_message_id)
                       values(?,?,'active',?,?,?,?,?,?,?,?,?)""",
                    (rp_session_id, group_id, count, count, first["user_id"], first["nickname_snapshot"], now, session["expires_at"], now, now, f"random-event:{session['session_id']}"),
                )
                for participant in participants:
                    self.conn.execute(
                        "insert into rp_participants(session_id,user_id,nickname_snapshot,joined_at,join_message_id) values(?,?,?,?,?)",
                        (rp_session_id, participant["user_id"], participant["nickname_snapshot"], participant["joined_at"], f"random-event:{session['session_id']}:{participant['role_number']}"),
                    )
                self.conn.execute(
                    "update random_event_sessions set current_count=?,status='active',started_at=?,rp_session_id=? where id=? and status='recruiting'",
                    (count, now, rp_session_id, int(session["id"])),
                )
            else:
                self.conn.execute("update random_event_sessions set current_count=? where id=?", (count, int(session["id"])))
            self.conn.commit()
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return {"ok": False, "reason": "duplicate"}
        return {"ok": True, "opened": opened, "session": self.get_session(int(session["id"])), "role": role}

    def leave(self, message: dict[str, Any]) -> dict[str, Any]:
        user = self.db.ensure_user(message)
        user_id, _ = self._identity(message, user)
        group_id = self.db._message_group_id(message)
        now = self.db.now()
        message_id = str(message.get("message_id") or "")
        self.conn.execute("begin immediate")
        row = self.conn.execute(
            "select * from random_event_sessions where group_id=? and status in ('recruiting','active') order by id desc limit 1", (group_id,)
        ).fetchone()
        if not row:
            self.conn.rollback()
            return {"ok": False, "reason": "not_found"}
        session = dict(row)
        participant = self.conn.execute(
            "select * from random_event_participants where session_id=? and user_id=? and left_at is null", (session["session_id"], user_id)
        ).fetchone()
        if not participant:
            self.conn.rollback()
            return {"ok": False, "reason": "not_participant"}
        self.conn.execute(
            "update random_event_participants set left_at=?,leave_message_id=? where id=? and left_at is null",
            (now, message_id, int(participant["id"])),
        )
        count = int(self.conn.execute(
            "select count(*) from random_event_participants where session_id=? and left_at is null", (session["session_id"],)
        ).fetchone()[0])
        status = str(session["status"])
        if session.get("rp_session_id"):
            self.conn.execute(
                "update rp_participants set left_at=?,leave_message_id=?,leave_count=leave_count+1 where session_id=? and user_id=? and left_at is null",
                (now, message_id, session["rp_session_id"], user_id),
            )
            self.conn.execute("update rp_sessions set current_count=?,last_action_at=? where session_id=?", (count, now, session["rp_session_id"]))
        if count == 0:
            status = "cancelled" if status == "recruiting" else "ended"
            self.conn.execute(
                "update random_event_sessions set current_count=0,status=?,ended_at=?,end_reason='all_left' where id=?",
                (status, now, int(session["id"])),
            )
            if session.get("rp_session_id"):
                self.conn.execute("update rp_sessions set status='ended',ended_at=?,last_action_at=? where session_id=? and status='active'", (now, now, session["rp_session_id"]))
        else:
            self.conn.execute("update random_event_sessions set current_count=? where id=?", (count, int(session["id"])))
        self.conn.commit()
        return {"ok": True, "closed": count == 0, "current_count": count, "role_number": int(participant["role_number"]), "session": self.get_session(int(session["id"]))}

    def end(self, message: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        group_id = self.db._message_group_id(message)
        session = self.get_current_session(group_id)
        if not session:
            return {"ok": False, "reason": "not_found"}
        user = self.db.get_user(message)
        user_id = str((user or {}).get("platform_user_id") or (user or {}).get("user_id") or message.get("platform_user_id") or message.get("user_id") or "")
        is_participant = any(str(item["user_id"]) == user_id and not item.get("left_at") for item in session["participants"])
        is_admin = bool(force or self.db.is_admin_user(message))
        if session["status"] == "active" and not (is_participant or is_admin):
            return {"ok": False, "reason": "forbidden"}
        if session["status"] == "recruiting" and not is_admin:
            return {"ok": False, "reason": "forbidden"}
        now = self.db.now()
        end_status = "cancelled" if session["status"] == "recruiting" else "ended"
        self.conn.execute("begin immediate")
        changed = self.conn.execute(
            """update random_event_sessions set status=?,ended_at=?,end_reason=?,end_message_id=?
               where id=? and status in ('recruiting','active')""",
            (end_status, now, "admin_cancel" if end_status == "cancelled" else "completed", str(message.get("message_id") or ""), int(session["id"])),
        ).rowcount
        if session.get("rp_session_id"):
            self.conn.execute(
                "update rp_sessions set status='ended',ended_at=?,last_action_at=?,version=version+1 where session_id=? and status='active'",
                (now, now, session["rp_session_id"]),
            )
        self.conn.commit()
        return {"ok": bool(changed), "status": end_status, "session": self.get_session(int(session["id"]))}

    def reward_latest(self, message: dict[str, Any], amount: int) -> dict[str, Any]:
        amount = int(amount)
        if not 1 <= amount <= 100000:
            return {"ok": False, "reason": "amount"}
        group_id = self.db._message_group_id(message)
        admin = self.db.ensure_user(message)
        admin_id, _ = self._identity(message, admin)
        now = self.db.now()
        self.conn.execute("begin immediate")
        row = self.conn.execute(
            """select * from random_event_sessions where group_id=? and status='ended'
               order by ended_at desc,id desc limit 1""", (group_id,)
        ).fetchone()
        if not row:
            self.conn.rollback()
            return {"ok": False, "reason": "not_found"}
        session = dict(row)
        if session.get("rewarded_at"):
            self.conn.rollback()
            return {"ok": False, "reason": "duplicate"}
        participants = self.conn.execute(
            """select p.*,u.points from random_event_participants p join users u on u.id=p.user_pk
               where p.session_id=? and p.left_at is null order by p.role_number""", (session["session_id"],)
        ).fetchall()
        if not participants:
            self.conn.rollback()
            return {"ok": False, "reason": "no_participants"}
        balances: list[dict[str, Any]] = []
        for participant in participants:
            balance = int(participant["points"] or 0) + amount
            self.conn.execute("update users set points=?,last_seen_at=? where id=?", (balance, now, int(participant["user_pk"])))
            self.conn.execute(
                "insert into transactions(user_id,nickname,change_amount,reason,balance_after,created_at) values(?,?,?,?,?,?)",
                (participant["user_id"], participant["nickname_snapshot"], amount, f"随机事件 {session['session_id']} 完成奖励", balance, now),
            )
            balances.append({"nickname": participant["nickname_snapshot"], "balance": balance, "role_number": participant["role_number"]})
        changed = self.conn.execute(
            """update random_event_sessions set reward_amount=?,rewarded_at=?,rewarded_by_user_id=?,reward_message_id=?
               where id=? and rewarded_at is null""",
            (amount, now, admin_id, str(message.get("message_id") or ""), int(session["id"])),
        ).rowcount
        if not changed:
            self.conn.rollback()
            return {"ok": False, "reason": "duplicate"}
        self.conn.commit()
        return {"ok": True, "amount": amount, "participants": balances, "session": self.get_session(int(session["id"]))}

    def expire_recruiting(self) -> list[dict[str, Any]]:
        now = self.db.now()
        rows = self.conn.execute(
            "select id from random_event_sessions where status='recruiting' and expires_at<=? and expiry_notified=0", (now,)
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            self.conn.execute(
                """update random_event_sessions set status='expired',ended_at=?,end_reason='timeout',expiry_notified=1
                   where id=? and status='recruiting'""", (now, int(row["id"])),
            )
            item = self.get_session(int(row["id"]))
            if item:
                results.append(item)
        self.conn.commit()
        return results

    @staticmethod
    def schedule_times(features: dict[str, Any]) -> list[str]:
        raw = str(features.get("random_event_auto_times") or "20:00")
        values: list[str] = []
        for item in re.split(r"[,，\s]+", raw):
            if not item:
                continue
            match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", item)
            if match:
                values.append(f"{int(match.group(1)):02d}:{match.group(2)}")
        count = max(1, min(int(features.get("random_event_auto_daily_count", len(values) or 1) or 1), 12))
        return sorted(dict.fromkeys(values))[:count]

    def claim_due_schedule_runs(self, features: dict[str, Any], group_id: str = "main") -> list[dict[str, str]]:
        if not bool(features.get("random_event_enabled", True)) or not bool(features.get("random_event_auto_enabled", False)):
            return []
        now = datetime.now()
        current = now.strftime("%H:%M")
        date_key = now.strftime("%Y-%m-%d")
        due: list[dict[str, str]] = []
        for slot in self.schedule_times(features):
            if slot != current:
                continue
            run_key = f"{group_id}:{date_key}:{slot}"
            try:
                self.conn.execute(
                    """insert into random_event_schedule_runs(run_key,group_id,scheduled_date,scheduled_time,status,created_at,updated_at)
                       values(?,?,?,?, 'claimed',?,?)""", (run_key, group_id, date_key, slot, self.db.now(), self.db.now()),
                )
                self.conn.commit()
                due.append({"run_key": run_key, "group_id": group_id, "slot": slot})
            except sqlite3.IntegrityError:
                self.conn.rollback()
        return due

    def finish_schedule_run(self, run_key: str, *, status: str, detail: str = "", session_id: str = "") -> None:
        self.conn.execute(
            "update random_event_schedule_runs set status=?,detail=?,session_id=?,updated_at=? where run_key=?",
            (str(status), str(detail)[:500], str(session_id), self.db.now(), str(run_key)),
        )
        self.conn.commit()

    def list_admin(self) -> dict[str, Any]:
        current = [self.get_session(int(row["id"])) for row in self.conn.execute(
            "select id from random_event_sessions where status in ('recruiting','active') order by id desc"
        ).fetchall()]
        history = [self.get_session(int(row["id"])) for row in self.conn.execute(
            "select id from random_event_sessions where status not in ('recruiting','active') order by id desc limit 100"
        ).fetchall()]
        runs = [dict(row) for row in self.conn.execute(
            "select * from random_event_schedule_runs order by id desc limit 50"
        ).fetchall()]
        drafts = [dict(row) for row in self.conn.execute(
            "select * from random_event_drafts where status='pending' order by id desc limit 50"
        ).fetchall()]
        return {"templates": self.list_templates(True), "current": [x for x in current if x], "history": [x for x in history if x], "schedule_runs": runs, "drafts": drafts}
