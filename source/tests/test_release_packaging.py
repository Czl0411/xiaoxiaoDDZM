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
    assert "PYTHONPATH: ${{ github.workspace }}\\source" in workflow
    assert "playwright install chromium" in workflow
    assert 'DEEPSEEK_SECRET_BLOB = ""' in workflow
    assert "PyInstaller" in workflow
    assert "assemble_windows_release.ps1" in workflow
    assert "powershell -ExecutionPolicy" not in workflow
    assert "DZMMBot-Portable-win64.zip" in workflow
    assert "DZMMBot-Setup-win64.exe" in workflow
    assert "secrets." not in workflow


def test_release_assembly_copies_runtime_but_never_live_data() -> None:
    script = (SOURCE / "scripts/assemble_windows_release.ps1").read_text(encoding="utf-8")
    assert '"dist\\DZMM群聊机器人"' in script
    assert '"ms-playwright"' in script
    assert "Compress-Archive -LiteralPath" in script
    assert "Copy-Item" in script
    assert "data" not in script.lower()


def test_packaged_assets_and_image_dependency_are_declared() -> None:
    spec = (SOURCE / "DZMMBot.spec").read_text(encoding="utf-8")
    requirements = (SOURCE / "requirements.txt").read_text(encoding="utf-8")
    assert '("../塔罗牌素材", "塔罗牌素材")' in spec
    assert "Pillow==12.3.0" in requirements


def test_installer_is_per_user_and_never_manages_runtime_data() -> None:
    installer = (ROOT / "installer/DZMMBot.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in installer
    assert r"DefaultDirName={localappdata}\Programs\DZMMBot" in installer
    assert r'Source: "..\release\DZMM群聊机器人\*"' in installer
    assert "recursesubdirs" in installer
    assert "[Icons]" in installer
    assert "[Run]" in installer
    assert "DZMMBot-Setup-win64" in installer
    assert "[UninstallDelete]" not in installer
    assert "data\\" not in installer.lower()


def test_release_docs_explain_both_artifacts_and_private_import_order() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (SOURCE / "发布版使用说明.txt").read_text(encoding="utf-8")
    assert "DZMMBot-Portable-win64.zip" in readme
    assert "DZMMBot-Setup-win64.exe" in readme
    assert "不包含真实数据或 API Key" in readme
    assert "关闭机器人" in readme
    assert "DZMMBot-current-data.zip" in readme
    assert "关闭机器人" in guide
    assert "重新登录" in guide
    assert "自己的 DeepSeek API Key" in guide
    assert "data" in guide
