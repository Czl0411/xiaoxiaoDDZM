from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.ai_interaction import AIInteractionError, DeepSeekClient
from app.ai_character import AICharacterService, AICharacterStore
from app.browser import BrowserController
from app.command_router import (
    CHURCH_THEME_FEATURES,
    SIX_SEAL_FEATURES,
    THEFT_FEATURES,
    CommandRouter,
)
from app.database import Database
from app.dzmm_adapter import DzmmAdapter
from app.fortune_today import FORTUNE_FEATURE_VERSION, TODAY_FORTUNE_FEATURES
from app.image_generation import (
    ALLOWED_IMAGE_RATIOS,
    DEFAULT_IMAGE_SETTINGS,
    Image2Client,
    ImageGenerationError,
    ImageGenerationService,
    merged_image_settings,
)
from app.logger import BotLogger
from app.outgoing_text import prepare_outgoing_text_messages
from app.rule_engine import RuleEngine
from app.scheduler import BotScheduler
from app.tarot_reading import TarotReadingService


SOURCE_DIR = Path(__file__).resolve().parent
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SOURCE_DIR
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", SOURCE_DIR))
DATA_DIR = Path(os.environ.get("DZMM_DATA_DIR", APP_DIR / "data")).resolve()
WEB_DIR = RESOURCE_DIR / "web"


def _resolve_runtime_asset_dir(name: str) -> Path:
    candidates = (
        RESOURCE_DIR / name,
        APP_DIR / name,
        SOURCE_DIR.parent / name,
    )
    return next((path for path in candidates if path.is_dir()), candidates[0])


async def _send_adapter_text_messages(
    adapter,
    db,
    text: str,
    group_key: str = "main",
) -> bool:
    parts = prepare_outgoing_text_messages(text)
    if not parts:
        return False
    delay = float(
        db.get_config().get("dzmm", {}).get("send_delay_seconds", 1.5) or 1.5
    )
    for index, part in enumerate(parts):
        if index:
            await asyncio.sleep(delay)
        try:
            ok = await adapter.send_message(part, group_key=group_key)
        except TypeError as exc:
            if "group_key" not in str(exc):
                raise
            ok = await adapter.send_message(part)
        if not ok:
            return False
    return True


def _split_command_triggers(value: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,，\n]+", value or "") if x.strip()]


def _validate_command_triggers(value: str) -> None:
    triggers = _split_command_triggers(value)
    if not triggers:
        raise HTTPException(400, "命令不能为空")
    invalid = [item for item in triggers if not item.startswith("/")]
    if invalid:
        raise HTTPException(400, "每个命令都必须以 / 开头，多个命令请用逗号分隔")


class RulePayload(BaseModel):
    name: str
    enabled: bool = True
    priority: int = 0
    group_name: str = ""
    trigger_type: str = "exact"
    trigger_value: str
    reply_content: str
    reply_mode: str = "fixed"
    scope_type: str = "all"
    scope_value: str = ""
    exclude_users: str = ""
    rule_cooldown_seconds: int = 0
    user_cooldown_seconds: int = 0
    global_cooldown_seconds: int = 0
    daily_max_hits: int = 0
    allow_self: bool = False
    require_admin: bool = False
    note: str = ""


class TestRulePayload(BaseModel):
    sender: str
    text: str


class SendTestPayload(BaseModel):
    text: str


class CompensationPayload(BaseModel):
    request_id: str
    amount: int
    reason: str = "系统更新期间部分功能暂时不可用"
    notification_template: str


class FacilityWageRulePayload(BaseModel):
    keyword: str
    amount: int = 10
    enabled: bool = True
    sort_order: int = 0


class CraftingRecipePayload(BaseModel):
    id: int | None = None
    source_item_id: int
    source_quantity: int
    target_item_id: int
    target_quantity: int = 1
    per_user_limit: int = 0
    enabled: bool = True


class DropPoolEntryPayload(BaseModel):
    id: int | None = None
    item_id: int
    chance_percent: float
    min_quantity: int = 1
    max_quantity: int = 1
    deduct_stock: bool = False
    enabled: bool = True
    reply_template: str = ""
    sort_order: int = 0


class ExchangeOfferPayload(BaseModel):
    id: int | None = None
    code: str = ""
    name: str
    description: str = ""
    limit_type: str = "weekly"
    weekly_limit: int = 1
    enabled: bool = True
    sort_order: int = 0
    success_reply: str = ""
    costs: list[dict]
    rewards: list[dict]


class ShopItemPayload(BaseModel):
    id: int | None = None
    name: str
    item_category: str = "normal"
    special_kind: str = ""
    description: str = ""
    price: int = 0
    stock: int = -1
    enabled: bool = True
    sort_order: int = 0
    use_enabled: bool = True
    use_reply_template: str = ""
    status_template: str = ""
    remove_price: int = 5
    use_target: str = "other"
    direct_use_reply_template: str = ""
    self_use_reply_template: str = ""
    self_status_template: str = ""
    image_folder: str = ""



class UserPayload(BaseModel):
    nickname: str
    user_id: str = ""
    platform_user_id: str = ""
    avatar_id: str = ""
    identity_status: str = "pending"
    identity_conflict_reason: str = ""
    display_name: str = ""
    nickname_history: str = ""
    is_admin: bool = False
    message_count: int = 0
    hit_count: int = 0
    points: int = 0
    streak_days: int = 0
    total_checkins: int = 0
    last_checkin_date: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None


class StatusPayload(BaseModel):
    item_name: str
    status_text: str
    remove_price: int = 5
    active: bool = True


class InventoryUpdatePayload(BaseModel):
    item_name: str
    quantity: int = 0


PAID_INTERACTION_SETTING_KEYS = {
    "paid_interaction_enable_commands",
    "paid_interaction_disable_commands",
    "paid_interaction_amount",
    "paid_interaction_min_balance",
    "paid_interaction_ai_enabled",
    "paid_interaction_ai_base_url",
    "paid_interaction_ai_model",
    "paid_interaction_ai_temperature",
    "paid_interaction_ai_max_tokens",
    "paid_interaction_ai_max_output_chars",
    "paid_interaction_ai_timeout_seconds",
    "paid_interaction_max_action_chars",
    "paid_interaction_ai_system_prompt",
    "paid_interaction_ai_user_prompt",
    "paid_interaction_ai_disabled_reply",
    "paid_interaction_ai_not_configured_reply",
    "paid_interaction_ai_error_reply",
    "paid_interaction_action_too_long_reply",
    "paid_interaction_settlement_footer",
    "paid_interaction_enabled_reply",
    "paid_interaction_disabled_reply",
    "paid_interaction_target_disabled_reply",
    "paid_interaction_usage_reply",
    "paid_interaction_target_not_found_reply",
    "paid_interaction_identity_invalid_reply",
    "paid_interaction_self_reply",
    "paid_interaction_limit_reply",
}

FORTUNE_SETTING_KEYS = {
    "fortune_feature_version",
    "fortune_commands",
    "fortune_enabled",
    "fortune_reader_name",
    "fortune_cost",
    "fortune_daily_limit",
    "fortune_ai_base_url",
    "fortune_ai_model",
    "fortune_ai_temperature",
    "fortune_ai_max_tokens",
    "fortune_ai_max_output_chars",
    "fortune_ai_timeout_seconds",
    "fortune_ai_system_prompt",
    "fortune_ai_user_prompt",
    "fortune_ai_repair_prompt",
    "fortune_draw_reply",
    "fortune_usage_reply",
    "fortune_topic_too_long_reply",
    "fortune_disabled_reply",
    "fortune_identity_invalid_reply",
    "fortune_already_reply",
    "fortune_no_money_reply",
    "fortune_ai_not_configured_reply",
    "fortune_image_error_reply",
    "fortune_ai_error_reply",
    "fortune_format_error_reply",
    "fortune_settlement_footer",
}

BOUNTY_SETTING_KEYS = {
    "bounty_enabled",
    "bounty_invite_url",
    "bounty_publisher_cancel_compensation_percent",
    "bounty_publish_commands",
    "bounty_list_commands",
    "bounty_next_page_commands",
    "bounty_detail_commands",
    "bounty_accept_commands",
    "bounty_my_commands",
    "bounty_complete_commands",
    "bounty_confirm_commands",
    "bounty_cancel_commands",
    "bounty_ai_draft_ttl_seconds",
    "bounty_ai_base_url",
    "bounty_ai_model",
    "bounty_ai_timeout_seconds",
    "bounty_ai_system_prompt",
    "bounty_ai_user_prompt",
    "bounty_ai_failure_reply",
    "bounty_ai_not_configured_reply",
    "bounty_ai_error_reply",
    "bounty_ai_preview_reply",
    "bounty_ai_published_reply",
    "bounty_ai_cancelled_reply",
    "bounty_ai_expired_reply", "bounty_ai_missing_reply", "bounty_ai_invalid_reply",
    "bounty_business_error_reply",
    "bounty_help_reply", "bounty_disabled_reply", "bounty_group_only_reply",
    "bounty_card_reply", "bounty_card_accept_line", "bounty_synced_reply",
    "bounty_list_header_reply", "bounty_list_item_reply", "bounty_list_empty_reply", "bounty_list_footer_reply",
    "bounty_detail_usage_reply", "bounty_detail_not_found_reply",
    "bounty_accept_usage_reply", "bounty_accept_not_found_reply", "bounty_accept_not_waiting_reply",
    "bounty_accept_duplicate_reply", "bounty_accept_full_reply", "bounty_accept_self_reply",
    "bounty_accept_banned_reply", "bounty_accept_failed_reply", "bounty_accept_success_reply",
    "bounty_my_header_reply", "bounty_my_published_header_reply", "bounty_my_taken_header_reply",
    "bounty_my_item_reply", "bounty_my_empty_reply",
    "bounty_complete_usage_reply", "bounty_complete_not_found_reply", "bounty_complete_not_taker_reply",
    "bounty_complete_already_reply", "bounty_complete_invalid_reply", "bounty_complete_failed_reply",
    "bounty_complete_partial_reply", "bounty_complete_all_reply", "bounty_complete_individual_reply",
    "bounty_confirm_usage_reply", "bounty_confirm_not_found_reply", "bounty_confirm_not_publisher_reply",
    "bounty_confirm_invalid_reply", "bounty_confirm_failed_reply", "bounty_confirm_success_reply",
    "bounty_confirm_partial_success_reply", "bounty_confirm_final_success_reply",
    "bounty_cancel_usage_reply", "bounty_cancel_not_found_reply", "bounty_cancel_invalid_reply",
    "bounty_cancel_not_party_reply", "bounty_cancel_not_publisher_reply", "bounty_cancel_failed_reply",
    "bounty_cancel_success_reply", "bounty_cancel_abandonment_reply", "bounty_cancel_ban_reply",
    "bounty_cancel_partial_success_reply",
}
BOUNTY_SETTING_KEYS.update({
    "commission_feature_version",
    "commission_request_publish_commands", "commission_service_publish_commands",
    "commission_confirm_draft_commands", "commission_cancel_draft_commands",
    "commission_request_list_commands", "commission_service_list_commands",
    "commission_request_detail_commands", "commission_service_detail_commands",
    "commission_request_accept_commands", "commission_service_accept_commands",
    "commission_my_posts_commands", "commission_my_demands_commands",
    "commission_my_services_commands", "commission_my_orders_commands",
    "commission_order_detail_commands", "commission_order_complete_commands",
    "commission_order_confirm_commands", "commission_order_cancel_commands",
    "commission_order_cancel_approve_commands", "commission_order_cancel_reject_commands",
    "commission_close_request_commands", "commission_close_service_commands",
    "commission_service_restock_commands", "commission_service_renew_commands",
    "commission_help_commands", "commission_main_group_only_reply",
    "commission_bounty_group_only_reply", "commission_request_preview_reply",
    "commission_service_preview_reply", "commission_published_reply",
    "commission_draft_cancelled_reply", "commission_draft_missing_reply",
    "commission_draft_expired_reply", "commission_request_list_header_reply",
    "commission_request_list_item_reply", "commission_request_list_empty_reply",
    "commission_request_list_footer_reply", "commission_service_list_header_reply",
    "commission_service_list_item_reply", "commission_service_list_empty_reply",
    "commission_service_list_footer_reply", "commission_legacy_service_item_reply",
    "commission_legacy_service_footer_reply", "commission_request_card_reply",
    "commission_service_card_reply", "commission_order_created_reply",
    "commission_order_complete_reply", "commission_order_confirm_reply",
    "commission_order_cancel_requested_reply", "commission_order_cancel_approved_reply",
    "commission_order_cancel_rejected_reply", "commission_order_error_reply",
    "commission_post_closed_reply", "commission_help_reply",
    "commission_demand_fee_percent", "commission_demand_min_reward",
    "commission_demand_max_people", "commission_demand_default_recruitment_days",
    "commission_service_commission_percent", "commission_service_min_price",
    "commission_service_default_stock", "commission_service_max_stock",
    "commission_service_default_listing_days", "commission_service_max_active",
    "commission_demand_ai_system_prompt", "commission_demand_ai_user_prompt",
    "commission_service_ai_system_prompt", "commission_service_ai_user_prompt",
})

