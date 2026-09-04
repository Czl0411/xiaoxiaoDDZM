from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReferralOutcome:
    group_key: str
    newcomer_name: str
    inviter_name: str
    reward_amount: int
    announcement: str


class ReferralCore:
    def __init__(self, db):
        self.db = db
        self.conn = db.conn

    def ensure_schema(self) -> None:
        columns = {row["name"] for row in self.conn.execute("pragma table_info(users)")}
        if "saintess_affection" not in columns:
            self.conn.execute("alter table users add column saintess_affection integer not null default 0")
        self.conn.executescript(
            """
            create table if not exists referral_invites (
              id integer primary key autoincrement,
              join_message_id text not null unique,
              group_key text not null,
              chatroom_id text not null default '',
              newcomer_name text not null,
              newcomer_user_id text not null default '',
              inviter_name text not null,
              inviter_user_pk integer,
              message_count integer not null default 0,
              status text not null default 'pending',
              failure_reason text not null default '',
              joined_at text not null,
              settled_at text
            );
            create unique index if not exists idx_referral_newcomer
              on referral_invites(group_key,newcomer_user_id)
              where newcomer_user_id!='' and status='rewarded';
            create table if not exists referral_message_counts (
              message_id text primary key,
              referral_id integer not null,
              counted_at text not null
            );
            """
        )
        self.conn.commit()

    def _unique_user(self, name: str):
        normalized = self.db._normalized_nickname(name)
        matches = []
        for row in self.conn.execute("select * from users where platform_user_id!=''"):
            values = [row["nickname"], row["display_name"]]
            values.extend((row["nickname_history"] or "").split(","))
            if any(self.db._normalized_nickname(value) == normalized for value in values):
                matches.append(dict(row))
        return matches[0] if len(matches) == 1 else None, len(matches)

    def record_join(self, message: dict[str, Any]) -> dict[str, Any]:
        inviter, count = self._unique_user(str(message.get("inviter_name") or ""))
        status = "pending" if inviter else "needs_review"
        reason = "" if inviter else ("邀请人昵称不唯一" if count > 1 else "未找到邀请人")
        self.conn.execute(
            """insert or ignore into referral_invites(
                 join_message_id,group_key,chatroom_id,newcomer_name,inviter_name,
                 inviter_user_pk,status,failure_reason,joined_at)
               values(?,?,?,?,?,?,?,?,?)""",
            (
                str(message.get("message_id") or ""),
                str(message.get("group_key") or message.get("source_group") or "main"),
                str(message.get("chatroom_id") or ""),
                str(message.get("newcomer_name") or "").strip(),
                str(message.get("inviter_name") or "").strip(),
                int(inviter["id"]) if inviter else None,
                status,
                reason,
                str(message.get("sent_at") or self.db.now()),
            ),
        )
        self.conn.commit()
        row = self.conn.execute("select * from referral_invites where join_message_id=?", (str(message.get("message_id") or ""),)).fetchone()
        return dict(row)

    def observe_message(self, message: dict[str, Any]) -> ReferralOutcome | None:
        if str(message.get("source_type") or "") == "direct" or message.get("is_self"):
            return None
        newcomer = self.db.ensure_user(message)
        uid = str(newcomer.get("platform_user_id") or "")
        group = str(message.get("group_key") or message.get("source_group") or "main")
        name = str(message.get("sender") or "").strip()
        row = self.conn.execute(
            """select * from referral_invites where group_key=? and status='pending'
               and (newcomer_user_id=? or (newcomer_user_id='' and newcomer_name=?))
               order by id desc limit 1""",
            (group, uid, name),
        ).fetchone()
        if not row:
            return None
        row = dict(row)
        inviter = self.conn.execute("select * from users where id=?", (row["inviter_user_pk"],)).fetchone()
        if not inviter or str(inviter["platform_user_id"]) == uid:
            self.conn.execute("update referral_invites set status='needs_review',failure_reason=? where id=?", ("邀请人无效或自己邀请自己", row["id"]))
            self.conn.commit()
            return None
        try:
            self.conn.execute("begin immediate")
            if not row["newcomer_user_id"]:
                self.conn.execute("update referral_invites set newcomer_user_id=? where id=?", (uid, row["id"]))
            inserted = self.conn.execute(
                "insert or ignore into referral_message_counts(message_id,referral_id,counted_at) values(?,?,?)",
                (str(message.get("message_id") or ""), row["id"], self.db.now()),
            ).rowcount
            if not inserted:
                self.conn.rollback()
                return None
            current = int(row["message_count"] or 0) + 1
            self.conn.execute("update referral_invites set message_count=? where id=?", (current, row["id"]))
            if current < 3:
                self.conn.commit()
                return None
            reward = max(0, min(100000, int(self.db.get_config().get("features", {}).get("referral_reward_amount", 40))))
            balance = int(inviter["points"] or 0) + reward
            self.conn.execute(
                "update users set points=?,saintess_affection=saintess_affection+1 where id=?",
                (balance, inviter["id"]),
            )
            if reward:
                self.conn.execute(
                    "insert into transactions(user_id,nickname,change_amount,reason,balance_after,created_at) values(?,?,?,?,?,?)",
                    (inviter["platform_user_id"], inviter["display_name"] or inviter["nickname"], reward, "传送门拉新奖励", balance, self.db.now()),
                )
            self.conn.execute("update referral_invites set status='rewarded',settled_at=? where id=? and status='pending'", (self.db.now(), row["id"]))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        inviter_name = str(inviter["display_name"] or inviter["nickname"])
        newcomer_name = str(newcomer["display_name"] or newcomer["nickname"])
        announcement = (
            f"迷途的羔羊 {newcomer_name} 顺着 {inviter_name} 的传送门来到了大教堂，并成功进行了祈福。\n"
            f"圣女对 {inviter_name} 好感度 +1，并发放了 {reward}功德 功德奖励。\n"
            "提示：主页挂上传送门，方便接引更多迷途的羔羊进来洗礼，为你提供源源不断的功德。"
        )
        return ReferralOutcome(group, newcomer_name, inviter_name, reward, announcement)

    def list_admin(self) -> dict[str, Any]:
        return {"items": [dict(row) for row in self.conn.execute("select * from referral_invites order by id desc limit 200")]}
