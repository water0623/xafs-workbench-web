"""Runtime locations for source, portable, and PyInstaller builds."""

from __future__ import annotations

import os
import sys
import tempfile
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
        target = Path(configured).expanduser().resolve()
        if _prepare_writable_directory(target):
            return target
        raise PermissionError(f"XAFS_WORKBENCH_HOME 指向的目录不可写：{target}")

    candidates = [
        Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "XAFS Workbench",
        Path(tempfile.gettempdir()) / "XAFS Workbench",
        bundle_root() / ".xafs-workbench-data",
    ]
    attempted: list[str] = []
    for candidate in candidates:
        candidate = candidate.expanduser().resolve()
        if str(candidate) in attempted:
            continue
        attempted.append(str(candidate))
        if _prepare_writable_directory(candidate):
            return candidate
    raise PermissionError("找不到可写的 XAFS 工作目录：" + "；".join(attempted))


def _prepare_writable_directory(path: Path) -> bool:
    """Create *path* and verify that the current process can really write it."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".xafs-write-test-", dir=path):
            pass
        return True
    except OSError:
        return False


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)
