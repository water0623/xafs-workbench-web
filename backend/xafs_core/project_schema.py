"""Project metadata model for reproducible XAFS analysis."""
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class XAFSProject:
    sample: str
    element: str
    edge: str
    beamline: str = ""
    mode: str = "Transmission"
    metadata: Dict[str, str] = field(default_factory=dict)
    processing: Dict[str, float] = field(default_factory=dict)
    files: List[str] = field(default_factory=list)

    def export(self):
        return {
            "sample": self.sample,
            "element": self.element,
            "edge": self.edge,
            "beamline": self.beamline,
            "mode": self.mode,
            "metadata": self.metadata,
            "processing": self.processing,
            "files": self.files
        }
