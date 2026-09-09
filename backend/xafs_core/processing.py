"""Numerical XAFS preprocessing inspired by the Athena workflow.

The routines are dependency-light and expose deterministic primitives for
energy calibration, pre-edge normalization, E->k conversion and Fourier
transformation. They are not a reimplementation of Demeter/IFEFFIT.
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import UnivariateSpline
from scipy.signal import savgol_filter

KTOE = 3.80998211615486  # hbar^2/(2*m_e), eV A^2


def _xy(energy, mu):
    e = np.asarray(energy, dtype=float)
    y = np.asarray(mu, dtype=float)
    ok = np.isfinite(e) & np.isfinite(y)
    e, y = e[ok], y[ok]
    order = np.argsort(e)
    e, y = e[order], y[order]
    if e.size < 8:
        raise ValueError("At least 8 finite data points are required")
    return e, y


def find_e0(energy, mu, smooth=True):
    e, y = _xy(energy, mu)
    yy = y
    if smooth and len(y) >= 11:
        win = min(15, len(y) if len(y) % 2 else len(y) - 1)
        if win >= 5:
            yy = savgol_filter(y, win, 3)
    derivative = np.gradient(yy, e)
    return float(e[int(np.nanargmax(derivative))])


def calibrate_energy(energy, measured_e0, reference_e0):
    e = np.asarray(energy, dtype=float)
    shift = float(reference_e0) - float(measured_e0)
    return e + shift, shift


def normalize(energy, mu, e0=None, pre1=-150.0, pre2=-30.0,
              norm1=150.0, norm2=None, flatten=True):
    e, y = _xy(energy, mu)
    e0 = find_e0(e, y) if e0 is None else float(e0)
    if norm2 is None:
        norm2 = float(e[-1] - e0)
    pre_mask = (e >= e0 + pre1) & (e <= e0 + pre2)
    post_mask = (e >= e0 + norm1) & (e <= e0 + norm2)
    if pre_mask.sum() < 2 or post_mask.sum() < 3:
        raise ValueError("Selected pre-edge/post-edge ranges contain too few points")
    pre_coef = np.polyfit(e[pre_mask] - e0, y[pre_mask], 1)
    pre = np.polyval(pre_coef, e - e0)
    degree = 2 if post_mask.sum() >= 3 else 1
    post_coef = np.polyfit(e[post_mask] - e0, y[post_mask], degree)
    post = np.polyval(post_coef, e - e0)
    edge_step = float(np.polyval(post_coef, 0.0) - np.polyval(pre_coef, 0.0))
    if not np.isfinite(edge_step) or abs(edge_step) < 1e-15:
        raise ValueError("Could not determine a finite non-zero edge step")
    norm = (y - pre) / edge_step
    flat = norm.copy()
    if flatten:
        correction = (post - pre) / edge_step
        idx = e >= e0
        flat[idx] = norm[idx] - correction[idx] + 1.0
    return {"energy": e, "mu": y, "e0": e0, "pre_edge": pre,
            "post_edge": post, "edge_step": edge_step,
            "norm": norm, "flat": flat}


def energy_to_k(energy, e0):
    de = np.asarray(energy, dtype=float) - float(e0)
    return np.sqrt(np.clip(de, 0.0, None) / KTOE)


def autobk_simple(energy, mu, e0=None, rbkg=1.0, kmin=0.0, kmax=None,
                  kstep=0.05):
    """Approximate smooth-background removal for browser/API workflows.

    For publication-grade Athena equivalence use Larch/IFEFFIT autobk. This
    implementation uses a smoothing spline whose stiffness scales with rbkg.
    """
    e, y = _xy(energy, mu)
    e0 = find_e0(e, y) if e0 is None else float(e0)
    kraw = energy_to_k(e, e0)
    sel = e >= e0
    kraw, yy = kraw[sel], y[sel]
    if kmax is None:
        kmax = float(kraw[-1])
    mask = (kraw >= kmin) & (kraw <= kmax)
    kraw, yy = kraw[mask], yy[mask]
    if len(kraw) < 8:
        raise ValueError("Insufficient post-edge points for background removal")
    scale = max(float(np.var(yy)) * len(yy), 1e-12)
    spline = UnivariateSpline(kraw, yy, s=scale * max(float(rbkg), 0.05))
    bkg = spline(kraw)
    edge_step = np.nanmedian(np.abs(yy[-max(3, len(yy)//10):] - bkg[-max(3, len(yy)//10):]))
    if not np.isfinite(edge_step) or edge_step < 1e-12:
        edge_step = max(float(np.ptp(yy)), 1.0)
    chi_raw = (yy - bkg) / edge_step
    k = np.arange(max(kmin, float(kraw[0])), min(kmax, float(kraw[-1])) + kstep/2, kstep)
    chi = np.interp(k, kraw, chi_raw)
    return {"k": k, "chi": chi, "k_raw": kraw, "bkg": bkg, "e0": e0}


def ft_chi(k, chi, kmin=2.0, kmax=12.0, kweight=2, dk=1.0,
           window="hanning", nfft=2048):
    k = np.asarray(k, float); chi = np.asarray(chi, float)
    mask = np.isfinite(k) & np.isfinite(chi) & (k >= kmin) & (k <= kmax)
    kk, cc = k[mask], chi[mask]
    if len(kk) < 4:
        raise ValueError("Insufficient points in selected k range")
    step = float(np.median(np.diff(kk)))
    grid = np.arange(kmin, kmax + step/2, step)
    sig = np.interp(grid, kk, cc) * grid ** int(kweight)
    if window.lower() in {"hanning", "hann"}:
        win = np.hanning(len(grid))
    elif window.lower() == "kaiser":
        win = np.kaiser(len(grid), max(1.0, 3.0 * dk))
    else:
        win = np.ones(len(grid))
    transformed = np.fft.rfft(sig * win, n=nfft) * step / np.sqrt(np.pi)
    r = np.fft.rfftfreq(nfft, d=step) * np.pi
    return {"r": r, "real": transformed.real, "imag": transformed.imag,
            "magnitude": np.abs(transformed), "window": win, "k_grid": grid}
