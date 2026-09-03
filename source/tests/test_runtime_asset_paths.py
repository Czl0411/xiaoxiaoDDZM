from pathlib import Path

import main


def test_runtime_asset_resolver_finds_portable_root_assets():
    blind_box = main._resolve_runtime_asset_dir("盲盒小游戏素材")
    tarot = main._resolve_runtime_asset_dir("塔罗牌素材")

    assert blind_box.is_dir()
    assert (blind_box / "2660173a-8afe-4002-a9b0-c07fd40ae5aa.png").is_file()
    assert tarot.is_dir()
    assert any(path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} for path in tarot.iterdir())


def test_runtime_asset_resolver_prefers_packaged_resource_directory(tmp_path, monkeypatch):
    packaged = tmp_path / "internal"
    executable = tmp_path / "app"
    (packaged / "素材").mkdir(parents=True)
    (executable / "素材").mkdir(parents=True)
    monkeypatch.setattr(main, "RESOURCE_DIR", packaged)
    monkeypatch.setattr(main, "APP_DIR", executable)

    assert main._resolve_runtime_asset_dir("素材") == packaged / "素材"
