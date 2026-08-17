from __future__ import annotations

import argparse
import multiprocessing
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from .runtime_paths import user_data_root


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
PORT_SEARCH_SPAN = 100


def available_port(host: str, preferred: int, span: int = PORT_SEARCH_SPAN) -> int:
    for port in range(preferred, preferred + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"找不到可用端口（已检查 {preferred}-{preferred + span - 1}）。")


def open_browser_when_ready(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    health_url = f"{url.rstrip('/')}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                if response.status < 500:
                    webbrowser.open(url)
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="FicFrame", description="启动 FicFrame 桌面 Web 应用")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="启动服务但不自动打开浏览器")
    return parser


def main() -> None:
    multiprocessing.freeze_support()
    args = build_parser().parse_args()
    port = available_port(args.host, args.port)
    url = f"http://{args.host}:{port}"
    print(f"FicFrame 正在启动：{url}")
    print(f"用户数据目录：{user_data_root()}")
    print("关闭此窗口或按 Ctrl+C 即可退出。")
    if not args.no_browser:
        threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True).start()

    import uvicorn

    from .api import app

    uvicorn.run(app, host=args.host, port=port, log_level="info")


if __name__ == "__main__":
    main()