MARKET_SETTING_KEYS = {
    "market_enabled",
    "market_list_commands",
    "market_help_commands",
    "market_create_commands",
    "market_confirm_create_commands",
    "market_cancel_create_commands",
    "market_edit_commands",
    "market_confirm_edit_commands",
    "market_cancel_edit_commands",
    "market_detail_commands",
    "market_purchase_commands",
    "market_mine_commands",
    "market_off_shelf_commands",
    "market_renew_commands",
    "market_default_commission_percent",
    "market_max_active_listings",
    "market_default_stock",
    "market_default_duration_days",
    "market_min_price",
    "market_max_price",
    "market_page_size",
    "market_max_stock",
    "market_max_duration_days",
    "market_draft_ttl_seconds",
    "market_ai_base_url",
    "market_ai_model",
    "market_ai_timeout_seconds",
    "market_ai_system_prompt",
    "market_ai_user_prompt",
    "market_disabled_reply",
    "market_ai_not_configured_reply",
    "market_ai_error_reply",
    "market_draft_cancelled_reply",
    "market_draft_missing_reply",
    "market_draft_preview_reply",
    "market_created_reply",
    "market_updated_reply",
    "market_list_header_reply",
    "market_list_item_reply",
    "market_list_empty_reply",
    "market_list_footer_reply",
    "market_detail_reply",
    "market_purchase_reply",
    "market_off_shelf_reply",
    "market_renewed_reply",
    "market_help_reply",
}

RP_SETTING_KEYS = {
    "rp_enabled", "rp_max_participants", "rp_gather_timeout_seconds",
    "rp_start_reply", "rp_progress_reply", "rp_last_reply",
    "rp_announcement_reply", "rp_yellow_warning_reply",
    "rp_second_violation_reply", "rp_later_violation_reply",
    "rp_end_reply", "rp_timeout_reply",
}

RANDOM_EVENT_SETTING_KEYS = {
    "random_event_enabled", "random_event_create_commands", "random_event_confirm_commands",
    "random_event_cancel_commands", "random_event_start_commands", "random_event_status_commands",
    "random_event_join_commands", "random_event_leave_commands", "random_event_end_commands",
    "random_event_reward_commands", "random_event_recruit_timeout_seconds",
    "random_event_draft_ttl_seconds", "random_event_auto_enabled",
    "random_event_auto_daily_count", "random_event_auto_times",
    "random_event_ai_base_url", "random_event_ai_model", "random_event_ai_timeout_seconds",
    "random_event_ai_system_prompt", "random_event_ai_user_prompt",
    "random_event_admin_only_reply", "random_event_disabled_reply",
    "random_event_create_usage_reply", "random_event_ai_not_configured_reply",
    "random_event_ai_error_reply", "random_event_draft_preview_reply",
    "random_event_created_reply", "random_event_draft_cancelled_reply",
    "random_event_draft_missing_reply", "random_event_library_empty_reply",
    "random_event_busy_reply", "random_event_rp_busy_reply", "random_event_recruit_reply",
    "random_event_join_success_reply", "random_event_join_duplicate_reply",
    "random_event_join_role_taken_reply", "random_event_join_invalid_role_reply",
    "random_event_open_reply", "random_event_status_reply", "random_event_leave_reply",
    "random_event_end_reply", "random_event_cancelled_reply", "random_event_timeout_reply",
    "random_event_reward_usage_reply", "random_event_reward_success_reply",
    "random_event_reward_missing_reply",
}

IMAGE_GENERATION_SETTING_KEYS = set(DEFAULT_IMAGE_SETTINGS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "logs").mkdir(exist_ok=True)
    (DATA_DIR / "browser_profile").mkdir(exist_ok=True)

    db = Database(DATA_DIR / "bot.db")
    db.init()
    db.repair_paid_interaction_mojibake()
    config = db.get_config()
    old_fortune_version = str(config.get("features", {}).get("fortune_feature_version") or "")
    if old_fortune_version != FORTUNE_FEATURE_VERSION:
        # v2 只更新主持人、输出长度和抽牌文案，保留管理员已经设置的费用、次数与连接信息。
        if old_fortune_version == "tarot-reading-v1":
            migration_keys = {
                "fortune_feature_version", "fortune_ai_max_output_chars",
                "fortune_ai_system_prompt", "fortune_ai_user_prompt",
                "fortune_ai_repair_prompt", "fortune_draw_reply",
            }
            updates = {key: TODAY_FORTUNE_FEATURES[key] for key in migration_keys}
        else:
            updates = TODAY_FORTUNE_FEATURES
        # 今日运势被塔罗牌完整替换；仅迁移这一组配置，不触碰付费互动提示词。
        config["features"] = {**config.get("features", {}), **updates}
        help_reply = str(config["features"].get("help_reply") or "")
        help_reply = help_reply.replace("/今日运势：事项", "/塔罗牌：事项")
        help_reply = help_reply.replace("/今日运势", "/塔罗牌")
        help_reply = help_reply.replace(" /测运势", "").replace(" /测字", "")
        config["features"]["help_reply"] = help_reply
        db.save_config(config)
    if str(config.get("features", {}).get("church_theme_version") or "") != CHURCH_THEME_FEATURES["church_theme_version"]:
        config["features"] = {**config.get("features", {}), **CHURCH_THEME_FEATURES}
        db.save_config(config)
    if str(config.get("features", {}).get("theft_feature_version") or "") != THEFT_FEATURES["theft_feature_version"]:
        config["features"] = {**config.get("features", {}), **THEFT_FEATURES}
        help_reply = str(config["features"].get("help_reply") or "")
        if "/偷窃" not in help_reply:
            config["features"]["help_reply"] = help_reply + "{newline}/偷窃 昵称 - 每日最多两次的趣味功德点互动"
        db.save_config(config)
    if str(config.get("features", {}).get("six_seal_feature_version") or "") != SIX_SEAL_FEATURES["six_seal_feature_version"]:
        config["features"] = {**config.get("features", {}), **SIX_SEAL_FEATURES}
        help_reply = str(config["features"].get("help_reply") or "")
        help_reply = help_reply.replace(
            "/揭印 1～5 - 在六印圣裁中接受本轮考验",
            "/1～/5 - 在欲望圣裁中选择连续按压次数",
        )
        help_reply = help_reply.replace(
            "/1～/5 - 在六印圣裁中选择连续揭印数量",
            "/1～/5 - 在欲望圣裁中选择连续按压次数",
        )
        help_reply = help_reply.replace(
            "/六印圣裁 - 发起两人自愿仪式，5分钟内发送 /加入",
            "/六印圣裁 - 发起两人欲望圣裁，加入后随机一名真实男性",
        )
        if "/六印圣裁" not in help_reply:
            config["features"]["help_reply"] = (
                help_reply
                + "{newline}/六印圣裁 - 发起两人欲望圣裁，加入后随机一名真实男性"
                + "{newline}/1～/5 - 在欲望圣裁中选择连续按压次数"
                + "{newline}/圣裁状态 - 查看当前仪式状态"
            )
        else:
            config["features"]["help_reply"] = help_reply
        db.save_config(config)
    help_reply = str(config.get("features", {}).get("help_reply") or "")
    if "/发起奴隶契约" not in help_reply:
        config["features"]["help_reply"] = (
            help_reply
            + "{newline}/发起奴隶契约 对方称呼 金额 - 申请 1～100 功德点借款"
            + "{newline}/同意 - 同意当前奴隶契约申请"
            + "{newline}/还款 - 全额偿还并解除奴隶契约"
        )
        db.save_config(config)
    help_reply = str(config.get("features", {}).get("help_reply") or "")
    if "/拒绝" not in help_reply:
        config["features"]["help_reply"] = help_reply + "{newline}/拒绝 - 拒绝当前奴隶契约申请"
        db.save_config(config)
    old_public_lender_reply = "📣 奴隶契约公开招收：{lender} 正在寻找一名负债奴隶。负债用户可在 10 分钟内直接发送 /同意；成立时 {lender} 会替接受者补足欠款到 0，实际金额以接受时的负债为准。"
    if config.get("features", {}).get("slave_contract_public_lender_reply") == old_public_lender_reply:
        from app.command_router import DEFAULTS
        config["features"]["slave_contract_public_lender_reply"] = DEFAULTS["slave_contract_public_lender_reply"]
        db.save_config(config)
    old_special_reply = "🕯️ {user} 撕开「恶棍的绝对掠夺」，趁圣像转身的半秒从 {target} 那里卷走 {amount} {currency}！道具已化成一缕黑烟。{user} 当前 {actor_balance}，{target} 当前 {target_balance}。"
    if config.get("features", {}).get("theft_special_success_reply") == old_special_reply:
        config["features"]["theft_special_success_reply"] = THEFT_FEATURES["theft_special_success_reply"]
        db.save_config(config)
    db.ensure_theft_shop_items()
    db.ensure_requested_economy_items()
    config = db.get_config()
    features = config.setdefault("features", {})
    if int(features.get("fee_policy_version", 0) or 0) < 1:
        features["paid_interaction_loss_amount"] = 5
        features["six_seal_normal_min_commission"] = 0
        features["six_seal_high_priest_min_commission"] = 0
        for key in (
            "six_seal_failed_reply",
            "six_seal_final_reply",
            "six_seal_high_priest_failed_reply",
            "six_seal_high_priest_final_reply",
        ):
            features[key] = SIX_SEAL_FEATURES[key]
        features["fee_policy_version"] = 1
    help_reply = str(features.get("help_reply") or "")
    if "/兑换仓库" not in help_reply:
        features["help_reply"] = (
            help_reply
            + "{newline}/兑换仓库 - 查看收藏品兑换项目"
            + "{newline}/兑换1 - 按编号主动兑换"
        )
    shop_footer = str(features.get("shop_footer") or "")
    if "/购买7*10" not in shop_footer:
        features["shop_footer"] = (
            shop_footer.rstrip("。 ")
            + "；批量购买请发送 /购买7*10，例如一次购买第7件商品10个。"
        ).lstrip("；")
    buy_usage = str(features.get("buy_usage_reply") or "")
    if "/购买7*10" not in buy_usage:
        features["buy_usage_reply"] = (
            buy_usage.rstrip("。 ") + "；批量购买请发送 /购买7*10。"
        ).lstrip("；")
    old_purchase_templates = {
        "{user}，购买成功：{item}，花费 {price} {currency}，余额 {balance} {currency}。",
        "📦 {user} 从神殿仓库领取了「{item}」，消耗 {price} {currency}，剩余 {balance} {currency}。",
    }
    if features.get("purchase_success_reply") in old_purchase_templates:
        features["purchase_success_reply"] = (
            "📦 {user} 从神殿仓库领取了「{item}」x{quantity}，"
            "共消耗 {price} {currency}，剩余 {balance} {currency}。"
        )
    db.save_config(config)
    db.ensure_default_rules()
    logger = BotLogger(DATA_DIR / "logs", db)
    browser = BrowserController(DATA_DIR, logger)
    adapter = DzmmAdapter(browser, db, logger)
    image_generation_service = ImageGenerationService(db, adapter, logger, DATA_DIR)
    engine = RuleEngine(db)
    command_router = CommandRouter(
        db,
        game_asset_dir=_resolve_runtime_asset_dir("猜乳贴游戏素材"),
        blind_box_asset_dir=_resolve_runtime_asset_dir("盲盒小游戏素材"),
    )
    ai_service = AICharacterService(db, command_router)
    ai_service.store.apply_fee_policy_v1()
    tarot_asset_dir = _resolve_runtime_asset_dir("塔罗牌素材")
    tarot_service = TarotReadingService(db, tarot_asset_dir)
    scheduler = BotScheduler(
        db, adapter, engine, logger, command_router, ai_service, tarot_service,
        image_generation_service,
    )

    app.state.db = db
    app.state.logger = logger
    app.state.browser = browser
    app.state.adapter = adapter
    app.state.engine = engine
    app.state.command_router = command_router
    app.state.ai_service = ai_service
    app.state.tarot_service = tarot_service
    app.state.image_generation_service = image_generation_service
    app.state.scheduler = scheduler
    app.state.last_heartbeat = time.time()
    app.state.close_requested_at = 0.0

    async def shutdown_monitor():
        while True:
            await asyncio.sleep(1)
            close_requested_at = float(getattr(app.state, "close_requested_at", 0.0) or 0.0)
            last_heartbeat = float(getattr(app.state, "last_heartbeat", 0.0) or 0.0)
            now = time.time()
            if close_requested_at and now - close_requested_at > 5 and now - last_heartbeat > 5:
                logger.info("管理页面已关闭，正在自动退出服务。")
                await scheduler.stop()
                await browser.stop()
                db.close()
                os._exit(0)

    app.state.shutdown_monitor_task = asyncio.create_task(shutdown_monitor())

    await browser.start()
    await image_generation_service.recover_interrupted()
    initial_config = db.get_config()
    try:
        if initial_config.get("dzmm", {}).get("lock_group_urls", False) and initial_config.get("dzmm", {}).get("group_url"):
            await adapter.open_group(initial_config["dzmm"]["group_url"], "main")
            bounty_group_url = str(
                initial_config.get("dzmm", {}).get("bounty_group_url") or ""
            ).strip()
            if bounty_group_url:
                await adapter.open_group(bounty_group_url, "bounty")
            image_group_url = str(
                initial_config.get("dzmm", {}).get("image_group_url") or ""
            ).strip()
            if image_group_url:
                await adapter.open_group(image_group_url, "image")
        elif initial_config.get("dzmm", {}).get("home_url"):
            await adapter.open_home()
    except Exception as exc:
        logger.error(f"启动时打开 DZMM 页面失败，服务将继续启动：{exc}")
    await scheduler.start()
    if initial_config.get("ui", {}).get("auto_open_manager", True) and os.environ.get("DZMM_SKIP_AUTO_OPEN") != "1":
        webbrowser.open("http://127.0.0.1:7902")
    yield
    app.state.shutdown_monitor_task.cancel()
    await scheduler.stop()
    await browser.stop()
    db.close()


