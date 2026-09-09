"""FEFF interface layer placeholder.

Provides a clean API boundary for future FEFF executable/cloud integration.
"""


def generate_feff_input(cif_text, absorber="Cu", edge="K"):
    return f"""TITLE XAFS Workbench generated input
EDGE {edge}
COREHOLE RPA
* Absorber: {absorber}
* CIF parsing will be connected here
"""


def parse_feff_path(text):
    """Parse future FEFF path output into fitting-ready dictionaries."""
    return []
