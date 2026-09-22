from __future__ import annotations

from typing import Any

import numpy as np
from scipy.signal import medfilt

from .core import Spectrum


def _robust_sigma(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        return 0.0
    center = float(np.median(values))
    return float(1.4826 * np.median(np.abs(values - center)))


def _estimate_e0(energy: np.ndarray, mu: np.ndarray, hint: float | None) -> float:
    mask = np.ones(len(energy), dtype=bool)
    if hint is not None and energy[0] <= hint <= energy[-1]:
        mask = (energy >= hint - 35.0) & (energy <= hint + 45.0)
    if mask.sum() < 7:
        mask[:] = True
    indices = np.flatnonzero(mask)
    gradient = np.gradient(mu[mask], energy[mask])
    return float(energy[int(indices[int(np.nanargmax(gradient))])])


def diagnose_spectrum(
    spec: Spectrum,
    *,
    e0_hint: float | None = None,
    pre2: float = -30.0,
    norm1: float = 150.0,
) -> dict[str, Any]:
    """Diagnose acquisition quality without optimizing preprocessing against fit quality."""
    energy = np.asarray(spec.energy, dtype=float)
    mu = np.asarray(spec.mu, dtype=float)
    if len(energy) < 20:
        raise ValueError("数据质量诊断至少需要 20 个有效点")

    e0 = _estimate_e0(energy, mu, e0_hint)
    pre_indices = np.flatnonzero(energy <= e0 + pre2)
    post_points = int(np.sum(energy >= e0 + norm1))
    evidence: list[str] = []
    warnings: list[str] = []
    audit = dict(spec.audit)

    for key, label in (
        ("nonfinite_rows_removed", "非有限数值行"),
        ("invalid_signal_rows", "无效探测器计数行"),
        ("nonmonotonic_energy_steps", "能量倒序步"),
        ("duplicate_energy_points_removed", "重复能量点"),
    ):
        count = int(audit.get(key, 0) or 0)
        if count:
            evidence.append(f"发现 {count} 个{label}；导入时已记录并清理。")

    decision = "none"
    cutoff: float | None = None
    local_anomalies: list[float] = []
    abnormal_mask = np.zeros(len(energy), dtype=bool)

    if len(pre_indices) < 8:
        decision = "unusable"
        warnings.append("有效预边点少于 8 个，无法可靠判定前段稳定性或完成定量归一化。")
    else:
        ref_count = max(8, min(len(pre_indices) // 2, 40))
        ref_indices = pre_indices[-ref_count:]
        degree = 1 if len(ref_indices) >= 3 else 0
        coef = np.polyfit(energy[ref_indices], mu[ref_indices], degree)
        residual = mu - np.polyval(coef, energy)
        reference_sigma = _robust_sigma(residual[ref_indices])
        pre_range = float(np.ptp(mu[pre_indices]))
        scale = max(reference_sigma, pre_range * 0.01, np.finfo(float).eps)
        pre_abnormal = np.abs(residual[pre_indices] - np.median(residual[ref_indices])) > 6.0 * scale

        pre_steps = np.diff(mu[pre_indices])
        step_center = float(np.median(pre_steps))
        step_sigma = _robust_sigma(pre_steps)
        step_threshold = max(8.0 * step_sigma, pre_range * 0.15, np.finfo(float).eps)
        step_positions = np.flatnonzero(np.abs(pre_steps - step_center) > step_threshold)

        kernel = 5 if len(mu) >= 5 else 3
        local_residual = mu - medfilt(mu, kernel_size=kernel)
        local_sigma = _robust_sigma(local_residual[pre_indices])
        local_threshold = max(8.0 * local_sigma, pre_range * 0.025, np.finfo(float).eps)
        spike_mask = np.abs(local_residual) > local_threshold
        spike_mask[:2] = False
        spike_mask[-2:] = False
        abnormal_mask[pre_indices] = pre_abnormal

        stable_run = max(5, min(12, len(pre_indices) // 5))
        first_stable: int | None = None
        if len(step_positions) == 1:
            offset = int(step_positions[0] + 1)
            if offset >= 3 and len(pre_indices) - offset >= 5:
                first_stable = int(pre_indices[offset])
                evidence.append(
                    f"预边中检测到单一显著基线断点 {energy[first_stable]:.6g} eV；断点前后均有足够连续采集点。"
                )
        if first_stable is None:
            for offset in range(1, max(1, len(pre_indices) - stable_run + 1)):
                before = pre_abnormal[:offset]
                run = pre_abnormal[offset : offset + stable_run]
                if before.size and before.mean() >= 0.5 and not run.any():
                    first_stable = int(pre_indices[offset])
                    break

        if first_stable is not None:
            remaining_pre = pre_indices[pre_indices >= first_stable]
            remaining_span = float(energy[remaining_pre[-1]] - energy[remaining_pre[0]]) if len(remaining_pre) else 0.0
            if len(remaining_pre) >= 5 and remaining_span > 0:
                decision = "leading_truncation"
                cutoff = float(energy[first_stable])
                evidence.append(
                    f"扫描前段相对后续预边基线连续异常；从实际采集点 {cutoff:.6g} eV 起出现稳定区。"
                )
            else:
                decision = "unusable"
                warnings.append("去除异常前段后不足以支撑预边拟合；建议改用其他扫描或重新测量。")

        internal = np.flatnonzero(
            spike_mask
            & (energy <= e0 + pre2)
            & (np.arange(len(energy)) >= max(first_stable or 0, 1))
        )
        if first_stable is not None:
            internal = internal[np.abs(internal - first_stable) > 1]
        if len(internal):
            local_anomalies = [float(value) for value in energy[internal[:30]]]
            if decision == "none":
                decision = "local_mask"
            evidence.append(f"检测到 {len(internal)} 个孤立异常候选点；应逐点复核，不应改用前段整体截断。")

    retained_mask = np.ones(len(energy), dtype=bool) if cutoff is None else energy >= cutoff
    retained_pre = np.flatnonzero(retained_mask & (energy <= e0 + pre2))
    retained_pre_span = (
        float(energy[retained_pre[-1]] - energy[retained_pre[0]]) if len(retained_pre) >= 2 else 0.0
    )
    if post_points < 5:
        warnings.append("设定的归一化起点之后少于 5 个点，边后归一化范围可能不足。")

    if decision == "leading_truncation" and cutoff is not None:
        action = f"建议保留 E >= {cutoff:.6g} eV；应用前请结合原始计数通道确认。"
    else:
        action = {
            "none": "保留完整能量范围；不要人为设置截断值。",
            "local_mask": "保留完整前段，对列出的孤立点结合重复扫描或日志进行局部屏蔽。",
            "unusable": "不要进行定量拟合；优先选择其他扫描或重新测量。",
        }[decision]

    return {
        "source_name": spec.source_name,
        "signal_description": spec.signal_description,
        "decision": decision,
        "recommended_energy_min_eV": cutoff,
        "retain_rule": None if cutoff is None else f"E >= {cutoff:.6g} eV",
        "action": action,
        "evidence": evidence,
        "warnings": warnings,
        "local_anomaly_candidates_eV": local_anomalies,
        "metrics": {
            "estimated_e0_eV": e0,
            "original_energy_min_eV": float(energy[0]),
            "original_energy_max_eV": float(energy[-1]),
            "original_points": int(len(energy)),
            "retained_energy_min_eV": float(energy[retained_mask][0]),
            "retained_energy_max_eV": float(energy[retained_mask][-1]),
            "retained_points": int(retained_mask.sum()),
            "pre_edge_points_remaining": int(len(retained_pre)),
            "pre_edge_span_remaining_eV": retained_pre_span,
            "post_normalization_points": post_points,
        },
        "import_audit": audit,
        "plot": {
            "energy_eV": energy.tolist(),
            "mu": mu.tolist(),
            "leading_abnormal_energy_eV": energy[abnormal_mask].tolist(),
        },
        "policy": "11115 eV 仅属于此前诊断的 Ir 个案；本结果完全由当前数据确定。",
    }
