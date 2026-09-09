from __future__ import annotations

from pathlib import Path
from typing import Any
from copy import deepcopy

import numpy as np

from .hama import HamaConfig, hama_morlet, native_hama_morlet
from .native_artemis import fit_feff_paths_demeter

from .core import K_ENERGY, larch_available


def fit_feff_paths(
    processed: dict[str, Any],
    path_files: list[Path],
    settings: list[dict[str, Any]],
    *,
    s02: float = 0.85,
    s02_vary: bool = False,
    s02_min: float = 0.5,
    s02_max: float = 1.2,
    de0: float = 0.0,
    de0_vary: bool = True,
    de0_min: float = -10.0,
    de0_max: float = 10.0,
    kmin: float = 3.0,
    kmax: float = 12.0,
    kweight: int | list[int] = 2,
    dk: float = 2.0,
    rmin: float = 1.0,
    rmax: float = 3.5,
    fitspace: str = "r",
    window: str = "kaiser",
    rwindow: str = "hanning",
    wavelet_kweight: int = 2,
    wavelet_rmax: float = 5.0,
    wavelet_backend: str = "hama",
    wavelet_kappa: float = 10.0,
    wavelet_sigma: float = 1.0,
) -> dict[str, Any]:
    # Quantitative fitting is delegated to the installed Demeter/IFEFFIT
    # runtime.  Keeping this public function stable lets the staged fitting
    # manager and export/UI code remain backend-agnostic.
    return fit_feff_paths_demeter(
        processed,
        path_files,
        settings,
        s02=s02,
        s02_vary=s02_vary,
        s02_min=s02_min,
        s02_max=s02_max,
        de0=de0,
        de0_vary=de0_vary,
        de0_min=de0_min,
        de0_max=de0_max,
        kmin=kmin,
        kmax=kmax,
        kweight=kweight,
        dk=dk,
        rmin=rmin,
        rmax=rmax,
        fitspace=fitspace,
        window=window,
        rwindow=rwindow,
        wavelet_kweight=wavelet_kweight,
        wavelet_rmax=wavelet_rmax,
        wavelet_backend=wavelet_backend,
        wavelet_kappa=wavelet_kappa,
        wavelet_sigma=wavelet_sigma,
    )

    # The former XrayLarch implementation is retained below temporarily for
    # output-schema comparison while the migration is being verified.  It is
    # intentionally unreachable and is never imported at runtime.
    if not larch_available():
        raise RuntimeError("Artemis 定量拟合需要安装 xraylarch（其中包含 FEFF6L/FEFF8L 接口）")
    if not path_files:
        raise ValueError("至少需要一个 feffNNNN.dat 路径文件")
    if len(settings) != len(path_files):
        raise ValueError("每个 FEFF 路径都必须有一组初始参数")

    from larch import Group
    from larch.fitting import param
    from larch.xafs import cauchy_wavelet, feffit, feffit_dataset, feffit_report, feffit_transform, feffpath, xftf
    from larch.xafs.xafsft import ftwindow

    data = processed.get("larch_group")
    if data is None:
        data = Group(k=np.asarray(processed["k"], dtype=float), chi=np.asarray(processed["chi"], dtype=float))

    def managed_param(name: str, value: float, minimum: float, maximum: float, vary: bool, expr: str | None = None):
        """Create a Larch parameter while allowing an exact fixed value.

        lmfit rejects min == max even when vary=False.  For fixed or expression
        parameters the bounds are therefore intentionally omitted: the value or
        expression itself is the constraint.
        """
        if expr is not None:
            return param(float(value), vary=False, expr=expr)
        if not vary:
            return param(float(value), vary=False)
        if not float(minimum) < float(maximum):
            raise ValueError(f"参数 {name} 参与拟合时，下限必须小于上限；如需固定，请取消勾选‘允许变化’")
        if not float(minimum) <= float(value) <= float(maximum):
            raise ValueError(f"参数 {name} 的初值必须位于下限和上限之间")
        return param(float(value), min=float(minimum), max=float(maximum), vary=True)

    if not 0 <= float(kmin) < float(kmax):
        raise ValueError("k 空间范围无效：必须满足 0 ≤ kmin < kmax")
    if not 0 <= float(rmin) < float(rmax):
        raise ValueError("R 空间范围无效：必须满足 0 ≤ Rmin < Rmax")

    pars = Group()
    pars.s02 = managed_param("S₀²", s02, s02_min, s02_max, bool(s02_vary))
    pars.de0 = managed_param("ΔE₀", de0, de0_min, de0_max, bool(de0_vary))
    paths = []
    initial = []
    for index, (filename, opts) in enumerate(zip(path_files, settings), start=1):
        cn = float(opts.get("cn", 1.0))
        cn_min = float(opts.get("cn_min", 0.0))
        cn_max = float(opts.get("cn_max", max(20.0, cn * 2.0)))
        sigma2 = float(opts.get("sigma2", 0.004))
        sigma2_min = float(opts.get("sigma2_min", 0.0))
        sigma2_max = float(opts.get("sigma2_max", 0.04))
        dr = float(opts.get("deltar", 0.0))
        dr_min = float(opts.get("deltar_min", -0.15))
        dr_max = float(opts.get("deltar_max", 0.15))
        cn_expr = str(opts.get("cn_expr", "")).strip() or None
        sigma2_expr = str(opts.get("sigma2_expr", "")).strip() or None
        dr_expr = str(opts.get("deltar_expr", "")).strip() or None
        setattr(pars, f"n_{index}", managed_param(f"路径 {index} 的 CN", cn, cn_min, cn_max, bool(opts.get("vary_cn", True)), cn_expr))
        setattr(pars, f"sig2_{index}", managed_param(f"路径 {index} 的 σ²", sigma2, sigma2_min, sigma2_max, bool(opts.get("vary_sigma2", True)), sigma2_expr))
        setattr(pars, f"delr_{index}", managed_param(f"路径 {index} 的 ΔR", dr, dr_min, dr_max, bool(opts.get("vary_deltar", True)), dr_expr))
        path = feffpath(
            str(filename),
            label=str(opts.get("label", filename.stem)),
            degen=1,
            s02=f"s02*n_{index}",
            e0="de0",
            sigma2=f"sig2_{index}",
            deltar=f"delr_{index}",
        )
        paths.append(path)
        initial.append({"index": index, "label": path.label, "reff": float(path.reff), "cn": cn, "sigma2": sigma2, "deltar": dr})

    transform = feffit_transform(
        fitspace=fitspace,
        kmin=float(kmin),
        kmax=float(kmax),
        kweight=kweight,
        dk=float(dk),
        window=window,
        rmin=float(rmin),
        rmax=float(rmax),
        rwindow=rwindow,
    )
    dataset = feffit_dataset(data=data, pathlist=paths, transform=transform)
    output = feffit(pars, dataset)
    report = feffit_report(output, with_paths=True, min_correl=0.1)

    fitted_paths = []
    for item in initial:
        index = item["index"]
        npar = output.params[f"n_{index}"]
        spar = output.params[f"sig2_{index}"]
        rpar = output.params[f"delr_{index}"]
        fitted_paths.append(
            {
                "index": index,
                "label": item["label"],
                "shell": int(settings[item["index"] - 1].get("shell", 1)),
                "Reff_A": item["reff"],
                "CN": float(npar.value),
                "CN_stderr": None if npar.stderr is None else float(npar.stderr),
                "R_A": item["reff"] + float(rpar.value),
                "deltar_A": float(rpar.value),
                "deltar_stderr": None if rpar.stderr is None else float(rpar.stderr),
                "sigma2_A2": float(spar.value),
                "sigma2_stderr": None if spar.stderr is None else float(spar.stderr),
            }
        )

    model = dataset.model
    correlations = []
    if output.covar is not None and output.var_names:
        covariance = np.asarray(output.covar, dtype=float)
        diagonal = np.sqrt(np.maximum(np.diag(covariance), 0.0))
        for i, left in enumerate(output.var_names):
            for j in range(i + 1, len(output.var_names)):
                denom = diagonal[i] * diagonal[j]
                if denom > 0:
                    value = float(covariance[i, j] / denom)
                    if abs(value) >= 0.5:
                        correlations.append({"parameter_1": left, "parameter_2": output.var_names[j], "correlation": value})
        correlations.sort(key=lambda item: abs(item["correlation"]), reverse=True)
    warnings = []
    nind = float(getattr(output, "n_independent", getattr(dataset, "n_idp", np.nan)))
    nvars = int(getattr(output, "nvarys", 0))
    if np.isfinite(nind) and nind <= nvars:
        warnings.append(f"独立点数 Nind={nind:.2f} 不大于变量数 {nvars}，模型过度参数化")
    elif np.isfinite(nind) and nind - nvars < 2:
        warnings.append(f"Nind 仅比变量数多 {nind - nvars:.2f}，自由度余量偏小")
    if not bool(getattr(output, "errorbars", True)):
        warnings.append("拟合未能可靠估计参数误差")
    if correlations and abs(correlations[0]["correlation"]) >= 0.9:
        item = correlations[0]
        warnings.append(f"参数 {item['parameter_1']} 与 {item['parameter_2']} 高度相关 ({item['correlation']:.3f})")
    if float(getattr(output, "rfactor", np.nan)) > 0.05:
        warnings.append("R-factor 高于 0.05，请检查路径、拟合范围或数据质量")
    if bool(s02_vary) and any(bool(item.get("vary_cn", True)) for item in settings):
        warnings.append("S₀² 与 CN 同时自由拟合通常高度相关；建议先用标准样标定 S₀²")
    for name in output.var_names:
        par = output.params[name]
        span = float(par.max - par.min) if np.isfinite(par.min) and np.isfinite(par.max) else np.nan
        if np.isfinite(span) and span > 0 and min(abs(par.value - par.min), abs(par.max - par.value)) < 0.01 * span:
            warnings.append(f"参数 {name} 接近拟合边界，结果可能受约束主导")
        if par.stderr is not None:
            if name.startswith("delr_") and abs(par.stderr) > 0.02:
                warnings.append(f"参数 {name} 的绝对误差超过 0.02 Å，ΔR 尚未可靠确定")
            elif name == "de0" and abs(par.stderr) > 2.0:
                warnings.append("参数 de0 的误差超过 2 eV，能量修正尚未可靠确定")
            elif not name.startswith("delr_") and name != "de0" and abs(par.value) > 1e-12 and abs(par.stderr / par.value) > 0.5:
                warnings.append(f"参数 {name} 的相对误差超过 50%")

    display_kw = 2 if isinstance(kweight, (list, tuple)) and 2 in kweight else (kweight[0] if isinstance(kweight, (list, tuple)) else kweight)
    display_kw = int(display_kw)
    model = dataset.model
    data_k = np.asarray(data.k, dtype=float)
    data_chi = np.asarray(data.chi, dtype=float)
    model_k = np.asarray(model.k, dtype=float)
    model_chi = np.asarray(model.chi, dtype=float)
    model_on_data = np.interp(data_k, model_k, model_chi, left=0.0, right=0.0)
    residual_chi = data_chi - model_on_data
    energy_axis = np.asarray(processed["energy"], dtype=float)
    raw_mu = np.asarray(processed["mu"], dtype=float)
    normalized_mu = np.asarray(processed.get("display_norm", processed["norm"]), dtype=float)
    energy_k = np.sqrt(np.maximum((energy_axis - float(processed["e0"])) / K_ENERGY, 0.0))
    fit_energy_mask = (energy_axis >= float(processed["e0"])) & (energy_k >= float(kmin)) & (energy_k <= float(kmax))
    residual_on_energy = np.interp(energy_k, data_k, residual_chi, left=np.nan, right=np.nan)
    normalized_fit = np.full_like(normalized_mu, np.nan)
    normalized_fit[fit_energy_mask] = normalized_mu[fit_energy_mask] - residual_on_energy[fit_energy_mask]

    def r_transform(k: np.ndarray, chi: np.ndarray) -> Group:
        group = Group(k=k.copy(), chi=chi.copy())
        xftf(group, kmin=float(kmin), kmax=float(kmax), kweight=display_kw, dk=float(dk), window=window, rmax_out=max(6.0, float(rmax) + 1.0))
        return group

    data_r = r_transform(data_k, data_chi)
    model_r = r_transform(data_k, model_on_data)
    residual_r = r_transform(data_k, residual_chi)

    def wavelet(k: np.ndarray, chi: np.ndarray) -> Group:
        group = Group(k=k.copy(), chi=chi.copy())
        win = ftwindow(k, xmin=float(kmin), xmax=float(kmax), dx=float(dk), window=window)
        cauchy_wavelet(group.k, group.chi * win, group=group, kweight=int(wavelet_kweight), rmax_out=float(wavelet_rmax))
        return group

    def reduce_wavelet(group: Group, max_k_points: int = 240, max_r_points: int = 150) -> tuple[list[float], list[float], list[list[float]]]:
        kmask = (data_k >= float(kmin)) & (data_k <= float(kmax))
        k_indices = np.flatnonzero(kmask)
        kstep = max(1, int(np.ceil(len(k_indices) / max_k_points)))
        r_values = np.asarray(group.wcauchy_r, dtype=float)
        r_indices = np.arange(len(r_values))
        rstep = max(1, int(np.ceil(len(r_indices) / max_r_points)))
        ki, ri = k_indices[::kstep], r_indices[::rstep]
        magnitude = np.asarray(group.wcauchy_mag, dtype=float)[np.ix_(ri, ki)]
        return data_k[ki].tolist(), r_values[ri].tolist(), magnitude.tolist()

    if wavelet_backend.lower() == "hama":
        hama_config = HamaConfig(
            kmin=float(kmin), kmax=float(kmax), rmin=0.0, rmax=float(wavelet_rmax),
            kweight=int(wavelet_kweight), kappa=float(wavelet_kappa), sigma=float(wavelet_sigma),
        )
        hama_data = hama_morlet(data_k, data_chi, hama_config)
        hama_model = hama_morlet(data_k, model_on_data, hama_config)
        hama_residual = hama_morlet(data_k, residual_chi, hama_config)
        wk, wr = hama_data["k"], hama_data["r"]
        wave_data_mag, wave_model_mag, wave_residual_mag = hama_data["magnitude"], hama_model["magnitude"], hama_residual["magnitude"]
        wavelet_meta = {
            "backend": hama_data["backend"], "mother": hama_data["mother"],
            "kappa": hama_data["kappa"], "sigma": hama_data["sigma"],
            "input_k_step": hama_data["input_k_step"],
        }
    elif wavelet_backend.lower() == "cauchy":
        wave_data, wave_model, wave_residual = wavelet(data_k, data_chi), wavelet(data_k, model_on_data), wavelet(data_k, residual_chi)
        wk, wr, wave_data_mag = reduce_wavelet(wave_data)
        _, _, wave_model_mag = reduce_wavelet(wave_model)
        _, _, wave_residual_mag = reduce_wavelet(wave_residual)
        wavelet_meta = {"backend": "larch_cauchy", "mother": "Cauchy", "kappa": None, "sigma": None, "input_k_step": float(np.median(np.diff(data_k)))}
    else:
        raise ValueError("小波后端只能选择 HAMA Morlet 或 Larch Cauchy")
    parameter_rows = []
    for name, par in output.params.items():
        if hasattr(par, "value"):
            stderr = None if par.stderr is None else float(par.stderr)
            value = float(par.value)
            parameter_rows.append(
                {
                    "name": name,
                    "initial_value": float(getattr(par, "init_value", value) if getattr(par, "init_value", None) is not None else value),
                    "value": value,
                    "stderr": stderr,
                    "relative_error_percent": None if stderr is None or abs(value) < 1e-12 else abs(stderr / value) * 100.0,
                    "state": "def" if par.expr else ("guess" if par.vary else "set"),
                    "vary": bool(par.vary),
                    "min": None if not np.isfinite(par.min) else float(par.min),
                    "max": None if not np.isfinite(par.max) else float(par.max),
                    "expr": par.expr or "",
                }
            )
    def value_with_uncertainty(value: float, stderr: float | None) -> str:
        if stderr is None or not np.isfinite(stderr) or stderr <= 0:
            return f"{value:.5g}"
        exponent = int(np.floor(np.log10(abs(stderr))))
        decimals = max(0, -exponent)
        rounded_error = int(round(stderr * (10**decimals)))
        return f"{value:.{decimals}f}({rounded_error})"

    paper_table = []
    for index, path in enumerate(fitted_paths, start=1):
        paper_table.append(
            {
                "Path": path["label"],
                "d_FEFF_A": f"{path['Reff_A']:.4f}",
                "N": value_with_uncertainty(path["CN"], path["CN_stderr"]),
                "R_A": value_with_uncertainty(path["R_A"], path["deltar_stderr"]),
                "sigma2_A2": value_with_uncertainty(path["sigma2_A2"], path["sigma2_stderr"]),
                "N_state": "fixed" if not output.params[f"n_{index}"].vary else "refined",
                "sigma2_state": "constrained" if output.params[f"sig2_{index}"].expr else ("fixed" if not output.params[f"sig2_{index}"].vary else "refined"),
            }
        )
    s02_state = "refined" if output.params["s02"].vary else "fixed"
    paper_notes = [
        f"S₀² was {s02_state} at {float(output.params['s02'].value):.4f}; ΔE₀ was treated as a global parameter and returned {float(output.params['de0'].value):.3f} eV.",
        f"Fit ranges: {float(kmin):.2f} ≤ k ≤ {float(kmax):.2f} Å⁻¹ and {float(rmin):.2f} ≤ R ≤ {float(rmax):.2f} Å; k-weights: {','.join(str(v) for v in (kweight if isinstance(kweight, (list, tuple)) else [kweight]))}.",
        f"The fit used {int(getattr(output, 'nvarys', 0))} variable parameters and {float(getattr(output, 'n_independent', getattr(dataset, 'n_idp', np.nan))):.2f} independent points; R-factor = {float(getattr(output, 'rfactor', np.nan)):.5g}.",
        "d_FEFF is the effective half-path length from FEFF; fitted R = d_FEFF + ΔR. Parentheses give the uncertainty in the final digit(s).",
    ]
    return {
        "paths": fitted_paths,
        "delta_e0_eV": float(output.params["de0"].value),
        "delta_e0_stderr": None if output.params["de0"].stderr is None else float(output.params["de0"].stderr),
        "s02": float(output.params["s02"].value),
        "s02_stderr": None if output.params["s02"].stderr is None else float(output.params["s02"].stderr),
        "r_factor": float(getattr(output, "rfactor", np.nan)),
        "chi_square": float(getattr(output, "chi_square", np.nan)),
        "reduced_chi_square": float(getattr(output, "redchi", np.nan)),
        "n_variables": int(getattr(output, "nvarys", 0)),
        "n_independent": float(getattr(output, "n_independent", getattr(dataset, "n_idp", np.nan))),
        "n_free": int(getattr(output, "nfree", 0)),
        "aic": float(getattr(output, "aic", np.nan)),
        "bic": float(getattr(output, "bic", np.nan)),
        "kweights": list(kweight) if isinstance(kweight, (list, tuple)) else [int(kweight)],
        "display_kweight": display_kw,
        "parameter_rows": parameter_rows,
        "paper_table": paper_table,
        "paper_notes": paper_notes,
        "correlations": correlations,
        "warnings": warnings,
        "quality_status": "需要重点复核" if warnings else "自动审查未发现明显问题",
        "report": report,
        "data_k": data_k.tolist(),
        "data_chi": data_chi.tolist(),
        "model_k": data_k.tolist(),
        "model_chi": model_on_data.tolist(),
        "residual_chi": residual_chi.tolist(),
        "energy_fit_eV": (float(processed["e0"]) + K_ENERGY * np.square(data_k)).tolist(),
        "energy_data_chi": data_chi.tolist(),
        "energy_model_chi": model_on_data.tolist(),
        "energy_residual_chi": residual_chi.tolist(),
        "energy_spectrum_eV": energy_axis.tolist(),
        "energy_raw_mu": raw_mu.tolist(),
        "energy_normalized_mu": normalized_mu.tolist(),
        "energy_pre_edge": np.asarray(processed["pre_edge"], dtype=float).tolist(),
        "energy_post_edge": np.asarray(processed["post_edge"], dtype=float).tolist(),
        "energy_e0_eV": float(processed["e0"]),
        "energy_normalized_fit": [None if not np.isfinite(value) else float(value) for value in normalized_fit],
        "energy_fit_region_eV": [float(processed["e0"] + K_ENERGY * float(kmin) ** 2), float(processed["e0"] + K_ENERGY * float(kmax) ** 2)],
        "r": np.asarray(data_r.r).tolist(),
        "data_chir_mag": np.asarray(data_r.chir_mag).tolist(),
        "model_chir_mag": np.asarray(model_r.chir_mag).tolist(),
        "residual_chir_mag": np.asarray(residual_r.chir_mag).tolist(),
        "data_chir_re": np.asarray(data_r.chir_re).tolist(),
        "model_chir_re": np.asarray(model_r.chir_re).tolist(),
        "residual_chir_re": np.asarray(residual_r.chir_re).tolist(),
        "data_chir_im": np.asarray(data_r.chir_im).tolist(),
        "model_chir_im": np.asarray(model_r.chir_im).tolist(),
        "residual_chir_im": np.asarray(residual_r.chir_im).tolist(),
        "fit_config": {"fitspace": fitspace, "kmin": float(kmin), "kmax": float(kmax), "kweights": list(kweight) if isinstance(kweight, (list, tuple)) else [int(kweight)], "dk": float(dk), "window": window, "rmin": float(rmin), "rmax": float(rmax), "rwindow": rwindow},
        "wavelet": {"k": wk, "r": wr, "data_mag": wave_data_mag, "model_mag": wave_model_mag, "residual_mag": wave_residual_mag, "kweight": int(wavelet_kweight), **wavelet_meta},
    }


