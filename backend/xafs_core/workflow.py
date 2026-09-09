"""Complete Athena/Artemis style XAFS workflow.

Pipeline:
raw data -> calibration -> normalization -> chi(k) -> fitting dataset.
"""
import numpy as np
from .processing import find_e0, normalize, energy_to_k, ft_chi


def process_xafs_spectrum(energy, mu, reference_e0=None, shift=0.0,
                          pre1=-150, pre2=-30,
                          norm1=150, norm2=None,
                          kweight=2, kmax=12):
    energy = np.asarray(energy, float) + float(shift)
    mu = np.asarray(mu, float)

    e0_raw = find_e0(energy, mu)
    e0 = float(reference_e0) if reference_e0 is not None else e0_raw

    norm = normalize(
        energy,
        mu,
        e0=e0,
        pre1=pre1,
        pre2=pre2,
        norm1=norm1,
        norm2=norm2
    )

    k = energy_to_k(norm['energy'], e0)
    mask = (k > 0) & (k <= kmax)
    chi = norm['flat'][mask]
    kk = k[mask]

    chi_weighted = chi * kk ** int(kweight)

    ft = ft_chi(
        kk,
        chi,
        kmax=kmax,
        kweight=kweight
    )

    return {
        'e0': e0,
        'energy': norm['energy'],
        'normalized_mu': norm['norm'],
        'flattened_mu': norm['flat'],
        'k': kk,
        'chi': chi,
        'chi_weighted': chi_weighted,
        'ft': ft,
        'fit_ready': {
            'k': kk,
            'chi': chi,
            'kweight': kweight,
            'kmin': float(kk.min()),
            'kmax': float(kk.max())
        }
    }
