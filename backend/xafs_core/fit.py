"""Artemis-style EXAFS fitting utilities.

This module fits pre-calculated FEFF-like path arrays against experimental
chi(k). It supports bounded parameters, shared/global parameters, k-weighted
residuals, uncertainty estimates and a correlation matrix.
"""
from __future__ import annotations

from typing import Dict, List
import numpy as np
from scipy.optimize import least_squares

KTOE = 3.80998211615486


def _interp_path(k, path):
    pk = np.asarray(path.get("k", k), float)
    amp = np.asarray(path.get("amplitude", np.ones_like(pk)), float)
    phase = np.asarray(path.get("phase", np.zeros_like(pk)), float)
    lam = np.asarray(path.get("lambda", np.full_like(pk, np.inf)), float)
    red = np.asarray(path.get("reduction", np.ones_like(pk)), float)
    if pk.ndim != 1 or len(pk) < 2:
        raise ValueError("Each path requires at least two k points")
    return (
        np.interp(k, pk, amp),
        np.interp(k, pk, phase),
        np.interp(k, pk, lam),
        np.interp(k, pk, red),
    )


def _path_model(k, path, params):
    """Evaluate one FEFF-like EXAFS path.

    Supported path metadata: reff/r, degeneracy, k, amplitude, phase, lambda,
    reduction and optional parameter-name mappings (s02_parameter,
    cn_parameter, dr_parameter, sigma2_parameter, de0_parameter).
    """
    amp, phase, lam, red = _interp_path(k, path)
    reff = float(path.get("reff", path.get("r", 2.0)))
    degeneracy = float(path.get("degeneracy", path.get("CN", 1.0)))

    s02 = float(params.get(path.get("s02_parameter", "S02"), path.get("S02", 1.0)))
    cn = float(params.get(path.get("cn_parameter", "CN"), degeneracy))
    dr = float(params.get(path.get("dr_parameter", "dR"), path.get("dR", 0.0)))
    sigma2 = float(params.get(path.get("sigma2_parameter", "sigma2"), path.get("sigma2", 0.003)))
    de0 = float(params.get(path.get("de0_parameter", "DeltaE0"), path.get("DeltaE0", 0.0)))

    r = max(reff + dr, 1e-6)
    k_eff = np.sqrt(np.clip(k * k - de0 / KTOE, 1e-12, None))
    damping = np.exp(-2.0 * sigma2 * k_eff * k_eff)
    mfp = np.ones_like(k_eff)
    finite = np.isfinite(lam) & (lam > 0)
    mfp[finite] = np.exp(-2.0 * r / lam[finite])

    return (
        s02 * cn * amp * red * damping * mfp
        * np.sin(2.0 * k_eff * r + phase)
        / np.maximum(k_eff * r * r, 1e-12)
    )


def fit_exafs(k, chi, paths, parameters, kmin=None, kmax=None, kweight=2):
    k = np.asarray(k, float)
    chi = np.asarray(chi, float)
    mask = np.isfinite(k) & np.isfinite(chi)
    if kmin is not None:
        mask &= k >= float(kmin)
    if kmax is not None:
        mask &= k <= float(kmax)
    k, chi = k[mask], chi[mask]
    if len(k) < 6:
        raise ValueError("At least 6 data points are required in the selected fit range")
    if not paths:
        raise ValueError("At least one theoretical path is required")

    varying = [p for p in parameters if p.get("vary", True)]
    names = [p["name"] for p in varying]
    x0 = np.asarray([float(p["value"]) for p in varying], float)
    lower = np.asarray([float(p.get("min", -np.inf)) for p in varying], float)
    upper = np.asarray([float(p.get("max", np.inf)) for p in varying], float)
    if np.any(x0 < lower) or np.any(x0 > upper):
        raise ValueError("One or more starting values fall outside their bounds")

    def unpack(x):
        out = {p["name"]: float(p["value"]) for p in parameters}
        for n, v in zip(names, x):
            out[n] = float(v)
        return out

    weights = np.power(np.maximum(k, 1e-9), int(kweight))

    def model_for(pars):
        model = np.zeros_like(k)
        for path in paths:
            model += _path_model(k, path, pars)
        return model

    def residual(x):
        return (model_for(unpack(x)) - chi) * weights

    result = least_squares(residual, x0, bounds=(lower, upper), jac="2-point")
    pars = unpack(result.x)
    model = model_for(pars)
    raw_residual = chi - model
    denom = float(np.sum(chi ** 2))
    rfactor = float(np.sum(raw_residual ** 2) / denom) if denom > 0 else float("nan")

    stderr = {p["name"]: None for p in parameters}
    corr = {p["name"]: {} for p in parameters}
    cov = None
    nvar = len(result.x)
    dof = max(len(k) - nvar, 1)
    if nvar and result.jac is not None:
        try:
            jtj_inv = np.linalg.pinv(result.jac.T @ result.jac)
            s_sq = 2.0 * result.cost / dof
            cov = jtj_inv * s_sq
            sd = np.sqrt(np.clip(np.diag(cov), 0.0, None))
            for name, err in zip(names, sd):
                stderr[name] = float(err)
            for i, ni in enumerate(names):
                for j, nj in enumerate(names):
                    den = sd[i] * sd[j]
                    corr[ni][nj] = float(cov[i, j] / den) if den > 0 else None
        except np.linalg.LinAlgError:
            cov = None

    return {
        "k": k,
        "chi": chi,
        "parameters": pars,
        "stderr": stderr,
        "correlation": corr,
        "model": model,
        "residual": raw_residual,
        "r_factor": rfactor,
        "chi_square": float(np.sum((raw_residual * weights) ** 2)),
        "reduced_chi_square": float(np.sum((raw_residual * weights) ** 2) / dof),
        "n_points": int(len(k)),
        "n_vary": int(nvar),
        "success": bool(result.success),
        "message": str(result.message),
    }
