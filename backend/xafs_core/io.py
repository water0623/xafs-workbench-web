"""ASCII XAFS data import helpers."""
from __future__ import annotations

from io import StringIO
from typing import Dict, List, Optional
import re
import numpy as np


def parse_ascii_xafs(text: str, energy_col: int = 0, mu_col: Optional[int] = 1,
                     i0_col: Optional[int] = None, it_col: Optional[int] = None,
                     if_col: Optional[int] = None, mode: str = "auto") -> Dict:
    """Parse whitespace/comma separated synchrotron ASCII data.

    Column indices are zero-based. If i0/it are supplied, transmission mu is
    calculated as ln(I0/It). If i0/if are supplied, fluorescence mu is If/I0.
    Otherwise mu_col is used directly.
    """
    rows: List[List[float]] = []
    header: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("#", ";", "!", "%")):
            header.append(line)
            continue
        parts = re.split(r"[\s,;]+", line)
        try:
            vals = [float(v.replace("D", "E")) for v in parts if v != ""]
        except ValueError:
            header.append(line)
            continue
        if len(vals) >= 2:
            rows.append(vals)
    if len(rows) < 2:
        raise ValueError("Could not find at least two numeric data rows")
    ncol = min(len(r) for r in rows)
    arr = np.asarray([r[:ncol] for r in rows], float)
    if energy_col >= ncol:
        raise ValueError("energy_col is outside available columns")
    energy = arr[:, energy_col]

    resolved_mode = mode.lower()
    if resolved_mode == "auto":
        if i0_col is not None and it_col is not None:
            resolved_mode = "transmission"
        elif i0_col is not None and if_col is not None:
            resolved_mode = "fluorescence"
        else:
            resolved_mode = "mu"

    if resolved_mode == "transmission":
        if i0_col is None or it_col is None:
            raise ValueError("transmission mode requires i0_col and it_col")
        i0, it = arr[:, i0_col], arr[:, it_col]
        if np.any(i0 <= 0) or np.any(it <= 0):
            raise ValueError("Transmission intensities must be positive")
        mu = np.log(i0 / it)
    elif resolved_mode == "fluorescence":
        if i0_col is None or if_col is None:
            raise ValueError("fluorescence mode requires i0_col and if_col")
        i0, iff = arr[:, i0_col], arr[:, if_col]
        if np.any(i0 == 0):
            raise ValueError("I0 contains zero values")
        mu = iff / i0
    else:
        if mu_col is None or mu_col >= ncol:
            raise ValueError("mu_col is outside available columns")
        mu = arr[:, mu_col]

    ok = np.isfinite(energy) & np.isfinite(mu)
    energy, mu = energy[ok], mu[ok]
    order = np.argsort(energy)
    energy, mu = energy[order], mu[order]
    return {
        "energy": energy,
        "mu": mu,
        "mode": resolved_mode,
        "n_rows": int(len(energy)),
        "n_columns": int(ncol),
        "header": header,
    }


def merge_spectra(spectra: List[Dict], grid: Optional[np.ndarray] = None) -> Dict:
    """Interpolate and average multiple spectra on their common energy range."""
    if len(spectra) < 2:
        raise ValueError("At least two spectra are required for merging")
    starts = [float(np.min(np.asarray(s["energy"], float))) for s in spectra]
    stops = [float(np.max(np.asarray(s["energy"], float))) for s in spectra]
    lo, hi = max(starts), min(stops)
    if not lo < hi:
        raise ValueError("Spectra do not share an overlapping energy range")
    if grid is None:
        steps = []
        for s in spectra:
            e = np.asarray(s["energy"], float)
            d = np.diff(np.sort(e))
            d = d[d > 0]
            if len(d): steps.append(float(np.median(d)))
        step = min(steps) if steps else (hi - lo) / 1000.0
        grid = np.arange(lo, hi + step/2, step)
    curves = []
    for s in spectra:
        e = np.asarray(s["energy"], float)
        y = np.asarray(s["mu"], float)
        order = np.argsort(e)
        curves.append(np.interp(grid, e[order], y[order]))
    mat = np.vstack(curves)
    return {
        "energy": grid,
        "mu": np.mean(mat, axis=0),
        "std": np.std(mat, axis=0, ddof=1),
        "n_spectra": int(len(spectra)),
    }
