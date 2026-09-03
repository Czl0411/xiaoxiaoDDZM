from __future__ import annotations

import argparse
import sqlite3
import tempfile
import zipfile
from pathlib import Path


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()


def export_data(data_dir: Path, output: Path) -> list[str]:
    source = Path(data_dir).resolve()
    target = Path(output).resolve()
    if target.is_relative_to(source):
        raise ValueError("输出文件必须位于源数据目录之外")
    for required in ("bot.db", "config.json"):
        if not (source / required).is_file():
            raise FileNotFoundError(f"缺少必要文件：{required}")

    target.parent.mkdir(parents=True, exist_ok=True)
    members: list[tuple[Path, str]] = [(source / "config.json", "data/config.json")]
    for directory in ("image_generation", "shop_images"):
        root = source / directory
        if root.is_dir():
            members.extend(
                (path, f"data/{directory}/{path.relative_to(root).as_posix()}")
                for path in sorted(root.rglob("*"))
                if path.is_file()
            )

    with tempfile.TemporaryDirectory(prefix="dzmm-export-") as temporary:
        snapshot = Path(temporary) / "bot.db"
        _sqlite_snapshot(source / "bot.db", snapshot)
        all_members = [(snapshot, "data/bot.db"), *members]
        all_members.sort(key=lambda item: item[1])
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, name in all_members:
                archive.write(path, name)
    return [name for _, name in all_members]


def main() -> int:
    parser = argparse.ArgumentParser(description="导出可安全迁移的 DZMMBot 当前业务数据")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    members = export_data(args.data_dir, args.output)
    print(f"output={args.output.resolve()}")
    print(f"member_count={len(members)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
