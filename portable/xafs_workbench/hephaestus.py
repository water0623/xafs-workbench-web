from __future__ import annotations

from typing import Any


# Offline fallback for the absorption edges most relevant to this project.
FALLBACK_EDGES = {
    "Fe": {"K": 7112.0, "L3": 706.8},
    "Co": {"K": 7709.0, "L3": 778.1},
    "Ni": {"K": 8333.0, "L3": 852.7},
    "Cu": {"K": 8979.0, "L3": 932.7},
    "Ru": {"K": 22117.0, "L3": 2838.0},
    "Ir": {"K": 76111.0, "L3": 11215.0, "L2": 12824.0, "L1": 13419.0},
    "Pt": {"K": 78395.0, "L3": 11564.0, "L2": 13273.0, "L1": 13880.0},
}


def edge_lookup(symbol: str) -> dict[str, Any]:
    normalized = symbol.strip().capitalize()
    try:
        import xraydb

        edges = xraydb.xray_edges(normalized)
        return {
            "element": normalized,
            "backend": "xraydb",
            "edges": [
                {"edge": name, "energy_eV": float(item.energy), "fyield": float(item.fyield), "jump_ratio": float(item.jump_ratio)}
                for name, item in edges.items()
            ],
        }
    except Exception:
        if normalized not in FALLBACK_EDGES:
            raise ValueError("离线表暂不包含该元素；安装 xraylarch/xraydb 后可查询完整元素数据库")
        return {
            "element": normalized,
            "backend": "offline-reference",
            "edges": [{"edge": edge, "energy_eV": energy} for edge, energy in FALLBACK_EDGES[normalized].items()],
        }
