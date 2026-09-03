from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
from typing import Any
import urllib.error
import urllib.request
import uuid

from PIL import Image


ALLOWED_IMAGE_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9"}

DEFAULT_IMAGE_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "default_commands": "/SC",
    "portrait_commands": "/SC竖屏",
    "landscape_commands": "/SC横屏",
    "case_sensitive": False,
    "default_ratio": "3:4",
    "portrait_ratio": "3:4",
    "landscape_ratio": "16:9",
    "api_base": "https://api.qianyi.win/v1",
    "model": "gpt-image-2",
    "api_timeout_seconds": 300,
    "download_timeout_seconds": 300,
    "upload_timeout_seconds": 90,
    "max_file_mb": 25,
    "max_prompt_chars": 2000,
    "cost": 20,
    "per_user_daily_limit": 3,
    "global_daily_limit": 30,
    "cooldown_seconds": 60,
    "max_concurrent": 1,
    "admin_exempt_limits": True,
    "admin_free": False,
    "refund_on_api_failure": True,
    "refund_on_upload_failure": False,
    "refund_on_interrupt": True,
    "history_page_size": 10,
    "history_retention_days": 0,
    "history_save_prompt": True,
    "thumbnail_max_dimension": 360,
    "thumbnail_quality": 82,
    "send_success_reply": True,
    "usage_reply": "🎨 使用方法：/SC 提示词、/SC竖屏 提示词、/SC横屏 提示词",
    "accepted_reply": "🎨 已收到 {user} 的绘图请求，正在生成中……{newline}比例：{ratio}｜消耗：{cost}功德｜余额：{balance}",
    "busy_reply": "🎨 画笔正在忙碌，请等待当前图片完成后再试。",
    "empty_reply": "请在命令后填写图片提示词。{newline}示例：/SC 一只可爱猫猫",
    "too_long_reply": "提示词最多允许 {max_prompt_chars} 个字符，本次内容过长。",
    "cooldown_reply": "绘图冷却中，请等待 {cooldown} 秒后再试。",
    "daily_limit_reply": "你今天的图片生成次数已经用完（{daily_used}/{daily_limit}）。",
    "global_limit_reply": "今天的全群图片生成额度已经用完，请明天再试。",
    "insufficient_reply": "生成图片需要 {cost} 功德，你当前只有 {balance} 功德。",
    "api_key_missing_reply": "图片生成 API 尚未配置，请联系管理员。",
    "group_only_reply": "🎨 图片生成命令仅限绘图群使用。",
    "disabled_reply": "图片生成功能当前已关闭。",
    "success_reply": "✅ {user} 的图片已经生成完成｜{ratio}｜任务 {job_id}",
    "api_failed_reply": "图片生成失败：{error}{refund_text}",
    "upload_failed_reply": "图片已经生成，但发送到群聊失败。管理员可以在后台历史记录中查看、保存或重新发送。{refund_text}",
    "resend_success_reply": "✅ 历史图片 {job_id} 已重新发送到绘图群。",
}


class ImageGenerationError(RuntimeError):
    def __init__(self, message: str, *, error_type: str = "image_error"):
        super().__init__(message)
        self.error_type = error_type


def merged_image_settings(config: dict[str, Any]) -> dict[str, Any]:
    stored = config.get("image_generation", {})
    return {**DEFAULT_IMAGE_SETTINGS, **(stored if isinstance(stored, dict) else {})}


def _command_values(value: Any) -> list[str]:
    values = []
    for item in re.split(r"[,，\n]+", str(value or "")):
        command = item.strip()
        if command and command.startswith("/") and command not in values:
            values.append(command)
    return values


@dataclass
class ParsedImageCommand:
    matched: bool = False
    prompt: str = ""
    ratio: str = ""
    command: str = ""
    error: str = ""