def intelligent_fit_feff_paths(
    processed: dict[str, Any],
    path_files: list[Path],
    settings: list[dict[str, Any]],
    *,
    fit_mode: str = "unknown",
    smart_fit: bool = True,
    s02_source: str = "manual",
    temperature_profile: str = "room",
    max_shell: int | None = None,
    **fit_kwargs: Any,
) -> dict[str, Any]:
    """Run an auditable Artemis-like staged fit.

    This is deliberately rule-based rather than a black-box optimizer.  Early
    stages estimate phase/distance and disorder before the amplitude parameters
    are released.  The final stage always uses the user's bounds/constraints.
    """
    if fit_mode not in ("standard", "unknown", "advanced"):
        raise ValueError("拟合模式必须为 standard、unknown 或 advanced")
    original = deepcopy(settings)
    working = deepcopy(settings)
    shell_numbers = [max(1, int(item.get("shell", 1))) for item in original]
    active_indices = [index for index, shell in enumerate(shell_numbers) if max_shell is None or shell <= max_shell]
    if not active_indices:
        raise ValueError("当前选择中没有符合壳层范围的 FEFF 路径")
    stage_history: list[dict[str, Any]] = []
    decisions: list[str] = []
    rejected_reasons: list[str] = []
    current_s02 = float(fit_kwargs.get("s02", 0.85))
    current_de0 = float(fit_kwargs.get("de0", 0.0))
    accepted_result: dict[str, Any] | None = None

    if fit_mode == "standard":
        for item in original:
            item["vary_cn"] = False
        fit_kwargs["s02_vary"] = True
        decisions.append("标准样模式：固定 FEFF/用户给定 CN，最终拟合 S₀²")
    elif fit_mode == "unknown":
        fit_kwargs["s02_vary"] = False
        source_label = "标准样标定" if s02_source == "standard_calibration" else "手工输入/默认值"
        decisions.append(f"未知样品模式：固定 S₀²={current_s02:.4f}（来源：{source_label}），最终拟合允许变化的 CN")
    else:
        decisions.append("高级模式：完全遵循用户设置，不自动改变自由参数")

    def run_stage(
        name: str,
        stage_settings: list[dict[str, Any]],
        *,
        vary_s02: bool,
        indices: list[int] | None = None,
        require_model_improvement: bool = False,
    ) -> dict[str, Any]:
        nonlocal current_s02, current_de0, working, accepted_result
        selected = indices if indices is not None else list(range(len(path_files)))
        output = fit_feff_paths(
            processed,
            [path_files[index] for index in selected],
            stage_settings,
            **{**fit_kwargs, "s02": current_s02, "de0": current_de0, "s02_vary": vary_s02},
        )
        reasons = []
        r_factor = float(output["r_factor"])
        if not np.isfinite(r_factor):
            reasons.append("R-factor 不是有限数值")
        if np.isfinite(output["n_independent"]) and output["n_independent"] <= output["n_variables"]:
            reasons.append("Nind 不大于自由变量数")
        if accepted_result is not None and np.isfinite(r_factor):
            previous_r = float(accepted_result["r_factor"])
            if np.isfinite(previous_r) and r_factor > max(previous_r * 1.05, previous_r + 1e-6):
                reasons.append(f"R-factor 相比上一接受阶段恶化超过 5%（{previous_r:.5g} → {r_factor:.5g}）")
            if require_model_improvement:
                previous_aic, current_aic = float(accepted_result["aic"]), float(output["aic"])
                relative_gain = (previous_r - r_factor) / max(abs(previous_r), 1e-12)
                if np.isfinite(previous_aic) and np.isfinite(current_aic):
                    if current_aic > previous_aic - 2.0 and relative_gain < 0.02:
                        reasons.append("新增壳层未使 AIC 改善至少 2，且 R-factor 改善不足 2%")
                elif relative_gain < 0.02:
                    reasons.append("新增壳层使 R-factor 改善不足 2%")
        max_correlation = max((abs(float(item["correlation"])) for item in output["correlations"]), default=0.0)
        if max_correlation >= 0.98:
            reasons.append(f"存在近退化参数相关性 |r|={max_correlation:.3f}")
        if fit_mode == "standard" and name == "3_final_amplitude" and not 0.6 <= float(output["s02"]) <= 1.1:
            reasons.append(f"标准样 S₀²={output['s02']:.3f} 超出建议审查范围 0.6–1.1")
        accepted = not reasons
        stage_history.append(
            {
                "stage": name,
                "r_factor": r_factor,
                "reduced_chi_square": output["reduced_chi_square"],
                "n_variables": output["n_variables"],
                "n_independent": output["n_independent"],
                "max_abs_correlation": max_correlation,
                "s02": float(output["s02"]),
                "delta_e0_eV": float(output["delta_e0_eV"]),
                "path_count": len(selected),
                "shells": ",".join(str(value) for value in sorted({shell_numbers[index] for index in selected})),
                "accepted": accepted,
                "reason": "通过确定性检查" if accepted else "；".join(reasons),
            }
        )
        if accepted:
            current_s02, current_de0 = output["s02"], output["delta_e0_eV"]
            for index, fitted in zip(selected, output["paths"]):
                working[index]["cn"] = fitted["CN"]
                working[index]["sigma2"] = fitted["sigma2_A2"]
                working[index]["deltar"] = fitted["deltar_A"]
            accepted_result = output
        else:
            rejected_reasons.extend(f"{name}：{reason}" for reason in reasons)
            decisions.append(f"{name} 未接受，后续阶段继续使用上一个已接受状态")
        return output

    if not smart_fit or fit_mode == "advanced":
        result = run_stage("single_advanced_fit", [deepcopy(original[index]) for index in active_indices], vary_s02=bool(fit_kwargs.get("s02_vary", False)), indices=active_indices)
    else:
        first_shell = min(shell_numbers[index] for index in active_indices)
        first_indices = [index for index in active_indices if shell_numbers[index] == first_shell]
        geometry = [deepcopy(working[index]) for index in first_indices]
        for item in geometry:
            item.update(vary_cn=False, vary_sigma2=False)
            item["vary_deltar"] = bool(item.get("vary_deltar", True))
        run_stage("1_first_shell_geometry", geometry, vary_s02=False, indices=first_indices)

        disorder = [deepcopy(working[index]) for index in first_indices]
        for item in disorder:
            item["vary_cn"] = False
            item["vary_sigma2"] = bool(item.get("vary_sigma2", True))
        run_stage("2_first_shell_disorder", disorder, vary_s02=False, indices=first_indices)

        first_final = [deepcopy(original[index]) for index in first_indices]
        for target, index in zip(first_final, first_indices):
            seed = working[index]
            target["cn"], target["sigma2"], target["deltar"] = seed["cn"], seed["sigma2"], seed["deltar"]
            if fit_mode == "standard":
                target["vary_cn"] = False
        final_attempt = run_stage("3_final_amplitude", first_final, vary_s02=(fit_mode == "standard"), indices=first_indices)

        if fit_mode == "standard" and len(first_indices) < len(original):
            decisions.append("标准样标定仅采用第一壳路径；更高壳层不参与 S₀² 标定")
        elif fit_mode == "unknown":
            for shell in sorted({shell_numbers[index] for index in active_indices}):
                if shell == first_shell:
                    continue
                cumulative = [index for index in active_indices if shell_numbers[index] <= shell]
                cumulative_settings = [deepcopy(original[index]) for index in cumulative]
                for target, index in zip(cumulative_settings, cumulative):
                    seed = working[index]
                    target["cn"], target["sigma2"], target["deltar"] = seed["cn"], seed["sigma2"], seed["deltar"]
                final_attempt = run_stage(
                    f"add_shell_{shell}",
                    cumulative_settings,
                    vary_s02=False,
                    indices=cumulative,
                    require_model_improvement=True,
                )
        result = accepted_result if accepted_result is not None else final_attempt

    result["fit_mode"] = fit_mode
    result["s02_source"] = s02_source
    result["temperature_profile"] = temperature_profile
    result["max_shell"] = max_shell
    result["smart_fit"] = bool(smart_fit)
    result["stage_history"] = stage_history
    result["manager_decisions"] = decisions
    if rejected_reasons:
        result["warnings"] = list(dict.fromkeys([*result.get("warnings", []), *rejected_reasons]))
        result["quality_status"] = "需要重点复核"
    for path in result.get("paths", []):
        if float(path["sigma2_A2"]) > 0.03:
            result["warnings"].append(f"路径 {path['label']} 的 σ²>0.03 Å²，单壳模型可能不足")
            result["quality_status"] = "需要重点复核"
    result["warnings"] = list(dict.fromkeys(result.get("warnings", [])))
    result["manager_next_actions"] = list(dict.fromkeys(result.get("warnings", [])))
    result["accepted_stage"] = next((item["stage"] for item in reversed(stage_history) if item["accepted"]), None)
    result["calibration_eligible"] = bool(fit_mode == "standard" and result["accepted_stage"] == "3_final_amplitude")
    sigma_profiles = {
        "low": (0.002, 0.006, "低温参考 0.002–0.006 Å²"),
        "room": (0.003, 0.010, "室温参考 0.003–0.010 Å²"),
        "high": (0.006, 0.015, "高温参考 0.006–0.015 Å²"),
        "general": (0.001, 0.020, "通用审查 0.001–0.020 Å²"),
    }
    sigma_low, sigma_high, sigma_note = sigma_profiles.get(temperature_profile, sigma_profiles["room"])
    assessments: list[dict[str, Any]] = []

    def assess(scope: str, field: str, value: float, severity: str, recommended: str, action: str, index: int | None = None) -> None:
        assessments.append({"scope": scope, "index": index, "field": field, "value": float(value), "severity": severity, "recommended": recommended, "action": action})

    fitted_s02 = float(result["s02"])
    s02_severity = "danger" if not 0.6 <= fitted_s02 <= 1.1 else ("warning" if not 0.75 <= fitted_s02 <= 1.05 else ("ok" if 0.8 <= fitted_s02 <= 1.0 else "info"))
    assess("global", "s02", fitted_s02, s02_severity, "优选 0.80–1.00；通用复核 0.75–1.05", "超出时检查标准样、CN、路径振幅及自吸收")
    fitted_de0 = float(result["delta_e0_eV"])
    de0_abs = abs(fitted_de0)
    assess("global", "de0", fitted_de0, "danger" if de0_abs > 10 else ("warning" if de0_abs > 5 else "ok"), "|E₀| ≤ 10 eV，优选 ≤ 5 eV", "超出时返回 Athena 检查 E₀ 与能量校准")
    for index, path in enumerate(result.get("paths", [])):
        cn = float(path["CN"])
        cn_error = path.get("CN_stderr")
        cn_severity = "danger" if cn < 0 else ("warning" if cn_error is not None and abs(float(cn_error)) > 0.5 * max(abs(cn), 1e-12) else "ok")
        assess("path", "cn", cn, cn_severity, "依据晶体结构/化学计量设置；误差宜 <50%", "异常时固定 CN 或收紧结构合理范围", index)
        sigma2 = float(path["sigma2_A2"])
        sigma_severity = "danger" if sigma2 < 0 or sigma2 > 0.03 else ("warning" if not sigma_low <= sigma2 <= sigma_high else "ok")
        assess("path", "sigma2", sigma2, sigma_severity, sigma_note, "超出时检查温度、CN–σ²相关性或拆分配位壳", index)
        deltar = float(path["deltar_A"])
        dr_abs = abs(deltar)
        assess("path", "deltar", deltar, "danger" if dr_abs > 0.10 else ("warning" if dr_abs > 0.05 else "ok"), "|ΔR| ≤ 0.10 Å，优选 ≤ 0.05 Å", "超出时检查 FEFF 路径/结构模型", index)
    result["parameter_assessment"] = assessments
    result["guidance_profile"] = {
        "s02": "优选 0.80–1.00；通用复核 0.75–1.05",
        "de0": "|ΔE₀| ≤ 10 eV，优选 ≤ 5 eV",
        "deltar": "|ΔR| ≤ 0.10 Å，优选 ≤ 0.05 Å",
        "sigma2": sigma_note,
        "note": "这些是经验审查范围，不替代样品结构、温度和标准样判断。",
    }
    if str(fit_kwargs.get("wavelet_backend", "hama")).lower() == "hama":
        hama_config = HamaConfig(
            kmin=float(fit_kwargs.get("kmin", 3.0)),
            kmax=float(fit_kwargs.get("kmax", 12.0)),
            rmin=0.0,
            rmax=float(fit_kwargs.get("wavelet_rmax", 5.0)),
            kweight=int(fit_kwargs.get("wavelet_kweight", 2)),
            kappa=float(fit_kwargs.get("wavelet_kappa", 10.0)),
            sigma=float(fit_kwargs.get("wavelet_sigma", 1.0)),
        )
        native_maps = [
            native_hama_morlet(np.asarray(result["data_k"]), np.asarray(values), hama_config)
            for values in (result["data_chi"], result["model_chi"], result["residual_chi"])
        ]
        result["wavelet"] = {
            "k": native_maps[0]["k"], "r": native_maps[0]["r"],
            "data_mag": native_maps[0]["magnitude"], "model_mag": native_maps[1]["magnitude"],
            "residual_mag": native_maps[2]["magnitude"], "kweight": hama_config.kweight,
            "backend": native_maps[0]["backend"], "mother": native_maps[0]["mother"],
            "kappa": native_maps[0]["kappa"], "sigma": native_maps[0]["sigma"],
            "input_k_step": native_maps[0]["input_k_step"],
        }
    return result
