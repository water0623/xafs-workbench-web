"""Discovery and safe launching for optional native XAFS desktop tools.

The project does not redistribute Demeter or HAMA binaries.  A local user may
configure executable paths in ``native_tools.local.json`` or through the
documented environment variables. Installation discovery and running state are
reported separately because Demeter applications share the ``perl.exe`` image.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .runtime_paths import executable_root, user_data_root


LOCAL_CONFIGS = (
    executable_root() / "native_tools.local.json",
    user_data_root() / "native_tools.local.json",
)
_PROCESS_CACHE: tuple[float, list[dict[str, Any]]] = (0.0, [])
_PROCESS_CACHE_LOCK = threading.Lock()

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "athena": {
        "label": "Athena (Demeter)",
        "env": "XAFS_ATHENA_EXE",
        "commands": ("dathena", "dathena.bat", "athena", "athena.exe"),
        "homepage": "https://bruceravel.github.io/demeter/",
        "role": "原生 XAS 数据处理与 Athena .prj 项目输出",
    },
    "artemis": {
        "label": "Artemis (Demeter)",
        "env": "XAFS_ARTEMIS_EXE",
        "commands": ("dartemis", "dartemis.bat", "artemis", "artemis.exe"),
        "homepage": "https://bruceravel.github.io/demeter/",
        "role": "原生 FEFF/IFEFFIT EXAFS 拟合与 .fpj 项目输出",
    },
    "hephaestus": {
        "label": "Hephaestus (Demeter)",
        "env": "XAFS_HEPHAESTUS_EXE",
        "commands": ("dhephaestus", "dhephaestus.bat", "hephaestus", "hephaestus.exe"),
        "homepage": "https://bruceravel.github.io/demeter/",
        "role": "原生 X 射线吸收边与元素数据库",
    },
    "hama": {
        "label": "HAMA Fortran",
        "env": "XAFS_HAMA_EXE",
        "commands": ("hamaFortran", "hamaFortran.exe", "hama", "hama.exe"),
        "homepage": "https://www.esrf.fr/files/live/sites/www/files/UsersAndScience/Experiments/CRG/BM20/Software/Wavelets/HAMA/hamareadmepdf.pdf",
        "role": "原生 Morlet/Cauchy EXAFS 小波变换",
    },
}


def _windows_processes() -> list[dict[str, Any]]:
    """Return Windows process command lines without requiring psutil."""
    global _PROCESS_CACHE
    if os.name != "nt":
        return []
    with _PROCESS_CACHE_LOCK:
        if time.monotonic() - _PROCESS_CACHE[0] < 3.0:
            return _PROCESS_CACHE[1]
    command = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        if completed.returncode != 0 or not (completed.stdout or "").strip():
            return []
        payload = json.loads(completed.stdout)
        processes = payload if isinstance(payload, list) else [payload]
        with _PROCESS_CACHE_LOCK:
            _PROCESS_CACHE = (time.monotonic(), processes)
        return processes
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []


def _running_tools() -> dict[str, dict[str, Any]]:
    running = {name: {"running": False, "process_ids": [], "command": None} for name in TOOL_SPECS}
    for process in _windows_processes():
        command_line = str(process.get("CommandLine") or "")
        lowered = command_line.lower()
        image_name = str(process.get("Name") or "").lower()
        for name, spec in TOOL_SPECS.items():
            if name in {"athena", "artemis", "hephaestus"}:
                if image_name not in {"perl.exe", f"d{name}.exe", f"{name}.exe"}:
                    continue
            elif name == "hama" and "hama" not in image_name:
                continue
            if not any(command.lower() in lowered for command in spec["commands"]):
                continue
            running[name]["running"] = True
            running[name]["process_ids"].append(int(process.get("ProcessId") or 0))
            running[name]["command"] = command_line
    return running


def _installed_candidates(name: str) -> list[Path]:
    candidates: list[Path] = []
    if os.name == "nt" and name in {"athena", "artemis", "hephaestus"}:
        roots: list[Path] = []
        if os.environ.get("DEMETER_BASE"):
            roots.append(Path(os.environ["DEMETER_BASE"]))
        for drive in "CDEFG":
            roots.extend((Path(f"{drive}:/DemeterPerl"), Path(f"{drive}:/Install/DemeterPerl")))
        for root in roots:
            for command in TOOL_SPECS[name]["commands"]:
                candidates.append(root / "perl" / "site" / "bin" / command)
    elif os.name == "nt" and name == "hama":
        for drive in "CDEFG":
            candidates.extend(
                (
                    Path(f"{drive}:/Install/HAMA/hama_fortran.exe"),
                    Path(f"{drive}:/HAMA/hama_fortran.exe"),
                )
            )
    return candidates


def _local_values() -> dict[str, str]:
    for config in LOCAL_CONFIGS:
        if not config.is_file():
            continue
        try:
            payload = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        return {str(key).lower(): str(value) for key, value in payload.items() if value}
    return {}


def discover_native_tools() -> dict[str, dict[str, Any]]:
    configured = _local_values()
    running = _running_tools()
    results: dict[str, dict[str, Any]] = {}
    for name, spec in TOOL_SPECS.items():
        executable: str | None = None
        source = "not_found"
        for candidate, candidate_source in (
            (os.environ.get(spec["env"]), "environment"),
            (configured.get(name), "local_config"),
        ):
            if candidate and Path(candidate).expanduser().is_file():
                executable = str(Path(candidate).expanduser().resolve())
                source = candidate_source
                break
        if executable is None:
            for command in spec["commands"]:
                found = shutil.which(command)
                if found:
                    executable, source = str(Path(found).resolve()), "PATH"
                    break
        if executable is None:
            for candidate in _installed_candidates(name):
                if candidate.is_file():
                    executable, source = str(candidate.resolve()), "common_installation"
                    break
        running_info = running[name]
        results[name] = {
            "name": name,
            "label": spec["label"],
            "available": executable is not None,
            "executable": executable,
            "source": source,
            "homepage": spec["homepage"],
            "role": spec["role"],
            "running": bool(running_info["running"]),
            "process_ids": [pid for pid in running_info["process_ids"] if pid],
        }
    return results


def launch_native_tool(name: str) -> dict[str, Any]:
    if name not in TOOL_SPECS:
        raise ValueError("不支持的原生软件名称")
    status = discover_native_tools()[name]
    if not status["available"]:
        raise FileNotFoundError(f"未找到 {status['label']}；请安装后在 native_tools.local.json 中配置路径")
    executable = str(status["executable"])
    # Explicit user action from the local web UI authorizes opening the desktop
    # program. No shell is used and no untrusted arguments are accepted.
    subprocess.Popen([executable], cwd=str(Path(executable).parent), shell=False)
    return status
