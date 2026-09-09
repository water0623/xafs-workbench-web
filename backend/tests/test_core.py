import numpy as np

from xafs_core.processing import find_e0, normalize, ft_chi
from xafs_core.lcf import linear_combination_fit
from xafs_core.fit import fit_exafs
from xafs_core.feff import parse_feff_path
from xafs_core.io import parse_ascii_xafs, merge_spectra


def test_ascii_transmission():
    text = "# E I0 It\n1 100 50\n2 100 25\n3 100 20\n"
    out = parse_ascii_xafs(text, energy_col=0, i0_col=1, it_col=2, mode="transmission")
    assert np.allclose(out["mu"], np.log([2, 4, 5]))


def test_merge_spectra():
    s1 = {"energy": [0, 1, 2], "mu": [0, 1, 2]}
    s2 = {"energy": [0, 1, 2], "mu": [0, 2, 4]}
    out = merge_spectra([s1, s2], grid=np.array([0.0, 1.0, 2.0]))
    assert np.allclose(out["mu"], [0, 1.5, 3])


def test_lcf_recovers_mixture():
    e = np.linspace(0, 10, 101)
    a = np.exp(-0.5 * ((e - 3) / 0.7) ** 2)
    b = np.exp(-0.5 * ((e - 7) / 0.9) ** 2)
    y = 0.3 * a + 0.7 * b
    out = linear_combination_fit(e, y, {"a": a, "b": b})
    assert abs(out["weights"]["a"] - 0.3) < 1e-3
    assert abs(out["weights"]["b"] - 0.7) < 1e-3


def test_feff_parser_common_table():
    txt = """# reff=2.50 degeneracy=4\n# k 2phc mag phase red lambda p\n0.5 0 2.0 0.1 0.9 8.0 0\n1.0 0 2.1 0.2 0.9 7.5 0\n"""
    out = parse_feff_path(txt)
    assert np.allclose(out["k"], [0.5, 1.0])
    assert out["reff"] == 2.5
    assert out["degeneracy"] == 4


def test_fit_exafs_returns_diagnostics():
    k = np.linspace(2, 12, 250)
    path = {
        "k": k.tolist(), "amplitude": np.ones_like(k).tolist(),
        "phase": np.zeros_like(k).tolist(), "lambda": (np.ones_like(k)*20).tolist(),
        "reduction": np.ones_like(k).tolist(), "reff": 2.0, "degeneracy": 4.0,
    }
    true_pars = {"S02": 0.9, "CN": 4.0, "dR": 0.03, "sigma2": 0.004, "DeltaE0": 1.0}
    from xafs_core.fit import _path_model
    y = _path_model(k, path, true_pars)
    pars = [
        {"name": "S02", "value": 0.8, "min": 0.2, "max": 1.2},
        {"name": "CN", "value": 4.0, "vary": False},
        {"name": "dR", "value": 0.0, "min": -0.2, "max": 0.2},
        {"name": "sigma2", "value": 0.005, "min": 0.0, "max": 0.03},
        {"name": "DeltaE0", "value": 0.0, "min": -10.0, "max": 10.0},
    ]
    out = fit_exafs(k, y, [path], pars, 2, 12, 2)
    assert out["success"]
    assert out["r_factor"] < 1e-5
    assert "correlation" in out
