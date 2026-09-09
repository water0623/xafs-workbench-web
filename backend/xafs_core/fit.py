"""Artemis-style EXAFS fitting engine (first implementation).

This module provides a flexible nonlinear EXAFS fitting framework. It accepts
pre-calculated theoretical paths (for example from FEFF) and refines
structural parameters against experimental chi(k).
"""
from dataclasses import dataclass
from typing import Dict, List
import numpy as np
from scipy.optimize import least_squares


@dataclass
class FitParameter:
    name: str
    value: float
    vary: bool = True


def _path_model(k, path, params):
    """Simplified EXAFS path equation.

    path fields:
      amplitude, phase, sigma2, r

    For production FEFF integration the path arrays will be replaced by
    feffNNNN.dat interpolation.
    """
    amp = float(path.get("amplitude", 1.0))
    phase = np.asarray(path.get("phase", np.zeros_like(k)))
    r = params.get(path.get("r_parameter", "R"), path.get("r", 2.0))
    sigma2 = params.get(path.get("sigma_parameter", "sigma2"), path.get("sigma2", 0.003))
    cn = params.get(path.get("cn_parameter", "CN"), path.get("CN", 4.0))
    return amp * cn / (k * r*r + 1e-9) * np.exp(-2*sigma2*k*k) * np.sin(2*k*r + phase)


def fit_exafs(k, chi, paths, parameters):
    k = np.asarray(k, float)
    chi = np.asarray(chi, float)
    names = [p["name"] for p in parameters if p.get("vary", True)]
    x0 = [float(p["value"]) for p in parameters if p.get("vary", True)]

    def unpack(x):
        result = {p["name"]: float(p["value"]) for p in parameters}
        for n, v in zip(names, x):
            result[n] = float(v)
        return result

    def residual(x):
        pars = unpack(x)
        model = np.zeros_like(k)
        for path in paths:
            model += _path_model(k, path, pars)
        return (model - chi) * k*k

    result = least_squares(residual, x0)
    pars = unpack(result.x)
    model = chi + result.fun / np.maximum(k*k, 1e-12)
    rfactor = float(np.sum((chi-model)**2) / np.sum(chi**2))
    return {
        "parameters": pars,
        "model": model,
        "residual": chi-model,
        "r_factor": rfactor,
        "success": bool(result.success),
        "message": result.message,
    }
