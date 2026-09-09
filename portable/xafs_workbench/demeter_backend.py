"""Native Demeter/IFEFFIT bridge for Athena-equivalent processing."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from .core import ProcessConfig, Spectrum, _clean_spectrum
from .native_tools import discover_native_tools


WORKSPACE = Path(__file__).resolve().parent.parent
PROCESS_SCRIPT = WORKSPACE / "scripts" / "demeter_process.pl"


def _demeter_base() -> Path:
    tools = discover_native_tools()
    for name in ("athena", "artemis", "hephaestus"):
        executable = tools[name].get("executable")
        if not executable:
            continue
        path = Path(str(executable)).resolve()
        # <base>/perl/site/bin/dathena.bat
        if path.parent.name.lower() == "bin" and len(path.parents) >= 4:
            return path.parents[3]
    raise RuntimeError("未检测到 Demeter；请安装 Athena/Artemis 并配置 native_tools.local.json")


def demeter_available() -> bool:
    try:
        base = _demeter_base()
    except RuntimeError:
        return False
    return (base / "perl" / "bin" / "perl.exe").is_file() and (base / "c" / "share" / "ifeffit").is_dir()


def _runtime(base: Path) -> tuple[Path, dict[str, str]]:
    perl = base / "perl" / "bin" / "perl.exe"
    if not perl.is_file():
        raise RuntimeError(f"Demeter Perl 不存在：{perl}")
    env = os.environ.copy()
    env["DEMETER_BASE"] = str(base)
    env["DEMETER_BACKEND"] = "ifeffit"
    env["DEMETER_FORCE_IFEFFIT"] = "1"
    env["IFEFFIT_DIR"] = str(base / "c" / "share" / "ifeffit")
    extra = [
        base / "c" / "bin",
        base / "perl" / "site" / "bin",
        base / "perl" / "bin",
        base / "c" / "bin" / "gnuplot" / "bin",
    ]
    env["PATH"] = os.pathsep.join(str(path) for path in extra) + os.pathsep + env.get("PATH", "")
    for locale_name in ("LC_ALL", "LC_CTYPE", "LANG"):
        env.pop(locale_name, None)
    return perl, env


def _columns(path: Path, minimum: int) -> np.ndarray:
    rows: list[list[float]] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            values = [float(value) for value in line.split()]
        except ValueError:
            continue
        if len(values) >= minimum:
            rows.append(values)
    if not rows:
        raise RuntimeError(f"Demeter 没有生成有效数据：{path.name}")
    return np.asarray(rows, dtype=float)


def process_spectrum_demeter(spec: Spectrum, cfg: ProcessConfig) -> dict[str, Any]:
    """Process a spectrum with the installed Demeter library and IFEFFIT."""
    cfg.validate()
    cleaned, removed = _clean_spectrum(spec, cfg)
    base = _demeter_base()
    perl, env = _runtime(base)
    window = "kaiser-bessel" if cfg.window.lower() == "kaiser" else cfg.window.lower()
    e0 = 0.0 if cfg.e0 is None or cfg.auto_e0 else float(cfg.e0)

    with tempfile.TemporaryDirectory(prefix="xafs-demeter-") as directory:
        root = Path(directory)
        appdata = root / "appdata"
        appdata.mkdir()
        env["APPDATA"] = str(appdata)
        input_path = root / "input.xmu"
        xmu_path, norm_path = root / "output.xmu", root / "output.norm"
        chi_path, r_path, meta_path = root / "output.chi", root / "output.r", root / "meta.json"
        np.savetxt(input_path, np.column_stack((cleaned.energy, cleaned.mu)), header="energy mu")
        command = [
            str(perl), str(PROCESS_SCRIPT), str(input_path), str(xmu_path), str(norm_path),
            str(chi_path), str(r_path), str(meta_path), str(e0), str(cfg.pre1), str(cfg.pre2),
            str(cfg.norm1), str(cfg.norm2), str(cfg.rbkg), str(cfg.kmin), str(cfg.kmax),
            str(cfg.dk), window, str(cfg.kweight),
        ]
        completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120, check=False)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise RuntimeError(f"Demeter/IFEFFIT 处理失败：{detail or '未知错误'}")
        xmu = _columns(xmu_path, 7)
        norm = _columns(norm_path, 7)
        chi = _columns(chi_path, 6)
        rdata = _columns(r_path, 6)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    result: dict[str, Any] = {
        "backend": "Demeter/IFEFFIT",
        "e0": float(meta["e0"]), "edge_step": float(meta["edge_step"]),
        "energy": xmu[:, 0], "mu": xmu[:, 1], "pre_edge": xmu[:, 3], "post_edge": xmu[:, 4],
        "norm": norm[:, 1], "flat": norm[:, 3],
        "k": chi[:, 0], "chi": chi[:, 1], "kwin": chi[:, 5],
        "r": rdata[:, 0], "chir_re": rdata[:, 1], "chir_im": rdata[:, 2], "chir_mag": rdata[:, 3],
        "kmax_used": min(cfg.kmax, float(np.max(chi[:, 0]))),
        "removed_energy": removed, "removed_points": int(len(removed)), "energy_shift": cfg.energy_shift,
    }
    energy = result["energy"]
    display_norm = result["flat"] if cfg.flatten else result["norm"]
    result["display_norm"] = display_norm
    result["normalization_mode"] = "Athena flattened (Demeter/IFEFFIT)" if cfg.flatten else "Athena normalized (Demeter/IFEFFIT)"
    result["dmude"] = np.gradient(display_norm, energy)
    white = (energy >= result["e0"] - 5.0) & (energy <= result["e0"] + 40.0)
    index = int(np.flatnonzero(white)[np.nanargmax(display_norm[white])]) if white.any() else 0
    result["white_line_energy"] = float(energy[index]) if white.any() else float("nan")
    result["white_line_height"] = float(display_norm[index]) if white.any() else float("nan")
    return result