def parse_image_command(text: str, settings: dict[str, Any]) -> ParsedImageCommand:
    source = str(text or "").strip()
    if not source:
        return ParsedImageCommand()
    case_sensitive = bool(settings.get("case_sensitive"))
    candidates: list[tuple[str, str]] = []
    for key, ratio_key in (
        ("portrait_commands", "portrait_ratio"),
        ("landscape_commands", "landscape_ratio"),
        ("default_commands", "default_ratio"),
    ):
        for command in _command_values(settings.get(key)):
            candidates.append((command, str(settings.get(ratio_key) or "3:4")))
    candidates.sort(key=lambda item: len(item[0]), reverse=True)
    comparable = source if case_sensitive else source.casefold()
    for command, ratio in candidates:
        trigger = command if case_sensitive else command.casefold()
        if not comparable.startswith(trigger):
            continue
        remainder = source[len(command):].strip()
        if remainder.startswith((":", "：")):
            remainder = remainder[1:].strip()
        if not remainder:
            return ParsedImageCommand(True, ratio=ratio, command=command, error="empty")
        maximum = max(1, int(settings.get("max_prompt_chars", 2000) or 2000))
        if len(remainder) > maximum:
            return ParsedImageCommand(True, ratio=ratio, command=command, error="too_long")
        return ParsedImageCommand(True, prompt=remainder, ratio=ratio, command=command)
    return ParsedImageCommand()


