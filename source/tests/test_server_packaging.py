from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_server_deployment_files_are_present_and_safe():
    required = [
        "deploy/env/dzmmbot.example.env",
        "deploy/scripts/provision.sh",
        "deploy/scripts/deploy.sh",
        "deploy/scripts/create-release.sh",
        "deploy/systemd/dzmmbot-display.service",
        "deploy/systemd/dzmmbot.service",
        "deploy/systemd/dzmmbot-browser.service",
        "deploy/nginx/dzmmbot.conf",
    ]
    for relative in required:
        assert (ROOT / relative).is_file(), relative

    app_service = (ROOT / "deploy/systemd/dzmmbot.service").read_text()
    assert "User=dzmmbot" in app_service
    assert "127.0.0.1" in app_service
    assert "EnvironmentFile=/etc/dzmmbot/dzmmbot.env" in app_service
    assert "DZMM_SERVER_MODE=1" in app_service

    browser_service = (ROOT / "deploy/systemd/dzmmbot-browser.service").read_text()
    assert "127.0.0.1:6080" in browser_service
    assert "--listen 127.0.0.1:6080" in browser_service

    nginx = (ROOT / "deploy/nginx/dzmmbot.conf").read_text()
    assert "listen 18080" in nginx
    assert "listen 18081" in nginx
    assert "auth_request /_auth" in nginx
    assert "proxy_pass http://127.0.0.1:7902" in nginx
    assert "proxy_pass http://127.0.0.1:6080/" in nginx

    all_text = "\n".join((ROOT / item).read_text() for item in required)
    assert "Czl/LcL" not in all_text
    assert "124.223.175.168" not in all_text


def test_server_release_builder_includes_all_runtime_asset_directories():
    script = (ROOT / "deploy/scripts/create-release.sh").read_text()
    assert "source" in script
    assert "塔罗牌素材" in script
    assert "盲盒小游戏素材" in script
