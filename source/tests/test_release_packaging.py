from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "source"


def test_public_repository_ignores_private_and_generated_files() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    required = {
        "data/",
        "source/data/",
        "source/app/_embedded_secret_payload.py",
        "*.db",
        "secrets.json",
        "browser_profile/",
        "*.log",
        "DZMMBot-current-data.zip",
        "_internal/",
        "ms-playwright/",
        "webview2-runtime/",
    }
    assert required <= {line.strip() for line in ignore.splitlines()}


def test_spec_allows_public_build_without_embedded_api_key() -> None:
    spec = (SOURCE / "DZMMBot.spec").read_text(encoding="utf-8")
    assert "DeepSeek embedded payload is empty" not in spec
    assert "from app._embedded_secret_payload import DEEPSEEK_SECRET_BLOB" in spec


def test_windows_workflow_builds_portable_and_setup_without_secret_injection() -> None:
    workflow = (ROOT / ".github/workflows/build-windows.yml").read_text(encoding="utf-8")
    assert "windows-latest" in workflow
    assert "python-version: '3.12'" in workflow
    assert "playwright install chromium" in workflow
    assert 'DEEPSEEK_SECRET_BLOB = ""' in workflow
    assert "PyInstaller" in workflow
    assert "assemble_windows_release.ps1" in workflow
    assert "DZMMBot-Portable-win64.zip" in workflow
    assert "DZMMBot-Setup-win64.exe" in workflow
    assert "secrets." not in workflow


def test_release_assembly_copies_runtime_but_never_live_data() -> None:
    script = (SOURCE / "scripts/assemble_windows_release.ps1").read_text(encoding="utf-8")
    assert '"dist\\DZMM群聊机器人"' in script
    assert '"ms-playwright"' in script
    assert "Compress-Archive" in script
    assert "Copy-Item" in script
    assert "data" not in script.lower()


def test_packaged_assets_and_image_dependency_are_declared() -> None:
    spec = (SOURCE / "DZMMBot.spec").read_text(encoding="utf-8")
    requirements = (SOURCE / "requirements.txt").read_text(encoding="utf-8")
    assert '("../塔罗牌素材", "塔罗牌素材")' in spec
    assert "Pillow==12.3.0" in requirements