class Image2Client:
    def __init__(
        self,
        api_base: str,
        api_key: str,
        *,
        api_timeout: float = 300,
        download_timeout: float = 300,
        max_file_bytes: int = 25 * 1024 * 1024,
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.api_timeout = api_timeout
        self.download_timeout = download_timeout
        self.max_file_bytes = max_file_bytes

    @property
    def endpoint(self) -> str:
        return f"{self.api_base}/images/generations"

    @staticmethod
    def _server_error(payload: Any, status: int) -> tuple[str, str]:
        value = payload.get("error", payload) if isinstance(payload, dict) else {}
        message = str(value.get("message") or "") if isinstance(value, dict) else ""
        code = str(value.get("type") or value.get("code") or "") if isinstance(value, dict) else ""
        return code or f"http_{status}", message or f"图片服务返回 HTTP {status}"

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "DZMMBot-Image2/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.api_timeout) as response:
                raw = response.read()
                status = int(response.status)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = int(exc.code)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ImageGenerationError("无法连接图片服务，请检查API地址或网络。", error_type="network_error") from exc
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = {"raw": raw.decode("utf-8", errors="replace")[:1000]}
        if not 200 <= status < 300:
            error_type, message = self._server_error(parsed, status)
            raise ImageGenerationError(message, error_type=error_type)
        if not isinstance(parsed, dict):
            raise ImageGenerationError("图片服务响应格式无效。", error_type="invalid_response")
        return parsed

    def _download(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "DZMMBot-Image2/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=self.download_timeout) as response:
                content = response.read(self.max_file_bytes + 1)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            raise ImageGenerationError("Image2图片下载失败。", error_type="download_error") from exc
        if len(content) > self.max_file_bytes:
            raise ImageGenerationError("Image2返回图片超过允许的文件大小。", error_type="file_too_large")
        return content

    @staticmethod
    def _verify(path: Path) -> tuple[int, int, str]:
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                return image.width, image.height, (image.format or "png").lower()
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise ImageGenerationError("Image2返回的文件不是有效图片。", error_type="invalid_image") from exc

    def generate(self, *, prompt: str, model: str, ratio: str, output_dir: Path) -> dict[str, Any]:
        response = self._post({"model": model, "prompt": prompt, "size": ratio, "n": 1})
        data = response.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ImageGenerationError("Image2没有返回有效图片。", error_type="empty_result")
        item = data[0]
        if item.get("url"):
            content = self._download(str(item["url"]))
        elif item.get("b64_json"):
            try:
                content = base64.b64decode(str(item["b64_json"]), validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ImageGenerationError("Image2返回的Base64图片无效。", error_type="invalid_image") from exc
            if len(content) > self.max_file_bytes:
                raise ImageGenerationError("Image2返回图片超过允许的文件大小。", error_type="file_too_large")
        else:
            raise ImageGenerationError("Image2返回图片缺少URL或Base64数据。", error_type="invalid_response")
        output_dir.mkdir(parents=True, exist_ok=True)
        temporary = output_dir / "result.image"
        temporary.write_bytes(content)
        width, height, image_format = self._verify(temporary)
        suffix = {"jpeg": ".jpg", "jpg": ".jpg", "webp": ".webp", "gif": ".gif"}.get(image_format, ".png")
        final_path = output_dir / f"result{suffix}"
        temporary.replace(final_path)
        return {
            "remote_task_id": str(response.get("task_id") or ""),
            "path": final_path,
            "width": width,
            "height": height,
            "format": image_format,
            "file_size": len(content),
        }


class ImageGenerationCore:
    ACTIVE_STATUSES = {"accepted", "generating", "downloading", "sending"}

    def __init__(self, db):
        self.db = db
        self.conn = db.conn

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """
            create table if not exists image_generation_jobs (
              id integer primary key autoincrement,
              job_id text not null unique,
              message_id text not null unique,
              user_pk integer not null,
              user_id text not null default '',
              nickname text not null,
              command text not null,
              prompt text not null default '',
              ratio text not null,
              model text not null,
              cost integer not null default 0,
              balance_after integer not null default 0,
              status text not null,
              remote_task_id text not null default '',
              error_type text not null default '',
              error_message text not null default '',
              image_path text not null default '',
              thumbnail_path text not null default '',
              width integer not null default 0,
              height integer not null default 0,
              image_format text not null default '',
              file_size integer not null default 0,
              send_success integer not null default 0,
              refunded integer not null default 0,
              refund_amount integer not null default 0,
              created_at text not null,
              started_at text not null default '',
              generated_at text not null default '',
              completed_at text not null default '',
              updated_at text not null,
              foreign key(user_pk) references users(id)
            );
            create index if not exists idx_image_generation_jobs_created
              on image_generation_jobs(created_at desc);
            create index if not exists idx_image_generation_jobs_user_created
              on image_generation_jobs(user_pk, created_at desc);
            create index if not exists idx_image_generation_jobs_status
              on image_generation_jobs(status, updated_at desc);
            """
        )
        self.conn.commit()

    @staticmethod
    def _job_dict(row) -> dict[str, Any]:
        result = dict(row)
        result["send_success"] = bool(result.get("send_success"))
        result["refunded"] = bool(result.get("refunded"))
        return result

    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "select * from image_generation_jobs where job_id=?", (str(job_id),)
        ).fetchone()
        return self._job_dict(row) if row else None

    def reserve(
        self,
        message: dict[str, Any],
        parsed: ParsedImageCommand,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        user = self.db.ensure_user(message)
        is_admin = self.db.is_admin_user(user)
        cost = max(0, int(settings.get("cost", 20) or 0))
        if is_admin and bool(settings.get("admin_free")):
            cost = 0
        now = self.db.now()
        today = now[:10]
        job_id = uuid.uuid4().hex[:12]
        try:
            self.conn.execute("begin immediate")
            duplicate = self.conn.execute(
                "select * from image_generation_jobs where message_id=?",
                (str(message.get("message_id") or ""),),
            ).fetchone()
            if duplicate:
                self.conn.rollback()
                return {"ok": False, "reason": "duplicate", "job": self._job_dict(duplicate)}
            if not (is_admin and bool(settings.get("admin_exempt_limits"))):
                per_user_limit = max(0, int(settings.get("per_user_daily_limit", 3) or 0))
                daily_used = int(
                    self.conn.execute(
                        "select count(*) from image_generation_jobs where user_pk=? and substr(created_at,1,10)=?",
                        (int(user["id"]), today),
                    ).fetchone()[0]
                )
                if per_user_limit and daily_used >= per_user_limit:
                    self.conn.rollback()
                    return {"ok": False, "reason": "daily_limit", "daily_used": daily_used, "daily_limit": per_user_limit}
                global_limit = max(0, int(settings.get("global_daily_limit", 30) or 0))
                global_used = int(
                    self.conn.execute(
                        "select count(*) from image_generation_jobs where substr(created_at,1,10)=?",
                        (today,),
                    ).fetchone()[0]
                )
                if global_limit and global_used >= global_limit:
                    self.conn.rollback()
                    return {"ok": False, "reason": "global_limit", "global_used": global_used, "global_limit": global_limit}
                cooldown = max(0, int(settings.get("cooldown_seconds", 60) or 0))
                latest = self.conn.execute(
                    "select created_at from image_generation_jobs where user_pk=? order by id desc limit 1",
                    (int(user["id"]),),
                ).fetchone()
                if cooldown and latest:
                    try:
                        elapsed = (datetime.now() - datetime.fromisoformat(str(latest["created_at"]))).total_seconds()
                    except ValueError:
                        elapsed = cooldown
                    if elapsed < cooldown:
                        self.conn.rollback()
                        return {"ok": False, "reason": "cooldown", "cooldown": max(1, int(cooldown - elapsed))}
            balance = int(user.get("points") or 0)
            if balance < cost:
                self.conn.rollback()
                return {"ok": False, "reason": "insufficient", "balance": balance, "cost": cost}
            balance_after = balance - cost
            if cost:
                self.conn.execute(
                    "update users set points=?,last_seen_at=? where id=?",
                    (balance_after, now, int(user["id"])),
                )
                self.conn.execute(
                    "insert into transactions(user_id,nickname,change_amount,reason,balance_after,created_at) values(?,?,?,?,?,?)",
                    (
                        str(user.get("platform_user_id") or user.get("user_id") or ""),
                        str(user.get("nickname") or message.get("sender") or "未知用户"),
                        -cost,
                        f"图片生成：{job_id}",
                        balance_after,
                        now,
                    ),
                )
            stored_prompt = parsed.prompt if bool(settings.get("history_save_prompt", True)) else ""
            self.conn.execute(
                """insert into image_generation_jobs(
                     job_id,message_id,user_pk,user_id,nickname,command,prompt,ratio,model,cost,
                     balance_after,status,created_at,updated_at)
                   values(?,?,?,?,?,?,?,?,?,?,?,'accepted',?,?)""",
                (
                    job_id,
                    str(message.get("message_id") or ""),
                    int(user["id"]),
                    str(user.get("platform_user_id") or user.get("user_id") or ""),
                    str(user.get("display_name") or user.get("nickname") or message.get("sender") or "未知用户"),
                    parsed.command,
                    stored_prompt,
                    parsed.ratio,
                    str(settings.get("model") or "gpt-image-2"),
                    cost,
                    balance_after,
                    now,
                    now,
                ),
            )
            self.conn.commit()
            return {"ok": True, "job": self.get(job_id), "balance": balance_after, "cost": cost}
        except Exception:
            self.conn.rollback()
            raise

    def update(self, job_id: str, **values: Any) -> dict[str, Any]:
        allowed = {
            "status", "remote_task_id", "error_type", "error_message", "image_path",
            "thumbnail_path", "width", "height", "image_format", "file_size",
            "send_success", "started_at", "generated_at", "completed_at",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        updates["updated_at"] = self.db.now()
        if updates:
            sql = ",".join(f"{key}=?" for key in updates)
            self.conn.execute(
                f"update image_generation_jobs set {sql} where job_id=?",
                (*updates.values(), str(job_id)),
            )
            self.conn.commit()
        return self.get(job_id) or {}

    def refund(self, job_id: str, reason: str) -> dict[str, Any]:
        try:
            self.conn.execute("begin immediate")
            row = self.conn.execute(
                "select * from image_generation_jobs where job_id=?", (str(job_id),)
            ).fetchone()
            if not row:
                self.conn.rollback()
                return {"ok": False, "reason": "not_found"}
            if bool(row["refunded"]) or int(row["cost"] or 0) <= 0:
                self.conn.rollback()
                return {"ok": True, "refunded": bool(row["refunded"]), "amount": int(row["refund_amount"] or 0), "job": self._job_dict(row)}
            user = self.conn.execute("select * from users where id=?", (int(row["user_pk"]),)).fetchone()
            if not user:
                self.conn.rollback()
                return {"ok": False, "reason": "user_not_found"}
            amount = int(row["cost"])
            balance = int(user["points"] or 0) + amount
            now = self.db.now()
            self.conn.execute("update users set points=?,last_seen_at=? where id=?", (balance, now, int(user["id"])))
            self.conn.execute(
                "insert into transactions(user_id,nickname,change_amount,reason,balance_after,created_at) values(?,?,?,?,?,?)",
                (
                    str(user["platform_user_id"] or user["user_id"] or ""),
                    str(user["nickname"] or row["nickname"]),
                    amount,
                    f"图片生成退款：{job_id}｜{reason}",
                    balance,
                    now,
                ),
            )
            self.conn.execute(
                "update image_generation_jobs set refunded=1,refund_amount=?,balance_after=?,updated_at=? where job_id=?",
                (amount, balance, now, str(job_id)),
            )
            self.conn.commit()
            return {"ok": True, "refunded": True, "amount": amount, "balance": balance, "job": self.get(job_id)}
        except Exception:
            self.conn.rollback()
            raise

    def list_jobs(self, *, page: int = 1, page_size: int = 10, status: str = "", search: str = "") -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if search:
            clauses.append("(job_id like ? or nickname like ? or prompt like ?)")
            like = f"%{search}%"
            params.extend([like, like, like])
        where = "where " + " and ".join(clauses) if clauses else ""
        page_size = max(1, min(int(page_size), 100))
        page = max(1, int(page))
        total = int(self.conn.execute(f"select count(*) from image_generation_jobs {where}", params).fetchone()[0])
        rows = self.conn.execute(
            f"select * from image_generation_jobs {where} order by id desc limit ? offset ?",
            (*params, page_size, (page - 1) * page_size),
        ).fetchall()
        return {"items": [self._job_dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    def stats(self) -> dict[str, Any]:
        today = self.db.now()[:10]
        row = self.conn.execute(
            """select count(*) total,
                      sum(case when status='completed' then 1 else 0 end) completed,
                      sum(case when status in ('failed','interrupted') then 1 else 0 end) failed,
                      sum(case when status='upload_failed' then 1 else 0 end) upload_failed,
                      sum(case when refunded=1 then refund_amount else 0 end) refunded_amount
                 from image_generation_jobs where substr(created_at,1,10)=?""",
            (today,),
        ).fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}

    def interrupted_jobs(self) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in self.ACTIVE_STATUSES)
        rows = self.conn.execute(
            f"select * from image_generation_jobs where status in ({placeholders}) order by id",
            tuple(self.ACTIVE_STATUSES),
        ).fetchall()
        return [self._job_dict(row) for row in rows]


class ImageGenerationService:
    def __init__(self, db, adapter, logger, data_dir: Path):
        self.db = db
        self.adapter = adapter
        self.logger = logger
        self.core: ImageGenerationCore = db.image_generation_core
        self.root = (data_dir / "image_generation").resolve()
        self.generated_dir = self.root / "generated"
        self.thumbnail_dir = self.root / "thumbnails"
        self.temp_dir = self.root / "temp"
        for directory in (self.generated_dir, self.thumbnail_dir, self.temp_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.tasks: dict[str, asyncio.Task] = {}
        self.submit_lock = asyncio.Lock()

    def settings(self) -> dict[str, Any]:
        return merged_image_settings(self.db.get_config())

    def status(self) -> dict[str, Any]:
        return {
            "active_count": sum(1 for task in self.tasks.values() if not task.done()),
            "active_jobs": [job_id for job_id, task in self.tasks.items() if not task.done()],
            "stats": self.core.stats(),
        }

    async def recover_interrupted(self) -> None:
        settings = self.settings()
        for job in self.core.interrupted_jobs():
            self.core.update(job["job_id"], status="interrupted", error_type="interrupted", error_message="程序上次退出时任务尚未完成")
            if bool(settings.get("refund_on_interrupt", True)):
                self.core.refund(job["job_id"], "任务中断")

    async def stop(self) -> None:
        pending = [task for task in self.tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.tasks.clear()

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        value = re.sub(r"\s+", " ", str(exc or "图片生成失败")).strip()
        return value[:300] or "图片生成失败"

    @staticmethod
    def _render(template: Any, values: dict[str, Any]) -> str:
        text = str(template or "")
        safe = {key: str(value) for key, value in values.items()}
        safe.setdefault("newline", "\n")
        for key, value in safe.items():
            text = text.replace("{" + key + "}", value)
        return text.strip()

    async def _send_text(self, text: str) -> bool:
        return bool(text) and await self.adapter.send_message(text, group_key="image")

    def is_command(self, text: str) -> bool:
        return parse_image_command(text, self.settings()).matched

    async def send_group_only_reply(self, group_key: str) -> None:
        settings = self.settings()
        await self.adapter.send_message(
            str(settings.get("group_only_reply") or "图片生成仅限绘图群使用。"),
            group_key=group_key,
        )

    async def handle_message(self, message: dict[str, Any]) -> bool:
        settings = self.settings()
        parsed = parse_image_command(str(message.get("text") or ""), settings)
        if not parsed.matched:
            return False
        base_values = {
            "user": message.get("sender") or "群友",
            "max_prompt_chars": settings.get("max_prompt_chars", 2000),
            "cost": settings.get("cost", 20),
            "ratio": parsed.ratio or settings.get("default_ratio", "3:4"),
        }
        if not bool(settings.get("enabled", True)):
            await self._send_text(self._render(settings.get("disabled_reply"), base_values))
            return True
        if parsed.error == "empty":
            await self._send_text(self._render(settings.get("empty_reply"), base_values))
            return True
        if parsed.error == "too_long":
            await self._send_text(self._render(settings.get("too_long_reply"), base_values))
            return True
        if not self.db.get_secret("image2_api_key"):
            await self._send_text(self._render(settings.get("api_key_missing_reply"), base_values))
            return True
        async with self.submit_lock:
            active = sum(1 for task in self.tasks.values() if not task.done())
            maximum = max(1, min(int(settings.get("max_concurrent", 1) or 1), 3))
            if active >= maximum:
                await self._send_text(self._render(settings.get("busy_reply"), base_values))
                return True
            result = self.core.reserve(message, parsed, settings)
            if not result.get("ok"):
                reason = result.get("reason")
                if reason == "duplicate":
                    return True
                template_key = {
                    "daily_limit": "daily_limit_reply",
                    "global_limit": "global_limit_reply",
                    "cooldown": "cooldown_reply",
                    "insufficient": "insufficient_reply",
                }.get(str(reason), "busy_reply")
                await self._send_text(self._render(settings.get(template_key), {**base_values, **result}))
                return True
            job = result["job"]
            values = {**base_values, **result, "job_id": job["job_id"], "balance": result.get("balance", 0)}
            await self._send_text(self._render(settings.get("accepted_reply"), values))
            task = asyncio.create_task(self._run_job(job["job_id"], parsed.prompt, dict(settings)))
            self.tasks[job["job_id"]] = task
            task.add_done_callback(lambda _task, job_id=job["job_id"]: self.tasks.pop(job_id, None))
        return True

    def _archive(self, job_id: str, source: Path, settings: dict[str, Any]) -> dict[str, Any]:
        month = datetime.now().strftime("%Y-%m")
        directory = self.generated_dir / month
        thumb_directory = self.thumbnail_dir / month
        directory.mkdir(parents=True, exist_ok=True)
        thumb_directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{job_id}{source.suffix.lower()}"
        shutil.copy2(source, target)
        thumb = thumb_directory / f"{job_id}.webp"
        with Image.open(target) as image:
            preview = image.convert("RGB")
            maximum = max(120, min(int(settings.get("thumbnail_max_dimension", 360) or 360), 1200))
            preview.thumbnail((maximum, maximum))
            preview.save(thumb, "WEBP", quality=max(30, min(int(settings.get("thumbnail_quality", 82) or 82), 100)))
            width, height = image.size
            image_format = (image.format or source.suffix.lstrip(".") or "png").lower()
        return {
            "image_path": str(target.relative_to(self.root)).replace("\\", "/"),
            "thumbnail_path": str(thumb.relative_to(self.root)).replace("\\", "/"),
            "width": width,
            "height": height,
            "image_format": image_format,
            "file_size": target.stat().st_size,
            "absolute_path": target,
        }

    async def _run_job(self, job_id: str, prompt: str, settings: dict[str, Any]) -> None:
        job_temp = self.temp_dir / job_id
        try:
            self.core.update(job_id, status="generating", started_at=self.db.now())
            client = Image2Client(
                str(settings.get("api_base") or ""),
                self.db.get_secret("image2_api_key"),
                api_timeout=max(30, float(settings.get("api_timeout_seconds", 300) or 300)),
                download_timeout=max(30, float(settings.get("download_timeout_seconds", 300) or 300)),
                max_file_bytes=max(1, int(settings.get("max_file_mb", 25) or 25)) * 1024 * 1024,
            )
            generated = await asyncio.to_thread(
                client.generate,
                prompt=prompt,
                model=str(settings.get("model") or "gpt-image-2"),
                ratio=str((self.core.get(job_id) or {}).get("ratio") or settings.get("default_ratio") or "3:4"),
                output_dir=job_temp,
            )
            archived = self._archive(job_id, Path(generated["path"]), settings)
            self.core.update(
                job_id,
                status="sending",
                remote_task_id=generated.get("remote_task_id", ""),
                generated_at=self.db.now(),
                **{key: archived[key] for key in ("image_path", "thumbnail_path", "width", "height", "image_format", "file_size")},
            )
            try:
                sent = await asyncio.wait_for(
                    self.adapter.send_image(str(archived["absolute_path"]), group_key="image"),
                    timeout=max(30, float(settings.get("upload_timeout_seconds", 90) or 90)),
                )
            except asyncio.TimeoutError:
                sent = False
            job = self.core.get(job_id) or {}
            values = {**job, "user": job.get("nickname", "群友"), "job_id": job_id, "ratio": job.get("ratio", "")}
            if sent:
                self.core.update(job_id, status="completed", send_success=1, completed_at=self.db.now())
                if bool(settings.get("send_success_reply", True)):
                    await self._send_text(self._render(settings.get("success_reply"), values))
                self.logger.info(f"Image2任务完成：job_id={job_id}，比例={job.get('ratio', '')}", kind="rule")
                return
            self.core.update(job_id, status="upload_failed", error_type="upload_failed", error_message="DZMM图片上传失败")
            refund = self.core.refund(job_id, "图片上传失败") if bool(settings.get("refund_on_upload_failure")) else {"refunded": False}
            values["refund_text"] = f" 已退还 {refund.get('amount', 0)} 功德。" if refund.get("refunded") else ""
            await self._send_text(self._render(settings.get("upload_failed_reply"), values))
        except asyncio.CancelledError:
            self.core.update(job_id, status="interrupted", error_type="interrupted", error_message="程序停止，任务中断")
            if bool(settings.get("refund_on_interrupt", True)):
                self.core.refund(job_id, "任务中断")
            raise
        except ImageGenerationError as exc:
            reason = self._safe_error(exc)
            self.core.update(job_id, status="failed", error_type=exc.error_type, error_message=reason, completed_at=self.db.now())
            refund = self.core.refund(job_id, "API未生成有效图片") if bool(settings.get("refund_on_api_failure", True)) else {"refunded": False}
            job = self.core.get(job_id) or {}
            values = {
                **job,
                "user": job.get("nickname", "群友"),
                "job_id": job_id,
                "error": reason,
                "refund_text": f" 已退还 {refund.get('amount', 0)} 功德。" if refund.get("refunded") else "",
            }
            await self._send_text(self._render(settings.get("api_failed_reply"), values))
            self.logger.error(f"Image2任务失败：job_id={job_id}，类型={exc.error_type}，原因={reason}")
        except Exception as exc:
            reason = self._safe_error(exc)
            self.core.update(job_id, status="failed", error_type="internal_error", error_message=reason, completed_at=self.db.now())
            refund = self.core.refund(job_id, "内部错误") if bool(settings.get("refund_on_api_failure", True)) else {"refunded": False}
            job = self.core.get(job_id) or {}
            await self._send_text(self._render(settings.get("api_failed_reply"), {
                **job,
                "user": job.get("nickname", "群友"),
                "job_id": job_id,
                "error": "内部错误，请联系管理员。",
                "refund_text": f" 已退还 {refund.get('amount', 0)} 功德。" if refund.get("refunded") else "",
            }))
            self.logger.error(f"Image2内部错误：job_id={job_id}，原因={reason}")
        finally:
            if job_temp.is_dir():
                shutil.rmtree(job_temp, ignore_errors=True)

    def resolve_media(self, job_id: str, *, thumbnail: bool = False) -> Path | None:
        job = self.core.get(job_id)
        if not job:
            return None
        relative = str(job.get("thumbnail_path" if thumbnail else "image_path") or "")
        if not relative:
            return None
        try:
            path = (self.root / relative).resolve()
            path.relative_to(self.root)
        except ValueError:
            return None
        return path if path.is_file() else None

    async def resend(self, job_id: str) -> dict[str, Any]:
        job = self.core.get(job_id)
        path = self.resolve_media(job_id)
        if not job or not path:
            raise ValueError("没有找到可以重新发送的历史图片")
        settings = self.settings()
        sent = await asyncio.wait_for(
            self.adapter.send_image(str(path), group_key="image"),
            timeout=max(30, float(settings.get("upload_timeout_seconds", 90) or 90)),
        )
        if not sent:
            raise ValueError("历史图片重新发送失败")
        self.core.update(job_id, send_success=1, status="completed", completed_at=self.db.now(), error_type="", error_message="")
        await self._send_text(self._render(settings.get("resend_success_reply"), {**job, "job_id": job_id}))
        return self.core.get(job_id) or {}
