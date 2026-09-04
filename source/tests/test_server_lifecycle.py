import os

from main import manager_shutdown_monitor_enabled


def test_server_mode_does_not_stop_bot_when_admin_page_closes(monkeypatch):
    monkeypatch.setenv("DZMM_SERVER_MODE", "1")
    assert manager_shutdown_monitor_enabled() is False


def test_desktop_mode_keeps_existing_close_behavior(monkeypatch):
    monkeypatch.delenv("DZMM_SERVER_MODE", raising=False)
    assert manager_shutdown_monitor_enabled() is True
