from __future__ import annotations

from dataclasses import asdict, dataclass
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
from scipy.interpolate import LSQUnivariateSpline, interp1d
from scipy.signal import medfilt


K_ENERGY = 3.80998212


@dataclass
class ProcessConfig:
    e0: float | None = 11215.0
    auto_e0: bool = False
    pre1: float = -150.0
    pre2: float = -30.0
    norm1: float = 150.0
    norm2: float = 700.0
    rbkg: float = 1.0
    kmin: float = 3.0
    kmax: float = 12.0
    kweight: int = 2
    dk: float = 1.0
    window: str = "kaiser"
    energy_shift: float = 0.0
    energy_min: float | None = None
    energy_max: float | None = None
    exclude_ranges: str = ""
    deglitch_sigma: float = 0.0
    flatten: bool = True

    def validate(self) -> None:
        if self.pre1 >= self.pre2:
            raise ValueError("pre1 必须小于 pre2")
        if self.norm1 >= self.norm2:
            raise ValueError("norm1 必须小于 norm2")
        if self.kmin < 0 or self.kmin >= self.kmax:
            raise ValueError("k 范围无效")
        if self.rbkg <= 0:
            raise ValueError("Rbkg 必须大于 0")
        if self.kweight not in (0, 1, 2, 3):
            raise ValueError("k-weight 只能为 0、1、2 或 3")
        if self.energy_min is not None and self.energy_max is not None and self.energy_min >= self.energy_max:
            raise ValueError("能量截取下限必须小于上限")
        if self.deglitch_sigma < 0:
            raise ValueError("去毛刺阈值不能为负数")


@dataclass
class Spectrum:
    energy: np.ndarray
    mu: np.ndarray
    source_name: str
    signal_description: str


