from __future__ import annotations

from datetime import datetime


class SafetyGuard:
    def __init__(self, db):
        self.db = db

    def can_send(self) -> tuple[bool, str]:
        config = self.db.get_config()
        safety = config.get("safety", {})
        if not safety.get("enabled", True):
            return True, "安全限制未启用"
        if self._in_silence_time(safety):
            return False, "当前处于夜间静默时间"
        per_min = int(safety.get("max_replies_per_minute", 10) or 0)
        per_hour = int(safety.get("max_replies_per_hour", 100) or 0)
        if per_min and self.db.count_recent_replies(60) >= per_min:
            return False, "达到每分钟最大发送次数"
        if per_hour and self.db.count_recent_replies(3600) >= per_hour:
            return False, "达到每小时最大发送次数"
        return True, "允许发送"

    def user_allowed(self, sender: str) -> tuple[bool, str]:
        safety = self.db.get_config().get("safety", {})
        blacklist = set(safety.get("blacklist_names") or [])
        whitelist = set(safety.get("whitelist_names") or [])
        if sender in blacklist:
            return False, "该昵称在黑名单中"
        if whitelist and sender not in whitelist:
            return False, "启用了白名单，该昵称不在白名单中"
        return True, "允许用户"

    def _in_silence_time(self, safety: dict) -> bool:
        if not safety.get("night_silence_enabled"):
            return False
        try:
            start = datetime.strptime(safety.get("night_silence_start", "23:00"), "%H:%M").time()
            end = datetime.strptime(safety.get("night_silence_end", "08:00"), "%H:%M").time()
        except ValueError:
            return False
        now = datetime.now().time()
        if start <= end:
            return start <= now <= end
        return now >= start or now <= end
