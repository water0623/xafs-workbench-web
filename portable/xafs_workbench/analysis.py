from __future__ import annotations

from typing import Any

import numpy as np
from scipy.interpolate import interp1d
from scipy.optimize import lsq_linear


def linear_combination_fit(
    sample: dict[str, Any],
    references: list[tuple[str, dict[str, Any]]],
    emin: float,
    emax: float,
    sum_to_one: bool = True,
) -> dict[str, Any]:
    if len(references) < 2:
        raise ValueError("LCF 至少需要两个参考谱")
    step = max(0.1, float(np.median(np.diff(np.asarray(sample["energy"], dtype=float)))))
    grid = np.arange(emin, emax + step * 0.25, step)
    sample_values = sample.get("display_norm", sample["norm"])
    sample_interp = interp1d(sample["energy"], sample_values, bounds_error=False, fill_value=np.nan)(grid)
    ref_arrays = [interp1d(ref["energy"], ref.get("display_norm", ref["norm"]), bounds_error=False, fill_value=np.nan)(grid) for _, ref in references]
    matrix = np.column_stack(ref_arrays)
    finite = np.isfinite(sample_interp) & np.all(np.isfinite(matrix), axis=1)
    y, design, x = sample_interp[finite], matrix[finite], grid[finite]
    if len(y) < 15:
        raise ValueError("LCF 能量区间的共同有效数据点不足")
    if sum_to_one:
        weight = max(20.0, np.sqrt(len(y)) * 10.0)
        design = np.vstack([design, np.ones((1, design.shape[1])) * weight])
        yfit = np.r_[y, weight]
    else:
        yfit = y
    result = lsq_linear(design, yfit, bounds=(0.0, 1.0))
    fractions = result.x
    if sum_to_one and fractions.sum() > 0:
        fractions = fractions / fractions.sum()
    fit = matrix[finite] @ fractions
    residual = y - fit
    denom = float(np.sum(y * y))
    return {
        "fractions": [{"reference": name, "fraction": float(frac)} for (name, _), frac in zip(references, fractions)],
        "energy": x.tolist(),
        "sample": y.tolist(),
        "fit": fit.tolist(),
        "residual": residual.tolist(),
        "r_factor": float(np.sum(residual**2) / denom) if denom else float("nan"),
        "rmse": float(np.sqrt(np.mean(residual**2))),
        "range": [float(emin), float(emax)],
        "sum_to_one": bool(sum_to_one),
    }
