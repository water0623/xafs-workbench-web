"""Generate FEFF paths with the FEFF executable distributed with Demeter.

Larch is intentionally not used here. It is neither required by Demeter nor
included in the standalone application.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from .demeter_backend import _demeter_base, _runtime


def _path_summary(path: Path) -> tuple[int, float, float]:
    """Read nleg, degeneracy and Reff from a native ``feffNNNN.dat`` file."""
    armed = False
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if line.startswith("-------"):
            armed = True
            continue
        if not armed or not line:
            continue
        values = line.split()
        try:
            nleg, degeneracy, reff = int(values[0]), float(values[1]), float(values[2])
        except (ValueError, IndexError):
            continue
        if nleg > 0 and degeneracy > 0 and reff > 0:
            return nleg, degeneracy, reff
    raise ValueError(f"Cannot read native FEFF path parameters from {path.name}")


def _file_ranks(path: Path) -> dict[str, float]:
    ranks: dict[str, float] = {}
    if not path.is_file():
        return ranks
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"\s*(feff\d+\.dat)\s+\S+\s+(\S+)", line, re.IGNORECASE)
        if match:
            try:
                ranks[match.group(1).lower()] = float(match.group(2))
            except ValueError:
                continue
    return ranks


def _native_feff_executable() -> Path:
    base = _demeter_base()
    for name in ("feff6.exe", "feff6l.exe", "feff8.exe", "feff8l.exe"):
        candidate = base / "c" / "bin" / name
        if candidate.is_file():
            return candidate
    raise RuntimeError("Demeter installation has no FEFF6/FEFF8 executable")


def _path_rows(generated: list[Path], ranks: dict[str, float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in generated:
        nleg, degen, reff = _path_summary(path)
        match = re.search(r"(\d+)", path.stem)
        index = int(match.group(1)) if match else len(rows) + 1
        kind = "single scattering" if nleg == 2 else "multiple scattering"
        rows.append({
            "name": path.name, "index": index, "degen": degen, "reff": reff,
            "rank": ranks.get(path.name.lower()), "nleg": nleg, "type": kind,
            "scattering_path": path.stem,
            "label": f"{path.stem} ({kind}, Reff={reff:.3f} A)",
            "feff_degeneracy": degen, "cn": degen, "cn_min": 0.0,
            "cn_max": max(degen * 1.5, degen + 2.0),
            "sigma2": 0.003 if reff <= 2.3 else (0.005 if reff <= 3.3 else 0.007),
            "sigma2_min": 0.0, "sigma2_max": 0.02,
            "deltar": 0.0, "deltar_min": -0.12, "deltar_max": 0.12,
            "vary_cn": True, "vary_sigma2": True, "vary_deltar": True,
        })
    ordered_reff = sorted({round(float(item["reff"]), 3) for item in rows})
    shell_by_reff: dict[float, int] = {}
    shell, previous = 0, None
    for reff in ordered_reff:
        if previous is None or reff - previous > 0.45:
            shell += 1
        shell_by_reff[reff] = shell
        previous = reff
    for item in rows:
        item["shell"] = shell_by_reff[round(float(item["reff"]), 3)]
    return rows


def generate_native_feff(cif_text: str, absorber: str, edge: str, radius: float) -> dict[str, Any]:
    """Build FEFF input from CIF, run native FEFF, and return selectable paths."""
    try:
        from pymatgen.core import Structure
        from pymatgen.io.feff.sets import MPEXAFSSet
    except ImportError as exc:
        raise RuntimeError("Missing pymatgen CIF parser; install the current XAFS Workbench release") from exc
    structure = Structure.from_str(cif_text, fmt="cif")
    if not any(site.specie.symbol == absorber for site in structure):
        raise ValueError(f"CIF has no absorber atom {absorber}")
    feff = _native_feff_executable()
    base = _demeter_base()
    _, env = _runtime(base)
    with tempfile.TemporaryDirectory(prefix="xafs_cif_feff_") as folder_text:
        folder = Path(folder_text)
        MPEXAFSSet(absorber, structure, edge=edge, radius=radius, user_tag_settings={
            "RPATH": radius, "NLEG": 4, "CRITERIA": "4.0 2.5", "PRINT": "1 0 0 0 0 3",
            "S02": 1.0, "SCF": f"{min(4.0, radius):.1f} 0 20 .2 1",
        }).write_input(folder)
        feff_input = folder / "feff.inp"
        # Older FEFF6 builds shipped with Demeter reject pymatgen's COREHOLE FSR form.
        lines = [line for line in feff_input.read_text(encoding="utf-8").splitlines() if not line.strip().upper().startswith("COREHOLE")]
        feff_input.write_text("\n".join(lines) + "\n", encoding="utf-8")
        completed = subprocess.run([str(feff)], cwd=folder, env=env, capture_output=True,
            text=True, errors="replace", timeout=180, check=False)
        log = f"===== native Demeter FEFF ({feff.name}) =====\n{completed.stdout}\n{completed.stderr}"
        if completed.returncode != 0:
            raise RuntimeError(f"Native FEFF failed: {(completed.stderr or completed.stdout).strip()[-1200:]}")
        generated = sorted(folder.glob("feff*.dat"))
        if not generated:
            files = ", ".join(sorted(path.name for path in folder.iterdir()))
            raise RuntimeError(f"Native FEFF produced no paths. Files: {files}. Log: {log[-1200:]}")
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in ("feff.inp", "paths.dat", "files.dat", "list.dat"):
                path = folder / name
                if path.exists():
                    zf.write(path, path.name)
            zf.writestr("feff_run.log", log)
            for path in generated:
                zf.write(path, path.name)
        return {"archive": archive.getvalue(), "paths": _path_rows(generated, _file_ranks(folder / "files.dat")),
                "path_files": {path.name: path.read_bytes() for path in generated}}
