from app.database import Database


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    return db


def test_direct_chat_mapping_updates_by_user(tmp_path):
    db = make_db(tmp_path)
    db.upsert_direct_chat("user-a", "room-1")
    db.upsert_direct_chat("user-a", "room-2")

    assert db.get_direct_chatroom_id("user-a") == "room-2"
    assert db.list_direct_chatroom_ids() == ["room-2"]


def test_direct_chat_room_is_reassigned_without_cross_user_delivery(tmp_path):
    db = make_db(tmp_path)
    db.upsert_direct_chat("user-a", "shared-room")
    db.upsert_direct_chat("user-b", "shared-room")

    assert db.get_direct_chatroom_id("user-a") is None
    assert db.get_direct_chatroom_id("user-b") == "shared-room"


def test_startup_recovers_direct_chat_mapping_from_message_history(tmp_path):
    path = tmp_path / "bot.db"
    db = Database(path, allow_legacy_user_creation=True)
    db.init()
    db.save_message({
        "message_id": "old-direct-message",
        "platform_user_id": "seller-id",
        "sender": "卖家",
        "text": "/服务",
        "source_group": "direct:seller-room",
    })
    assert db.get_direct_chatroom_id("seller-id") is None
    db.close()

    restarted = Database(path, allow_legacy_user_creation=True)
    restarted.init()

    assert restarted.get_direct_chatroom_id("seller-id") == "seller-room"
