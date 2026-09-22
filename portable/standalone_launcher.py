"""One-click Windows launcher for the packaged XAFS Workbench."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime

from xafs_workbench.runtime_paths import user_data_root
from xafs_workbench.webapp import create_app


URL = "http://127.0.0.1:8765/"
STATUS_URL = f"{URL}api/status"


def backend_is_running() -> bool:
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def open_when_ready() -> None:
    for _ in range(60):
        if backend_is_running():
            webbrowser.open(URL)
            return
        time.sleep(0.25)


def main() -> None:
    parser = argparse.ArgumentParser(description="XAFS Workbench launcher")
    parser.add_argument("--network", action="store_true", help="serve other computers on the network")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--access-token", default="")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    home = user_data_root()
    home.mkdir(parents=True, exist_ok=True)
    if args.network:
        access_token = args.access_token or os.environ.get("XAFS_ACCESS_TOKEN") or secrets.token_urlsafe(32)
        os.environ["XAFS_HOST"] = "0.0.0.0"
        os.environ["XAFS_PORT"] = str(args.port)
        os.environ["XAFS_ACCESS_TOKEN"] = access_token
        network_url = f"http://{socket.gethostname()}:{args.port}/"
        (home / "launcher-status.json").write_text(
            json.dumps({"started_at": datetime.now().isoformat(), "url": network_url, "network": True}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("XAFS Workbench network service", flush=True)
        print(f"Open from another computer: {network_url}", flush=True)
        print(f"Access token: {access_token}", flush=True)
        print("Keep this window open. Press Ctrl+C to stop.", flush=True)
        from waitress import serve

        serve(create_app(), host="0.0.0.0", port=args.port, threads=4)
        return

    (home / "launcher-status.json").write_text(
        json.dumps({"started_at": datetime.now().isoformat(), "url": URL}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if backend_is_running():
        webbrowser.open(URL)
        return
    threading.Thread(target=open_when_ready, daemon=True).start()
    create_app().run(host="127.0.0.1", port=8765, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