app = FastAPI(title="DZMM 网页群聊机器人", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.middleware("http")
async def disable_manager_cache(request, call_next):
    """管理页更新频繁，避免新 HTML 与旧静态脚本混用。"""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/status")
async def status():
    logged_in = await app.state.adapter.is_logged_in()
    bounty_group_url = str(
        app.state.db.get_config().get("dzmm", {}).get("bounty_group_url") or ""
    ).strip()
    bounty_logged_in = (
        await app.state.adapter.is_logged_in("bounty") if bounty_group_url else False
    )
    image_group_url = str(
        app.state.db.get_config().get("dzmm", {}).get("image_group_url") or ""
    ).strip()
    image_logged_in = (
        await app.state.adapter.is_logged_in("image") if image_group_url else False
    )
    return {
        "status": app.state.scheduler.status(),
        "logged_in": logged_in,
        "bounty_logged_in": bounty_logged_in,
        "image_logged_in": image_logged_in,
        "image_generation": app.state.image_generation_service.status(),
        "settings": app.state.db.get_config(),
        "logs": app.state.db.list_logs(limit=10),
        "rule_count": app.state.db.count_enabled_rules(),
        "today_reply_count": app.state.db.count_today_replies(),
        "recent_messages": app.state.db.list_messages(limit=10),
    }


@app.get("/api/config")
async def get_config():
    config = app.state.db.get_config()
    from app.command_router import DEFAULTS
    config["features"] = {**DEFAULTS, **config.get("features", {})}
    return config


@app.post("/api/app/heartbeat")
async def app_heartbeat():
    app.state.last_heartbeat = time.time()
    app.state.close_requested_at = 0.0
    return {"ok": True}


@app.post("/api/app/client-closed")
async def app_client_closed():
    app.state.close_requested_at = time.time()
    return {"ok": True}


@app.post("/api/config")
async def save_config(payload: dict):
    app.state.db.save_config(payload)
    app.state.logger.info("设置已保存")
    return {"ok": True, "message": "设置已保存"}


@app.post("/api/browser/open-home")
async def open_home():
    await app.state.adapter.open_home()
    return {"ok": True, "message": "已打开 DZMM 首页"}


@app.post("/api/browser/open-group")
async def open_group(payload: dict):
    url = payload.get("url") or app.state.db.get_config().get("dzmm", {}).get("group_url")
    group_key = str(payload.get("group_key") or "main")
    if not url:
        raise HTTPException(400, "请先填写群聊地址")
    await app.state.adapter.open_group(url, group_key)
    return {"ok": True, "message": "已打开群聊"}


@app.post("/api/browser/group-url-lock")
async def set_group_url_lock(payload: dict):
    enabled = bool(payload.get("enabled", False))
    config = app.state.db.get_config()
    config.setdefault("dzmm", {})["lock_group_urls"] = enabled
    # 旧开关只保留配置兼容，不再参与真实跳转判断。
    config["dzmm"]["auto_open_group"] = False
    app.state.db.save_config(config)
    if enabled:
        main_url = str(config["dzmm"].get("group_url") or "").strip()
        bounty_url = str(config["dzmm"].get("bounty_group_url") or "").strip()
        image_url = str(config["dzmm"].get("image_group_url") or "").strip()
        if main_url:
            await app.state.adapter.open_group(main_url, "main")
            app.state.scheduler.primed_groups.discard("main")
        if bounty_url:
            await app.state.adapter.open_group(bounty_url, "bounty")
            app.state.scheduler.primed_groups.discard("bounty")
        if image_url:
            await app.state.adapter.open_group(image_url, "image")
            app.state.scheduler.primed_groups.discard("image")
    app.state.logger.info("群聊地址自动锁定已" + ("开启" if enabled else "关闭"))
    return {
        "ok": True,
        "enabled": enabled,
        "message": "已开启群聊地址自动锁定" if enabled else "已关闭群聊地址自动锁定，可正常停留在登录页",
    }


@app.get("/api/browser/login-status")
async def login_status():
    page_state = await app.state.adapter.debug_page_state()
    logged_in = await app.state.adapter.is_logged_in()
    return {
        "logged_in": logged_in,
        "url": page_state.get("url", ""),
        "title": page_state.get("title", ""),
        "hint": "已进入群聊，可以读取消息" if logged_in else "机器人浏览器未登录 DZMM。请在机器人浏览器里登录一次。",
    }


@app.post("/api/browser/detect-selectors")
async def detect_selectors():
    selectors = await app.state.adapter.detect_selectors()
    config = app.state.db.get_config()
    config["selectors"] = {**config.get("selectors", {}), **selectors}
    app.state.db.save_config(config)
    return {"ok": True, "message": "页面选择器已保存", "selectors": selectors}


@app.post("/api/browser/reset-profile")
async def reset_profile():
    await app.state.adapter.close()
    await app.state.browser.reset_profile()
    await app.state.adapter.open_home()
    app.state.logger.info("登录状态已重置，请重新登录 DZMM")
    return {"ok": True, "message": "登录状态已重置，已重新打开 DZMM"}


@app.post("/api/bot/pause")
async def pause_bot():
    app.state.scheduler.pause("用户手动暂停")
    return {"ok": True}


@app.post("/api/bot/resume")
async def resume_bot():
    app.state.scheduler.resume()
    return {"ok": True}


@app.post("/api/bot/emergency-stop")
async def emergency_stop():
    app.state.scheduler.emergency_stop()
    return {"ok": True}


@app.post("/api/messages/read-test")
async def read_test():
    if not await app.state.adapter.is_logged_in():
        return {"ok": False, "messages": [], "error": "机器人浏览器未登录 DZMM，无法读取群聊消息。请先在机器人浏览器里登录。"}
    messages = await app.state.adapter.read_recent_messages()
    for msg in messages:
        app.state.db.save_message(msg)
        app.state.db.mark_message_processed(msg["message_id"], "测试读取", "")
    return {"ok": True, "messages": messages[-10:]}


@app.get("/api/debug/page")
async def debug_page():
    return await app.state.adapter.debug_page_state()


@app.post("/api/messages/send-test")
async def send_test(payload: SendTestPayload):
    ok = await _send_adapter_text_messages(
        app.state.adapter, app.state.db, payload.text
    )
    return {"ok": ok}


def _render_compensation_notification(
    template: str,
    batch: dict,
    currency: str,
) -> str:
    values = {
        "amount": batch.get("amount", 0),
        "currency": currency,
        "count": batch.get("recipient_count", 0),
        "total": batch.get("total_amount", 0),
        "normal_count": batch.get("normal_count", 0),
        "pending_count": batch.get("pending_count", 0),
        "conflict_count": batch.get("conflict_count", 0),
        "reason": batch.get("reason", ""),
        "batch": batch.get("request_id", ""),
    }
    rendered = (template or "").strip()
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


@app.get("/api/compensation/preview")
async def compensation_preview():
    preview = app.state.db.compensation_preview()
    features = app.state.db.get_config().get("features", {})
    return {
        **preview,
        "currency": features.get("currency_name", "功德点"),
        "notification_template": features.get(
            "compensation_notification_template",
            "⛪ 全员补偿通知\n因{reason}，现已向全部 {count} 位用户发放 {amount} {currency}。",
        ),
    }


@app.post("/api/compensation/grant")
async def grant_compensation(payload: CompensationPayload):
    request_id = payload.request_id.strip()
    reason = payload.reason.strip()
    template = payload.notification_template.strip()
    if not 8 <= len(request_id) <= 100:
        raise HTTPException(400, "补偿请求编号无效")
    if payload.amount <= 0 or payload.amount > 100000:
        raise HTTPException(400, "每人补偿数量必须在 1 到 100000 之间")
    if not reason or len(reason) > 200:
        raise HTTPException(400, "补偿原因不能为空且不能超过 200 字")
    if not template or len(template) > 2000:
        raise HTTPException(400, "通知消息不能为空且不能超过 2000 字")

    config = app.state.db.get_config()
    features = config.setdefault("features", {})
    features["compensation_notification_template"] = template
    app.state.db.save_config(config)
    try:
        batch = app.state.db.grant_compensation(
            request_id=request_id,
            amount=payload.amount,
            reason=reason,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    was_duplicate = bool(batch.get("duplicate", False))
    currency = str(features.get("currency_name") or "功德点")
    notification = _render_compensation_notification(template, batch, currency)
    notification_sent = bool(batch.get("notification_sent"))
    if not notification_sent:
        notification_sent = await _send_adapter_text_messages(
            app.state.adapter, app.state.db, notification
        )
        batch = app.state.db.set_compensation_notification(
            int(batch["id"]),
            notification,
            notification_sent,
        )
    app.state.logger.info(
        f"全员补偿批次：batch={request_id}, recipients={batch.get('recipient_count')}, "
        f"amount={payload.amount}, notification_sent={notification_sent}"
    )
    return {
        "ok": True,
        "duplicate": was_duplicate,
        "notification_sent": notification_sent,
        "batch": batch,
        "message": (
            f"已向 {batch.get('recipient_count', 0)} 位用户发放补偿并发送群通知"
            if notification_sent
            else f"已向 {batch.get('recipient_count', 0)} 位用户发放补偿，但群通知发送失败"
        ),
    }


@app.get("/api/facility-wages")
async def facility_wages():
    claim_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    preview = app.state.db.facility_wage_preview(claim_date)
    features = app.state.db.get_config().get("features", {})
    currency = features.get("currency_name", "功德点")
    return {
        "rules": app.state.db.list_facility_wage_rules(),
        "preview": preview,
        "currency": currency,
        "claim_command": features.get("facility_wage_claim_commands", "/领取工资"),
        "schedule": "仅支持手动领取昨天工资",
    }


@app.get("/api/newcomer-benefit")
async def newcomer_benefit():
    return app.state.db.newcomer_benefit_stats()


@app.post("/api/newcomer-benefit")
async def save_newcomer_benefit(payload: dict):
    try:
        amount = int(payload.get("amount", 60))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "新人福利数量必须是整数") from exc
    if amount < 1 or amount > 100000:
        raise HTTPException(400, "新人福利数量必须在 1 到 100000 之间")
    config = app.state.db.get_config()
    features = config.setdefault("features", {})
    features["newcomer_benefit_enabled"] = bool(payload.get("enabled", True))
    features["newcomer_benefit_amount"] = amount
    app.state.db.save_config(config)
    return app.state.db.newcomer_benefit_stats()


@app.get("/api/lucky-bags")
async def lucky_bags():
    features = app.state.db.get_config().get("features", {})
    packets = app.state.db.list_red_packets(100)
    return {
        "packets": packets,
        "active_count": sum(1 for packet in packets if packet.get("active")),
        "admin_count": sum(
            1 for packet in packets if packet.get("funding_type") == "admin"
        ),
        "user_count": sum(
            1 for packet in packets if packet.get("funding_type") == "user"
        ),
        "currency": features.get("currency_name", "功德点"),
    }


@app.post("/api/facility-wages/rules")
async def create_facility_wage_rule(payload: FacilityWageRulePayload):
    try:
        rule = app.state.db.save_facility_wage_rule(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    app.state.logger.info(
        f"新增公共设施工资规则：文案={rule['keyword']}，工资={rule['amount']}"
    )
    return {"ok": True, "rule": rule}


@app.put("/api/facility-wages/rules/{rule_id}")
async def update_facility_wage_rule(rule_id: int, payload: FacilityWageRulePayload):
    try:
        rule = app.state.db.save_facility_wage_rule(payload.model_dump(), rule_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    app.state.logger.info(
        f"更新公共设施工资规则：ID={rule_id}，文案={rule['keyword']}，工资={rule['amount']}"
    )
    return {"ok": True, "rule": rule}


@app.delete("/api/facility-wages/rules/{rule_id}")
async def delete_facility_wage_rule(rule_id: int):
    try:
        app.state.db.delete_facility_wage_rule(rule_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    app.state.logger.info(f"删除公共设施工资规则：ID={rule_id}")
    return {"ok": True}


@app.get("/api/item-economy")
async def get_item_economy():
    from app.command_router import DEFAULTS

    config = app.state.db.get_config()
    features = {**DEFAULTS, **config.get("features", {})}
    return {
        "settings": {
            "enabled": str(features.get("random_item_drop_enabled", "true")).lower() != "false",
            "chance_percent": float(features.get("random_item_drop_chance_percent", 20) or 0),
            "sources": features.get("random_item_drop_sources") or [],
            "drop_reply": features.get("random_item_drop_reply", "{newline}🎁 {user}意外掉落：{item} x{quantity}，已放入背包。"),
            "exchange_shop_enabled": bool(features.get("exchange_shop_enabled", True)),
            "exchange_shop_commands": features.get("exchange_shop_commands", "/兑换仓库,/兑换商店"),
            "exchange_commands": features.get("exchange_commands", "/兑换"),
            "exchange_shop_header": features.get("exchange_shop_header", "🐓 大祭司的魔法鸡鸡兑换仓库"),
            "exchange_shop_story": features.get("exchange_shop_story", ""),
            "exchange_shop_footer": features.get("exchange_shop_footer", ""),
            "exchange_success_reply": features.get("exchange_success_reply", ""),
            "exchange_missing_reply": features.get("exchange_missing_reply", ""),
            "exchange_limit_once_reply": features.get("exchange_limit_once_reply", ""),
            "exchange_limit_weekly_reply": features.get("exchange_limit_weekly_reply", ""),
        },
        "items": app.state.db.list_shop_items(include_disabled=True),
        "drop_pool": app.state.db.list_drop_pool_entries(),
        "offers": app.state.db.list_exchange_offers(),
        "history": app.state.db.list_exchange_history(100),
    }


@app.post("/api/item-economy/settings")
async def save_item_economy_settings(payload: dict):
    allowed_sources = {
        "checkin",
        "wage",
        "beg_success",
        "game_win",
        "game_loss",
        "six_seal_loss",
        "paid_interaction_payer",
    }
    sources = payload.get("sources") or []
    if not isinstance(sources, list) or any(source not in allowed_sources for source in sources):
        raise HTTPException(400, "掉落来源设置无效")
    config = app.state.db.get_config()
    features = config.setdefault("features", {})
    features["random_item_drop_enabled"] = "true" if payload.get("enabled", True) else "false"
    try:
        chance_percent = float(payload.get("chance_percent", 20))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "其他项目总掉落概率必须是数字") from exc
    if chance_percent < 0 or chance_percent > 100:
        raise HTTPException(400, "其他项目总掉落概率必须在 0% 到 100% 之间")
    features["random_item_drop_chance_percent"] = chance_percent
    features["random_item_drop_sources"] = sources
    editable_text = (
        "random_item_drop_reply", "exchange_shop_commands", "exchange_commands",
        "exchange_shop_header", "exchange_shop_story", "exchange_shop_footer",
        "exchange_success_reply", "exchange_missing_reply",
        "exchange_limit_once_reply", "exchange_limit_weekly_reply",
    )
    for key in editable_text:
        if key in payload:
            features[key] = str(payload.get(key) or "")
    features["exchange_shop_enabled"] = bool(payload.get("exchange_shop_enabled", True))
    app.state.db.save_config(config)
    return await get_item_economy()


@app.post("/api/item-economy/drop-pool")
async def save_drop_pool_entry(payload: DropPoolEntryPayload):
    try:
        entry_id = app.state.db.upsert_drop_pool_entry(payload.model_dump())
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "id": entry_id, "drop_pool": app.state.db.list_drop_pool_entries()}


@app.delete("/api/item-economy/drop-pool/{entry_id}")
async def delete_drop_pool_entry(entry_id: int):
    app.state.db.delete_drop_pool_entry(entry_id)
    return {"ok": True}


@app.post("/api/item-economy/exchange-offers")
async def save_exchange_offer(payload: ExchangeOfferPayload):
    try:
        offer_id = app.state.db.save_exchange_offer(payload.model_dump())
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "id": offer_id, "offers": app.state.db.list_exchange_offers()}


@app.delete("/api/item-economy/exchange-offers/{offer_id}")
async def delete_exchange_offer(offer_id: int):
    app.state.db.delete_exchange_offer(offer_id)
    return {"ok": True}


@app.get("/api/item-economy/exchange-history")
async def get_exchange_history(limit: int = 200):
    return app.state.db.list_exchange_history(limit)


@app.post("/api/item-economy/recipes")
async def save_crafting_recipe(payload: CraftingRecipePayload):
    raise HTTPException(410, "自动合成已停用，请在兑换仓库中创建兑换项目")


@app.delete("/api/item-economy/recipes/{recipe_id}")
async def delete_crafting_recipe(recipe_id: int):
    app.state.db.delete_crafting_recipe(recipe_id)
    return {"ok": True}


@app.get("/api/export/full")
async def export_full_data():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = DATA_DIR / "exports" / f"dzmm-data-export-{stamp}.zip"
    app.state.db.export_data_zip(path)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
    )


