"""HAMA-compatible Morlet wavelet transform for uniformly sampled EXAFS chi(k)."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np

from .native_tools import discover_native_tools


@dataclass(frozen=True)
class HamaConfig:
    kmin: float = 3.0
    kmax: float = 12.0
    rmin: float = 0.0
    rmax: float = 6.0
    kweight: int = 2
    kappa: float = 10.0
    sigma: float = 1.0
    k_points: int = 240
    r_points: int = 150

    def validate(self) -> None:
        if not 0 <= self.kmin < self.kmax:
            raise ValueError("HAMA 必须满足 0 ≤ kmin < kmax")
        if not 0 <= self.rmin < self.rmax:
            raise ValueError("HAMA 必须满足 0 ≤ Rmin < Rmax")
        if self.kweight not in (0, 1, 2, 3):
            raise ValueError("HAMA k-weight 必须为 0–3")
        if self.kappa <= 0 or self.sigma <= 0:
            raise ValueError("HAMA Morlet κ 和 σ 必须大于 0")
        if self.k_points < 32 or self.r_points < 24:
            raise ValueError("HAMA 输出网格点数过少")


def hama_morlet(k: np.ndarray, chi: np.ndarray, config: HamaConfig) -> dict[str, object]:
    """Calculate the HAMA-style Morlet amplitude map on a k/R grid.

    HAMA relates an EXAFS oscillation sin(2*k*R) to the Morlet angular
    frequency through scale = kappa/(2*R). Input is resampled to an exactly
    equidistant k grid, as required by the original HAMA programs.
    """

    config.validate()
    k = np.asarray(k, dtype=float)
    chi = np.asarray(chi, dtype=float)
    valid = np.isfinite(k) & np.isfinite(chi) & (k >= config.kmin) & (k <= config.kmax)
    if np.count_nonzero(valid) < 16:
        raise ValueError("HAMA 小波变换范围内至少需要 16 个有效 χ(k) 点")
    k, chi = k[valid], chi[valid]
    order = np.argsort(k)
    k, chi = k[order], chi[order]
    unique = np.r_[True, np.diff(k) > 1e-10]
    k, chi = k[unique], chi[unique]

    step = float(np.median(np.diff(k)))
    uniform_k = np.arange(float(k[0]), float(k[-1]) + step * 0.25, step)
    uniform_chi = np.interp(uniform_k, k, chi)
    weighted = uniform_chi * np.power(uniform_k, config.kweight)
    centers = np.linspace(float(uniform_k[0]), float(uniform_k[-1]), config.k_points)
    radii = np.linspace(config.rmin, config.rmax, config.r_points)
    magnitude = np.zeros((config.r_points, config.k_points), dtype=float)
    correction = np.exp(-0.5 * (config.kappa * config.sigma) ** 2)

    for row, radius in enumerate(radii):
        if radius <= 1e-12:
            continue
        scale = config.kappa / (2.0 * radius)
        u = (uniform_k[:, None] - centers[None, :]) / scale
        envelope = np.exp(-0.5 * np.square(u / config.sigma))
        mother = envelope * (np.exp(1j * config.kappa * u) - correction)
        transform = step * np.sum(weighted[:, None] * np.conjugate(mother), axis=0) / np.sqrt(scale)
        magnitude[row, :] = np.abs(transform)

    return {
        "k": centers.tolist(),
        "r": radii.tolist(),
        "magnitude": magnitude.tolist(),
        "uniform_input_k": uniform_k.tolist(),
        "uniform_weighted_chi": weighted.tolist(),
        "backend": "hama_morlet_integrated",
        "mother": "Morlet",
        "kappa": float(config.kappa),
        "sigma": float(config.sigma),
        "kweight": int(config.kweight),
        "input_k_step": step,
    }


def native_hama_morlet(k: np.ndarray, chi: np.ndarray, config: HamaConfig) -> dict[str, object]:
    """Run the official ESRF HAMA Fortran executable without its plot window."""
    config.validate()
    status = discover_native_tools()["hama"]
    if not status["available"]:
        raise RuntimeError("未检测到原生 HAMA Fortran；请安装并配置 XAFS_HAMA_EXE")
    executable = Path(str(status["executable"])).resolve()
    k = np.asarray(k, dtype=float)
    chi = np.asarray(chi, dtype=float)
    valid = np.isfinite(k) & np.isfinite(chi) & (k >= config.kmin) & (k <= config.kmax)
    if np.count_nonzero(valid) < 16:
        raise ValueError("HAMA 变换范围内至少需要 16 个有效 χ(k) 点")
    k, chi = k[valid], chi[valid]
    order = np.argsort(k)
    k, chi = k[order], chi[order]
    unique = np.r_[True, np.diff(k) > 1e-10]
    k, chi = k[unique], chi[unique]
    step = float(np.median(np.diff(k)))
    uniform_k = np.arange(float(k[0]), float(k[-1]) + 0.25 * step, step)
    uniform_chi = np.interp(uniform_k, k, chi)

    with tempfile.TemporaryDirectory(prefix="xafs-hama-") as directory:
        root = Path(directory)
        local_executable = root / "hama_fortran.exe"
        shutil.copy2(executable, local_executable)
        model_parameters = executable.parent / "ModelParameters.txt"
        if model_parameters.is_file():
            shutil.copy2(model_parameters, root / model_parameters.name)
        # HAMA launches WGNUPLOT even after an N answer.  A short-lived Windows
        # system executable preserves the Fortran calculation while suppressing
        # the interactive plotting child process required by the 2006 UI.
        plot_stub = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "where.exe"
        if not plot_stub.is_file():
            raise RuntimeError("无法建立 HAMA 无界面绘图适配器")
        shutil.copy2(plot_stub, root / "WGNUPLOT.EXE")
        input_file, output_file = root / "input.dat", root / "wavelet.dat"
        np.savetxt(input_file, np.column_stack((uniform_k, uniform_chi)), fmt="%.10g")
        answers = "\n".join(
            (
                "1", output_file.name, "0", input_file.name, str(config.kweight), "N",
                f"{config.rmin:g}", f"{config.rmax:g}", "1", f"{config.kappa:g}",
                f"{config.sigma:g}", "N", "N", "",
            )
        )
        completed = subprocess.run(
            [str(local_executable)], input=answers, cwd=root, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=240, check=False,
        )
        if completed.returncode != 0 or not output_file.is_file():
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise RuntimeError(f"原生 HAMA Fortran 变换失败：{detail or '未生成输出文件'}")
        rows = np.loadtxt(output_file, dtype=float)

    k_axis = np.unique(rows[:, 0])
    r_axis = np.unique(rows[:, 1])
    k_axis = k_axis[(k_axis >= config.kmin - 1e-8) & (k_axis <= config.kmax + 1e-8)]
    k_pick = np.linspace(0, len(k_axis) - 1, min(config.k_points, len(k_axis))).round().astype(int)
    r_pick = np.linspace(0, len(r_axis) - 1, min(config.r_points, len(r_axis))).round().astype(int)
    k_axis, r_axis = k_axis[k_pick], r_axis[r_pick]
    lookup = {(round(float(row[0]), 8), round(float(row[1]), 8)): float(row[2]) for row in rows}
    magnitude = np.asarray(
        [[lookup.get((round(float(kv), 8), round(float(rv), 8)), np.nan) for kv in k_axis] for rv in r_axis]
    )
    return {
        "k": k_axis.tolist(), "r": r_axis.tolist(), "magnitude": magnitude.tolist(),
        "uniform_input_k": uniform_k.tolist(),
        "uniform_weighted_chi": (uniform_chi * uniform_k**config.kweight).tolist(),
        "backend": "HAMA Fortran (ESRF)", "mother": "Morlet",
        "kappa": float(config.kappa), "sigma": float(config.sigma),
        "kweight": int(config.kweight), "input_k_step": step,
    }
