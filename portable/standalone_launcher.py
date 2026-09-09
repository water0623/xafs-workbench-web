"""One-click Windows launcher for the packaged XAFS Workbench."""

from __future__ import annotations

import json
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
    home = user_data_root()
    home.mkdir(parents=True, exist_ok=True)
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
