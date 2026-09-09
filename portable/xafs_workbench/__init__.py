"""Local XAFS workbench combining Athena, Artemis and Hephaestus workflows."""

from pathlib import Path
import os
import sys


# Keep the scientific backend project-local so the launcher is reproducible even
# when a Conda environment disables user-level site-packages.
_vendor = Path(__file__).resolve().parent.parent / ".vendor"
if _vendor.is_dir() and str(_vendor) not in sys.path:
    sys.path.insert(0, str(_vendor))
    if os.name == "nt":
        for subdir in ("win32", "win32/lib", "pywin32_system32"):
            candidate = _vendor / subdir
            if candidate.is_dir() and str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
        dll_dir = _vendor / "pywin32_system32"
        if dll_dir.is_dir() and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(dll_dir))

__version__ = "0.1.0"