@app.get("/api/messages")
async def list_messages():
    return app.state.db.list_messages(limit=100)


@app.get("/api/ai-character/overview")
async def ai_character_overview():
    overview = app.state.ai_service.store.overview()
    scheduler = app.state.scheduler
    overview["queued"] = sum(scheduler.ai_queue_counts.values())
    overview["processing"] = sum(
        1 for task in scheduler.ai_request_tasks if not task.done()
    )
    failed = app.state.db.conn.execute(
        "select error from ai_tasks where error!='' order by updated_at desc limit 1"
    ).fetchone()
    overview["recent_error"] = str(failed["error"] or "") if failed else ""
    return overview


@app.get("/api/ai-character/settings")
async def ai_character_settings():
    return app.state.ai_service.store.settings()


@app.put("/api/ai-character/settings")
async def save_ai_character_settings(payload: dict):
    try:
        return {"ok": True, "settings": app.state.ai_service.store.save_settings(payload)}
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/ai-character/settings/restore/{target}")
async def restore_ai_character_settings(target: str):
    if target not in {"default", "previous"}:
        raise HTTPException(400, "恢复目标只能是 default 或 previous")
    try:
        return {"ok": True, "settings": app.state.ai_service.store.restore_settings(target)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/ai-character/profile")
async def ai_character_profile():
    return app.state.ai_service.store.profile()


@app.put("/api/ai-character/profile")
async def save_ai_character_profile(payload: dict):
    try:
        return {"ok": True, "profile": app.state.ai_service.store.save_profile(payload)}
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/ai-character/profile/restore/{target}")
async def restore_ai_character_profile(target: str):
    if target not in {"default", "previous"}:
        raise HTTPException(400, "恢复目标只能是 default 或 previous")
    try:
        return {"ok": True, "profile": app.state.ai_service.store.restore_profile(target)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/ai-character/persona/restore/{target}")
async def restore_ai_character_persona(target: str):
    if target not in {"default", "previous"}:
        raise HTTPException(400, "恢复目标只能是 default 或 previous")
    try:
        profile = app.state.ai_service.store.restore_profile_fields({"persona_prompt"}, target)
        return {"ok": True, "profile": profile}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/ai-character/system-rules/restore/{target}")
async def restore_ai_system_rules(target: str):
    if target not in {"default", "previous"}:
        raise HTTPException(400, "恢复目标只能是 default 或 previous")
    try:
        settings = app.state.ai_service.store.restore_setting_fields({"system_rules"}, target)
        return {"ok": True, "settings": settings}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/ai-character/supreme-system-prompt/restore/{target}")
async def restore_ai_supreme_system_prompt(target: str):
    if target not in {"default", "previous"}:
        raise HTTPException(400, "恢复目标只能是 default 或 previous")
    try:
        settings = app.state.ai_service.store.restore_setting_fields({"supreme_system_prompt"}, target)
        return {"ok": True, "settings": settings}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/ai-character/model-test")
async def test_ai_character_model(payload: dict):
    settings = app.state.ai_service.store.settings()
    target = str(payload.get("target") or "primary")
    thinking = bool(payload.get("thinking", False))
    model = settings["backup_model" if target == "backup" else "primary_model"]
    timeout = settings["thinking_timeout_seconds" if thinking else "normal_timeout_seconds"]
    try:
        result = await asyncio.to_thread(
            app.state.ai_service._client(model, float(timeout)).generate_response,
            system_prompt="你是连接测试助手。不要展示推理，只回复：连接成功。",
            user_prompt="测试当前模型连接。",
            thinking=thinking,
            temperature=0,
            max_tokens=80,
            max_output_chars=200,
        )
        return {
            "ok": True,
            "message": "连接成功",
            "model": result.model,
            "token_input": result.input_tokens,
            "token_output": result.output_tokens,
            "token_available": result.input_tokens is not None and result.output_tokens is not None,
        }
    except AIInteractionError as exc:
        detail = str(exc)
        if "401" in detail or "密钥" in detail:
            category = "密钥无效"
        elif "超时" in detail or "timed out" in detail.lower():
            category = "请求超时"
        elif "解析" in detail or "格式" in detail:
            category = "返回内容无法解析"
        elif "连接" in detail or "网络" in detail:
            category = "网络失败"
        else:
            category = "模型不可用"
        app.state.logger.error(f"AI角色模型测试失败：{detail}")
        raise HTTPException(400, category) from exc


@app.post("/api/ai-character/persona-test")
async def test_ai_character_persona(payload: dict):
    settings = app.state.ai_service.store.settings()
    profile = app.state.ai_service.store.profile()
    prompt = str(payload.get("prompt") or "请自然地向一位刚刚召唤你的普通群友打招呼。")[:500]
    try:
        result = await asyncio.to_thread(
            app.state.ai_service._client(
                str(settings["primary_model"]), float(settings["normal_timeout_seconds"]), settings
            ).generate_response,
            system_prompt=f"{profile['persona_prompt']}\n当前角色资料：{json.dumps(profile, ensure_ascii=False)}\n这是后台人格测试，不调用工具、不执行命令、不输出Token尾注。",
            user_prompt=prompt,
            thinking=False,
            temperature=0.9,
            max_tokens=500,
            max_output_chars=2000,
        )
        return {"ok": True, "reply": result.content, "model": result.model, "token_input": result.input_tokens, "token_output": result.output_tokens}
    except AIInteractionError as exc:
        app.state.logger.error(f"AI角色人格测试失败：{exc}")
        raise HTTPException(400, "人格测试失败，请检查模型连接和后台日志") from exc


@app.get("/api/ai-character/tasks")
async def ai_character_tasks(limit: int = 100):
    rows = app.state.db.conn.execute(
        "select * from ai_tasks order by created_at desc limit ?", (max(1, min(int(limit), 500)),)
    ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/ai-character/usage")
async def ai_character_usage(limit: int = 100):
    rows = app.state.db.conn.execute(
        "select * from ai_usage_records order by id desc limit ?", (max(1, min(int(limit), 500)),)
    ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/ai-character/pending-actions")
async def ai_pending_actions():
    rows = app.state.db.conn.execute(
        "select * from ai_pending_actions where status='pending' order by created_at desc limit 200"
    ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/ai-character/pending-actions/{action_id}/cancel")
async def cancel_ai_pending_action(action_id: str):
    row = app.state.db.conn.execute("select action_id from ai_pending_actions where action_id=?", (action_id,)).fetchone()
    if not row:
        raise HTTPException(404, "确认草稿不存在")
    app.state.ai_service.store.finish_action(action_id, "admin_cancelled", {"admin_cancelled": True})
    return {"ok": True}


@app.get("/api/ai-character/relationships")
async def ai_relationships(group_id: str = "main"):
    rows = app.state.db.conn.execute(
        """select r.*,
                  coalesce(nullif(subject.display_name,''),nullif(subject.nickname,''),'') subject_display_name,
                  coalesce(subject.nickname,'') subject_nickname,
                  coalesce(nullif(object_user.display_name,''),nullif(object_user.nickname,''),'') object_display_name,
                  coalesce(object_user.nickname,'') object_nickname
           from ai_relationships r
           left join users subject on subject.platform_user_id=r.subject_user_id
           left join users object_user on object_user.platform_user_id=r.object_user_id
           where r.group_id=? order by r.locked desc,r.updated_at desc limit 500""",
        (group_id,),
    ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/ai-character/relationships")
async def create_ai_relationship(payload: dict):
    try:
        return {"ok": True, "relationship": app.state.ai_service.store.save_admin_relationship(payload)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/ai-character/relationships/{relationship_id}")
async def update_ai_relationship(relationship_id: int, payload: dict):
    try:
        return {"ok": True, "relationship": app.state.ai_service.store.save_admin_relationship(payload, relationship_id)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/ai-character/relationships/{relationship_id}")
async def delete_ai_relationship(relationship_id: int):
    try:
        app.state.ai_service.store.deactivate_admin_relationship(relationship_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/ai-character/events")
async def ai_memory_events(group_id: str = "main", user_id: str = ""):
    if user_id:
        rows = app.state.db.conn.execute(
            "select * from ai_memory_events where group_id=? and user_id=? order by event_date desc limit 200",
            (group_id, user_id),
        ).fetchall()
    else:
        rows = app.state.db.conn.execute(
            "select * from ai_memory_events where group_id=? order by event_date desc limit 200", (group_id,)
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/ai-character/events")
async def create_ai_memory_event(payload: dict):
    try:
        return {"ok": True, "event": app.state.ai_service.store.add_manual_event(payload)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/ai-character/events/{event_id}")
async def delete_ai_memory_event(event_id: str):
    row = app.state.db.conn.execute(
        "select event_id from ai_memory_events where event_id=?", (event_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "事件卡不存在")
    app.state.db.conn.execute(
        "update ai_memory_events set active=0 where event_id=?", (event_id,)
    )
    app.state.db.conn.commit()
    return {"ok": True}


@app.get("/api/ai-character/tasks/{task_id}")
async def ai_character_task_detail(task_id: str):
    task = app.state.db.conn.execute("select * from ai_tasks where task_id=?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(404, "AI任务不存在")
    messages = app.state.db.conn.execute("select * from ai_messages where task_id=? order by id", (task_id,)).fetchall()
    tools = app.state.db.conn.execute("select * from ai_tool_calls where task_id=? order by call_index", (task_id,)).fetchall()
    return {"task": dict(task), "messages": [dict(row) for row in messages], "tools": [dict(row) for row in tools]}


@app.get("/api/ai-character/group-memory")
async def ai_group_memory(group_id: str = "main"):
    row = app.state.db.conn.execute("select * from ai_group_memories where group_id=?", (group_id,)).fetchone()
    return dict(row) if row else {"group_id": group_id, "status": "idle", "updated_at": None, "processed_message_count": 0, "last_error": "", "next_check_at": None}


@app.post("/api/ai-character/group-memory/regenerate")
async def regenerate_ai_group_memory(payload: dict):
    group_id = str(payload.get("group_id") or "main")
    app.state.db.conn.execute(
        """insert into ai_group_memories(group_id,status,updated_at,next_check_at) values(?,'queued',null,null)
           on conflict(group_id) do update set status='queued',updated_at=null,next_check_at=null,last_error=''""",
        (group_id,),
    )
    app.state.db.conn.commit()
    app.state.ai_service._next_background_check = datetime.now().astimezone()
    return {"ok": True, "message": "群摘要已加入后台重新生成队列。"}


@app.get("/api/ai-character/capabilities")
async def ai_capabilities():
    names = {
        "balance": "查询本人功德余额", "profile": "查询用户资料", "inventory": "查询本人背包",
        "shop": "查询神殿仓库摘要", "contracts": "查询本人奴隶契约", "public_facility": "查询公共设施状态",
        "bounties": "查询悬赏列表", "my_bounties": "查询我的悬赏", "rp_status": "查询RP结界状态",
        "recent_events": "查询真实事件卡", "user_lookup": "按昵称查找用户", "traditional_read": "调用传统只读命令",
        "merit_ranking": "查询功德榜", "interaction_ranking": "查询互动榜",
        "transactions": "查询用户功德流水", "game_history": "查询用户游戏记录",
    }
    read_tools = sorted(app.state.ai_service.READ_TOOLS)
    return [
        {"name": names.get(name, name), "capability_id": name, "enabled": True, "risk": "只读", "confirmation": False, "reply_mode": "AI统一回复", "structured": True}
        for name in read_tools
    ] + [
        {"name": "命令管理与自定义命令", "enabled": True, "risk": "沿用原命令权限和冷却", "confirmation": False, "reply_mode": "程序执行后AI简短修饰", "structured": True},
        {"name": "购买、兑换、发布悬赏、发送福袋", "enabled": True, "risk": "影响功德或物品", "confirmation": True, "reply_mode": "确认后程序处理", "structured": True},
        {"name": "其他现有命令", "enabled": True, "risk": "沿用原业务规则", "confirmation": False, "reply_mode": "直接执行", "structured": True},
        {"name": "现有游戏", "enabled": True, "risk": "由现有游戏规则决定", "confirmation": False, "reply_mode": "程序固定回复", "structured": True},
    ]


@app.get("/api/users/{ref}/ai-memory")
async def get_user_ai_memory(ref: str, group_id: str = "main"):
    user = app.state.db._resolve_user_ref(unquote(ref))
    if not user:
        raise HTTPException(404, "用户不存在")
    return app.state.ai_service.store.user_memory(int(user["id"]), group_id)


@app.put("/api/users/{ref}/ai-memory")
async def save_user_ai_memory(ref: str, payload: dict, group_id: str = "main"):
    user = app.state.db._resolve_user_ref(unquote(ref))
    if not user:
        raise HTTPException(404, "用户不存在")
    try:
        return {"ok": True, "memory": app.state.ai_service.store.save_user_memory(int(user["id"]), payload, group_id)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/users/{ref}/ai-memory/restore")
async def restore_user_ai_memory(ref: str, group_id: str = "main"):
    user = app.state.db._resolve_user_ref(unquote(ref))
    if not user:
        raise HTTPException(404, "用户不存在")
    try:
        return {"ok": True, "memory": app.state.ai_service.store.restore_user_memory(int(user["id"]), group_id)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/users/{ref}/ai-memory/regenerate")
async def regenerate_user_ai_memory(ref: str, group_id: str = "main"):
    user = app.state.db._resolve_user_ref(unquote(ref))
    if not user:
        raise HTTPException(404, "用户不存在")
    user_id = str(user.get("platform_user_id") or user.get("user_id") or "")
    app.state.db.conn.execute(
        """insert into ai_user_memories(group_id,user_id,user_pk,paused,updated_at)
           values(?,?,?,0,null) on conflict(group_id,user_id) do update set paused=0,updated_at=null,last_error=''""",
        (group_id, user_id, int(user["id"])),
    )
    app.state.db.conn.commit()
    app.state.ai_service._next_background_check = datetime.now().astimezone()
    return {"ok": True, "message": "已加入后台重新生成队列，不会向群内发送提示或收费。"}


@app.get("/api/users")
async def list_users(search: str = "", nickname_conflict: bool = False):
    return app.state.db.list_users(
        limit=300,
        search=search,
        nickname_conflict=nickname_conflict,
    )


@app.get("/api/identity-conflicts")
async def list_identity_conflicts():
    return app.state.db.list_identity_conflicts(limit=300)


@app.post("/api/identity-conflicts/{conflict_id}/resolve")
async def resolve_identity_conflict(conflict_id: int, payload: dict):
    try:
        user = app.state.db.resolve_identity_conflict(
            conflict_id,
            str(payload.get("action") or ""),
            int(payload["candidate_user_pk"]) if payload.get("candidate_user_pk") is not None else None,
        )
        app.state.logger.info(
            f"身份冲突已人工处理：conflict_id={conflict_id}, user_pk={user.get('id')}, "
            f"platform_user_id={user.get('platform_user_id')}"
        )
        return {"ok": True, "user": user}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/users/{ref}/inventory")
async def update_inventory(ref: str, payload: InventoryUpdatePayload):
    try:
        return {"ok": True, "inventory": app.state.db.update_inventory_quantity(unquote(ref), payload.item_name, payload.quantity)}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/users/{nickname}")
async def user_detail(nickname: str):
    try:
        return app.state.db.user_detail(unquote(nickname))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.put("/api/users/{nickname}")
async def update_user(nickname: str, payload: UserPayload):
    try:
        return {"ok": True, "user": app.state.db.update_user(unquote(nickname), payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.delete("/api/users/{ref}")
async def delete_user(ref: str):
    try:
        deleted = app.state.db.delete_user(unquote(ref))
        app.state.logger.info(
            f"用户已删除并归档：user_pk={deleted['id']}, nickname={deleted['nickname']}"
        )
        return {"ok": True, "deleted": deleted}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc



@app.post("/api/users/merge")
async def merge_users(payload: dict):
    source = payload.get("source", "").strip()
    target = payload.get("target", "").strip()
    if not source or not target:
        raise HTTPException(400, "请提供源用户和目标用户昵称")
    try:
        user = app.state.db.merge_users(unquote(source), unquote(target))
        app.state.logger.info(f"用户已合并：{source} -> {target}")
        return {"ok": True, "user": user}
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@app.put("/api/statuses/{status_id}")
async def update_status(status_id: int, payload: StatusPayload):
    try:
        return {"ok": True, "status": app.state.db.update_status_effect(status_id, payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/users/cleanup")
async def cleanup_users():
    count = app.state.db.cleanup_invalid_users()
    return {"ok": True, "count": count}


@app.get("/api/features")
async def get_features():
    from app.command_router import DEFAULTS
    stored = app.state.db.get_config().get("features", {})
    return {**DEFAULTS, **stored}


@app.post("/api/features")
async def save_features(payload: dict):
    for key in [k for k in payload if k.endswith("_commands")]:
        raw = str(payload.get(key, "") or "")
        for item in [x.strip() for x in raw.replace("，", ",").split(",") if x.strip()]:
            if not item.startswith("/"):
                raise HTTPException(400, f"{key} 中的命令必须以 / 开头：{item}")
    if "nipple_guess_base_bet" in payload:
        value = payload.get("nipple_guess_base_bet")
        if type(value) is not int or not 1 <= value <= 100000:
            raise HTTPException(400, "猜乳头基础下注必须是 1～100000 的整数")
    config = app.state.db.get_config()
    config["features"] = {**config.get("features", {}), **payload}
    app.state.db.save_config(config)
    app.state.logger.info("功能设置已保存")
    return {"ok": True, "features": config["features"]}


@app.get("/api/paid-interaction/settings")
async def get_paid_interaction_settings():
    from app.command_router import DEFAULTS

    stored = app.state.db.get_config().get("features", {})
    merged = {**DEFAULTS, **stored}
    if str(stored.get("fortune_feature_version") or "") != FORTUNE_FEATURE_VERSION:
        merged.update(TODAY_FORTUNE_FEATURES)
    settings = {
        key: merged.get(key)
        for key in PAID_INTERACTION_SETTING_KEYS
        if key in merged
    }
    api_key = app.state.db.get_secret("deepseek_api_key")
    settings["api_key_configured"] = bool(api_key)
    settings["api_key_hint"] = ("••••" + api_key[-4:]) if api_key else ""
    settings["api_key_source"] = app.state.db.secret_source("deepseek_api_key")
    settings["api_key_locked"] = False
    return settings


@app.post("/api/paid-interaction/settings")
async def save_paid_interaction_settings(payload: dict):
    new_api_key = str(payload.get("api_key") or "").strip()
    if new_api_key and not 10 <= len(new_api_key) <= 512:
        raise HTTPException(400, "DeepSeek API 密钥长度应为 10～512 个字符")
    updates = {
        key: value
        for key, value in payload.items()
        if key in PAID_INTERACTION_SETTING_KEYS
    }
    for key in (
        "paid_interaction_ai_system_prompt",
        "paid_interaction_ai_user_prompt",
    ):
        if key in updates and not str(updates.get(key) or "").strip():
            raise HTTPException(400, f"{key} 不能为空，已拒绝覆盖原提示词")
    for key in (
        "paid_interaction_enable_commands",
        "paid_interaction_disable_commands",
    ):
        _validate_command_triggers(str(updates.get(key) or ""))
    base_url = str(updates.get("paid_interaction_ai_base_url") or "").strip()
    if not (
        base_url.startswith("https://")
        or base_url.startswith("http://127.0.0.1")
        or base_url.startswith("http://localhost")
    ):
        raise HTTPException(400, "DeepSeek API 地址必须使用 HTTPS")
    model = str(updates.get("paid_interaction_ai_model") or "").strip()
    allowed_models = {"deepseek-v4-flash", "deepseek-v4-pro"}
    if model not in allowed_models:
        raise HTTPException(400, "模型仅允许选择 deepseek-v4-flash 或 deepseek-v4-pro")
    numeric_bounds = {
        "paid_interaction_amount": (10, 100000),
        "paid_interaction_min_balance": (-1000000, 0),
        "paid_interaction_ai_temperature": (0, 2),
        "paid_interaction_ai_max_tokens": (32, 4096),
        "paid_interaction_ai_max_output_chars": (80, 4000),
        "paid_interaction_ai_timeout_seconds": (3, 120),
        "paid_interaction_max_action_chars": (20, 2000),
    }
    for key, (minimum, maximum) in numeric_bounds.items():
        try:
            value = float(updates[key])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, f"{key} 的数值无效")
        if not minimum <= value <= maximum:
            raise HTTPException(400, f"{key} 必须在 {minimum} 到 {maximum} 之间")
        if key in {"fortune_cost", "fortune_daily_limit"}:
            if not value.is_integer():
                raise HTTPException(400, f"{key} 必须是整数")
            updates[key] = int(value)
    updates["paid_interaction_ai_version"] = "2"
    config = app.state.db.get_config()
    config["features"] = {**config.get("features", {}), **updates}
    app.state.db.save_config(config)

    if bool(payload.get("clear_api_key")):
        app.state.db.set_secret("deepseek_api_key", "")
    elif new_api_key:
        app.state.db.set_secret("deepseek_api_key", new_api_key)

    app.state.logger.info("付费互动 AI 设置已保存；API 密钥内容未写入日志")
    return await get_paid_interaction_settings()


@app.post("/api/paid-interaction/test")
async def test_paid_interaction_ai():
    settings = await get_paid_interaction_settings()
    api_key = app.state.db.get_secret("deepseek_api_key")
    if not api_key:
        raise HTTPException(400, "请先保存 DeepSeek API 密钥")
    try:
        result = DeepSeekClient(
            api_key=api_key,
            base_url=str(settings["paid_interaction_ai_base_url"]),
            model=str(settings["paid_interaction_ai_model"]),
            timeout_seconds=float(settings["paid_interaction_ai_timeout_seconds"]),
        ).generate(
            system_prompt="你是连接测试助手，只回复：DeepSeek 连接成功。",
            user_prompt="执行连接测试。",
            temperature=0,
            max_tokens=64,
            max_output_chars=100,
        )
    except AIInteractionError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "message": result}

@app.get("/api/fortune/settings")
async def get_fortune_settings():
    from app.command_router import DEFAULTS

    stored = app.state.db.get_config().get("features", {})
    merged = {**DEFAULTS, **stored}
    settings = {
        key: merged.get(key)
        for key in FORTUNE_SETTING_KEYS
        if key in merged
    }
    settings.update(
        {
            "fortune_commands": merged["fortune_commands"],
            "fortune_cost": int(merged.get("fortune_cost", 20) or 20),
            "fortune_daily_limit": int(
                merged.get("fortune_daily_limit", 1) or 1
            ),
            "api_key_configured": bool(
                app.state.db.get_secret("deepseek_api_key")
            ),
            "stats": app.state.db.fortune_reading_stats(),
        }
    )
    return settings


@app.post("/api/fortune/settings")
async def save_fortune_settings(payload: dict):
    if "api_key" in payload or "clear_api_key" in payload:
        raise HTTPException(403, "DeepSeek API 密钥已内置锁定，禁止通过管理接口修改")
    updates = {
        key: value for key, value in payload.items() if key in FORTUNE_SETTING_KEYS
    }
    for key in (
        "fortune_ai_system_prompt",
        "fortune_ai_user_prompt",
        "fortune_ai_repair_prompt",
    ):
        if key in updates and not str(updates.get(key) or "").strip():
            raise HTTPException(400, f"{key} 不能为空，已拒绝覆盖原提示词")
    updates["fortune_feature_version"] = FORTUNE_FEATURE_VERSION
    updates["fortune_commands"] = TODAY_FORTUNE_FEATURES["fortune_commands"]
    if "fortune_reader_name" in updates and not str(updates.get("fortune_reader_name") or "").strip():
        raise HTTPException(400, "占卜师身份不能为空")
    base_url = str(updates.get("fortune_ai_base_url") or "").strip()
    if not (
        base_url.startswith("https://")
        or base_url.startswith("http://127.0.0.1")
        or base_url.startswith("http://localhost")
    ):
        raise HTTPException(400, "塔罗牌 AI 地址必须使用 HTTPS")
    model = str(updates.get("fortune_ai_model") or "").strip()
    if model not in {"deepseek-v4-flash", "deepseek-v4-pro"}:
        raise HTTPException(400, "模型仅允许选择 deepseek-v4-flash 或 deepseek-v4-pro")
    numeric_bounds = {
        "fortune_cost": (1, 100000),
        "fortune_daily_limit": (1, 100),
        "fortune_ai_temperature": (0, 2),
        "fortune_ai_max_tokens": (32, 4096),
        "fortune_ai_max_output_chars": (80, 1000),
        "fortune_ai_timeout_seconds": (3, 120),
    }
    for key, (minimum, maximum) in numeric_bounds.items():
        if key not in updates:
            continue
        try:
            value = float(updates[key])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, f"{key} 的数值无效")
        if not minimum <= value <= maximum:
            raise HTTPException(400, f"{key} 必须在 {minimum} 到 {maximum} 之间")
    config = app.state.db.get_config()
    config["features"] = {**config.get("features", {}), **updates}
    app.state.db.save_config(config)
    app.state.logger.info("塔罗牌设置已保存；付费互动提示词未改动")
    return await get_fortune_settings()

@app.get("/api/bounties/settings")
async def get_bounty_settings():
    from app.command_router import DEFAULTS

    config = app.state.db.get_config()
    merged = {**DEFAULTS, **config.get("features", {})}
    settings = {
        key: merged.get(key)
        for key in BOUNTY_SETTING_KEYS
        if key in merged
    }
    settings.update(
        {
            "main_group_url": str(config.get("dzmm", {}).get("group_url") or ""),
            "bounty_group_url": str(
                config.get("dzmm", {}).get("bounty_group_url") or ""
            ),
            "main_group_name": "圣女小小的淫光大教堂（入群拟定身份后入戏）",
            "bounty_group_name": "《圣殿悬赏令》（禁闲聊违反者清算）",
            "stats": app.state.db.commission_house.admin_overview()["counts"],
            "prompt_revisions": app.state.db.commission_house.list_prompt_revisions(),
        }
    )
    return settings


@app.post("/api/bounties/settings")
async def save_bounty_settings(payload: dict):
    from app.command_router import DEFAULTS

    updates = {
        key: value for key, value in payload.items() if key in BOUNTY_SETTING_KEYS
    }
    prompt_keys = {
        "commission_demand_ai_system_prompt",
        "commission_demand_ai_user_prompt",
        "commission_service_ai_system_prompt",
        "commission_service_ai_user_prompt",
    }
    for key in prompt_keys.intersection(updates):
        if not str(updates.get(key) or "").strip():
            raise HTTPException(400, f"{key} 不能为空，已拒绝覆盖原提示词")
    for key in [key for key in updates if key.endswith("_commands")]:
        _validate_command_triggers(str(updates.get(key) or ""))
    commission_command_keys = {
        key for key in BOUNTY_SETTING_KEYS
        if key.startswith("commission_") and key.endswith("_commands")
    }
    merged_commands = {
        **DEFAULTS,
        **app.state.db.get_config().get("features", {}),
        **updates,
    }
    seen: dict[str, str] = {}
    for key in sorted(commission_command_keys):
        commands = _split_command_triggers(str(merged_commands.get(key) or ""))
        if not commands:
            raise HTTPException(400, f"{key} 至少需要保留一个命令")
        for trigger in commands:
            owner = seen.get(trigger)
            if owner and owner != key:
                raise HTTPException(400, f"委托所命令重复：{trigger}")
            seen[trigger] = key
    removed_command_prefixes = ("bounty_", "market_")
    for key, value in merged_commands.items():
        if (
            not key.endswith("_commands")
            or key in commission_command_keys
            or key.startswith(removed_command_prefixes)
        ):
            continue
        for trigger in _split_command_triggers(str(value or "")):
            if trigger in seen:
                raise HTTPException(
                    400,
                    f"委托所命令 {trigger} 与其他模块的 {key} 冲突，请先修改其中一个命令",
                )
    if "bounty_publisher_cancel_compensation_percent" in updates:
        try:
            compensation = int(updates["bounty_publisher_cancel_compensation_percent"])
        except (TypeError, ValueError):
            raise HTTPException(400, "发起人中途取消补偿比例必须是整数")
        if not 0 <= compensation <= 100:
            raise HTTPException(400, "发起人中途取消补偿比例必须在 0 到 100 之间")
        updates["bounty_publisher_cancel_compensation_percent"] = compensation
    try:
        if "bounty_ai_draft_ttl_seconds" in updates:
            draft_ttl = int(updates["bounty_ai_draft_ttl_seconds"])
            if not 60 <= draft_ttl <= 3600:
                raise HTTPException(400, "AI草稿有效期必须为60～3600秒")
            updates["bounty_ai_draft_ttl_seconds"] = draft_ttl
        if "bounty_ai_timeout_seconds" in updates:
            ai_timeout = int(updates["bounty_ai_timeout_seconds"])
            if not 3 <= ai_timeout <= 120:
                raise HTTPException(400, "AI解析超时必须为3～120秒")
            updates["bounty_ai_timeout_seconds"] = ai_timeout
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "AI草稿有效期和超时时间必须是整数") from exc
    numeric_bounds = {
        "commission_demand_fee_percent": (0, 100),
        "commission_demand_min_reward": (1, 100000),
        "commission_demand_max_people": (1, 10),
        "commission_demand_default_recruitment_days": (1, 365),
        "commission_service_commission_percent": (0, 100),
        "commission_service_min_price": (1, 100000),
        "commission_service_default_stock": (1, 999),
        "commission_service_max_stock": (1, 999),
        "commission_service_default_listing_days": (1, 365),
        "commission_service_max_active": (1, 100),
    }
    for key, (minimum, maximum) in numeric_bounds.items():
        if key not in updates:
            continue
        try:
            updates[key] = int(updates[key])
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"{key} 必须是整数") from exc
        if not minimum <= updates[key] <= maximum:
            raise HTTPException(400, f"{key} 必须在 {minimum} 到 {maximum} 之间")
    if "bounty_ai_base_url" in updates:
        ai_url = str(updates.get("bounty_ai_base_url") or "").strip()
        if not (ai_url.startswith("https://") or ai_url.startswith("http://127.0.0.1") or ai_url.startswith("http://localhost")):
            raise HTTPException(400, "委托AI地址必须使用HTTPS或本机地址")
    current_config = app.state.db.get_config()
    effective_features = {**DEFAULTS, **current_config.get("features", {}), **updates}
    invite_url = str(effective_features.get("bounty_invite_url") or "").strip()
    if not re.fullmatch(r"https://www\.dzmm\.ai/invite/[A-Za-z0-9_-]+", invite_url):
        raise HTTPException(400, "悬赏群邀请链接格式不正确")
    bounty_group_url = str(payload.get("bounty_group_url") or current_config.get("dzmm", {}).get("bounty_group_url") or "").strip()
    if not re.fullmatch(
        r"https://www\.aikda\.com/chat\?c=[0-9a-fA-F-]{36}",
        bounty_group_url,
    ):
        raise HTTPException(400, "悬赏群聊天 URL 格式不正确")

    config = current_config
    old_features = config.get("features", {})
    for key in prompt_keys.intersection(updates):
        old_value = str(old_features.get(key, DEFAULTS.get(key, "")) or "")
        if old_value != str(updates[key]):
            app.state.db.commission_house.record_prompt_revision(key, old_value)
    config["features"] = {**config.get("features", {}), **updates}
    config.setdefault("dzmm", {})["bounty_group_url"] = bounty_group_url
    app.state.db.save_config(config)
    app.state.logger.info("群友委托所设置已保存")
    if bool(config.get("dzmm", {}).get("lock_group_urls", False)):
        await app.state.adapter.open_group(bounty_group_url, "bounty")
        app.state.scheduler.primed_groups.discard("bounty")
    return await get_bounty_settings()


@app.get("/api/bounties/all")
async def get_all_bounties():
    """兼容旧管理端路径；数据已统一来自群友委托所V2。"""
    return app.state.db.commission_house.admin_overview()


@app.get("/api/commission-house/overview")
async def get_commission_house_overview():
    return app.state.db.commission_house.admin_overview()


@app.get("/api/commission-house/prompts/history")
async def get_commission_prompt_history():
    return {"revisions": app.state.db.commission_house.list_prompt_revisions()}


@app.post("/api/commission-house/prompts/restore/{revision_id}")
async def restore_commission_prompt(revision_id: int):
    from app.command_router import DEFAULTS

    revision = app.state.db.commission_house.get_prompt_revision(revision_id)
    allowed = {
        "commission_demand_ai_system_prompt", "commission_demand_ai_user_prompt",
        "commission_service_ai_system_prompt", "commission_service_ai_user_prompt",
    }
    if not revision or revision["prompt_key"] not in allowed:
        raise HTTPException(404, "没有找到这条提示词历史版本")
    config = app.state.db.get_config()
    current = str(config.get("features", {}).get(revision["prompt_key"], DEFAULTS.get(revision["prompt_key"], "")) or "")
    app.state.db.commission_house.record_prompt_revision(revision["prompt_key"], current)
    config.setdefault("features", {})[revision["prompt_key"]] = revision["prompt_value"]
    app.state.db.save_config(config)
    return {"ok": True, "prompt_key": revision["prompt_key"], "value": revision["prompt_value"]}


@app.get("/api/commission-house/orders")
async def get_commission_house_orders():
    return {"orders": app.state.db.commission_house.list_orders()}


@app.put("/api/commission-house/demands/{demand_id}")
async def update_commission_house_demand(demand_id: int, payload: dict):
    try:
        return app.state.db.commission_house.admin_update_demand(
            demand_id, payload, admin_identity="local-manager"
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/commission-house/services/{service_id}")
async def update_commission_house_service(service_id: int, payload: dict):
    try:
        return app.state.db.commission_house.admin_update_service(
            service_id, payload, admin_identity="local-manager"
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/commission-house/orders/{order_id}")
async def update_commission_house_order(order_id: int, payload: dict):
    action = str(payload.get("action") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    try:
        return app.state.db.commission_house.admin_order_action(
            order_id,
            action=action,
            admin_identity="local-manager",
            reason=reason,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/marketplace/settings")
async def get_marketplace_settings():
    from app.command_router import DEFAULTS

    config = app.state.db.get_config()
    merged = {**DEFAULTS, **config.get("features", {})}
    listings = []
    for item in app.state.db.marketplace_core.list_all():
        item = dict(item)
        item["commission_number"] = app.state.db.commission_public_code(
            "market_listing", int(item["id"]), "S"
        )
        listings.append(item)
    orders = []
    for item in app.state.db.marketplace_core.list_orders():
        item = dict(item)
        item["commission_order_number"] = app.state.db.commission_public_code(
            "market_order", int(item["id"]), "O"
        )
        item["commission_listing_number"] = app.state.db.commission_public_code(
            "market_listing", int(item["listing_id"]), "S"
        )
        orders.append(item)
    return {
        "settings": {
            key: merged.get(key)
            for key in MARKET_SETTING_KEYS
            if key in merged
        },
        "api_key_configured": bool(app.state.db.get_secret("deepseek_api_key")),
        "stats": app.state.db.marketplace_core.stats(),
        "listings": listings,
        "orders": orders,
    }


@app.post("/api/marketplace/settings")
async def save_marketplace_settings(payload: dict):
    from app.command_router import DEFAULTS

    if "api_key" in payload or "clear_api_key" in payload:
        raise HTTPException(403, "DeepSeek API 密钥已内置锁定，禁止通过市场接口修改")
    updates = {key: value for key, value in payload.items() if key in MARKET_SETTING_KEYS}
    market_command_keys = (
        "market_list_commands", "market_help_commands", "market_create_commands",
        "market_confirm_create_commands", "market_cancel_create_commands",
        "market_edit_commands", "market_confirm_edit_commands", "market_cancel_edit_commands",
        "market_detail_commands", "market_purchase_commands", "market_mine_commands",
        "market_off_shelf_commands", "market_renew_commands",
    )
    current_commands = {**DEFAULTS, **app.state.db.get_config().get("features", {}), **updates}
    seen_commands: dict[str, str] = {}
    for key in market_command_keys:
        commands = [item.strip() for item in re.split(r"[,，]+", str(current_commands.get(key) or "")) if item.strip()]
        if not commands:
            raise HTTPException(400, f"{key} 至少需要保留一个指令")
        for command in commands:
            if not re.fullmatch(r"/[^\s,，：:*xX×]+", command):
                raise HTTPException(400, f"市场指令格式错误：{command}。指令必须以 / 开头，且不能包含空格、冒号或数量符号")
            owner = seen_commands.get(command)
            if owner and owner != key:
                raise HTTPException(400, f"市场指令重复：{command}")
            seen_commands[command] = key
    for key in ("market_ai_system_prompt", "market_ai_user_prompt"):
        if key in updates and not str(updates.get(key) or "").strip():
            raise HTTPException(400, f"{key} 不能为空，已拒绝覆盖原提示词")
    if "market_ai_base_url" in updates:
        ai_url = str(updates.get("market_ai_base_url") or "").strip()
        if not (
            ai_url.startswith("https://")
            or ai_url.startswith("http://127.0.0.1")
            or ai_url.startswith("http://localhost")
        ):
            raise HTTPException(400, "市场 AI 地址必须使用 HTTPS 或本机地址")
    if "market_ai_model" in updates:
        model = str(updates.get("market_ai_model") or "").strip()
        if model not in {"deepseek-v4-flash", "deepseek-v4-pro"}:
            raise HTTPException(400, "模型仅允许选择 deepseek-v4-flash 或 deepseek-v4-pro")
    numeric_bounds = {
        "market_default_commission_percent": (0, 100),
        "market_max_active_listings": (1, 100),
        "market_default_stock": (1, 999),
        "market_default_duration_days": (1, 365),
        "market_min_price": (1, 100000),
        "market_max_price": (1, 10000000),
        "market_page_size": (1, 10),
        "market_max_stock": (1, 9999),
        "market_max_duration_days": (1, 3650),
        "market_draft_ttl_seconds": (60, 3600),
        "market_ai_timeout_seconds": (3, 120),
    }
    for key, (minimum, maximum) in numeric_bounds.items():
        if key not in updates:
            continue
        try:
            value = int(updates[key])
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"{key} 必须是整数") from exc
        if not minimum <= value <= maximum:
            raise HTTPException(400, f"{key} 必须在 {minimum} 到 {maximum} 之间")
        updates[key] = value
    current = {**DEFAULTS, **app.state.db.get_config().get("features", {}), **updates}
    if int(current["market_min_price"]) > int(current["market_max_price"]):
        raise HTTPException(400, "市场最低价格不能高于最高价格")
    if int(current["market_default_stock"]) > int(current["market_max_stock"]):
        raise HTTPException(400, "默认库存不能高于库存上限")
    if int(current["market_default_duration_days"]) > int(current["market_max_duration_days"]):
        raise HTTPException(400, "默认有效期不能高于有效期上限")
    config = app.state.db.get_config()
    config["features"] = {**config.get("features", {}), **updates}
    app.state.db.save_config(config)
    app.state.logger.info("群友市场设置已保存；官方商店设置与数据未改动")
    return await get_marketplace_settings()


@app.put("/api/marketplace/listings/{listing_id}")
async def update_marketplace_listing(listing_id: int, payload: dict):
    reason = str(payload.get("reason") or "").strip()
    changes = {key: value for key, value in payload.items() if key != "reason"}
    from app.command_router import DEFAULTS

    features = {**DEFAULTS, **app.state.db.get_config().get("features", {})}
    try:
        return app.state.db.marketplace_core.admin_update(
            listing_id,
            changes,
            admin_identity="local-manager",
            reason=reason,
            minimum_price=int(features.get("market_min_price", 50) or 50),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/rp")
async def get_rp_admin():
    return app.state.db.list_rp_admin()


@app.get("/api/rp/settings")
async def get_rp_settings():
    from app.command_router import DEFAULTS
    merged = {**DEFAULTS, **app.state.db.get_config().get("features", {})}
    return {key: merged.get(key) for key in RP_SETTING_KEYS}


@app.post("/api/rp/settings")
async def save_rp_settings(payload: dict):
    updates = {key: value for key, value in payload.items() if key in RP_SETTING_KEYS}
    try:
        maximum = int(updates.get("rp_max_participants", 10))
        timeout = int(updates.get("rp_gather_timeout_seconds", 300))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "RP人数上限和集结时间必须是整数") from exc
    if not 1 <= maximum <= 10:
        raise HTTPException(400, "RP人数上限必须为1～10")
    if not 30 <= timeout <= 3600:
        raise HTTPException(400, "RP集结时间必须为30～3600秒")
    updates["rp_max_participants"] = maximum
    updates["rp_gather_timeout_seconds"] = timeout
    config = app.state.db.get_config()
    config["features"] = {**config.get("features", {}), **updates}
    app.state.db.save_config(config)
    app.state.logger.info("沉浸RP结界设置已保存")
    return await get_rp_settings()


@app.post("/api/rp/{group_id}/close")
async def close_rp_admin(group_id: str):
    event = app.state.db.random_event_core.get_current_session(group_id)
    if event:
        result = app.state.db.random_event_core.end(
            {"group_id": group_id, "group_key": group_id, "sender": "后台管理员", "message_id": f"rp-admin:{time.time()}"},
            force=True,
        )
        return {"ok": bool(result.get("ok")), "random_event_closed": True}
    return {"ok": app.state.db.admin_close_rp(group_id)}


@app.post("/api/rp/violations/{violation_id}")
async def update_rp_violation_admin(violation_id: int, payload: dict):
    try:
        return app.state.db.update_rp_violation(
            violation_id, str(payload.get("status") or ""), str(payload.get("note") or "")
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/random-events")
async def get_random_events_admin():
    return app.state.db.random_event_core.list_admin()


@app.get("/api/random-events/settings")
async def get_random_event_settings():
    from app.command_router import DEFAULTS

    merged = {**DEFAULTS, **app.state.db.get_config().get("features", {})}
    return {key: merged.get(key) for key in RANDOM_EVENT_SETTING_KEYS}


@app.post("/api/random-events/settings")
async def save_random_event_settings(payload: dict):
    from app.command_router import DEFAULTS

    updates = {key: value for key, value in payload.items() if key in RANDOM_EVENT_SETTING_KEYS}
    command_keys = [key for key in RANDOM_EVENT_SETTING_KEYS if key.endswith("_commands")]
    for key in command_keys:
        if key not in updates:
            continue
        commands = [item.strip() for item in str(updates[key]).replace("，", ",").split(",") if item.strip()]
        if not commands or any(not item.startswith("/") for item in commands):
            raise HTTPException(400, f"{key} 必须至少包含一个以 / 开头的命令")
        updates[key] = ",".join(dict.fromkeys(commands))
    try:
        timeout = int(updates.get("random_event_recruit_timeout_seconds", DEFAULTS["random_event_recruit_timeout_seconds"]))
        draft_ttl = int(updates.get("random_event_draft_ttl_seconds", DEFAULTS["random_event_draft_ttl_seconds"]))
        daily_count = int(updates.get("random_event_auto_daily_count", DEFAULTS["random_event_auto_daily_count"]))
        ai_timeout = int(updates.get("random_event_ai_timeout_seconds", DEFAULTS["random_event_ai_timeout_seconds"]))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "随机事件数值设置格式不正确") from exc
    if not 60 <= timeout <= 3600:
        raise HTTPException(400, "招募超时必须为60至3600秒")
    if not 60 <= draft_ttl <= 3600:
        raise HTTPException(400, "草稿有效期必须为60至3600秒")
    if not 1 <= daily_count <= 12:
        raise HTTPException(400, "每天自动发起次数必须为1至12次")
    if not 3 <= ai_timeout <= 120:
        raise HTTPException(400, "AI超时必须为3至120秒")
    times = app.state.db.random_event_core.schedule_times({
        **DEFAULTS,
        **app.state.db.get_config().get("features", {}),
        **updates,
    })
    if len(times) < daily_count:
        raise HTTPException(400, f"每天设置了{daily_count}次，请填写{daily_count}个不同的有效时间（HH:MM）")
    for key in ("random_event_ai_system_prompt", "random_event_ai_user_prompt"):
        if key in updates and not str(updates[key] or "").strip():
            raise HTTPException(400, "AI提示词不能为空，避免保存后全部提示词失效")
    updates.update({
        "random_event_recruit_timeout_seconds": timeout,
        "random_event_draft_ttl_seconds": draft_ttl,
        "random_event_auto_daily_count": daily_count,
        "random_event_ai_timeout_seconds": ai_timeout,
        "random_event_auto_times": ",".join(times),
    })
    config = app.state.db.get_config()
    config.setdefault("features", {}).update(updates)
    app.state.db.save_config(config)
    return await get_random_event_settings()


@app.post("/api/random-events/templates")
async def create_random_event_template(payload: dict):
    try:
        return app.state.db.random_event_core.save_template(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/random-events/templates/{template_id}")
async def update_random_event_template(template_id: int, payload: dict):
    try:
        return app.state.db.random_event_core.save_template(payload, template_id=template_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/random-events/templates/{template_id}/archive")
async def archive_random_event_template(template_id: int):
    if not app.state.db.random_event_core.archive_template(template_id):
        raise HTTPException(404, "没有找到可以归档的随机事件")
    return {"ok": True}


@app.post("/api/random-events/{group_id}/close")
async def close_random_event_admin(group_id: str):
    result = app.state.db.random_event_core.end(
        {"group_id": group_id, "group_key": group_id, "sender": "后台管理员", "message_id": f"admin:{time.time()}"},
        force=True,
    )
    if not result.get("ok"):
        raise HTTPException(404, "当前群没有正在招募或进行中的随机事件")
    return result


@app.get("/api/image-generation/settings")
async def get_image_generation_settings():
    config = app.state.db.get_config()
    settings = merged_image_settings(config)
    api_key = app.state.db.get_secret("image2_api_key")
    return {
        **settings,
        "image_group_url": str(config.get("dzmm", {}).get("image_group_url") or ""),
        "api_key_configured": bool(api_key),
        "api_key_hint": ("••••" + api_key[-4:]) if api_key else "",
        "api_key_source": app.state.db.secret_source("image2_api_key"),
        "service": app.state.image_generation_service.status(),
    }


@app.post("/api/image-generation/settings")
async def save_image_generation_settings(payload: dict):
    new_api_key = str(payload.get("api_key") or "").strip()
    if new_api_key and not 10 <= len(new_api_key) <= 2048:
        raise HTTPException(400, "图片 API 密钥长度应为 10～2048 个字符")
    updates = {key: value for key, value in payload.items() if key in IMAGE_GENERATION_SETTING_KEYS}
    for key in ("default_commands", "portrait_commands", "landscape_commands"):
        if key in updates:
            _validate_command_triggers(str(updates[key] or ""))
            commands = _split_command_triggers(str(updates[key]))
            updates[key] = ",".join(dict.fromkeys(commands))

    for key in ("default_ratio", "portrait_ratio", "landscape_ratio"):
        if key in updates and str(updates[key]) not in ALLOWED_IMAGE_RATIOS:
            raise HTTPException(400, f"{key} 仅支持：{', '.join(sorted(ALLOWED_IMAGE_RATIOS))}")

    if "api_base" in updates:
        api_base = str(updates["api_base"] or "").strip().rstrip("/")
        if not (api_base.startswith("https://") or api_base.startswith("http://127.0.0.1") or api_base.startswith("http://localhost")):
            raise HTTPException(400, "图片API地址必须使用HTTPS或本机地址")
        updates["api_base"] = api_base
    if "model" in updates:
        model = str(updates["model"] or "").strip()
        if not model:
            raise HTTPException(400, "图片模型名称不能为空")
        updates["model"] = model

    numeric_bounds = {
        "api_timeout_seconds": (30, 1800),
        "download_timeout_seconds": (30, 1800),
        "upload_timeout_seconds": (30, 600),
        "max_file_mb": (1, 100),
        "max_prompt_chars": (1, 2000),
        "cost": (0, 100000),
        "per_user_daily_limit": (0, 1000),
        "global_daily_limit": (0, 100000),
        "cooldown_seconds": (0, 86400),
        "max_concurrent": (1, 3),
        "history_page_size": (1, 100),
        "history_retention_days": (0, 3650),
        "thumbnail_max_dimension": (120, 1200),
        "thumbnail_quality": (30, 100),
    }
    for key, (minimum, maximum) in numeric_bounds.items():
        if key not in updates:
            continue
        try:
            value = int(updates[key])
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"{key} 必须是整数") from exc
        if not minimum <= value <= maximum:
            raise HTTPException(400, f"{key} 必须在 {minimum} 到 {maximum} 之间")
        updates[key] = value

    command_owner: dict[str, str] = {}
    effective = {**merged_image_settings(app.state.db.get_config()), **updates}
    for key in ("default_commands", "portrait_commands", "landscape_commands"):
        for command in _split_command_triggers(str(effective.get(key) or "")):
            normalized = command if bool(effective.get("case_sensitive")) else command.casefold()
            if normalized in command_owner and command_owner[normalized] != key:
                raise HTTPException(400, f"图片命令重复：{command}")
            command_owner[normalized] = key

    image_group_url = str(payload.get("image_group_url") or "").strip()
    if not re.fullmatch(r"https://www\.aikda\.com/chat\?c=[0-9a-fA-F-]{36}", image_group_url):
        raise HTTPException(400, "绘图群地址格式不正确，应为 aikda.com 的完整群聊地址")
    config = app.state.db.get_config()
    main_url = str(config.get("dzmm", {}).get("group_url") or "").strip()
    bounty_url = str(config.get("dzmm", {}).get("bounty_group_url") or "").strip()
    if image_group_url in {main_url, bounty_url}:
        raise HTTPException(400, "绘图群必须与主群、悬赏群使用不同地址")
    config["image_generation"] = {**config.get("image_generation", {}), **updates}
    config.setdefault("dzmm", {})["image_group_url"] = image_group_url
    app.state.db.save_config(config)

    if bool(payload.get("clear_api_key")):
        app.state.db.set_secret("image2_api_key", "")
    elif new_api_key:
        app.state.db.set_secret("image2_api_key", new_api_key)
    app.state.scheduler.primed_groups.discard("image")
    app.state.logger.info("图片生成设置已保存；主群和悬赏群配置未改动")
    return await get_image_generation_settings()


@app.post("/api/image-generation/test")
async def test_image_generation_connection(payload: dict):
    settings = merged_image_settings(app.state.db.get_config())
    api_key = app.state.db.get_secret("image2_api_key")
    if not api_key:
        raise HTTPException(400, "请先保存图片API密钥")
    prompt = str(payload.get("prompt") or "一只可爱猫猫，精致插画").strip()
    if not prompt or len(prompt) > 2000:
        raise HTTPException(400, "测试提示词必须为1至2000个字符")
    ratio = str(payload.get("ratio") or settings.get("default_ratio") or "3:4")
    if ratio not in ALLOWED_IMAGE_RATIOS:
        raise HTTPException(400, "测试图片比例不受支持")
    test_dir = app.state.image_generation_service.temp_dir / f"api-test-{time.time_ns()}"
    try:
        client = Image2Client(
            str(settings.get("api_base") or ""),
            api_key,
            api_timeout=float(settings.get("api_timeout_seconds", 300)),
            download_timeout=float(settings.get("download_timeout_seconds", 300)),
            max_file_bytes=int(settings.get("max_file_mb", 25)) * 1024 * 1024,
        )
        result = await asyncio.to_thread(
            client.generate,
            prompt=prompt,
            model=str(settings.get("model") or "gpt-image-2"),
            ratio=ratio,
            output_dir=test_dir,
        )
        return {
            "ok": True,
            "message": "图片API连接成功，并已生成有效测试图片",
            "width": result["width"],
            "height": result["height"],
            "format": result["format"],
            "file_size": result["file_size"],
        }
    except ImageGenerationError as exc:
        raise HTTPException(502, f"图片API测试失败：{exc}") from exc
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


@app.get("/api/image-generation/history")
async def list_image_generation_history(page: int = 1, page_size: int = 10, status: str = "", search: str = ""):
    return app.state.db.image_generation_core.list_jobs(
        page=page,
        page_size=page_size,
        status=status.strip(),
        search=search.strip(),
    )


@app.get("/api/image-generation/history/{job_id}/image")
async def get_image_generation_file(job_id: str, download: bool = False):
    job = app.state.db.image_generation_core.get(job_id)
    path = app.state.image_generation_service.resolve_media(job_id)
    if not job or not path:
        raise HTTPException(404, "历史图片不存在或文件已丢失")
    return FileResponse(
        path,
        media_type=f"image/{'jpeg' if path.suffix.lower() in {'.jpg', '.jpeg'} else path.suffix.lower().lstrip('.')}",
        filename=f"DZMM-{job_id}{path.suffix}" if download else None,
    )


@app.get("/api/image-generation/history/{job_id}/thumbnail")
async def get_image_generation_thumbnail(job_id: str):
    path = app.state.image_generation_service.resolve_media(job_id, thumbnail=True)
    if not path:
        raise HTTPException(404, "缩略图不存在")
    return FileResponse(path, media_type="image/webp")


@app.post("/api/image-generation/history/{job_id}/resend")
async def resend_image_generation(job_id: str):
    try:
        job = await app.state.image_generation_service.resend(job_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "job": job}


@app.get("/api/bounties/{bounty_id}")
async def get_bounty(bounty_id: int):
    bounty = app.state.db.get_bounty(bounty_id)
    if not bounty:
        raise HTTPException(404, "没有找到这个悬赏编号")
    return bounty


@app.get("/api/bounties/{bounty_id}/delete-preview")
async def preview_delete_bounty(bounty_id: int):
    try:
        return app.state.db.preview_admin_delete_bounty(bounty_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/bounties/{bounty_id}")
async def update_bounty(bounty_id: int, payload: dict):
    try:
        return app.state.db.admin_update_bounty(
            bounty_id,
            payload,
            admin_identity="local-manager",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/bounties/{bounty_id}")
async def delete_bounty(bounty_id: int, payload: dict | None = None):
    try:
        return app.state.db.admin_delete_bounty(
            bounty_id,
            admin_identity="local-manager",
            reason=str((payload or {}).get("reason") or "").strip(),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/shop-items")
async def list_shop_items():
    return app.state.db.list_shop_items(include_disabled=True)


@app.post("/api/shop-items")
async def save_shop_item(payload: ShopItemPayload):
    try:
        item_id = app.state.db.upsert_shop_item(payload.model_dump())
        return {"ok": True, "id": item_id}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/shop-items/{item_id}")
async def delete_shop_item(item_id: int):
    app.state.db.delete_shop_item(item_id)
    return {"ok": True}


def _select_local_folder(initial_folder: str = "") -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        initial = initial_folder if initial_folder and Path(initial_folder).is_dir() else str(APP_DIR)
        return filedialog.askdirectory(
            parent=root,
            initialdir=initial,
            title="选择图片商品图库文件夹",
            mustexist=True,
        ) or ""
    finally:
        root.destroy()


@app.post("/api/folders/select")
async def select_folder(payload: dict):
    folder = await asyncio.to_thread(_select_local_folder, str(payload.get("current") or ""))
    return {"ok": True, "path": folder}


@app.get("/api/rules/groups")
async def list_rule_groups():
    groups = app.state.db.list_rule_groups()
    return {"groups": [g["name"] for g in groups], "counts": [g["count"] for g in groups]}


@app.post("/api/rules/groups/create")
async def create_rule_group(payload: dict):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "分组名不能为空")
    config = app.state.db.get_config()
    groups = config.get("rule_groups", [])
    if name not in groups:
        groups.append(name)
        config["rule_groups"] = groups
        app.state.db.save_config(config)
    return {"ok": True, "name": name}

@app.post("/api/rules/groups/rename")
async def rename_rule_group(payload: dict):
    old_name = (payload.get("old_name") or "").strip()
    new_name = (payload.get("new_name") or "").strip()
    if not old_name or not new_name:
        raise HTTPException(400, "分组名不能为空")
    count = app.state.db.rename_rule_group(old_name, new_name)
    config = app.state.db.get_config()
    groups = config.get("rule_groups", [])
    if old_name in groups:
        groups[groups.index(old_name)] = new_name
        config["rule_groups"] = groups
        app.state.db.save_config(config)
    return {"ok": True, "updated": count}


@app.post("/api/rules/groups/delete")
async def delete_rule_group(payload: dict):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "分组名不能为空")
    count = app.state.db.delete_rule_group(name)
    config = app.state.db.get_config()
    groups = config.get("rule_groups", [])
    if name in groups:
        groups.remove(name)
        config["rule_groups"] = groups
        app.state.db.save_config(config)
    return {"ok": True, "updated": count}


@app.get("/api/rules")
async def list_rules():
    return app.state.db.list_rules()


@app.post("/api/rules")
async def create_rule(payload: RulePayload):
    data = payload.model_dump()
    data["trigger_type"] = "exact"
    _validate_command_triggers(data["trigger_value"])
    rid = app.state.db.create_rule(data)
    return {"ok": True, "id": rid}


@app.put("/api/rules/{rule_id}")
async def update_rule(rule_id: int, payload: RulePayload):
    data = payload.model_dump()
    data["trigger_type"] = "exact"
    _validate_command_triggers(data["trigger_value"])
    app.state.db.update_rule(rule_id, data)
    return {"ok": True}


@app.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: int):
    app.state.db.delete_rule(rule_id)
    return {"ok": True}


@app.post("/api/rules/{rule_id}/duplicate")
async def duplicate_rule(rule_id: int):
    return {"ok": True, "id": app.state.db.duplicate_rule(rule_id)}


@app.get("/api/rules/export")
async def export_rules():
    return {"rules": app.state.db.list_rules()}


@app.post("/api/rules/import")
async def import_rules(payload: dict):
    return {"ok": True, "imported": app.state.db.import_rules(payload.get("rules", []))}


@app.post("/api/rules/test")
async def test_rules(payload: TestRulePayload):
    config = app.state.db.get_config()
    text = payload.text.strip()
    if config.get("dzmm", {}).get("require_slash_prefix", True) and not text.startswith("/"):
        return {
            "hits": [],
            "details": [{"rule_id": 0, "rule_name": "命令模式", "enabled": True, "matched": False, "reason": "消息不是 / 开头，机器人会忽略普通聊天。", "blocked": False, "block_reason": "未进入规则匹配", "reply": ""}],
        }
    command_result = app.state.command_router.handle({"sender": payload.sender, "text": payload.text, "is_self": False}, dry_run=True)
    if command_result.handled:
        item = {"rule_id": 0, "rule_name": f"内置命令：/{command_result.name}", "enabled": True, "matched": True, "reason": command_result.reason, "blocked": False, "block_reason": "未触发冷却", "reply": "\n".join(command_result.replies)}
        return {"hits": [item], "details": [item]}
    result = app.state.engine.test_rule({"sender": payload.sender, "text": payload.text, "is_self": False}, payload.sender)
    if text.startswith("/") and not result["hits"]:
        result["hits"] = [{"rule_id": 0, "rule_name": "未知命令", "enabled": True, "matched": True, "reason": "消息以 / 开头，但没有命中任何内置功能或自定义命令。", "blocked": False, "block_reason": "会回复未知命令提示", "reply": config.get("dzmm", {}).get("unknown_command_reply", "命令错误")}]
    return result


@app.get("/api/logs")
async def list_logs(kind: str = "all"):
    return app.state.db.list_logs(limit=300, kind=kind)


@app.delete("/api/logs")
async def clear_logs():
    app.state.db.clear_logs()
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=7902, reload=False)
