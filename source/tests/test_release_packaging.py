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
