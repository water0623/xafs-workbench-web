"""FEFF interoperability helpers.

This module does not bundle FEFF. It generates a minimal FEFF input skeleton
and parses common feffNNNN.dat columns so external/local FEFF runs can feed the
Artemis-style fitting engine.
"""
from __future__ import annotations

import re
from typing import Dict, List
import numpy as np


def generate_feff_input(cluster_atoms, absorber_index=0, edge="K", title="XAFS Workbench"):
    """Generate a FEFF input file from an explicit atom cluster.

    cluster_atoms: iterable of {symbol, x, y, z, potential?}. The absorber is
    marked as potential 0; remaining potentials are assigned deterministically
    by chemical symbol unless explicitly supplied.
    """
    atoms = list(cluster_atoms)
    if not atoms:
        raise ValueError("cluster_atoms cannot be empty")
    if absorber_index < 0 or absorber_index >= len(atoms):
        raise ValueError("absorber_index is outside the atom list")

    absorber_symbol = str(atoms[absorber_index]["symbol"])
    symbol_to_ipot = {absorber_symbol: 0}
    next_ipot = 1
    for i, atom in enumerate(atoms):
        if i == absorber_index:
            continue
        symbol = str(atom["symbol"])
        if symbol not in symbol_to_ipot:
            symbol_to_ipot[symbol] = next_ipot
            next_ipot += 1

    potentials = ["POTENTIALS", "* ipot  Z  tag"]
    try:
        from xraydb import atomic_number
        z_lookup = lambda s: int(atomic_number(s))
    except Exception:
        z_lookup = lambda s: 0
    for symbol, ipot in sorted(symbol_to_ipot.items(), key=lambda x: x[1]):
        potentials.append(f"  {ipot:3d} {z_lookup(symbol):3d} {symbol}")

    ax = float(atoms[absorber_index]["x"])
    ay = float(atoms[absorber_index]["y"])
    az = float(atoms[absorber_index]["z"])
    atom_lines = ["ATOMS", "* x y z ipot tag distance"]
    enriched = []
    for i, atom in enumerate(atoms):
        dx = float(atom["x"]) - ax
        dy = float(atom["y"]) - ay
        dz = float(atom["z"]) - az
        r = float(np.sqrt(dx*dx + dy*dy + dz*dz))
        ipot = 0 if i == absorber_index else int(atom.get("potential", symbol_to_ipot[str(atom["symbol"])]))
        enriched.append((r, dx, dy, dz, ipot, str(atom["symbol"])))
    for r, dx, dy, dz, ipot, symbol in sorted(enriched, key=lambda v: v[0]):
        atom_lines.append(f" {dx:11.6f} {dy:11.6f} {dz:11.6f} {ipot:3d} {symbol:>3s} {r:10.6f}")

    return "\n".join([
        f"TITLE {title}",
        f"EDGE {edge}",
        "S02 1.0",
        "CONTROL 1 1 1 1 1 1",
        "PRINT 1 0 0 0 0 3",
        *potentials,
        *atom_lines,
        "END",
        "",
    ])


def parse_feff_path(text: str) -> Dict:
    """Parse the numerical table from a common FEFF feffNNNN.dat file.

    Expected columns are k, real[2*phc], mag[feff], phase[feff], red factor,
    lambda, real[p]. Header metadata such as reff and degeneracy are extracted
    when present. Unknown header variants are tolerated.
    """
    lines = text.splitlines()
    reff = None
    degeneracy = None
    for line in lines:
        low = line.lower()
        m = re.search(r"reff\s*[=:]?\s*([-+0-9.eE]+)", low)
        if m:
            try: reff = float(m.group(1))
            except ValueError: pass
        m = re.search(r"degeneracy\s*[=:]?\s*([-+0-9.eE]+)", low)
        if m:
            try: degeneracy = float(m.group(1))
            except ValueError: pass

    rows: List[List[float]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "*")):
            continue
        parts = stripped.replace("D", "E").split()
        try:
            nums = [float(v) for v in parts]
        except ValueError:
            continue
        if len(nums) >= 6 and nums[0] >= 0:
            rows.append(nums)
    if len(rows) < 2:
        raise ValueError("No FEFF numerical path table was found")

    arr = np.asarray(rows, float)
    k = arr[:, 0]
    # Common FEFF8/9 feffNNNN.dat convention:
    # k, real[2*phc], mag[feff], phase[feff], red factor, lambda, real[p]
    amplitude = arr[:, 2] if arr.shape[1] > 2 else np.ones_like(k)
    phase = arr[:, 3] if arr.shape[1] > 3 else np.zeros_like(k)
    reduction = arr[:, 4] if arr.shape[1] > 4 else np.ones_like(k)
    lam = arr[:, 5] if arr.shape[1] > 5 else np.full_like(k, np.inf)
    return {
        "k": k,
        "amplitude": amplitude,
        "phase": phase,
        "reduction": reduction,
        "lambda": lam,
        "reff": float(reff) if reff is not None else 2.0,
        "degeneracy": float(degeneracy) if degeneracy is not None else 1.0,
    }
