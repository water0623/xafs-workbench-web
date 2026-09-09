"""Continuous wavelet transform tools for EXAFS analysis."""
import numpy as np
from scipy import signal


def exafs_wavelet(k, chi, widths=None):
    k = np.asarray(k, float)
    chi = np.asarray(chi, float)
    if widths is None:
        widths = np.arange(1, 80)
    data = chi * k*k
    wt = signal.cwt(data, signal.ricker, widths)
    return {"k": k.tolist(), "scale": widths.tolist(), "intensity": np.abs(wt).tolist()}
