"""Reference foil calibration utilities for XAFS workflows."""
import numpy as np
from .processing import find_e0


def calculate_e0_shift(sample_energy, sample_mu, ref_energy, ref_mu):
    """Calculate energy correction using a reference spectrum.

    The correction follows common Athena practice:
    shift = E0(reference)-E0(sample)
    """
    sample_e0 = find_e0(sample_energy, sample_mu)
    ref_e0 = find_e0(ref_energy, ref_mu)
    shift = float(ref_e0 - sample_e0)
    corrected = np.asarray(sample_energy, dtype=float) + shift
    return {
        "sample_e0": sample_e0,
        "reference_e0": ref_e0,
        "shift": shift,
        "corrected_energy": corrected
    }


def merge_scans(scans):
    """Average multiple scans on a common energy grid."""
    if not scans:
        raise ValueError("No scans provided")
    grid = np.asarray(scans[0][0], float)
    values = []
    for energy, mu in scans:
        values.append(np.interp(grid, energy, mu))
    return grid, np.mean(values, axis=0), np.std(values, axis=0)
