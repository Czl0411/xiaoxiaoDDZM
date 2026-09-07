from __future__ import annotations

import asyncio
import time
import traceback
from collections import deque
from typing import Any

from app.ai_character import AIRequestRateLimitError, parse_ai_command
from app.outgoing_text import (
    AI_MAX_OUTGOING_LINES,
    MAX_OUTGOING_CHARS,
    MAX_OUTGOING_LINES,
    normalize_outgoing_text,
    outgoing_char_count,
    outgoing_line_count,
    prepare_outgoing_text_messages,
    prepare_outgoing_text_sequence,
)
from app.safety import SafetyGuard


class BotScheduler:
    MESSAGE_MEMORY_LIMIT = 600

    def __init__(
        self, db, adapter, engine, logger, command_router=None, ai_service=None,
        tarot_service=None, image_generation_service=None,
    ):
        self.db = db
        self.adapter = adapter
        self.engine = engine
        self.logger = logger
        self.command_router = command_router
        self.ai_service = ai_service
        self.tarot_service = tarot_service
        self.image_generation_service = image_generation_service
        self.safety = SafetyGuard(db)
        self.task: asyncio.Task | None = None
        self.running = False
        self.paused = False
        self.emergency = False
        self.fail_count = 0
        self.image_fail_count = 0
        self.loop_fail_count = 0
        self.auto_resume_at = 0.0
        self.auto_pause_reason = ""
        self.media_send_tasks: set[asyncio.Task] = set()
        self.media_delivery_locks: dict[str, asyncio.Lock] = {}
        self.last_message_time = ""
        self.primed = False
        self.primed_groups: set[str] = set()
        self.seen_message_ids: set[str] = set()
        self.seen_message_order: deque[str] = deque()
        self.deferred_identity_message_ids: set[str] = set()
        self.deferred_identity_message_order: deque[str] = deque()
        self.identity_pending_counts: dict[str, int] = {}
        self.identity_pending_last_summary_at = time.monotonic()
        self.baseline_incomplete_source_keys: set[str] = set()
        self.ai_background_task: asyncio.Task | None = None
        self.ai_proactive_task: asyncio.Task | None = None
        self.ai_request_tasks: set[asyncio.Task] = set()
        self.ai_user_locks: dict[str, asyncio.Lock] = {}
        self.ai_queue_counts: dict[str, int] = {}
        self.ai_group_queue_counts: dict[str, int] = {}
        self.ai_normal_semaphore: asyncio.Semaphore | None = None
        self.ai_thinking_semaphore: asyncio.Semaphore | None = None
        self.ai_semaphore_limits: tuple[int, int] | None = None
        self.inbound_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.inbound_task: asyncio.Task | None = None

    async def start(self) -> None:
        self.running = True
        self.paused = True
        set_handler = getattr(self.adapter, "set_message_handler", None)
        if callable(set_handler):
            set_handler(self._enqueue_socket_message)
            self.inbound_task = asyncio.create_task(self._inbound_loop())
        self.task = asyncio.create_task(self._loop())
        self.logger.info("机器人后台监听任务已启动（默认暂停，需手动恢复）")

    async def stop(self) -> None:
        self.running = False
        set_handler = getattr(self.adapter, "set_message_handler", None)
        if callable(set_handler):
            set_handler(None)
        if self.inbound_task:
            self.inbound_task.cancel()
            try:
                await self.inbound_task
            except asyncio.CancelledError:
                pass
            self.inbound_task = None
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        for pending in list(self.media_send_tasks):
            pending.cancel()
        if self.media_send_tasks:
            await asyncio.gather(*self.media_send_tasks, return_exceptions=True)
        for pending in list(self.ai_request_tasks):
            pending.cancel()
        if self.ai_request_tasks:
            await asyncio.gather(*self.ai_request_tasks, return_exceptions=True)
        if self.image_generation_service:
            await self.image_generation_service.stop()
        # background_tick uses the shared SQLite connection inside a worker thread.
        # Let it finish before application shutdown closes that connection.
        if self.ai_background_task and not self.ai_background_task.done():
            await asyncio.gather(self.ai_background_task, return_exceptions=True)
        if self.ai_proactive_task and not self.ai_proactive_task.done():
            await asyncio.gather(self.ai_proactive_task, return_exceptions=True)
        self.ai_request_tasks.clear()
        self.media_send_tasks.clear()
        self.ai_queue_counts.clear()
        self.ai_group_queue_counts.clear()
        self.ai_user_locks.clear()
        self.ai_background_task = None
        self.ai_proactive_task = None
        self.task = None
        self.ai_normal_semaphore = None
        self.ai_thinking_semaphore = None
        self.ai_semaphore_limits = None
        close_adapter = getattr(self.adapter, "close", None)
        if close_adapter is not None:
            await close_adapter()

    def _enqueue_socket_message(self, message: dict[str, Any]) -> None:
        if not self.running or self.paused or self.emergency:
            return
        self.inbound_queue.put_nowait(message)

    async def _inbound_loop(self) -> None:
        while self.running:
            message = await self.inbound_queue.get()
            try:
                config = self.db.get_config()
                if not self.paused and not self.emergency and bool(config.get("dzmm", {}).get("bot_enabled")):
                    if str(message.get("source_type") or "") == "direct":
                        self.db.upsert_direct_chat(
                            str(message.get("platform_user_id") or message.get("user_id") or ""),
                            str(message.get("chatroom_id") or ""),
                        )
                    await self._tick(
                        config,
                        messages=[message],
                        group_key=str(message.get("group_key") or message.get("source_group") or "main"),
                    )
            except Exception as exc:
                self.loop_fail_count += 1
                self.logger.error(f"实时消息处理异常：{exc}")
                self.logger.error(traceback.format_exc())
            finally:
                self.inbound_queue.task_done()

    def pause(self, reason: str, *, auto_resume_seconds: float | None = None) -> None:
        self.paused = True
        if auto_resume_seconds is None:
            self.auto_resume_at = 0.0
            self.auto_pause_reason = ""
        else:
            self.auto_resume_at = time.monotonic() + max(5.0, float(auto_resume_seconds))
            self.auto_pause_reason = reason
        config = self.db.get_config()
        config["dzmm"]["bot_enabled"] = False
        self.db.save_config(config)
        suffix = (
            f"，将在 {max(5, int(auto_resume_seconds))} 秒后自动恢复"
            if auto_resume_seconds is not None
            else ""
        )
        self.logger.warning(f"机器人已暂停：{reason}{suffix}")

    def resume(self) -> None:
        self.paused = False
        self.emergency = False
        self.auto_resume_at = 0.0
        self.auto_pause_reason = ""
        self.fail_count = 0
        self.primed = False
        self.primed_groups.clear()
        self.seen_message_ids.clear()
        self.seen_message_order.clear()
        self.baseline_incomplete_source_keys.clear()
        clear_pending = getattr(self.adapter, "clear_pending_messages", None)
        if clear_pending is not None:
            clear_pending()
        config = self.db.get_config()
        config["dzmm"]["bot_enabled"] = True
        self.db.save_config(config)
        self.logger.info("机器人已恢复")

    def emergency_stop(self) -> None:
        self.emergency = True
        self.pause("紧急停止")

    def _resume_if_due(self) -> None:
        if (
            self.paused
            and not self.emergency
            and self.auto_resume_at > 0
            and time.monotonic() >= self.auto_resume_at
        ):
            reason = self.auto_pause_reason or "发送异常"
            self.resume()
            self.logger.info(f"机器人已从自动暂停中恢复：{reason}")

    def _track_media_task(self, task: asyncio.Task) -> None:
        self.media_send_tasks.add(task)

        def finished(done: asyncio.Task) -> None:
            self.media_send_tasks.discard(done)
            if done.cancelled():
                return
            try:
                done.result()
            except Exception as exc:
                self.logger.error(f"异步图片发送任务异常：{exc}")
                self.logger.error(traceback.format_exc())

        task.add_done_callback(finished)

    def status(self) -> dict[str, Any]:
        page = self.adapter.browser.page
        return {
            "running": self.running,
            "paused": self.paused,
            "emergency": self.emergency,
            "browser_connected": bool(page and not page.is_closed()),
            "last_message_time": self.last_message_time,
            "fail_count": self.fail_count,
            "text_fail_count": self.fail_count,
            "image_fail_count": self.image_fail_count,
            "loop_fail_count": self.loop_fail_count,
            "auto_resume_seconds": max(0, int(self.auto_resume_at - time.monotonic()))
            if self.auto_resume_at
            else 0,
        }

    async def _loop(self) -> None:
        while self.running:
            self._resume_if_due()
            config = self.db.get_config()
            interval = float(config.get("dzmm", {}).get("scan_interval_seconds", 2) or 2)
            try:
                await self._run_cycle(config)
            except Exception as exc:
                self.loop_fail_count += 1
                self.logger.error(f"监听循环异常：{exc}")
                self.logger.error(traceback.format_exc())
                if "closed" in str(exc).lower():
                    self.primed = False
                    self.primed_groups.clear()
            await asyncio.sleep(max(1.0, interval))

    async def _run_cycle(self, config: dict[str, Any]) -> None:
        dzmm = config.get("dzmm", {})
        business_enabled = bool(dzmm.get("bot_enabled")) and not self.paused and not self.emergency

        cleanup = self.db.run_weekly_bounty_cleanup()
        if cleanup.get("ran"):
            self.logger.info(
                "北京时间每周悬赏清理完成："
                f"取消 {cleanup['cancelled_count']} 条，归档 {cleanup['archived_count']} 条，"
                f"退款 {cleanup['refunded_amount']} 功德。",
                kind="rule",
            )

        if business_enabled:
            if (
                self.ai_service
                and self.ai_service.background_due()
                and (not self.ai_background_task or self.ai_background_task.done())
            ):
                self.ai_background_task = asyncio.create_task(self._run_ai_background())
            if (
                self.ai_service
                and self.ai_service.proactive_due()
                and (not self.ai_proactive_task or self.ai_proactive_task.done())
            ):
                self.ai_proactive_task = asyncio.create_task(self._run_ai_proactive())
            await self._process_random_events(config)
            await self._process_expired_rp_gatherings(config)
            await self._process_expired_nipple_guess(config)
            await self._process_expired_waiting_games(config)
            await self._process_expired_six_seal_games(config)
            await self._process_expired_slave_contract_offers(config)
            await self._process_expired_bounties(config)
            self.db.marketplace_core.expire_due()
            maintain_socket = getattr(self.adapter, "maintain_socket", None)
            if callable(maintain_socket) and callable(getattr(self.adapter, "set_message_handler", None)):
                await maintain_socket()
                self.primed = True
            else:
                group_keys = ["main"]
                if str(dzmm.get("bounty_group_url") or "").strip():
                    group_keys.append("bounty")
                if self.image_generation_service is not None and str(dzmm.get("image_group_url") or "").strip():
                    group_keys.append("image")
                for group_key in group_keys:
                    if group_key not in self.primed_groups:
                        await self._prime_messages(group_key=group_key)
                        self.primed_groups.add(group_key)
                    else:
                        await self._tick(config, group_key=group_key)
                read_direct = getattr(self.adapter, "read_direct_messages", None)
                if callable(read_direct):
                    direct_messages = await read_direct()
                    if direct_messages:
                        for direct_message in direct_messages:
                            platform_user_id = str(direct_message.get("platform_user_id") or direct_message.get("user_id") or "")
                            chatroom_id = str(direct_message.get("chatroom_id") or "")
                            self.db.upsert_direct_chat(platform_user_id, chatroom_id)
                        await self._tick(config, messages=direct_messages, group_key="direct")
                self.primed = "main" in self.primed_groups

    async def _run_ai_background(self) -> None:
        try:
            self.ai_service.defer_background()
            outputs = await asyncio.to_thread(self.ai_service.background_tick_isolated)
            if not self.running:
                return
            for item in outputs:
                text = normalize_outgoing_text(str(item.get("text") or ""))
                for part in prepare_outgoing_text_messages(
                    text, max_lines=AI_MAX_OUTGOING_LINES
                ):
                    can_send, reason = self.safety.can_send()
                    if not can_send:
                        self.logger.info(f"AI主动聊天已跳过：{reason}")
                        break
                    ok = await self._adapter_send_message(part, str(item.get("group_key") or "main"))
                    self.db.record_reply(str(item.get("task_id") or ""), None, "AI主动聊天", part, ok)
                    if not ok:
                        self.logger.error("AI主动聊天发送失败")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.error(f"AI后台记忆任务失败：{exc}")

    async def _run_ai_proactive(self) -> None:
        try:
            self.ai_service.defer_proactive()
            outputs = await asyncio.to_thread(self.ai_service.proactive_tick_isolated)
            if not self.running:
                return
            for item in outputs:
                text = normalize_outgoing_text(str(item.get("text") or ""))
                for part in prepare_outgoing_text_messages(
                    text, max_lines=AI_MAX_OUTGOING_LINES
                ):
                    can_send, reason = self.safety.can_send()
                    if not can_send:
                        self.logger.info(f"AI主动聊天已跳过：{reason}")
                        break
                    ok = await self._adapter_send_message(part, str(item.get("group_key") or "main"))
                    self.db.record_reply(str(item.get("task_id") or ""), None, "AI主动聊天", part, ok)
                    if not ok:
                        self.logger.error("AI主动聊天发送失败")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.error(f"AI主动聊天任务失败：{exc}")

    async def _adapter_send_message(self, text: str, group_key: str = "main") -> bool:
        normalized = normalize_outgoing_text(text)
        if not normalized:
            self.logger.warning("已拦截空文字消息。")
            return False
        if outgoing_line_count(normalized) > MAX_OUTGOING_LINES:
            self.logger.error("已拦截超过单页行数且未经过发送前拆分的文字消息。")
            return False
        if outgoing_char_count(normalized) > MAX_OUTGOING_CHARS:
            self.logger.error("已拦截超过单页字数且未经过发送前拆分的文字消息。")
            return False
        try:
            return await self.adapter.send_message(normalized, group_key=group_key)
        except TypeError as exc:
            if "group_key" not in str(exc):
                raise
            return await self.adapter.send_message(normalized)

    async def _adapter_send_direct_message(self, chatroom_id: str, text: str) -> bool:
        normalized = normalize_outgoing_text(text)
        if not normalized:
            return False
        if outgoing_line_count(normalized) > MAX_OUTGOING_LINES:
            return False
        if outgoing_char_count(normalized) > MAX_OUTGOING_CHARS:
            return False
        return await self.adapter.send_direct_message(chatroom_id, normalized)

    async def _adapter_send_prepared_messages(
        self,
        text: str,
        group_key: str,
        delay_seconds: float,
    ) -> bool:
        parts = prepare_outgoing_text_messages(text)
        if not parts:
            return False
        for index, part in enumerate(parts):
            if index:
                await asyncio.sleep(delay_seconds)
            if not await self._adapter_send_message(part, group_key):
                return False
        return True

    async def _adapter_send_image(self, path: str, group_key: str = "main") -> bool:
        try:
            return await self.adapter.send_image(path, group_key=group_key)
        except TypeError as exc:
            if "group_key" not in str(exc):
                raise
            return await self.adapter.send_image(path)

    async def _adapter_read_messages(self, group_key: str = "main") -> list[dict[str, Any]]:
        try:
            return await self.adapter.read_recent_messages(group_key=group_key)
        except TypeError as exc:
            if "group_key" not in str(exc):
                raise
            return await self.adapter.read_recent_messages()

    async def _process_expired_bounties(self, config: dict[str, Any]) -> None:
        if not self.command_router:
            return
        if not str(config.get("dzmm", {}).get("bounty_group_url") or "").strip():
            return
        for bounty in self.db.claim_expired_bounties():
            reply = (
                f"⌛ 悬赏 #{bounty['number']} 的约定时间已到。\n"
                f"发起人：{bounty['publisher_title']}\n"
                f"接取人：{'、'.join(bounty.get('participant_names') or []) or '暂无'}\n"
                f"内容：{self.command_router._bounty_clean_content(bounty['content'], 180)}\n"
                "请双方核实完成情况；履约方可发送 /我的订单 查看O订单号，再使用 /完成订单O编号。"
            )
            await asyncio.sleep(
                float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5)
            )
            sent = await self._adapter_send_prepared_messages(
                reply,
                "bounty",
                float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5),
            )
            if sent:
                self.db.finish_expired_bounty_notification(int(bounty["id"]))
                self.fail_count = 0
                self.logger.info(
                    f"悬赏到期已通知：#{bounty['number']}", kind="rule"
                )
            else:
                self.fail_count += 1
                self.logger.error(f"悬赏到期通知发送失败：#{bounty['number']}")

    async def _process_expired_rp_gatherings(self, config: dict[str, Any]) -> None:
        delay = float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5)
        from app.command_router import DEFAULTS
        features = {**DEFAULTS, **config.get("features", {})}
        timeout_reply = str(features.get("rp_timeout_reply") or DEFAULTS["rp_timeout_reply"])
        for session in self.db.expire_rp_gatherings():
            sent = await self._adapter_send_prepared_messages(
                timeout_reply,
                str(session.get("group_id") or "main"),
                delay,
            )
            if sent:
                self.logger.info(f"RP集结超时已结束：{session.get('session_id')}", kind="rule")
            else:
                self.logger.error(f"RP集结超时通知发送失败：{session.get('session_id')}")

    async def _process_random_events(self, config: dict[str, Any]) -> None:
        if not self.command_router:
            return
        delay = float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5)
        for output in self.command_router.random_event_scheduler_tick():
            sent = True
            for index, reply in enumerate(output.get("replies") or []):
                if index:
                    await asyncio.sleep(delay)
                if not await self._adapter_send_prepared_messages(
                    str(reply), str(output.get("group_id") or "main"), delay
                ):
                    sent = False
                    break
            if sent:
                self.logger.info(
                    f"随机事件定时处理完成：{output.get('kind')} {output.get('session_id', '')}",
                    kind="rule",
                )
            else:
                if output.get("kind") == "auto" and output.get("session_id"):
                    self.db.random_event_core.cancel_failed_launch(str(output["session_id"]))
                    if output.get("run_key"):
                        self.db.random_event_core.finish_schedule_run(
                            str(output["run_key"]), status="failed", detail="announcement_failed"
                        )
                self.logger.error(
                    f"随机事件消息发送失败：{output.get('kind')} {output.get('session_id', '')}"
                )

    async def _process_expired_nipple_guess(self, config: dict[str, Any]) -> None:
        features = config.get("features", {})
        timeout = int(features.get("nipple_guess_timeout_seconds", 300) or 300)
        delay = float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5)
        for session in self.db.expire_nipple_guess_sessions(timeout):
            await self._adapter_send_prepared_messages(
                f"猜乳头游戏已超时，原始冻结的 {session['refund']} 功德已安全退回。",
                "main", delay,
            )

    async def _process_expired_slave_contract_offers(self, config: dict[str, Any]) -> None:
        if not self.command_router:
            return
        offers = self.db.claim_expired_lender_offers()
        if not offers:
            return
        features = config.get("features", {})
        currency = features.get("currency_name", "金币")
        template = features.get(
            "slave_contract_public_lender_expired_reply",
            "⌛ {lender} 发布的奴隶招收悬赏已超过 5 分钟无人回应，本次悬赏已自动取消。",
        )
        for offer in offers:
            lender_title = (
                offer.get("display_name")
                or offer.get("current_nickname")
                or offer.get("creator_nickname")
                or "用户"
            )
            reply = self.command_router._render(
                template,
                lender_title,
                currency,
                offer,
                {"lender": lender_title},
            )
            await asyncio.sleep(float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5))
            sent = await self._adapter_send_prepared_messages(
                reply,
                "main",
                float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5),
            )
            self.db.finish_expired_lender_offer_notification(int(offer["id"]), sent)
            if sent:
                self.fail_count = 0
                self.logger.info(
                    f"奴隶招收悬赏已超时取消并通知：发布者={lender_title}，悬赏ID={offer['id']}",
                    kind="rule",
                )
            else:
                self.fail_count += 1
                self.logger.error(
                    f"奴隶招收悬赏取消通知发送失败：发布者={lender_title}，悬赏ID={offer['id']}"
                )

    async def _process_expired_waiting_games(self, config: dict[str, Any]) -> None:
        from app.command_router import DEFAULTS

        features = {**DEFAULTS, **config.get("features", {})}
        timeout = max(
            30,
            min(int(features.get("battle_zjh_wait_timeout_seconds", 120) or 120), 3600),
        )
        for game in self.db.claim_expired_waiting_games(timeout):
            reply = self.command_router._render(
                features["battle_zjh_timeout_reply"],
                str(game.get("initiator_nickname") or ""),
                str(features.get("currency_name") or "功德点"),
                {},
                {"timeout_minutes": max(1, timeout // 60)},
            )
            await self._adapter_send_prepared_messages(
                reply,
                "main",
                float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5),
            )

    async def _process_expired_six_seal_games(self, config: dict[str, Any]) -> None:
        if not self.command_router:
            return
        games = self.db.claim_expired_six_seal_games()
        if not games:
            return
        from app.command_router import DEFAULTS

        features = {**DEFAULTS, **config.get("features", {})}
        currency = features.get("currency_name", "功德点")
        template = features["six_seal_expired_reply"]
        wait_seconds = max(
            30,
            min(int(features.get("six_seal_wait_seconds", 300) or 300), 3600),
        )
        for game in games:
            if game.get("expiry_kind") == "turn":
                loser = self.command_router._six_seal_title(
                    str(game["loser_user_id"]), str(game["loser_nickname"])
                )
                winner = self.command_router._six_seal_title(
                    str(game["winner_user_id"]), str(game["winner_nickname"])
                )
                turn_timeout_seconds = max(
                    30,
                    min(
                        int(features.get("six_seal_turn_timeout_seconds", 120) or 120),
                        3600,
                    ),
                )
                reply = self.command_router._render(
                    features["six_seal_turn_expired_reply"],
                    loser,
                    currency,
                    {},
                    {
                        **game,
                        "loser": loser,
                        "winner": winner,
                        "turn_timeout_minutes": max(1, turn_timeout_seconds // 60),
                    },
                )
                log_subject = f"逃战者={loser}"
            else:
                initiator = self.command_router._six_seal_title(
                    str(game["initiator_user_id"]),
                    str(game["initiator_nickname"]),
                )
                reply = self.command_router._render(
                    template,
                    initiator,
                    currency,
                    {},
                    {
                        "initiator": initiator,
                        "wait_minutes": max(1, wait_seconds // 60),
                        "max_wager": int(game["max_wager"]),
                    },
                )
                log_subject = f"发起者={initiator}"
            await asyncio.sleep(
                float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5)
            )
            sent = await self._adapter_send_prepared_messages(
                reply,
                "main",
                float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5),
            )
            self.db.finish_expired_six_seal_notification(int(game["id"]), sent)
            if sent:
                self.fail_count = 0
                self.logger.info(
                    f"六印圣裁超时已结算并通知：{log_subject}，仪式ID={game['id']}",
                    kind="rule",
                )
            else:
                self.fail_count += 1
                self.logger.error(
                    f"六印圣裁超时通知发送失败：{log_subject}，仪式ID={game['id']}"
                )

    def _remember_deferred_identity(self, message_id: str) -> bool:
        """Return True only when this incomplete observation is first deferred."""
        if not message_id or message_id in self.deferred_identity_message_ids:
            return False
        self.deferred_identity_message_ids.add(message_id)
        self.deferred_identity_message_order.append(message_id)
        while len(self.deferred_identity_message_order) > self.MESSAGE_MEMORY_LIMIT:
            expired = self.deferred_identity_message_order.popleft()
            self.deferred_identity_message_ids.discard(expired)
        return True

    def _forget_deferred_identity(self, message_id: str) -> None:
        self.deferred_identity_message_ids.discard(message_id)

    def _log_deferred_identity(self, message: dict[str, Any]) -> None:
        text = str(message.get("text") or "").strip()
        group_key = str(
            message.get("group_key") or message.get("source_group") or "main"
        )
        if text.startswith("/"):
            self.logger.warning(
                "命令尚未取得可确认身份，已挂起等待重试；"
                f"消息ID={message.get('message_id', '')}；"
                f"昵称={message.get('sender', '')}；"
                f"头像UUID={message.get('avatar_id', '') or '无'}"
            )
            return
        self.identity_pending_counts[group_key] = (
            self.identity_pending_counts.get(group_key, 0) + 1
        )
        now = time.monotonic()
        if now - self.identity_pending_last_summary_at < 60.0:
            return
        summary = "、".join(
            f"{key}群{count}条" for key, count in sorted(self.identity_pending_counts.items())
        )
        self.logger.warning(
            f"用户身份待确认汇总：{summary or '0条'}；普通聊天不会执行业务，命令继续安全重试"
        )
        self.identity_pending_counts.clear()
        self.identity_pending_last_summary_at = now

    def _remember_seen(self, message_id: str) -> None:
        if not message_id or message_id in self.seen_message_ids:
            return
        self.seen_message_ids.add(message_id)
        self.seen_message_order.append(message_id)
        while len(self.seen_message_order) > self.MESSAGE_MEMORY_LIMIT:
            expired = self.seen_message_order.popleft()
            self.seen_message_ids.discard(expired)

    def _message_has_complete_identity(self, message: dict[str, Any]) -> bool:
        platform_user_id = (message.get("platform_user_id") or message.get("user_id") or "").strip()
        return bool(platform_user_id)

    async def _handle_normal_chat_drop(
        self,
        msg: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        message_id = msg["message_id"]
        if not (msg.get("text") or "").strip():
            self.db.mark_message_processed(message_id, "普通聊天忽略", "")
            return
        if not self._message_has_complete_identity(msg):
            return
        identity_ok, identity_reason, identity_user = self.db.identity_decision(msg)
        if not identity_ok:
            self.logger.warning(
                f"普通聊天掉落已跳过：{identity_reason}；昵称={msg.get('sender', '')}；"
                f"主页ID={msg.get('platform_user_id') or msg.get('user_id') or ''}"
            )
            self.db.mark_message_processed(message_id, identity_reason, "")
            return
        user_ok, user_reason = self.safety.user_allowed(msg.get("sender", ""))
        if not user_ok:
            self.db.mark_message_processed(message_id, "安全跳过", "")
            return
        can_send, send_reason = self.safety.can_send()
        if not can_send:
            self.logger.info(f"普通聊天掉落已跳过：{send_reason}")
            self.db.mark_message_processed(message_id, "普通聊天忽略", "")
            return
        features = config.get("features", {})
        drop = self.db.maybe_grant_normal_chat_drop(msg, features)
        if not drop:
            self.db.mark_message_processed(message_id, "普通聊天忽略", "")
            return

        item = drop["item"]
        quantity = int(drop.get("quantity", 1))
        user = self.db.get_user(msg) or identity_user or msg
        title = self.db.display_name(user)
        template = features.get(
            "normal_chat_item_drop_reply",
            "🎁 {user}聊天时意外捡到：{item} x{quantity}，已放入背包。",
        )
        render = getattr(self.command_router, "_render", None)
        if callable(render):
            reply = render(
                template,
                title,
                features.get("currency_name", "功德点"),
                user,
                {"item": item["name"], "quantity": quantity},
            )
        else:
            reply = str(template)
            for key, value in {
                "user": title,
                "item": item["name"],
                "quantity": quantity,
                "newline": "\n",
            }.items():
                reply = reply.replace("{" + key + "}", str(value))

        sent_parts: list[str] = []
        all_sent = True
        for part in prepare_outgoing_text_messages(reply):
            can_send, send_reason = self.safety.can_send()
            if not can_send:
                self.logger.info(f"普通聊天掉落后续通知已停止：{send_reason}")
                all_sent = False
                break
            await asyncio.sleep(float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 0))
            sent = await self._adapter_send_message(
                part, str(msg.get("group_key") or msg.get("source_group") or "main")
            )
            self.db.record_reply(message_id, None, msg, part, sent)
            if not sent:
                all_sent = False
                break
            sent_parts.append(part)
        self.db.mark_message_processed(
            message_id,
            "普通聊天掉落",
            "\n".join(sent_parts),
        )
        if all_sent and sent_parts:
            self.fail_count = 0
            self.logger.info(
                f"普通聊天掉落成功：用户={title}，物品={item['name']}，数量={quantity}",
                kind="rule",
            )
        else:
            self.fail_count += 1
            self.logger.error(
                f"普通聊天掉落通知发送失败：用户={title}，物品={item['name']}"
            )

    @staticmethod
    def _baseline_source_key(message: dict[str, Any]) -> str:
        if not message.get("source_stable"):
            return ""
        source_index = (message.get("source_index") or "").strip()
        if not source_index:
            return ""
        return "\x1f".join(
            [
                (message.get("group_key") or message.get("source_group") or "main").strip(),
                source_index,
                (message.get("avatar_id") or "").strip().lower(),
                (message.get("text") or "").strip(),
                "1" if message.get("is_self") else "0",
            ]
        )

    async def _tick(
        self,
        config: dict[str, Any],
        messages: list[dict[str, Any]] | None = None,
        group_key: str = "main",
    ) -> None:
        if messages is None:
            messages = await self._adapter_read_messages(group_key)
        if not messages:
            return
        allow_multi = bool(config.get("dzmm", {}).get("allow_multi_rule_reply", False))
        for msg in messages:
            msg.setdefault("group_key", group_key)
            msg.setdefault("source_group", group_key)
            text = (msg.get("text") or "").strip()
            message_id = msg["message_id"]
            if message_id in self.seen_message_ids:
                continue
            if msg.get("event_type") == "member_joined_by_invite":
                self.db.referral_core.record_join(msg)
                self._remember_seen(message_id)
                continue
            source_key = self._baseline_source_key(msg)
            if source_key and source_key in self.baseline_incomplete_source_keys:
                self.db.save_message(msg)
                self.db.mark_message_processed(message_id, "启动基线延续", "")
                self._remember_seen(message_id)
                if self._message_has_complete_identity(msg) or msg.get("is_self"):
                    self.baseline_incomplete_source_keys.discard(source_key)
                continue
            is_new = self.db.save_message(msg)
            if not is_new:
                existing = self.db.get_message(msg["message_id"])
                if not existing or existing.get("processed"):
                    self._remember_seen(message_id)
                    continue
            self.last_message_time = msg.get("time", "")
            if config.get("safety", {}).get("ignore_self_messages", True) and msg.get("is_self"):
                self._remember_seen(message_id)
                self.db.mark_message_processed(msg["message_id"], "自己消息", "")
                continue
            if not self._message_has_complete_identity(msg):
                if self._remember_deferred_identity(message_id):
                    self._log_deferred_identity(msg)
                continue
            if msg.get("identity_source") == "avatar_uuid" and text.startswith("/"):
                self.logger.info(
                    "命令已通过唯一头像UUID安全补回平台用户ID；"
                    f"消息ID={message_id}；昵称={msg.get('sender', '')}"
                )
            referral_outcome = self.db.referral_core.observe_message(msg)
            if referral_outcome is not None:
                await self._adapter_send_message(
                    referral_outcome.announcement,
                    referral_outcome.group_key,
                )
            if str(msg.get("group_key") or group_key) == "image":
                if not self.image_generation_service or not self.image_generation_service.is_command(text):
                    self._remember_seen(message_id)
                    self.db.mark_message_processed(message_id, "绘图群非图片命令忽略", "")
                    continue
                identity_ok, identity_reason, identity_user = self.db.identity_decision(msg)
                if not identity_ok:
                    self._remember_seen(message_id)
                    self.db.mark_message_processed(message_id, identity_reason, "")
                    continue
                msg["identity_user_pk"] = identity_user.get("id")
                user_ok, user_reason = self.safety.user_allowed(msg.get("sender", ""))
                if not user_ok:
                    self._remember_seen(message_id)
                    self.db.mark_message_processed(message_id, f"安全跳过：{user_reason}", "")
                    continue
                self._remember_seen(message_id)
                handled = await self.image_generation_service.handle_message(msg)
                self.db.mark_message_processed(
                    message_id,
                    "图片生成" if handled else "绘图群非图片命令忽略",
                    "",
                )
                continue
            require_slash = bool(config.get("dzmm", {}).get("require_slash_prefix", True))
            if require_slash and not text.startswith("/"):
                identity_ok, _, identity_user = self.db.identity_decision(msg)
                if (
                    identity_ok
                    and self.command_router
                    and str(msg.get("source_type") or "") == "direct"
                    and self.db.commission_house.get_wizard(msg)
                ):
                    msg["identity_user_pk"] = identity_user.get("id")
                    wizard_result = self.command_router.handle(msg)
                    if wizard_result.handled:
                        self._remember_seen(message_id)
                        await self._send_replies(
                            msg, wizard_result.replies, wizard_result.name, None, config,
                            media_paths=wizard_result.media_paths,
                            media_first=wizard_result.media_first,
                            deliveries=wizard_result.deliveries,
                            direct_deliveries=wizard_result.direct_deliveries,
                            media_refund_inventory_id=wizard_result.media_refund_inventory_id,
                        )
                        continue
                passive_handler = getattr(self.command_router, "handle_passive", None)
                if identity_ok and callable(passive_handler):
                    msg["identity_user_pk"] = identity_user.get("id")
                    passive_result = passive_handler(msg)
                    if passive_result.handled:
                        self._remember_seen(message_id)
                        await self._send_replies(
                            msg, passive_result.replies, passive_result.name, None, config,
                            media_paths=passive_result.media_paths,
                            media_first=passive_result.media_first,
                            deliveries=passive_result.deliveries,
                        )
                        continue
                self._remember_seen(message_id)
                if str(msg.get("group_key") or group_key) == "bounty":
                    self.db.mark_message_processed(message_id, "悬赏群普通消息忽略", "")
                    continue
                await self._handle_normal_chat_drop(msg, config)
                continue
            identity_ok, identity_reason, identity_user = self.db.identity_decision(msg)
            if not identity_ok:
                self.logger.warning(
                    f"用户业务已暂停：{identity_reason}；昵称={msg.get('sender', '')}；"
                    f"主页ID={msg.get('platform_user_id') or msg.get('user_id') or ''}；"
                    f"头像ID={msg.get('avatar_id') or ''}"
                )
                self._forget_deferred_identity(message_id)
                self._remember_seen(message_id)
                self.db.mark_message_processed(msg["message_id"], identity_reason, "")
                continue
            self._forget_deferred_identity(message_id)
            self._remember_seen(message_id)
            msg["identity_user_pk"] = identity_user.get("id")
            user_ok, user_reason = self.safety.user_allowed(msg.get("sender", ""))
            if not user_ok:
                self.logger.info(f"消息被安全规则跳过：{user_reason}")
                self.db.mark_message_processed(msg["message_id"], "安全跳过", "")
                continue
            if self.command_router:
                if self.image_generation_service and self.image_generation_service.is_command(text):
                    await self.image_generation_service.send_group_only_reply(
                        str(msg.get("group_key") or group_key)
                    )
                    self.db.mark_message_processed(message_id, "图片生成仅限绘图群", "")
                    continue
                tarot_command = (
                    self.tarot_service.parse_command(text)
                    if self.tarot_service
                    else None
                )
                if tarot_command and tarot_command.matched:
                    self._queue_tarot_request(msg, tarot_command, config)
                    continue
                ai_command = parse_ai_command(text)
                if self.ai_service and ai_command.matched:
                    await self._queue_ai_request(msg, ai_command, config)
                    continue
                command_result = self.command_router.handle(msg)
                if command_result.handled:
                    await self._send_replies(
                        msg,
                        command_result.replies,
                        command_result.name,
                        None,
                        config,
                        media_paths=command_result.media_paths,
                        media_first=command_result.media_first,
                        deliveries=command_result.deliveries,
                        direct_deliveries=command_result.direct_deliveries,
                        media_refund_inventory_id=command_result.media_refund_inventory_id,
                    )
                    self.logger.info(f"命令已处理：/{command_result.name}，{command_result.reason}", kind="rule")
                    continue

            matches = self.engine.match_rules(msg, msg.get("sender", ""))
            if not matches:
                if require_slash and text.startswith("/"):
                    unknown_reply = config.get("dzmm", {}).get("unknown_command_reply", "命令错误") or "命令错误"
                    await self._send_replies(msg, [unknown_reply], "未知命令", None, config)
                    continue
                self.db.mark_message_processed(msg["message_id"], "未命中", "")
                continue

            selected = matches if allow_multi else matches[:1]
            reply_texts = []
            matched_names = []
            for item in selected:
                rule = item["rule"]
                blocked, reason = self.engine.check_cooldown(rule, msg)
                if blocked:
                    self.logger.info(f"规则命中但未发送：{rule['name']}，{reason}", kind="rule")
                    continue
                prepared_replies = prepare_outgoing_text_sequence(
                    self.engine.pick_replies(rule, msg)
                )
                for reply in prepared_replies:
                    can_send, send_reason = self.safety.can_send()
                    if not can_send:
                        self.logger.warning(f"发送被安全限制拦截：{send_reason}")
                        break
                    await asyncio.sleep(float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5))
                    ok = await self._adapter_send_message(
                        reply,
                        str(msg.get("group_key") or msg.get("source_group") or group_key),
                    )
                    self.db.record_reply(msg["message_id"], rule["id"], msg, reply, ok)
                    if ok:
                        self.fail_count = 0
                        self.engine.update_rule_hit(rule, msg, item["reason"])
                        reply_texts.append(reply)
                        matched_names.append(rule["name"])
                    else:
                        self.fail_count += 1
                        self.logger.error(f"发送失败：连续失败 {self.fail_count} 次，消息ID={msg.get('message_id', '')}，规则={rule['name']}")
                        if self.fail_count >= 3:
                            self.pause("文字连续发送失败 3 次", auto_resume_seconds=30)
                            break
            self.db.mark_message_processed(msg["message_id"], ", ".join(matched_names), "\n".join(reply_texts))

    async def _send_replies(
        self,
        msg: dict[str, Any],
        replies: list[str],
        matched_name: str,
        rule_id: int | None,
        config: dict[str, Any],
        media_paths: list[str] | None = None,
        media_first: bool = False,
        deliveries: list[dict[str, str]] | None = None,
        direct_deliveries: list[dict[str, str]] | None = None,
        preserve_parts: bool = False,
        media_refund_inventory_id: int | None = None,
        _execute_media_now: bool = False,
        _media_lock_held: bool = False,
    ) -> bool:
        rp_passive_reply = matched_name in {
            "RP监控", "RP观众消息", "发布向导", "需求发布草稿", "服务发布草稿"
        }
        if (
            config.get("dzmm", {}).get("require_slash_prefix", True)
            and not (msg.get("text") or "").strip().startswith("/")
            and not rp_passive_reply
        ):
            self.logger.warning("已拦截一次非 / 消息回复请求，这是安全保护。")
            self.db.mark_message_processed(msg["message_id"], "普通聊天忽略", "")
            return False
        can_send, send_reason = self.safety.can_send()
        if not can_send:
            self.logger.warning(f"回复被安全限制拦截：{send_reason}")
            self.db.mark_message_processed(msg["message_id"], matched_name, "")
            return False
        if media_paths and not _execute_media_now:
            # 图片上传最慢时会等待网页完成预览和按钮激活。把整组图文交给
            # 独立任务，避免占住消息扫描循环；任务内部仍保留原有图文顺序。
            task = asyncio.create_task(
                self._send_replies(
                    msg,
                    replies,
                    matched_name,
                    rule_id,
                    config,
                    media_paths=list(media_paths),
                    media_first=media_first,
                    deliveries=list(deliveries or []),
                    direct_deliveries=list(direct_deliveries or []),
                    preserve_parts=preserve_parts,
                    media_refund_inventory_id=media_refund_inventory_id,
                    _execute_media_now=True,
                )
            )
            self._track_media_task(task)
            return True
        if media_paths and _execute_media_now and not _media_lock_held:
            target_group = str(
                msg.get("group_key") or msg.get("source_group") or "main"
            )
            async with self.media_delivery_locks.setdefault(
                target_group, asyncio.Lock()
            ):
                return await self._send_replies(
                    msg,
                    replies,
                    matched_name,
                    rule_id,
                    config,
                    media_paths=media_paths,
                    media_first=media_first,
                    deliveries=deliveries,
                    direct_deliveries=direct_deliveries,
                    preserve_parts=preserve_parts,
                    media_refund_inventory_id=media_refund_inventory_id,
                    _execute_media_now=True,
                    _media_lock_held=True,
                )
        # AI and traditional commands share one hard two-page budget.  Keeping
        # caller-provided parts here would let an AI response bypass that cap.
        replies = prepare_outgoing_text_sequence(replies)
        sent = []

        async def send_media_items() -> bool:
            for media_path in media_paths or []:
                await asyncio.sleep(float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5))
                try:
                    ok = await asyncio.wait_for(
                        self._adapter_send_image(
                            media_path,
                            str(msg.get("group_key") or msg.get("source_group") or "main"),
                        ),
                        timeout=95,
                    )
                except asyncio.TimeoutError:
                    ok = False
                    self.logger.error(f"图片发送超时：文件={media_path}")
                except Exception as exc:
                    ok = False
                    self.logger.error(f"图片发送异常：文件={media_path}；错误={exc}")
                record_text = f"[图片] {media_path}"
                self.db.record_reply(msg["message_id"], rule_id, msg, record_text, ok)
                if ok:
                    self.image_fail_count = 0
                    sent.append(record_text)
                    continue
                self.image_fail_count += 1
                self.logger.error(
                    f"图片发送失败：图片通道连续失败 {self.image_fail_count} 次，"
                    f"消息ID={msg.get('message_id', '')}，文件={media_path}"
                )
                return False
            return True

        media_ok = True
        if media_first:
            media_ok = await send_media_items()
        # 图片失败不能吞掉已经结算完成的游戏文本；文字通道独立继续发送。
        all_text_sent = True
        for reply in replies:
            if not all_text_sent:
                break
            can_send, send_reason = self.safety.can_send()
            if not can_send:
                self.logger.warning(f"后续回复被安全限制拦截：{send_reason}")
                all_text_sent = False
                break
            await asyncio.sleep(float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5))
            if str(msg.get("source_type") or "") == "direct":
                ok = await self._adapter_send_direct_message(
                    str(msg.get("chatroom_id") or ""), reply
                )
            else:
                ok = await self._adapter_send_message(
                    reply,
                    str(msg.get("group_key") or msg.get("source_group") or "main"),
                )
            self.db.record_reply(msg["message_id"], rule_id, msg, reply, ok)
            if ok:
                self.fail_count = 0
                sent.append(reply)
            else:
                all_text_sent = False
                self.fail_count += 1
                self.logger.error(f"发送失败：连续失败 {self.fail_count} 次，消息ID={msg.get('message_id', '')}，匹配={matched_name}")
                if self.fail_count >= 3:
                    self.pause("文字连续发送失败 3 次", auto_resume_seconds=30)
                    break
        if all_text_sent and not media_first:
            media_ok = await send_media_items()
        if all_text_sent:
            for delivery in deliveries or []:
                target_group = str(delivery.get("group_key") or "main")
                target_text = str(delivery.get("text") or "")
                if not target_text:
                    continue
                for target_part in prepare_outgoing_text_messages(target_text):
                    can_send, send_reason = self.safety.can_send()
                    if not can_send:
                        self.logger.warning(f"跨群后续回复被安全限制拦截：{send_reason}")
                        all_text_sent = False
                        break
                    await asyncio.sleep(
                        float(config.get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5)
                    )
                    ok = await self._adapter_send_message(target_part, target_group)
                    record_text = f"[{target_group}] {target_part}"
                    self.db.record_reply(
                        msg["message_id"], rule_id, msg, record_text, ok
                    )
                    if ok:
                        self.fail_count = 0
                        sent.append(record_text)
                        continue
                    all_text_sent = False
                    self.fail_count += 1
                    self.logger.error(
                        f"跨群发送失败：目标={target_group}，消息ID={msg.get('message_id', '')}"
                    )
                    if self.fail_count >= 3:
                        self.pause("文字连续发送失败 3 次", auto_resume_seconds=30)
                    break
                if not all_text_sent:
                    break
        if all_text_sent:
            for delivery in direct_deliveries or []:
                target_room = str(delivery.get("chatroom_id") or "")
                target_text = str(delivery.get("text") or "")
                for target_part in prepare_outgoing_text_messages(target_text):
                    ok = await self._adapter_send_direct_message(target_room, target_part)
                    self.db.record_reply(
                        msg["message_id"], rule_id, msg, f"[私聊] {target_part}", ok
                    )
                    if not ok:
                        all_text_sent = False
                        break
                if not all_text_sent:
                    break
        media_delivered = media_ok and (media_first or all_text_sent)
        if media_refund_inventory_id is not None and not media_delivered:
            if self.db.refund_inventory_image_use(media_refund_inventory_id):
                self.logger.warning(
                    f"图片发送失败，已退回图库物品：库存ID={media_refund_inventory_id}"
                )
        self.db.mark_message_processed(msg["message_id"], matched_name, "\n".join(sent))
        return all_text_sent and (media_ok or bool(replies))

    def _queue_tarot_request(
        self, msg: dict[str, Any], tarot_command, config: dict[str, Any]
    ) -> None:
        task = asyncio.create_task(
            self._run_tarot_request(msg, tarot_command, dict(config))
        )
        self.ai_request_tasks.add(task)
        task.add_done_callback(self.ai_request_tasks.discard)

    async def _run_tarot_request(
        self, msg: dict[str, Any], tarot_command, config: dict[str, Any]
    ) -> None:
        user_id = str(msg.get("platform_user_id") or msg.get("user_id") or "")
        user_lock = self.ai_user_locks.setdefault(user_id, asyncio.Lock())
        async with user_lock:
            prepared = self.tarot_service.prepare(msg, tarot_command)
            if not prepared.get("ok"):
                await self._send_replies(
                    msg, [str(prepared.get("reply") or "")], "塔罗牌", None, config
                )
                return

            # 这三个阶段故意拆开发送，顺序固定为牌面图片、抽牌文案、AI 解读。
            image_sent = await self._send_replies(
                msg,
                [],
                "塔罗牌牌面",
                None,
                config,
                media_paths=[prepared["image_path"]],
                _execute_media_now=True,
            )
            if not image_sent:
                await self._send_replies(
                    msg,
                    [self.tarot_service.error_reply(prepared, "fortune_image_error_reply")],
                    "塔罗牌图片失败",
                    None,
                    config,
                )
                return
            intro_sent = await self._send_replies(
                msg, [prepared["draw_reply"]], "塔罗牌抽牌提示", None, config
            )
            if not intro_sent:
                self.db.add_log("ERROR", "tarot", "塔罗牌抽牌提示发送失败，任务已停止且未扣款")
                return

            try:
                body = await asyncio.to_thread(self.tarot_service.generate, prepared)
            except Exception as exc:
                self.db.add_log(
                    "ERROR", "tarot", f"塔罗牌 AI 最终失败，未扣款且未占次数：{str(exc)[:500]}"
                )
                await self._send_replies(
                    msg,
                    [self.tarot_service.error_reply(prepared, "fortune_ai_error_reply")],
                    "塔罗牌AI失败",
                    None,
                    config,
                )
                return

            settled = self.tarot_service.settle(prepared, body)
            if not settled.get("ok"):
                key = (
                    "fortune_already_reply"
                    if settled.get("reason") == "already"
                    else "fortune_no_money_reply"
                )
                await self._send_replies(
                    msg,
                    [self.tarot_service.error_reply(prepared, key)],
                    "塔罗牌结算失败",
                    None,
                    config,
                )
                return

            final_text = self.tarot_service.final_text(
                prepared, body, int(settled["balance"])
            )
            reading_id = int(settled["reading"]["id"])
            self.db.update_fortune_reading_result(reading_id, final_text)
            result_sent = await self._send_replies(
                msg, [final_text], "塔罗牌占卜", None, config
            )
            if not result_sent:
                refunded = self.db.refund_fortune_reading(reading_id)
                self.db.add_log(
                    "ERROR",
                    "tarot",
                    f"塔罗牌结果发送失败；自动退款={'成功' if refunded else '失败'}；记录={reading_id}",
                )

    async def _handle_ai_request(
        self,
        msg: dict[str, Any],
        ai_command,
        config: dict[str, Any],
    ) -> None:
        if not ai_command.content:
            await self._send_replies(
                msg, [self.ai_service.empty_text()], "AI角色空命令", None, config
            )
            return
        try:
            task, created = self.ai_service.begin(msg, ai_command)
        except AIRequestRateLimitError as exc:
            reason = str(exc)
            self.db.mark_message_processed(msg["message_id"], "AI角色频率限制", reason)
            await self._send_replies(msg, [reason], "AI角色频率限制", None, config)
            return
        except Exception as exc:
            self.logger.error(f"AI任务创建失败：{exc}")
            await self._send_replies(
                msg,
                ["AI任务无法建立，请稍后再试。此次没有扣除功德。"],
                "AI角色失败",
                None,
                config,
            )
            return
        if not created:
            self.db.mark_message_processed(msg["message_id"], "AI重复消息", "")
            return

        allowed, reason = self.ai_service.store.can_start(task)
        if not allowed:
            self.ai_service.store.fail(task["task_id"], reason)
            await self._send_replies(msg, [reason], "AI角色不可用", None, config)
            return

        status_text = self.ai_service.status_text(task["mode"] == "thinking")
        status_sent = await self._adapter_send_message(
            status_text,
            str(msg.get("group_key") or msg.get("source_group") or "main"),
        )
        self.db.record_reply(msg["message_id"], None, msg, status_text, status_sent)
        if not status_sent:
            self.ai_service.store.fail(task["task_id"], "思考提示发送失败")
            self.db.mark_message_processed(msg["message_id"], "AI状态发送失败", "")
            return
        self.ai_service.store.mark_status_sent(task["task_id"])
        result = await self.ai_service.process_async(msg, task)
        sent = await self._send_replies(
            msg,
            result.replies,
            "AI角色" if result.success else "AI角色失败",
            None,
            config,
            media_paths=result.media_paths,
            media_first=result.media_first,
            deliveries=result.deliveries,
            preserve_parts=True,
        )
        if sent and result.task_id:
            self.ai_service.store.mark_result_sent(result.task_id)

    async def _queue_ai_request(
        self,
        msg: dict[str, Any],
        ai_command,
        config: dict[str, Any],
    ) -> None:
        settings = self.ai_service.store.settings()
        user_id = str(msg.get("platform_user_id") or msg.get("user_id") or "")
        group_id = str(msg.get("group_key") or msg.get("source_group") or "main")
        if self.ai_queue_counts.get(user_id, 0) >= max(1, int(settings["per_user_queue"])):
            await self._send_replies(msg, ["你已有AI请求正在排队，请等待上一项完成。"], "AI用户队列已满", None, config)
            return
        if self.ai_group_queue_counts.get(group_id, 0) >= max(1, int(settings["per_group_queue"])):
            await self._send_replies(msg, ["当前群的AI请求队列已满，请稍后再试。"], "AI群队列已满", None, config)
            return
        limits = (
            max(1, int(settings["normal_concurrency"])),
            max(1, int(settings["thinking_concurrency"])),
        )
        active_tasks = any(not task.done() for task in self.ai_request_tasks)
        if self.ai_normal_semaphore is None or (
            self.ai_semaphore_limits != limits and not active_tasks
        ):
            self.ai_normal_semaphore = asyncio.Semaphore(limits[0])
            self.ai_thinking_semaphore = asyncio.Semaphore(limits[1])
            self.ai_semaphore_limits = limits
        self.ai_queue_counts[user_id] = self.ai_queue_counts.get(user_id, 0) + 1
        self.ai_group_queue_counts[group_id] = self.ai_group_queue_counts.get(group_id, 0) + 1
        task = asyncio.create_task(
            self._run_queued_ai_request(msg, ai_command, dict(config), user_id, group_id)
        )
        self.ai_request_tasks.add(task)
        task.add_done_callback(self.ai_request_tasks.discard)

    async def _run_queued_ai_request(
        self,
        msg: dict[str, Any],
        ai_command,
        config: dict[str, Any],
        user_id: str,
        group_id: str,
    ) -> None:
        settings = self.ai_service.store.settings()
        is_thinking = bool(ai_command.thinking or settings["normal_thinking"])
        semaphore = self.ai_thinking_semaphore if is_thinking else self.ai_normal_semaphore
        user_lock = self.ai_user_locks.setdefault(user_id, asyncio.Lock())
        acquired_semaphore = False
        acquired_user = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(1, int(settings["queue_wait_seconds"]))
        try:
            await asyncio.wait_for(user_lock.acquire(), timeout=max(0.001, deadline - loop.time()))
            acquired_user = True
            # A later request from the same user must not occupy global model
            # capacity while it is only waiting for that user's earlier request.
            await asyncio.wait_for(semaphore.acquire(), timeout=max(0.001, deadline - loop.time()))
            acquired_semaphore = True
            await self._handle_ai_request(msg, ai_command, config)
        except asyncio.TimeoutError:
            await self._send_replies(msg, ["AI请求等待超时，请稍后重新发送。此次没有扣除功德。"], "AI排队超时", None, config)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.error(f"AI排队任务异常：{exc}")
            await self._send_replies(msg, ["AI任务发生异常，请稍后再试。此次没有扣除功德。"], "AI任务异常", None, config)
        finally:
            if acquired_user:
                user_lock.release()
            if acquired_semaphore:
                semaphore.release()
            user_count = max(0, self.ai_queue_counts.get(user_id, 1) - 1)
            group_count = max(0, self.ai_group_queue_counts.get(group_id, 1) - 1)
            if user_count:
                self.ai_queue_counts[user_id] = user_count
            else:
                self.ai_queue_counts.pop(user_id, None)
                if not user_lock.locked():
                    self.ai_user_locks.pop(user_id, None)
            if group_count:
                self.ai_group_queue_counts[group_id] = group_count
            else:
                self.ai_group_queue_counts.pop(group_id, None)

    async def _prime_messages(
        self,
        messages: list[dict[str, Any]] | None = None,
        group_key: str = "main",
    ) -> None:
        if messages is None:
            messages = await self._adapter_read_messages(group_key)
        for msg in messages:
            msg.setdefault("group_key", group_key)
            msg.setdefault("source_group", group_key)
            self._remember_seen(msg["message_id"])
            if not self._message_has_complete_identity(msg):
                source_key = self._baseline_source_key(msg)
                if source_key:
                    self.baseline_incomplete_source_keys.add(source_key)
            self.db.save_message(msg)
            self.db.mark_message_processed(msg["message_id"], "启动基线", "")
        if messages:
            self.last_message_time = messages[-1].get("time", "")
        self.logger.info("已建立消息基线，旧消息不会触发自动回复")
