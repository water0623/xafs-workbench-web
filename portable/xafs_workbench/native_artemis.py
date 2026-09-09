"""Native Artemis-style FEFF fitting through Demeter and IFEFFIT."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from .core import K_ENERGY
from .demeter_backend import _demeter_base, _runtime
from .hama import HamaConfig, hama_morlet
from .runtime_paths import resource_path


FIT_SCRIPT = resource_path("scripts", "demeter_fit.pl")
_EXPRESSION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$|^[A-Za-z0-9_+*/(). \-]+$")


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
        raise RuntimeError(f"Demeter/IFEFFIT 没有生成有效的 {path.name}")
    return np.asarray(rows, dtype=float)


def _safe_expression(value: Any, fallback: str) -> str:
    expression = str(value or "").strip() or fallback
    if len(expression) > 120 or not _EXPRESSION.fullmatch(expression):
        raise ValueError(f"不安全或无效的拟合表达式：{expression}")
    return expression


def _parameter(
    items: list[dict[str, Any]], bounds: dict[str, tuple[float, float]], name: str,
    value: float, minimum: float, maximum: float, vary: bool, expression: str | None = None,
) -> str:
    if expression:
        expr = _safe_expression(expression, str(value))
        items.append({"name": name, "type": "def", "value": expr})
        bounds[name] = (minimum, maximum)
        return name
    if vary:
        if not minimum < maximum:
            raise ValueError(f"参数 {name} 参与拟合时，下限必须小于上限")
        if not minimum <= value <= maximum:
            raise ValueError(f"参数 {name} 的初值必须位于 {minimum:g}–{maximum:g} 之间")
        items.append({"name": name, "type": "guess", "value": value})
    else:
        items.append({"name": name, "type": "set", "value": value})
    bounds[name] = (minimum, maximum)
    return name


def _paper_value(value: float, error: float | None) -> str:
    if error is None or not np.isfinite(error) or error <= 0:
        return f"{value:.5g}"
    exponent = int(np.floor(np.log10(abs(error))))
    decimals = max(0, -exponent)
    return f"{value:.{decimals}f}({int(round(error * 10**decimals))})"


def fit_feff_paths_demeter(
    processed: dict[str, Any], path_files: list[Path], settings: list[dict[str, Any]], *,
    s02: float = 0.85, s02_vary: bool = False, s02_min: float = 0.5, s02_max: float = 1.2,
    de0: float = 0.0, de0_vary: bool = True, de0_min: float = -10.0, de0_max: float = 10.0,
    kmin: float = 3.0, kmax: float = 12.0, kweight: int | list[int] = 2, dk: float = 2.0,
    rmin: float = 1.0, rmax: float = 3.5, fitspace: str = "r", window: str = "kaiser",
    rwindow: str = "hanning", wavelet_kweight: int = 2, wavelet_rmax: float = 5.0,
    wavelet_backend: str = "hama", wavelet_kappa: float = 10.0, wavelet_sigma: float = 1.0,
) -> dict[str, Any]:
    if not path_files or len(path_files) != len(settings):
        raise ValueError("每个 FEFF 路径都必须有一组初始参数")
    if fitspace not in {"r", "k"}:
        raise ValueError("拟合空间只能为 R 或 K")
    kweights = [int(kweight)] if isinstance(kweight, int) else [int(v) for v in kweight]
    if not kweights or any(v not in {1, 2, 3} for v in kweights):
        raise ValueError("Demeter/IFEFFIT k-weight 只能选择 1、2、3")

    gds: list[dict[str, Any]] = []
    bounds: dict[str, tuple[float, float]] = {}
    _parameter(gds, bounds, "s02", float(s02), float(s02_min), float(s02_max), bool(s02_vary))
    _parameter(gds, bounds, "de0", float(de0), float(de0_min), float(de0_max), bool(de0_vary))
    path_config: list[dict[str, Any]] = []
    initial: dict[str, float] = {"s02": float(s02), "de0": float(de0)}
    for index, (path_file, options) in enumerate(zip(path_files, settings), start=1):
        cn = float(options.get("cn", 1.0))
        sigma2 = float(options.get("sigma2", 0.004))
        deltar = float(options.get("deltar", 0.0))
        degen = max(float(options.get("feff_degeneracy", options.get("degen", cn or 1.0))), 1e-12)
        n_name = _parameter(gds, bounds, f"n_{index}", cn, float(options.get("cn_min", 0)),
                            float(options.get("cn_max", max(20, cn * 2))), bool(options.get("vary_cn", True)),
                            str(options.get("cn_expr", "")).strip() or None)
        sig_name = _parameter(gds, bounds, f"sig2_{index}", sigma2, float(options.get("sigma2_min", 0)),
                              float(options.get("sigma2_max", 0.04)), bool(options.get("vary_sigma2", True)),
                              str(options.get("sigma2_expr", "")).strip() or None)
        dr_name = _parameter(gds, bounds, f"delr_{index}", deltar, float(options.get("deltar_min", -0.15)),
                             float(options.get("deltar_max", 0.15)), bool(options.get("vary_deltar", True)),
                             str(options.get("deltar_expr", "")).strip() or None)
        initial.update({n_name: cn, sig_name: sigma2, dr_name: deltar})
        path_config.append({
            "file": str(path_file.resolve()), "label": str(options.get("label", path_file.stem)),
            "s02": f"s02*{n_name}/{degen:.12g}", "e0": "de0", "sigma2": sig_name, "delr": dr_name,
        })

    display_kw = 2 if 2 in kweights else kweights[0]
    base = _demeter_base()
    perl, env = _runtime(base)
    with tempfile.TemporaryDirectory(prefix="xafs-demeter-fit-") as directory:
        root = Path(directory)
        appdata = root / "appdata"
        appdata.mkdir()
        env["APPDATA"] = str(appdata)
        chi_file = root / "experimental.chi"
        np.savetxt(chi_file, np.column_stack((processed["k"], processed["chi"])), header="k chi")
        local_script = root / "demeter_fit.pl"
        shutil.copy2(FIT_SCRIPT, local_script)
        for index, path_item in enumerate(path_config, start=1):
            local_path = root / f"feff{index:04d}.dat"
            shutil.copy2(path_files[index - 1], local_path)
            path_item["file"] = str(local_path)
        paths = {
            "fit_k_file": root / "fit_k.dat", "fit_rmag_file": root / "fit_rmag.dat",
            "fit_rre_file": root / "fit_rre.dat", "fit_rim_file": root / "fit_rim.dat",
            "result_file": root / "result.json", "log_file": root / "fit.log",
        }
        config = {
            "chi_file": str(chi_file), "data_name": "XAFS Workbench experimental chi(k)",
            "kmin": float(kmin), "kmax": float(kmax), "dk": float(dk),
            "window": "kaiser-bessel" if window.lower() == "kaiser" else window.lower(),
            "rmin": float(rmin), "rmax": float(rmax), "rwindow": rwindow.lower(),
            "fitspace": fitspace.lower(), "kweights": kweights, "display_kweight": display_kw,
            "gds": gds, "paths": path_config, **{key: str(value) for key, value in paths.items()},
        }
        config_file = root / "fit_config.json"
        # ASCII-escaped JSON avoids the legacy Strawberry Perl locale treating
        # UTF-8 path labels as malformed while JSON::PP still restores Unicode.
        config_file.write_text(json.dumps(config, ensure_ascii=True), encoding="ascii")
        completed = subprocess.run(
            [str(perl), str(local_script), str(config_file)], env=env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=240, check=False, cwd=appdata,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-4000:]
            raise RuntimeError(f"Demeter/IFEFFIT 原生拟合失败：{detail or '未知错误'}")
        raw = json.loads(paths["result_file"].read_text(encoding="utf-8"))
        fit_k = _columns(paths["fit_k_file"], 4)
        rmag, rre, rim = (_columns(paths[name], 4) for name in ("fit_rmag_file", "fit_rre_file", "fit_rim_file"))
        report = paths["log_file"].read_text(encoding="utf-8", errors="replace")

    parameter_map = {item["name"]: item for item in raw["parameters"]}
    parameter_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for item in raw["parameters"]:
        name, value = item["name"], float(item["value"])
        error = float(item["error"]) if item["state"] == "guess" and float(item["error"]) > 0 else None
        minimum, maximum = bounds.get(name, (-math.inf, math.inf))
        if value < minimum or value > maximum:
            warnings.append(f"参数 {name}={value:.5g} 超出设定范围 {minimum:g}–{maximum:g}")
        parameter_rows.append({
            "name": name, "initial_value": initial.get(name, item["initial"]), "value": value,
            "stderr": error, "relative_error_percent": None if error is None or abs(value) < 1e-12 else abs(error/value)*100,
            "state": item["state"], "vary": item["state"] == "guess",
            "min": None if not np.isfinite(minimum) else minimum, "max": None if not np.isfinite(maximum) else maximum,
            "expr": item["initial"] if item["state"] == "def" else "",
        })

    fitted_paths: list[dict[str, Any]] = []
    for index, (item, options) in enumerate(zip(raw["paths"], settings), start=1):
        npar, spar, rpar = (parameter_map[f"n_{index}"], parameter_map[f"sig2_{index}"], parameter_map[f"delr_{index}"])
        cn, sigma2, deltar, reff = float(npar["value"]), float(spar["value"]), float(rpar["value"]), float(item["reff"])
        error = lambda par: float(par["error"]) if par["state"] == "guess" and float(par["error"]) > 0 else None
        fitted_paths.append({
            "index": index, "label": item["label"], "shell": int(options.get("shell", 1)), "Reff_A": reff,
            "CN": cn, "CN_stderr": error(npar), "R_A": reff + deltar, "deltar_A": deltar,
            "deltar_stderr": error(rpar), "sigma2_A2": sigma2, "sigma2_stderr": error(spar),
        })

    data_k, data_chi, model_chi, residual_chi = fit_k[:, 0], fit_k[:, 1], fit_k[:, 2], fit_k[:, 3]
    energy_axis = np.asarray(processed["energy"], dtype=float)
    normalized_mu = np.asarray(processed.get("display_norm", processed["norm"]), dtype=float)
    energy_k = np.sqrt(np.maximum((energy_axis - float(processed["e0"])) / K_ENERGY, 0.0))
    fit_mask = (energy_axis >= processed["e0"]) & (energy_k >= kmin) & (energy_k <= kmax)
    energy_residual = np.interp(energy_k, data_k, residual_chi, left=np.nan, right=np.nan)
    normalized_fit = np.full_like(normalized_mu, np.nan)
    normalized_fit[fit_mask] = normalized_mu[fit_mask] - energy_residual[fit_mask]

    hcfg = HamaConfig(kmin=kmin, kmax=kmax, rmin=0, rmax=wavelet_rmax, kweight=wavelet_kweight,
                      kappa=wavelet_kappa, sigma=wavelet_sigma)
    hw_data, hw_model, hw_res = (hama_morlet(data_k, values, hcfg) for values in (data_chi, model_chi, residual_chi))
    nind, nvars = float(raw["n_independent"]), int(raw["n_variables"])
    chi_square = float(raw["chi_square"])
    if nind <= nvars:
        warnings.append(f"独立点数 Nind={nind:.2f} 不大于变量数 {nvars}")
    correlations = sorted(raw.get("correlations", []), key=lambda x: abs(float(x["correlation"])), reverse=True)
    if correlations and abs(float(correlations[0]["correlation"])) >= 0.9:
        warnings.append(f"参数 {correlations[0]['parameter_1']} 与 {correlations[0]['parameter_2']} 高度相关")
    r_factor = float(raw["r_factor"])
    if r_factor > 0.05:
        warnings.append("R-factor 高于 0.05，请检查路径、拟合范围或数据质量")
    paper_table = [{
        "Path": p["label"], "d_FEFF_A": f"{p['Reff_A']:.4f}", "N": _paper_value(p["CN"], p["CN_stderr"]),
        "R_A": _paper_value(p["R_A"], p["deltar_stderr"]), "sigma2_A2": _paper_value(p["sigma2_A2"], p["sigma2_stderr"]),
        "N_state": "refined" if parameter_map[f"n_{i}"]["state"] == "guess" else "fixed",
        "sigma2_state": "refined" if parameter_map[f"sig2_{i}"]["state"] == "guess" else "fixed",
    } for i, p in enumerate(fitted_paths, start=1)]
    return {
        "backend": "Demeter/IFEFFIT", "paths": fitted_paths,
        "delta_e0_eV": float(parameter_map["de0"]["value"]), "delta_e0_stderr": next((r["stderr"] for r in parameter_rows if r["name"] == "de0"), None),
        "s02": float(parameter_map["s02"]["value"]), "s02_stderr": next((r["stderr"] for r in parameter_rows if r["name"] == "s02"), None),
        "r_factor": r_factor, "chi_square": chi_square, "reduced_chi_square": float(raw["reduced_chi_square"]),
        "n_variables": nvars, "n_independent": nind, "n_free": max(0, int(round(nind)) - nvars),
        "aic": nind * math.log(max(chi_square / max(nind, 1), 1e-300)) + 2*nvars,
        "bic": nind * math.log(max(chi_square / max(nind, 1), 1e-300)) + nvars*math.log(max(nind, 1)),
        "kweights": kweights, "display_kweight": display_kw, "parameter_rows": parameter_rows,
        "paper_table": paper_table, "paper_notes": [
            f"Native Demeter/IFEFFIT fit; S₀²={float(parameter_map['s02']['value']):.4f}, ΔE₀={float(parameter_map['de0']['value']):.3f} eV.",
            f"Fit ranges: {kmin:.2f}≤k≤{kmax:.2f} Å⁻¹, {rmin:.2f}≤R≤{rmax:.2f} Å; k-weights: {','.join(map(str,kweights))}.",
        ],
        "correlations": correlations, "warnings": list(dict.fromkeys(warnings)),
        "quality_status": "需要重点复核" if warnings else "自动审查未发现明显问题", "report": report,
        "data_k": data_k.tolist(), "data_chi": data_chi.tolist(), "model_k": data_k.tolist(), "model_chi": model_chi.tolist(),
        "residual_chi": residual_chi.tolist(), "energy_fit_eV": (processed["e0"] + K_ENERGY*data_k**2).tolist(),
        "energy_data_chi": data_chi.tolist(), "energy_model_chi": model_chi.tolist(), "energy_residual_chi": residual_chi.tolist(),
        "energy_spectrum_eV": energy_axis.tolist(), "energy_raw_mu": np.asarray(processed["mu"]).tolist(),
        "energy_normalized_mu": normalized_mu.tolist(), "energy_pre_edge": np.asarray(processed["pre_edge"]).tolist(),
        "energy_post_edge": np.asarray(processed["post_edge"]).tolist(), "energy_e0_eV": float(processed["e0"]),
        "energy_normalized_fit": [None if not np.isfinite(v) else float(v) for v in normalized_fit],
        "energy_fit_region_eV": [float(processed["e0"]+K_ENERGY*kmin**2), float(processed["e0"]+K_ENERGY*kmax**2)],
        "r": rmag[:, 0].tolist(), "data_chir_mag": rmag[:, 1].tolist(), "model_chir_mag": rmag[:, 2].tolist(), "residual_chir_mag": rmag[:, 3].tolist(),
        "data_chir_re": rre[:, 1].tolist(), "model_chir_re": rre[:, 2].tolist(), "residual_chir_re": rre[:, 3].tolist(),
        "data_chir_im": rim[:, 1].tolist(), "model_chir_im": rim[:, 2].tolist(), "residual_chir_im": rim[:, 3].tolist(),
        "fit_config": {"fitspace": fitspace, "kmin": kmin, "kmax": kmax, "kweights": kweights, "dk": dk, "window": window, "rmin": rmin, "rmax": rmax, "rwindow": rwindow},
        "wavelet": {"k": hw_data["k"], "r": hw_data["r"], "data_mag": hw_data["magnitude"], "model_mag": hw_model["magnitude"],
                    "residual_mag": hw_res["magnitude"], "kweight": wavelet_kweight, "backend": hw_data["backend"],
                    "mother": hw_data["mother"], "kappa": hw_data["kappa"], "sigma": hw_data["sigma"], "input_k_step": hw_data["input_k_step"]},
    }
