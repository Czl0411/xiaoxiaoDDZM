from pathlib import Path

from app.database import Database


def make_db(tmp_path):
    db = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    db.init()
    return db


def create_image_item(db, gallery, name="轮播图片"):
    item_id = db.upsert_shop_item(
        {
            "name": name,
            "item_category": "image",
            "price": 1,
            "image_folder": str(gallery),
        }
    )
    return db.conn.execute(
        "select * from shop_items where id=?",
        (item_id,),
    ).fetchone()


def add_images(gallery, names):
    gallery.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        path = gallery / name
        path.write_bytes(name.encode("utf-8"))
        paths.append(str(path.resolve()))
    return paths


def test_images_do_not_repeat_before_the_round_is_complete(tmp_path):
    gallery = tmp_path / "gallery"
    expected = set(add_images(gallery, [f"{index}.png" for index in range(8)]))
    db = make_db(tmp_path)
    item = dict(create_image_item(db, gallery))

    first_round = [db.pick_shop_item_image(item) for _ in range(8)]
    next_round_first = db.pick_shop_item_image(item)

    assert len(first_round) == len(set(first_round)) == 8
    assert set(first_round) == expected
    assert next_round_first in expected
    assert next_round_first != first_round[-1]


def test_draw_progress_survives_database_restart(tmp_path):
    gallery = tmp_path / "gallery"
    expected = set(add_images(gallery, ["a.png", "b.png", "c.png", "d.png"]))
    db = make_db(tmp_path)
    item = dict(create_image_item(db, gallery))
    first_two = [db.pick_shop_item_image(item) for _ in range(2)]
    db.close()

    reopened = Database(tmp_path / "bot.db", allow_legacy_user_creation=True)
    reopened.init()
    reopened_item = dict(
        reopened.conn.execute(
            "select * from shop_items where id=?",
            (int(item["id"]),),
        ).fetchone()
    )
    next_two = [reopened.pick_shop_item_image(reopened_item) for _ in range(2)]

    assert len(set(first_two + next_two)) == 4
    assert set(first_two + next_two) == expected


def test_new_image_joins_the_current_round_without_repeating_old_images(tmp_path):
    gallery = tmp_path / "gallery"
    add_images(gallery, ["a.png", "b.png"])
    db = make_db(tmp_path)
    item = dict(create_image_item(db, gallery))
    first = db.pick_shop_item_image(item)
    new_image = add_images(gallery, ["c.png"])[0]

    second = db.pick_shop_item_image(item)
    third = db.pick_shop_item_image(item)

    assert len({first, second, third}) == 3
    assert new_image in {first, second, third}


def test_changing_gallery_starts_a_fresh_rotation(tmp_path):
    first_gallery = tmp_path / "first"
    second_gallery = tmp_path / "second"
    add_images(first_gallery, ["a.png", "b.png"])
    second_images = set(add_images(second_gallery, ["x.png", "y.png"]))
    db = make_db(tmp_path)
    item = dict(create_image_item(db, first_gallery))
    db.pick_shop_item_image(item)

    db.upsert_shop_item(
        {
            "id": int(item["id"]),
            "name": item["name"],
            "item_category": "image",
            "price": 1,
            "image_folder": str(second_gallery),
        }
    )
    updated = dict(
        db.conn.execute(
            "select * from shop_items where id=?",
            (int(item["id"]),),
        ).fetchone()
    )
    selected = db.pick_shop_item_image(updated)

    assert selected in second_images
    state = db.conn.execute(
        "select image_folder, cycle from shop_image_draw_state where item_id=?",
        (int(item["id"]),),
    ).fetchone()
    assert Path(state["image_folder"]) == second_gallery.resolve()
    assert state["cycle"] == 1


def test_relative_gallery_is_resolved_from_data_directory(tmp_path):
    gallery = tmp_path / "shop_images" / "item-1"
    expected = set(add_images(gallery, ["a.png", "b.png"]))
    db = make_db(tmp_path)
    item = dict(create_image_item(db, Path("shop_images") / "item-1"))

    selected = db.pick_shop_item_image(item)

    assert selected in expected
