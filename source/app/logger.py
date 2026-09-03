from __future__ import annotations

import logging
from pathlib import Path


class BotLogger:
    def __init__(self, log_dir: Path, db):
        self.db = db
        log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("dzmm-web-bot")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.FileHandler(log_dir / "bot.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            self.logger.addHandler(handler)

    def info(self, message: str, kind: str = "normal") -> None:
        self.logger.info(message)
        self.db.add_log("INFO", kind, message)

    def warning(self, message: str, kind: str = "normal") -> None:
        self.logger.warning(message)
        self.db.add_log("WARNING", kind, message)

    def error(self, message: str, kind: str = "error") -> None:
        self.logger.error(message)
        self.db.add_log("ERROR", kind, message)
