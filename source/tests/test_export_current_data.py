from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from scripts.export_current_data import export_data


def make_data_tree(root: Path) -> None:
    root.mkdir()
    connection = sqlite3.connect(root / "bot.db")
    connection.execute("create table marker(value text)")
    connection.execute("insert into marker values ('current')")
    connection.commit()
    connection.close()
    (root / "config.json").write_text('{"enabled": true}', encoding="utf-8")
    (root / "secrets.json").write_text('{"key": "private"}', encoding="utf-8")
    (root / "shop_images").mkdir()
    (root / "shop_images/item.png").write_bytes(b"shop")
    (root / "image_generation").mkdir()
    (root / "image_generation/result.png").write_bytes(b"image")
    (root / "browser_profile").mkdir()
    (root / "browser_profile/cookie").write_text("private", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs/bot.log").write_text("private", encoding="utf-8")


def test_export_contains_only_allowlisted_current_business_data(tmp_path: Path) -> None:
    data_dir = tmp_path / "current"
    make_data_tree(data_dir)
    output = tmp_path / "DZMMBot-current-data.zip"

    members = export_data(data_dir, output)

    assert members == [
        "data/bot.db",
        "data/config.json",
        "data/image_generation/result.png",
        "data/shop_images/item.png",
    ]
    with zipfile.ZipFile(output) as archive:
        assert sorted(archive.namelist()) == members
        extracted = tmp_path / "extracted.db"
        extracted.write_bytes(archive.read("data/bot.db"))
    connection = sqlite3.connect(extracted)
    assert connection.execute("select value from marker").fetchone()[0] == "current"
    connection.close()


@pytest.mark.parametrize("missing", ["bot.db", "config.json"])
def test_export_requires_database_and_config(tmp_path: Path, missing: str) -> None:
    data_dir = tmp_path / "current"
    make_data_tree(data_dir)
    (data_dir / missing).unlink()

    with pytest.raises(FileNotFoundError, match=missing):
        export_data(data_dir, tmp_path / "out.zip")


def test_export_refuses_output_inside_source_data_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "current"
    make_data_tree(data_dir)

    with pytest.raises(ValueError, match="数据目录之外"):
        export_data(data_dir, data_dir / "out.zip")
