"""Runtime locations for source, portable, and PyInstaller builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def bundle_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parent.parent


def executable_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return bundle_root()


def user_data_root() -> Path:
    configured = os.environ.get("XAFS_WORKBENCH_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "XAFS Workbench"


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)
