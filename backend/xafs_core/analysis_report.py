"""Generate structured XAFS analysis summaries."""


def build_report(project, calibration, processed, fit=None):
    return {
        "project": project.export() if hasattr(project, "export") else project,
        "calibration": calibration,
        "processing": {
            "e0": processed.get("e0"),
            "k_range": [float(processed["k"][0]), float(processed["k"][-1])] if "k" in processed else None
        },
        "fit": fit or {}
    }