def _numeric_rows(text: str) -> tuple[list[str], np.ndarray]:
    header: list[str] = []
    rows: list[list[float]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        candidate = line.lstrip("#").strip()
        parts = candidate.replace(",", " ").split()
        try:
            values = [float(item) for item in parts]
        except ValueError:
            if not line.startswith("#") and any(token.lower().startswith("energy") for token in parts):
                header = parts
            continue
        if len(values) >= 2:
            rows.append(values)
    if not rows:
        raise ValueError("文件中没有找到至少两列的数值数据")
    lengths, counts = np.unique([len(row) for row in rows], return_counts=True)
    width = int(lengths[np.argmax(counts)])
    kept = [row for row in rows if len(row) == width]
    return header, np.asarray(kept, dtype=float)


def read_spectrum(
    content: bytes | str,
    source_name: str,
    signal_mode: str = "auto",
    energy_column: int = 0,
    signal_column: int = -1,
    i0_column: int = 1,
    it_if_column: int = 2,
) -> Spectrum:
    text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else content
    header, data = _numeric_rows(text)
    ncol = data.shape[1]

    def col(index: int) -> np.ndarray:
        resolved = index if index >= 0 else ncol + index
        if resolved < 0 or resolved >= ncol:
            raise ValueError(f"列号 {index} 超出文件的 {ncol} 列范围")
        return data[:, resolved].astype(float)

    energy = col(energy_column)
    mode = signal_mode.lower()
    header_text = " ".join(header).lower()
    if mode == "auto":
        if "count2/count0" in header_text or "mufluor" in header_text or "if/i0" in header_text:
            mode = "direct"
            signal_column = -1
        elif "ln(count0/count1)" in header_text or "mutrans" in header_text:
            mode = "direct"
            signal_column = -1
        else:
            mode = "direct"

    if mode == "transmission":
        i0, it = col(i0_column), col(it_if_column)
        valid = (i0 > 0) & (it > 0)
        if valid.sum() < 5:
            raise ValueError("透射通道存在零值或负值，无法计算 ln(I0/It)")
        mu = np.full_like(i0, np.nan)
        mu[valid] = np.log(i0[valid] / it[valid])
        description = f"transmission ln(col {i0_column}/col {it_if_column})"
    elif mode == "fluorescence":
        i0, iff = col(i0_column), col(it_if_column)
        valid = i0 != 0
        if valid.sum() < 5:
            raise ValueError("I0 通道为零，无法计算 If/I0")
        mu = np.full_like(i0, np.nan)
        mu[valid] = iff[valid] / i0[valid]
        description = f"fluorescence col {it_if_column}/col {i0_column}"
    elif mode == "direct":
        mu = col(signal_column)
        description = f"direct column {signal_column}"
    else:
        raise ValueError("signal_mode 必须为 auto/direct/transmission/fluorescence")

    finite = np.isfinite(energy) & np.isfinite(mu)
    energy, mu = energy[finite], mu[finite]
    order = np.argsort(energy)
    energy, mu = energy[order], mu[order]
    keep = np.r_[True, np.diff(energy) > 1e-9]
    if keep.sum() < 20:
        raise ValueError("有效且不重复的数据点少于 20 个")
    return Spectrum(energy[keep], mu[keep], source_name, description)


def read_spectrum_file(path: Path, **kwargs: Any) -> Spectrum:
    return read_spectrum(path.read_bytes(), path.name, **kwargs)


def _find_e0(energy: np.ndarray, mu: np.ndarray, nominal: float | None) -> float:
    mask = np.ones_like(energy, dtype=bool)
    if nominal is not None:
        mask = (energy >= nominal - 35.0) & (energy <= nominal + 45.0)
    if mask.sum() < 7:
        mask = np.ones_like(energy, dtype=bool)
    x, y = energy[mask], mu[mask]
    return float(x[int(np.nanargmax(np.gradient(y, x)))])


def _window(k: np.ndarray, kmin: float, kmax: float, dk: float, name: str) -> np.ndarray:
    out = np.zeros_like(k)
    middle = (k >= kmin + dk) & (k <= kmax - dk)
    left = (k >= kmin) & (k < kmin + dk)
    right = (k > kmax - dk) & (k <= kmax)
    out[middle] = 1.0
    if name.lower() in ("hanning", "hann"):
        out[left] = 0.5 * (1 - np.cos(np.pi * (k[left] - kmin) / dk))
        out[right] = 0.5 * (1 - np.cos(np.pi * (kmax - k[right]) / dk))
    else:
        out[left] = (k[left] - kmin) / dk
        out[right] = (kmax - k[right]) / dk
    return out


def _fallback_process(spec: Spectrum, cfg: ProcessConfig) -> dict[str, Any]:
    e, mu = spec.energy, spec.mu
    e0 = _find_e0(e, mu, cfg.e0) if cfg.auto_e0 or cfg.e0 is None else float(cfg.e0)
    pre_mask = (e >= e0 + cfg.pre1) & (e <= e0 + cfg.pre2)
    post_mask = (e >= e0 + cfg.norm1) & (e <= e0 + cfg.norm2)
    if pre_mask.sum() < 3 or post_mask.sum() < 5:
        raise ValueError("当前 pre-edge 或 normalization 范围内数据点不足")
    pre_coef = np.polyfit(e[pre_mask], mu[pre_mask], 1)
    post_order = 2 if post_mask.sum() >= 8 else 1
    post_coef = np.polyfit(e[post_mask], mu[post_mask], post_order)
    pre_curve = np.polyval(pre_coef, e)
    post_curve = np.polyval(post_coef, e)
    edge_step = float(np.polyval(post_coef, e0) - np.polyval(pre_coef, e0))
    if abs(edge_step) < 1e-12:
        raise ValueError("计算得到的 edge step 接近 0")
    norm = (mu - pre_curve) / edge_step
    flat = (mu - pre_curve) / np.where(abs(post_curve - pre_curve) > 1e-12, post_curve - pre_curve, np.nan)

    raw_k = np.sqrt(np.maximum((e - e0) / K_ENERGY, 0.0))
    valid = (raw_k >= 1.0) & np.isfinite(flat)
    k0, y0 = raw_k[valid], flat[valid]
    keep = np.r_[True, np.diff(k0) > 1e-7]
    k0, y0 = k0[keep], y0[keep]
    knots = np.arange(2.5, min(float(k0.max()) - 1.0, 13.5), 1.5)
    if len(knots) >= 2:
        bkg = LSQUnivariateSpline(k0, y0, knots, k=3)(k0)
    else:
        bkg = np.polyval(np.polyfit(k0, y0, min(3, len(k0) - 1)), k0)
    chi0 = y0 - bkg
    kmax_used = min(cfg.kmax, float(k0.max()))
    k = np.arange(0.0, max(kmax_used, 0.05) + 0.025, 0.05)
    chi = interp1d(k0, chi0, bounds_error=False, fill_value=0.0)(k)
    kwin = _window(k, cfg.kmin, kmax_used, cfg.dk, cfg.window)
    weighted = chi * np.power(k, cfg.kweight) * kwin
    r = np.arange(0.0, 6.005, 0.01)
    ft = np.asarray([np.sum(weighted * np.exp(2j * k * rv)) * 0.05 for rv in r])
    return {
        "backend": "scipy-fallback",
        "e0": e0,
        "edge_step": edge_step,
        "energy": e,
        "mu": mu,
        "norm": norm,
        "flat": flat,
        "pre_edge": pre_curve,
        "post_edge": post_curve,
        "k": k,
        "chi": chi,
        "kwin": kwin,
        "r": r,
        "chir_mag": np.abs(ft),
        "chir_re": ft.real,
        "chir_im": ft.imag,
        "kmax_used": kmax_used,
    }


def _larch_process(spec: Spectrum, cfg: ProcessConfig) -> dict[str, Any]:
    from larch import Group
    from larch.xafs import autobk, find_e0, pre_edge, xftf

    group = Group(energy=spec.energy.copy(), mu=spec.mu.copy(), filename=spec.source_name)
    e0 = float(find_e0(group.energy, group.mu)) if cfg.auto_e0 or cfg.e0 is None else float(cfg.e0)
    pre_edge(group, e0=e0, pre1=cfg.pre1, pre2=cfg.pre2, norm1=cfg.norm1, norm2=cfg.norm2)
    autobk(group, e0=e0, edge_step=group.edge_step, rbkg=cfg.rbkg, kmin=0, kmax=cfg.kmax, kweight=cfg.kweight)
    kmax_used = min(cfg.kmax, float(np.max(group.k)))
    xftf(group, kmin=cfg.kmin, kmax=kmax_used, dk=cfg.dk, kweight=cfg.kweight, window=cfg.window)
    return {
        "backend": "xraylarch",
        "larch_group": group,
        "e0": e0,
        "edge_step": float(group.edge_step),
        "energy": np.asarray(group.energy),
        "mu": np.asarray(group.mu),
        "norm": np.asarray(group.norm),
        "flat": np.asarray(group.flat),
        "pre_edge": np.asarray(group.pre_edge),
        "post_edge": np.asarray(group.post_edge),
        "k": np.asarray(group.k),
        "chi": np.asarray(group.chi),
        "kwin": np.asarray(group.kwin),
        "r": np.asarray(group.r),
        "chir_mag": np.asarray(group.chir_mag),
        "chir_re": np.asarray(group.chir_re),
        "chir_im": np.asarray(group.chir_im),
        "kmax_used": kmax_used,
    }


def larch_available() -> bool:
    try:
        import larch.xafs  # noqa: F401
        return True
    except Exception:
        return False


def _clean_spectrum(spec: Spectrum, cfg: ProcessConfig) -> tuple[Spectrum, np.ndarray]:
    energy = spec.energy.astype(float) + cfg.energy_shift
    mu = spec.mu.astype(float).copy()
    keep = np.ones(len(energy), dtype=bool)
    if cfg.energy_min is not None:
        keep &= energy >= cfg.energy_min
    if cfg.energy_max is not None:
        keep &= energy <= cfg.energy_max
    for item in cfg.exclude_ranges.replace("；", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            left, right = [float(value.strip()) for value in item.split("-", 1)]
        except Exception as exc:
            raise ValueError(f"无法解析排除区间“{item}”，请使用 11230-11232 格式") from exc
        if left > right:
            left, right = right, left
        keep &= ~((energy >= left) & (energy <= right))

    if cfg.deglitch_sigma > 0 and keep.sum() >= 9:
        baseline = medfilt(mu, kernel_size=5)
        residual = mu - baseline
        center = float(np.median(residual[keep]))
        mad = float(np.median(np.abs(residual[keep] - center)))
        robust_sigma = 1.4826 * mad
        if robust_sigma > 0:
            keep &= np.abs(residual - center) <= cfg.deglitch_sigma * robust_sigma
    removed = energy[~keep]
    if keep.sum() < 20:
        raise ValueError("清洗后有效数据点少于 20 个，请放宽截取或去毛刺条件")
    cleaned = Spectrum(energy[keep], mu[keep], spec.source_name, spec.signal_description)
    return cleaned, removed


def process_spectrum(spec: Spectrum, cfg: ProcessConfig, prefer_larch: bool = False) -> dict[str, Any]:
    cfg.validate()
    spec, removed = _clean_spectrum(spec, cfg)
    if prefer_larch and larch_available():
        result = _larch_process(spec, cfg)
    else:
        result = _fallback_process(spec, cfg)
    result["removed_energy"] = removed
    result["removed_points"] = int(len(removed))
    result["energy_shift"] = cfg.energy_shift
    energy = np.asarray(result["energy"], dtype=float)
    norm = np.asarray(result["norm"], dtype=float)
    display_norm = np.asarray(result["flat"] if cfg.flatten else result["norm"], dtype=float)
    result["display_norm"] = display_norm
    result["normalization_mode"] = "Athena flattened" if cfg.flatten else "normalized"
    result["dmude"] = np.gradient(display_norm, energy)
    white_mask = (energy >= result["e0"] - 5.0) & (energy <= result["e0"] + 40.0)
    if white_mask.any():
        indices = np.flatnonzero(white_mask)
        peak_index = int(indices[np.nanargmax(display_norm[white_mask])])
        result["white_line_energy"] = float(energy[peak_index])
        result["white_line_height"] = float(display_norm[peak_index])
    else:
        result["white_line_energy"] = float("nan")
        result["white_line_height"] = float("nan")
    return result


def serializable_result(result: dict[str, Any], max_points: int = 1400) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in result.items():
        if key == "larch_group":
            continue
        if isinstance(value, np.ndarray):
            step = max(1, int(np.ceil(len(value) / max_points)))
            output[key] = np.nan_to_num(value[::step], nan=0.0, posinf=0.0, neginf=0.0).tolist()
        elif isinstance(value, np.generic):
            output[key] = value.item()
        else:
            output[key] = value
    return output


def config_from_mapping(values: dict[str, Any]) -> ProcessConfig:
    defaults = asdict(ProcessConfig())
    converted: dict[str, Any] = {}
    for key, default in defaults.items():
        raw = values.get(key, default)
        if isinstance(default, bool):
            converted[key] = str(raw).lower() in ("1", "true", "yes", "on")
        elif isinstance(default, int):
            converted[key] = int(raw)
        elif isinstance(default, float) or default is None:
            converted[key] = None if raw in (None, "", "null") else float(raw)
        else:
            converted[key] = str(raw)
    return ProcessConfig(**converted)
