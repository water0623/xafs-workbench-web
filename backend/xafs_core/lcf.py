"""XANES linear-combination fitting utilities."""
import numpy as np
from scipy.optimize import lsq_linear


def linear_combination_fit(energy, sample, references, emin=None, emax=None, sum_to_one=True):
    e = np.asarray(energy, float); y = np.asarray(sample, float)
    if len(references) < 1:
        raise ValueError("At least one reference spectrum is required")
    mask = np.isfinite(e) & np.isfinite(y)
    if emin is not None: mask &= e >= float(emin)
    if emax is not None: mask &= e <= float(emax)
    ee, yy = e[mask], y[mask]
    cols, names = [], []
    for name, ref in references.items():
        rr = np.asarray(ref, float)[mask]
        if not np.all(np.isfinite(rr)):
            raise ValueError(f"Reference {name} contains invalid values")
        cols.append(rr); names.append(name)
    A = np.column_stack(cols)
    if sum_to_one:
        weight = max(np.sqrt(len(yy)), 1.0) * 100.0
        Afit = np.vstack([A, np.ones((1, A.shape[1])) * weight])
        yfit = np.r_[yy, weight]
    else:
        Afit, yfit = A, yy
    result = lsq_linear(Afit, yfit, bounds=(0.0, 1.0))
    coef = result.x
    if sum_to_one and coef.sum() > 0: coef = coef / coef.sum()
    fit = A @ coef
    resid = yy - fit
    denom = float(np.sum(yy ** 2))
    rfactor = float(np.sum(resid ** 2) / denom) if denom else float("nan")
    return {"energy": ee, "fit": fit, "residual": resid,
            "weights": dict(zip(names, map(float, coef))), "r_factor": rfactor}
