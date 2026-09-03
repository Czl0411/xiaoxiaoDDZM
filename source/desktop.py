from __future__ import annotations

import ctypes
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path


APP_TITLE = "DZMM 群聊机器人"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, 0x10)


def acquire_single_instance():
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\DZMMBotDesktop-6F76A1B2")
    if ctypes.windll.kernel32.GetLastError() == 183:
        show_error("DZMM 群聊机器人已经在运行。")
        return None
    return handle


def choose_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_ready(url: str, timeout: float = 180.0, server_thread: threading.Thread | None = None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/status", timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            if server_thread is not None and not server_thread.is_alive():
                return False
            time.sleep(0.5)
    return False


def main() -> int:
    mutex = acquire_single_instance()
    if mutex is None:
        return 0

    root = app_dir()
    data_dir = root / "data"
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    service_log = (log_dir / "desktop-service.log").open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = service_log
    if sys.stderr is None:
        sys.stderr = service_log
    os.chdir(root)
    os.environ["DZMM_DATA_DIR"] = str(data_dir)
    os.environ["DZMM_SKIP_AUTO_OPEN"] = "1"
    os.environ["DZMM_DESKTOP"] = "1"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(root / "ms-playwright")
    os.environ["PYTHONUTF8"] = "1"
    fixed_webview = root / "webview2-runtime"
    if (fixed_webview / "msedgewebview2.exe").is_file():
        os.environ["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"] = str(fixed_webview)

    try:
        import uvicorn
        import webview
        from main import app

        port = choose_port()
        url = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", access_log=False)
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None
        def run_server():
            try:
                server.run()
            except BaseException:
                with (log_dir / "desktop-error.log").open("a", encoding="utf-8") as file:
                    file.write(f"\n{time.strftime('%Y-%m-%d %H:%M:%S')} 服务线程异常\n{traceback.format_exc()}\n")

        server_thread = threading.Thread(target=run_server, name="dzmm-api", daemon=True)
        server_thread.start()
        loading_html = """
        <!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
        <style>
        *{box-sizing:border-box}body{margin:0;background:#0b0e12;color:#eef1f4;font-family:"Segoe UI","Microsoft YaHei UI",sans-serif}
        main{height:100vh;display:grid;place-items:center}.card{width:min(440px,calc(100% - 40px));padding:32px;border:1px solid #2b323c;border-radius:12px;background:#14181e}
        .brand{margin:0 0 28px;color:#c7f05a;font-size:12px;font-weight:700;letter-spacing:.08em}
        h1{font-size:23px;margin:0 0 10px;font-weight:650}p{margin:0;color:#858e99;font-size:14px;line-height:1.7}
        .status{margin-top:24px;padding-top:16px;border-top:1px solid #272d36;color:#c1c7cf;font-size:12px;animation:pulse 1.4s ease-in-out infinite}@keyframes pulse{50%{opacity:.48}}
        </style></head><body><main><div class="card"><div class="brand">DZMM CONTROL</div><h1>DZMM 群聊机器人</h1><p>正在载入用户数据和浏览器环境。首次启动时，运行环境需要一点时间完成准备。</p><div class="status">正在启动本地服务…</div></div></main></body></html>
        """
        window = webview.create_window(
            APP_TITLE,
            html=loading_html,
            width=1440,
            height=920,
            min_size=(1080, 700),
            background_color="#0b0e12",
            text_select=True,
        )

        def finish_startup(target_window):
            if wait_until_ready(url, server_thread=server_thread):
                target_window.load_url(url)
            else:
                target_window.load_html(
                    "<body style='margin:0;background:#171717;color:#eee;font-family:Microsoft YaHei UI;display:grid;place-items:center;height:100vh'>"
                    f"<div><h2>程序服务启动失败</h2><p>请查看日志目录：{log_dir}</p></div></body>"
                )

        webview.start(finish_startup, window, gui="edgechromium", debug=False, private_mode=False)
        server.should_exit = True
        server_thread.join(timeout=8)
        return 0
    except Exception as exc:
        with (log_dir / "desktop-error.log").open("a", encoding="utf-8") as file:
            file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {type(exc).__name__}: {exc}\n")
        show_error(f"启动失败：{exc}\n\n详细日志：{log_dir / 'desktop-error.log'}")
        return 1
    finally:
        ctypes.windll.kernel32.ReleaseMutex(mutex)
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
