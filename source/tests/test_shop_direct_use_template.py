from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.command_router import CommandRouter
from app.database import (
    Database,
    IMAGE_SHOP_KIND,
    THEFT_ABSOLUTE_ITEM,
    THEFT_MULTI_DEFENSE_ITEM,
)
from main import ShopItemPayload


def test_shop_payload_keeps_direct_use_reply_template():
    payload = ShopItemPayload(
        name="小狗药水",
        direct_use_reply_template="{actor}使用了{item}，变成了小狗！",
        use_target="direct",
    )

    assert payload.model_dump()["direct_use_reply_template"] == "{actor}使用了{item}，变成了小狗！"


def test_shop_payload_keeps_image_folder():
    payload = ShopItemPayload(
        name="图片商品",
        item_category="image",
        image_folder=r"D:\图库",
    )

    assert payload.model_dump()["image_folder"] == r"D:\图库"


def test_direct_use_item_uses_direct_reply_template(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    db.upsert_shop_item(
        {
            "name": "小狗药水",
            "price": 1,
            "stock": -1,
            "enabled": True,
            "use_target": "direct",
            "direct_use_reply_template": "{actor}使用了{item}，变成了小狗！",
        }
    )
    db.add_points("大祭司", 10, "测试发放")
    db.purchase_item_by_number("大祭司", 1)

    result = db.use_inventory_item("大祭司", None, 1)

    assert result["ok"]
    assert result["reply"] == "大祭司使用了小狗药水，变成了小狗！"


def test_image_shop_item_selects_image_and_exposes_media_path(tmp_path):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    first = gallery / "first.webp"
    second = gallery / "second.png"
    first.write_bytes(b"webp")
    second.write_bytes(b"png")

    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    db.upsert_shop_item(
        {
            "name": "安洁莉卡的口交服务",
            "item_category": "image",
            "price": 20,
            "stock": -1,
            "enabled": True,
            "use_target": "direct",
            "direct_use_reply_template": "前置文字",
            "image_folder": str(gallery),
        }
    )
    item = db.list_shop_items()[0]
    assert item["special_kind"] == IMAGE_SHOP_KIND
    db.add_points("大祭司", 20, "测试发放")
    db.purchase_item_by_number("大祭司", 1)

    result = db.use_inventory_item("大祭司", None, 1)

    assert result["ok"]
    assert result["reply"] == "前置文字"
    assert Path(result["image_path"]) in {first.resolve(), second.resolve()}
    assert db.get_inventory("大祭司") == []


def test_image_shop_item_empty_gallery_does_not_consume_inventory(tmp_path):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    image = gallery / "only.webp"
    image.write_bytes(b"webp")

    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    db.upsert_shop_item(
        {
            "name": "图片服务",
            "item_category": "image",
            "price": 1,
            "image_folder": str(gallery),
        }
    )
    db.add_points("大祭司", 1, "测试发放")
    db.purchase_item_by_number("大祭司", 1)
    image.unlink()

    result = db.use_inventory_item("大祭司", None, 1)

    assert not result["ok"]
    assert result["reason"] == "image_folder_empty"
    assert db.get_inventory("大祭司")[0]["quantity"] == 1


def test_image_shop_command_returns_media_action(tmp_path):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    image = gallery / "only.webp"
    image.write_bytes(b"webp")
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    db.upsert_shop_item(
        {
            "name": "图片服务",
            "item_category": "image",
            "price": 1,
            "image_folder": str(gallery),
            "direct_use_reply_template": "图片马上送到",
        }
    )
    db.add_points("大祭司", 1, "测试发放")
    db.purchase_item_by_number("大祭司", 1)

    result = CommandRouter(db)._use_self_item(
        {"sender": "大祭司", "text": "/使用物品1"},
        1,
        {},
    )

    assert result.replies == ["图片马上送到"]
    assert result.media_paths == [str(image.resolve())]


def test_passive_items_do_not_take_manual_inventory_numbers(tmp_path):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    image = gallery / "only.webp"
    image.write_bytes(b"webp")
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    db.ensure_theft_shop_items()
    db.upsert_shop_item(
        {
            "name": "图片服务",
            "item_category": "image",
            "price": 1,
            "image_folder": str(gallery),
            "direct_use_reply_template": "图片马上送到",
        }
    )
    db.add_points("大祭司", 500, "测试发放")
    db.purchase_item("大祭司", THEFT_MULTI_DEFENSE_ITEM)
    db.purchase_item("大祭司", "图片服务")

    router = CommandRouter(db)
    inventory = router._inventory(
        {"sender": "大祭司", "text": "/背包"},
        {"currency_name": "功德点", "inventory_header": "{user}的背包：", "inventory_item_line": "{number}. {item} x {quantity}"},
    )
    result = router._use_self_item(
        {"sender": "大祭司", "text": "/使用物品1"},
        1,
        {},
    )

    assert "1. 图片服务（用法：/使用物品1） x 1" in inventory.replies[0]
    assert f"- {THEFT_MULTI_DEFENSE_ITEM}" in inventory.replies[0]
    assert "不占使用编号" in inventory.replies[0]
    assert result.media_paths == [str(image.resolve())]


def test_other_target_item_cannot_be_consumed_by_self_use(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    db.ensure_theft_shop_items()
    db.add_points("大祭司", 100, "测试发放")
    db.purchase_item("大祭司", THEFT_ABSOLUTE_ITEM)

    result = db.use_inventory_item("大祭司", None, 1)

    assert not result["ok"]
    assert result["reason"] == "target_required"
    inventory = db.get_inventory("大祭司")
    assert inventory[0]["item_name"] == THEFT_ABSOLUTE_ITEM
    assert inventory[0]["quantity"] == 1
