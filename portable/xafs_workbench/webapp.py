from __future__ import annotations

import json
import csv
import os
import re
import subprocess
import tempfile
import zipfile
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from dataclasses import asdict, replace
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file

from .artemis import intelligent_fit_feff_paths
from .analysis import linear_combination_fit
from .core import config_from_mapping, read_spectrum, read_spectrum_file, serializable_result
from .demeter_backend import demeter_available, process_spectrum_demeter
from .hephaestus import edge_lookup
from .native_tools import discover_native_tools, launch_native_tool
from .runtime_paths import resource_path, user_data_root


BUNDLED_DATA_DIR = resource_path("raw_data", "gjw")
USER_DATA_DIR = user_data_root() / "datasets"
FIT_RESULT_DIR = user_data_root() / "fit-results"
DATA_DIR = BUNDLED_DATA_DIR
STANDARD_LIBRARY = {
    "Ir-foil": {"element": "Ir", "edge": "L3", "e0_eV": 11215.0, "label": "Ir foil 标准样"},
}
FIT_RESULTS: OrderedDict[str, dict[str, Any]] = OrderedDict()
FIT_RESULTS_LOCK = threading.Lock()
MAX_SAVED_FITS = 12
FEFF_RESULTS: OrderedDict[str, dict[str, Any]] = OrderedDict()
FEFF_RESULTS_LOCK = threading.Lock()
MAX_SAVED_FEFF = 8


def _fit_result_path(result_id: str) -> Path:
    safe_id = re.sub(r"[^a-f0-9]", "", result_id.lower())
    if len(safe_id) != 32:
        raise ValueError("无效的拟合结果编号")
    return FIT_RESULT_DIR / f"{safe_id}.json"


def _persist_fit_result(result_id: str, saved: dict[str, Any]) -> None:
    FIT_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    target = _fit_result_path(result_id)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


def _get_fit_result(result_id: str) -> dict[str, Any] | None:
    with FIT_RESULTS_LOCK:
        saved = FIT_RESULTS.get(result_id)
    if saved is not None:
        return saved
    try:
        path = _fit_result_path(result_id)
        if not path.is_file():
            return None
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    with FIT_RESULTS_LOCK:
        FIT_RESULTS[result_id] = saved
        FIT_RESULTS.move_to_end(result_id)
    return saved


def _recent_fit_results() -> list[dict[str, Any]]:
    if not FIT_RESULT_DIR.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    paths = sorted(FIT_RESULT_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in paths[:20]:
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        result_id = path.stem
        rows.append({
            "result_id": result_id,
            "created_at": saved.get("created_at"),
            "sample": saved.get("sample"),
            "backend": saved.get("fit", {}).get("backend"),
            "quality_status": saved.get("fit", {}).get("quality_status"),
            "download_url": f"/api/artemis/results/{result_id}/download",
            "data_download_url": f"/api/artemis/results/{result_id}/data.csv",
            "wavelet_download_url": f"/api/artemis/results/{result_id}/wavelet.zip",
        })
    return rows


def read_feff_path_summary(path: Path) -> tuple[float, float]:
    """Read FEFF degeneracy and Reff directly from a feffNNNN.dat header."""
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
            return degeneracy, reff
    raise ValueError(f"无法从 {path.name} 读取 FEFF 路径简并度和 Reff")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
    allowed_origins = {
        "https://water0623.github.io",
        *(
            origin.strip().rstrip("/")
            for origin in os.environ.get("XAFS_ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        ),
    }

    def request_is_cross_origin() -> bool:
        origin = request.headers.get("Origin", "").rstrip("/")
        return bool(origin and origin != request.host_url.rstrip("/"))

    @app.after_request
    def allow_configured_frontend(response):
        origin = request.headers.get("Origin", "").rstrip("/")
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            if request.headers.get("Access-Control-Request-Private-Network") == "true":
                response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

    def bundled_path(name: str) -> Path:
        candidate = (DATA_DIR / Path(name).name).resolve()
        if candidate.parent != DATA_DIR.resolve() or not candidate.is_file():
            raise ValueError("未找到内置数据文件")
        return candidate

    def spectrum_from_request(form: dict[str, Any] | None = None):
        values = form or request.form
        kwargs = {
            "signal_mode": values.get("signal_mode", "auto"),
            "energy_column": int(values.get("energy_column", 0)),
            "signal_column": int(values.get("signal_column", -1)),
            "i0_column": int(values.get("i0_column", 1)),
            "it_if_column": int(values.get("it_if_column", 2)),
        }
        upload = request.files.get("data_file")
        if upload and upload.filename:
            return read_spectrum(upload.read(), Path(upload.filename).name, **kwargs)
        name = values.get("dataset", "")
        return read_spectrum_file(bundled_path(str(name)), **kwargs)

    @app.route("/", methods=["GET"])
    def index():
        return render_template("index.html")

    @app.route("/api/status", methods=["GET"])
    def status():
        native = discover_native_tools()
        return jsonify(
            {
                "larch": False,
                "xraylarch_disabled": True,
                "data_directory": str(DATA_DIR),
                "athena_backend": "Demeter/IFEFFIT" if demeter_available() else "unavailable",
                "artemis_backend": "Demeter/IFEFFIT" if demeter_available() else "unavailable",
                "artemis_ready": demeter_available(),
                "hama_wavelet": "HAMA Fortran (ESRF)" if native["hama"]["available"] else "unavailable",
                "native_tools": native,
                "native_mode_ready": demeter_available(),
            }
        )

    @app.route("/api/native/status", methods=["GET"])
    def native_status():
        return jsonify({"tools": discover_native_tools()})

    @app.route("/api/native/launch", methods=["POST"])
    def native_launch():
        if request_is_cross_origin():
            return jsonify({"error": "为安全起见，远程网页不能启动本机原生程序；请在本地工作台中启动。"}), 403
        try:
            name = str((request.get_json(silent=True) or {}).get("tool", "")).lower()
            return jsonify({"launched": True, "tool": launch_native_tool(name)})
        except (ValueError, FileNotFoundError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/datasets", methods=["GET"])
    def datasets():
        files = [] if not DATA_DIR.exists() else [p.name for p in DATA_DIR.iterdir() if p.is_file() and p.suffix.lower() != ".prj"]
        return jsonify(sorted(files))

    @app.route("/api/standards", methods=["GET"])
    def standards():
        return jsonify(STANDARD_LIBRARY)

    @app.route("/api/athena", methods=["POST"])
    def athena():
        try:
            spec = spectrum_from_request()
            cfg = config_from_mapping(dict(request.form))
            result = process_spectrum_demeter(spec, cfg)
            payload = serializable_result(result)
            payload.update({"source_name": spec.source_name, "signal_description": spec.signal_description})
            return jsonify(payload)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/athena/multi", methods=["POST"])
    def athena_multi():
        try:
            cfg = config_from_mapping(dict(request.form))
            kwargs = {
                "signal_mode": request.form.get("signal_mode", "auto"),
                "energy_column": int(request.form.get("energy_column", 0)),
                "signal_column": int(request.form.get("signal_column", -1)),
                "i0_column": int(request.form.get("i0_column", 1)),
                "it_if_column": int(request.form.get("it_if_column", 2)),
            }
            spectra = []
            for name in json.loads(request.form.get("datasets", "[]")):
                spectra.append(read_spectrum_file(bundled_path(str(name)), **kwargs))
            for upload in request.files.getlist("data_files"):
                if upload.filename:
                    spectra.append(read_spectrum(upload.read(), Path(upload.filename).name, **kwargs))
            if not spectra:
                raise ValueError("请选择或上传至少一条数据")
            if len(spectra) > 30:
                raise ValueError("一次最多处理 30 条数据")
            series = []
            for spec in spectra:
                result = process_spectrum_demeter(spec, cfg)
                payload = serializable_result(result, max_points=900)
                series.append(
                    {
                        "source_name": spec.source_name,
                        "e0": payload["e0"],
                        "edge_step": payload["edge_step"],
                        "energy_shift": payload["energy_shift"],
                        "energy": payload["energy"],
                        "normalized": payload["display_norm"],
                        "k": payload["k"],
                        "chi_weighted": [float(value * (k**cfg.kweight)) for value, k in zip(payload["chi"], payload["k"])],
                        "r": payload["r"],
                        "chir_mag": payload["chir_mag"],
                        "kmax_used": payload["kmax_used"],
                    }
                )
            return jsonify({"series": series, "normalization_mode": "Athena flattened" if cfg.flatten else "normalized", "kweight": cfg.kweight})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/align", methods=["POST"])
    def align_to_reference():
        try:
            sample_spec = spectrum_from_request()
            cfg = config_from_mapping(dict(request.form))
            peak_mode = request.form.get("peak_mode", "e0").lower()
            if peak_mode not in ("e0", "white_line"):
                raise ValueError("峰类型必须为 E0 或白线峰")

            sample_cfg = replace(cfg, energy_shift=0.0, auto_e0=True)
            reference_cfg = replace(
                sample_cfg,
                energy_min=None,
                energy_max=None,
                exclude_ranges="",
                deglitch_sigma=0.0,
            )
            reference_name = request.form.get("reference_dataset", "Ir-foil")
            reference_spec = read_spectrum_file(bundled_path(str(reference_name)), signal_mode="auto")
            standard = STANDARD_LIBRARY.get(str(reference_name), {})
            standard_e0 = standard.get("e0_eV")
            if standard_e0 is not None:
                reference_cfg = replace(reference_cfg, e0=float(standard_e0), auto_e0=False)
            sample = process_spectrum_demeter(sample_spec, sample_cfg)
            reference = process_spectrum_demeter(reference_spec, reference_cfg)

            def peak(result: dict[str, Any], mode: str) -> tuple[float, float]:
                position = float(result["e0"] if mode == "e0" else result["white_line_energy"])
                index = int(abs(result["energy"] - position).argmin())
                return position, float(result["display_norm"][index])

            sample_position, sample_height = peak(sample, peak_mode)
            reference_position, reference_height = peak(reference, peak_mode)
            if request.form.get("sample_peak", "").strip():
                sample_position = float(request.form["sample_peak"])
            if request.form.get("reference_peak", "").strip():
                reference_position = float(request.form["reference_peak"])
            shift = reference_position - sample_position
            aligned_cfg = replace(cfg, energy_shift=shift, e0=float(sample["e0"]) + shift, auto_e0=False)
            aligned = process_spectrum_demeter(sample_spec, aligned_cfg)
            aligned_payload = serializable_result(aligned)
            reference_payload = serializable_result(reference)
            return jsonify(
                {
                    "sample_name": sample_spec.source_name,
                    "reference_name": reference_spec.source_name,
                    "peak_mode": peak_mode,
                    "sample_peak_eV": sample_position,
                    "sample_peak_height": sample_height,
                    "reference_peak_eV": reference_position,
                    "reference_peak_height": reference_height,
                    "energy_shift_eV": shift,
                    "aligned_e0_eV": aligned["e0"],
                    "aligned": {"energy": aligned_payload["energy"], "norm": aligned_payload["display_norm"]},
                    "reference": {"energy": reference_payload["energy"], "norm": reference_payload["display_norm"]},
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/artemis", methods=["POST"])
    def artemis():
        try:
            spec = spectrum_from_request()
            cfg = config_from_mapping(dict(request.form))
            processed = process_spectrum_demeter(spec, cfg)
            uploads = [item for item in request.files.getlist("path_files") if item.filename]
            feff_result_id = request.form.get("feff_result_id", "").strip()
            selected_generated_names = json.loads(request.form.get("feff_path_names", "[]"))
            settings = json.loads(request.form.get("path_settings", "[]"))
            kweights = [int(value.strip()) for value in request.form.get("fit_kweights", str(cfg.kweight)).split(",") if value.strip()]
            if not kweights or any(value not in (0, 1, 2, 3) for value in kweights):
                raise ValueError("k-weight 请填写 0–3，例如 1,2,3")
            flag = lambda name, default=False: request.form.get(name, "true" if default else "false").lower() in ("1", "true", "on", "yes")
            fitspace = request.form.get("fitspace", "r").lower()
            if fitspace not in ("r", "k"):
                raise ValueError("拟合空间只能选择 R space 或 K space")
            if fitspace == "r":
                fit_kmin = float(cfg.kmin)
                fit_kmax = float(processed["kmax_used"])
                fit_rmin = float(request.form.get("rmin", 1.0))
                fit_rmax = float(request.form.get("rmax", 3.5))
            else:
                fit_kmin = float(request.form.get("fit_kmin", cfg.kmin))
                fit_kmax = float(request.form.get("fit_kmax", processed["kmax_used"]))
                fit_rmin = 0.0
                fit_rmax = max(6.0, float(request.form.get("rmax", 6.0)))
            max_shell_text = request.form.get("fit_max_shell", "").strip()
            fit_max_shell = int(max_shell_text) if max_shell_text else None
            if not 0 <= fit_kmin < fit_kmax:
                raise ValueError("k 空间范围错误：必须满足 0 ≤ kmin < kmax")
            if fit_kmax > float(processed["kmax_used"]) + 0.05:
                raise ValueError(f"拟合 kmax={fit_kmax:.2f} Å⁻¹ 超过当前数据可用上限 {processed['kmax_used']:.2f} Å⁻¹")
            if not 0 <= fit_rmin < fit_rmax:
                raise ValueError("R 空间范围错误：必须满足 0 ≤ Rmin < Rmax")
            with tempfile.TemporaryDirectory(prefix="xafs_feff_") as folder:
                path_files = []
                path_names = []
                if feff_result_id:
                    with FEFF_RESULTS_LOCK:
                        generated_result = FEFF_RESULTS.get(feff_result_id)
                    if generated_result is None:
                        raise ValueError("CIF 生成的 FEFF 路径已过期，请重新生成")
                    available = generated_result["path_files"]
                    if not selected_generated_names:
                        raise ValueError("请至少勾选一条 CIF 生成的 FEFF 路径")
                    for name in selected_generated_names:
                        safe_name = Path(str(name)).name
                        if safe_name != name or safe_name not in available:
                            raise ValueError(f"无效的 FEFF 路径：{name}")
                        target = Path(folder) / safe_name
                        target.write_bytes(available[safe_name])
                        path_files.append(target)
                        path_names.append(safe_name)
                else:
                    for upload in uploads:
                        target = Path(folder) / Path(upload.filename).name
                        upload.save(target)
                        path_files.append(target)
                        path_names.append(target.name)
                output = intelligent_fit_feff_paths(
                    processed,
                    path_files,
                    settings,
                    fit_mode=request.form.get("fit_mode", "unknown"),
                    smart_fit=flag("smart_fit", True),
                    s02_source=request.form.get("s02_source", "manual"),
                    temperature_profile=request.form.get("temperature_profile", "room"),
                    max_shell=fit_max_shell,
                    s02=float(request.form.get("s02", 0.85)),
                    s02_vary=flag("s02_vary"),
                    s02_min=float(request.form.get("s02_min", 0.5)),
                    s02_max=float(request.form.get("s02_max", 1.2)),
                    de0=float(request.form.get("de0", 0.0)),
                    de0_vary=flag("de0_vary", True),
                    de0_min=float(request.form.get("de0_min", -10.0)),
                    de0_max=float(request.form.get("de0_max", 10.0)),
                    kmin=fit_kmin,
                    kmax=fit_kmax,
                    kweight=kweights,
                    dk=float(request.form.get("fit_dk", 2.0)),
                    rmin=fit_rmin,
                    rmax=fit_rmax,
                    fitspace=fitspace,
                    window=request.form.get("fit_window", "kaiser"),
                    rwindow=request.form.get("fit_rwindow", "hanning"),
                    wavelet_kweight=int(request.form.get("wavelet_kweight", 2)),
                    wavelet_rmax=float(request.form.get("wavelet_rmax", 5.0)),
                    wavelet_backend=request.form.get("wavelet_backend", "hama"),
                    wavelet_kappa=float(request.form.get("wavelet_kappa", 10.0)),
                    wavelet_sigma=float(request.form.get("wavelet_sigma", 1.0)),
                )
            result_id = uuid.uuid4().hex
            preprocessing = serializable_result(processed, max_points=1_000_000)
            saved = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "sample": spec.source_name,
                "path_files": path_names,
                "request_parameters": {key: request.form.getlist(key) for key in request.form},
                "preprocessing": preprocessing,
                "fit": output,
            }
            with FIT_RESULTS_LOCK:
                FIT_RESULTS[result_id] = saved
                FIT_RESULTS.move_to_end(result_id)
                while len(FIT_RESULTS) > MAX_SAVED_FITS:
                    FIT_RESULTS.popitem(last=False)
            _persist_fit_result(result_id, saved)
            output["result_id"] = result_id
            output["source_name"] = spec.source_name
            output["download_url"] = f"/api/artemis/results/{result_id}/download"
            output["data_download_url"] = f"/api/artemis/results/{result_id}/data.csv"
            output["wavelet_download_url"] = f"/api/artemis/results/{result_id}/wavelet.zip"
            return jsonify(output)
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/artemis/suggest", methods=["POST"])
    def artemis_suggest():
        try:
            uploads = [item for item in request.files.getlist("path_files") if item.filename]
            if not uploads:
                raise ValueError("请先选择 FEFF 路径文件")
            suggestions = []
            with tempfile.TemporaryDirectory(prefix="xafs_feff_suggest_") as folder:
                for upload in uploads:
                    target = Path(folder) / Path(upload.filename).name
                    upload.save(target)
                    degen, reff = read_feff_path_summary(target)
                    sigma2 = 0.003 if reff <= 2.3 else (0.005 if reff <= 3.3 else 0.007)
                    suggestions.append(
                        {
                            "label": f"{target.stem} · R={reff:.3f} Å",
                            "reff": reff,
                            "feff_degeneracy": degen,
                            "cn": degen,
                            "cn_min": 0.0,
                            "cn_max": max(degen * 1.5, degen + 2.0),
                            "sigma2": sigma2,
                            "sigma2_min": 0.0,
                            "sigma2_max": 0.02,
                            "deltar": 0.0,
                            "deltar_min": -0.12,
                            "deltar_max": 0.12,
                            "shell": 1,
                            "vary_cn": True,
                            "vary_sigma2": True,
                            "vary_deltar": True,
                        }
                    )
            ordered_reff = sorted({round(item["reff"], 3) for item in suggestions})
            shell_by_reff: dict[float, int] = {}
            shell = 0
            previous = None
            for reff in ordered_reff:
                if previous is None or reff - previous > 0.45:
                    shell += 1
                shell_by_reff[reff] = shell
                previous = reff
            for item in suggestions:
                item["shell"] = shell_by_reff[round(item["reff"], 3)]
            reffs = [item["reff"] for item in suggestions]
            return jsonify(
                {
                    "paths": suggestions,
                    "global": {
                        "s02": 0.85,
                        "s02_min": 0.5,
                        "s02_max": 1.2,
                        "s02_vary": False,
                        "de0": 0.0,
                        "de0_min": -10.0,
                        "de0_max": 10.0,
                        "de0_vary": True,
                        "rmin": max(0.5, min(reffs) - 1.2),
                        "rmax": max(reffs) + 0.6,
                        "fit_dk": 1.0,
                        "fit_kweights": "2",
                        "fit_kmin": 3.0,
                        "fit_kmax": 12.0,
                    },
                    "note": "建议值来自 FEFF 路径简并度和有效距离，仅作为拟合起点，必须结合实际结构约束。",
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/artemis/results", methods=["GET"])
    def list_artemis_results():
        return jsonify({"results": _recent_fit_results(), "storage_directory": str(FIT_RESULT_DIR)})

    @app.route("/api/artemis/results/<result_id>", methods=["GET"])
    def get_artemis_result(result_id: str):
        saved = _get_fit_result(result_id)
        if saved is None:
            return jsonify({"error": "拟合结果不存在"}), 404
        output = dict(saved["fit"])
        output.update({
            "result_id": result_id,
            "source_name": saved.get("sample"),
            "download_url": f"/api/artemis/results/{result_id}/download",
            "data_download_url": f"/api/artemis/results/{result_id}/data.csv",
            "wavelet_download_url": f"/api/artemis/results/{result_id}/wavelet.zip",
        })
        return jsonify(output)

    @app.route("/api/artemis/results/<result_id>/data.csv", methods=["GET"])
    def download_artemis_curves(result_id: str):
        saved = _get_fit_result(result_id)
        if saved is None:
            return jsonify({"error": "拟合结果不存在或服务已重启，请重新运行拟合"}), 404

        fit = saved["fit"]
        stream = StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["domain", "x", "experimental", "fit"])
        energy_min, energy_max = fit["energy_fit_region_eV"]
        for x, experimental, model in zip(fit["energy_spectrum_eV"], fit["energy_normalized_mu"], fit["energy_normalized_fit"]):
            if model is not None and energy_min <= float(x) <= energy_max:
                writer.writerow(["energy_normalized", x, experimental, model])
        display_kweight = int(fit["display_kweight"])
        for x, experimental, model in zip(fit["data_k"], fit["data_chi"], fit["model_chi"]):
            weight = float(x) ** display_kweight
            writer.writerow([f"k_space_k{display_kweight}_chi", x, float(experimental) * weight, float(model) * weight])
        for x, experimental, model in zip(fit["r"], fit["data_chir_mag"], fit["model_chir_mag"]):
            writer.writerow(["r_space_magnitude", x, experimental, model])
        payload = BytesIO(("\ufeff" + stream.getvalue()).encode("utf-8"))
        safe_name = Path(saved["sample"]).name.replace(" ", "_")
        return send_file(payload, mimetype="text/csv; charset=utf-8", as_attachment=True, download_name=f"{safe_name}_E_k_R_experimental_fit.csv")

    @app.route("/api/artemis/results/<result_id>/wavelet.zip", methods=["GET"])
    def download_artemis_wavelet(result_id: str):
        saved = _get_fit_result(result_id)
        if saved is None:
            return jsonify({"error": "拟合结果不存在或服务已重启，请重新运行拟合"}), 404

        wavelet = saved["fit"]["wavelet"]
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for key, filename in (("data_mag", "wavelet_experimental.csv"), ("model_mag", "wavelet_fit.csv")):
                stream = StringIO(newline="")
                writer = csv.writer(stream)
                writer.writerow(["R_A", *wavelet["k"]])
                writer.writerows([[rvalue, *values] for rvalue, values in zip(wavelet["r"], wavelet[key])])
                zf.writestr(filename, "\ufeff" + stream.getvalue())
            zf.writestr("wavelet_axes.json", json.dumps({key: wavelet.get(key) for key in ("backend", "mother", "kappa", "sigma", "kweight", "input_k_step")} | {"k_A-1": wavelet["k"], "R_A": wavelet["r"]}, ensure_ascii=False, indent=2))
        archive.seek(0)
        safe_name = Path(saved["sample"]).name.replace(" ", "_")
        return send_file(archive, mimetype="application/zip", as_attachment=True, download_name=f"{safe_name}_wavelet_experimental_fit.zip")

    @app.route("/api/artemis/results/<result_id>/download", methods=["GET"])
    def download_artemis_result(result_id: str):
        saved = _get_fit_result(result_id)
        if saved is None:
            return jsonify({"error": "拟合结果不存在或服务已重启，请重新运行拟合"}), 404

        def csv_text(header: list[str], rows: list[list[Any]]) -> str:
            stream = StringIO(newline="")
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
            return "\ufeff" + stream.getvalue()

        fit, pre = saved["fit"], saved["preprocessing"]
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            manifest = {
                "format": "xafs-workbench-fit-package",
                "version": 1,
                "created_at": saved["created_at"],
                "sample": saved["sample"],
                "fit_mode": fit["fit_mode"],
                "smart_fit": fit["smart_fit"],
                "path_files": saved["path_files"],
                "quality_status": fit["quality_status"],
                "units": {"energy": "eV", "k": "angstrom^-1", "R": "angstrom", "sigma2": "angstrom^2"},
                "files": {
                    "energy_space.csv": "raw and normalized energy-domain data",
                    "energy_space_exafs_fit.csv": "experimental, fitted and residual EXAFS chi(E); not a full XANES/mu(E) model",
                    "energy_space_normalized_fit.csv": "raw mu(E), normalized experiment and post-edge fit projection",
                    "k_space.csv": "experimental, fitted and residual chi(k)",
                    "r_space.csv": "experimental, fitted and residual Fourier-transform data",
                    "wavelet_*.csv": "HAMA Morlet or Larch Cauchy magnitude matrices; first row is k and first column is R",
                    "parameters.csv": "all GDS parameters",
                    "paths.csv": "path-level structural results",
                    "publication_table.csv": "compact table for manuscript/supporting-information review",
                    "paper_style_table.csv": "publication-style d, N, R and sigma2 values with parenthetical uncertainties",
                    "correlations.csv": "parameter correlations above the reporting threshold",
                },
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.writestr("request_and_provenance.json", json.dumps({"request_parameters": saved["request_parameters"], "stage_history": fit["stage_history"], "manager_decisions": fit["manager_decisions"], "warnings": fit["warnings"]}, ensure_ascii=False, indent=2))
            energy_keys = [key for key in ("energy", "mu", "norm", "flat", "display_norm", "pre_edge", "post_edge", "dmude") if key in pre]
            zf.writestr("energy_space.csv", csv_text(energy_keys, [list(row) for row in zip(*(pre[key] for key in energy_keys))]))
            zf.writestr("energy_space_exafs_fit.csv", csv_text(["energy_eV", "experimental_chiE", "fit_chiE", "residual_chiE"], [list(row) for row in zip(fit["energy_fit_eV"], fit["energy_data_chi"], fit["energy_model_chi"], fit["energy_residual_chi"])]))
            zf.writestr("energy_space_normalized_fit.csv", csv_text(["energy_eV", "raw_muE", "normalized_experimental", "normalized_fit_projection"], [list(row) for row in zip(fit["energy_spectrum_eV"], fit["energy_raw_mu"], fit["energy_normalized_mu"], fit["energy_normalized_fit"])]))
            zf.writestr("k_space.csv", csv_text(["k_A-1", "experimental_chi", "fit_chi", "residual_chi"], [list(row) for row in zip(fit["data_k"], fit["data_chi"], fit["model_chi"], fit["residual_chi"])]))
            zf.writestr("r_space.csv", csv_text(["R_A", "experimental_mag", "fit_mag", "residual_mag", "experimental_real", "fit_real", "residual_real", "experimental_imaginary", "fit_imaginary", "residual_imaginary"], [list(row) for row in zip(fit["r"], fit["data_chir_mag"], fit["model_chir_mag"], fit["residual_chir_mag"], fit["data_chir_re"], fit["model_chir_re"], fit["residual_chir_re"], fit["data_chir_im"], fit["model_chir_im"], fit["residual_chir_im"])]))
            if fit["parameter_rows"]:
                keys = list(fit["parameter_rows"][0])
                zf.writestr("parameters.csv", csv_text(keys, [[row.get(key) for key in keys] for row in fit["parameter_rows"]]))
            if fit["paths"]:
                keys = list(fit["paths"][0])
                zf.writestr("paths.csv", csv_text(keys, [[row.get(key) for key in keys] for row in fit["paths"]]))
                publication_rows = [
                    [saved["sample"], row.get("shell"), row["label"], row["CN"], row["CN_stderr"], row["R_A"], row["deltar_A"], row["sigma2_A2"], row["sigma2_stderr"], fit["delta_e0_eV"], fit["r_factor"], fit["quality_status"]]
                    for row in fit["paths"]
                ]
                zf.writestr("publication_table.csv", csv_text(["sample", "shell", "path", "CN", "CN_stderr", "R_A", "deltaR_A", "sigma2_A2", "sigma2_stderr", "deltaE0_eV", "R_factor", "quality_status"], publication_rows))
            if fit["paper_table"]:
                paper_keys = list(fit["paper_table"][0])
                zf.writestr("paper_style_table.csv", csv_text(paper_keys, [[row.get(key) for key in paper_keys] for row in fit["paper_table"]]))
                zf.writestr("paper_style_notes.txt", "\n".join(fit["paper_notes"]))
            if fit["correlations"]:
                keys = list(fit["correlations"][0])
                zf.writestr("correlations.csv", csv_text(keys, [[row.get(key) for key in keys] for row in fit["correlations"]]))
            wavelet = fit["wavelet"]
            for key, filename in (("data_mag", "wavelet_experimental.csv"), ("model_mag", "wavelet_model.csv"), ("residual_mag", "wavelet_residual.csv")):
                rows = [[rvalue, *values] for rvalue, values in zip(wavelet["r"], wavelet[key])]
                zf.writestr(filename, csv_text(["R_A", *wavelet["k"]], rows))
            zf.writestr("fit_report.txt", fit["report"])
            zf.writestr("complete_result.json", json.dumps(fit, ensure_ascii=False, indent=2))
        archive.seek(0)
        safe_name = Path(saved["sample"]).name.replace(" ", "_")
        return send_file(archive, mimetype="application/zip", as_attachment=True, download_name=f"{safe_name}_FEFFIT_complete.zip")

    @app.route("/api/feff", methods=["POST"])
    def run_feff():
        try:
            upload = request.files.get("cif_file")
            if upload is None or not upload.filename:
                raise ValueError("请上传 CIF 结构文件")
            absorber = request.form.get("absorber", "Ir").strip().capitalize()
            edge = request.form.get("edge", "L3").strip().upper()
            radius = float(request.form.get("cluster_radius", 7.0))
            if not 3.0 <= radius <= 12.0:
                raise ValueError("FEFF 团簇半径应在 3–12 Å 之间")
            from larch.utils import bindir
            from pymatgen.core import Structure
            from pymatgen.io.feff.sets import MPEXAFSSet

            structure = Structure.from_str(upload.read().decode("utf-8", errors="ignore"), fmt="cif")
            if not any(site.specie.symbol == absorber for site in structure):
                raise ValueError(f"CIF 中没有找到吸收原子 {absorber}")
            with tempfile.TemporaryDirectory(prefix="xafs_cif_feff_") as folder:
                MPEXAFSSet(
                    absorber,
                    structure,
                    edge=edge,
                    radius=radius,
                    user_tag_settings={
                        "RPATH": radius,
                        "NLEG": 4,
                        "CRITERIA": "4.0 2.5",
                        "PRINT": "1 0 0 0 0 3",
                        "S02": 1.0,
                        "SCF": f"{min(4.0, radius):.1f} 0 20 .2 1",
                    },
                ).write_input(folder)
                # The FEFF8L build bundled with Larch does not accept pymatgen's
                # newer ``COREHOLE FSR`` keyword.  Omitting it restores FEFF8L's
                # own default final-state-rule behavior.
                feff_input = Path(folder) / "feff.inp"
                input_lines = [line for line in feff_input.read_text(encoding="utf-8").splitlines() if not line.strip().upper().startswith("COREHOLE")]
                feff_input.write_text("\n".join(input_lines) + "\n", encoding="utf-8")
                logs = []
                for module in ("rdinp", "pot", "xsph", "pathfinder", "genfmt", "ff2x"):
                    executable = Path(bindir) / f"feff8l_{module}.exe"
                    if not executable.is_file():
                        executable = Path(bindir) / f"feff8l_{module}"
                    if not executable.is_file():
                        raise RuntimeError(f"缺少 FEFF 模块：{module}")
                    completed = subprocess.run(
                        [str(executable)],
                        cwd=folder,
                        capture_output=True,
                        text=True,
                        errors="replace",
                        timeout=120,
                        check=False,
                    )
                    logs.append(f"===== {module} =====\n{completed.stdout}\n{completed.stderr}")
                    if completed.returncode != 0:
                        detail = (completed.stderr or completed.stdout).strip()[-600:]
                        raise RuntimeError(f"FEFF {module} 运行失败：{detail}")
                generated = sorted(Path(folder).glob("feff*.dat"))
                if not generated:
                    detail = "\n".join(logs)[-1200:].strip()
                    files = ", ".join(sorted(path.name for path in Path(folder).iterdir()))
                    raise RuntimeError(f"FEFF 未生成路径文件，请检查 CIF、吸收原子和吸收边。目录：{files}。日志：{detail}")
                archive = BytesIO()
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                    for name in ("feff.inp", "paths.dat", "files.dat", "list.dat"):
                        path = Path(folder) / name
                        if path.exists():
                            zf.write(path, path.name)
                    zf.writestr("feff_run.log", "\n".join(logs))
                    for path in generated:
                        zf.write(path, path.name)
                archive.seek(0)
                archive_bytes = archive.getvalue()
                file_ranks: dict[str, float] = {}
                files_dat = Path(folder) / "files.dat"
                if files_dat.exists():
                    for line in files_dat.read_text(encoding="utf-8", errors="ignore").splitlines():
                        match = re.match(r"\s*(feff\d+\.dat)\s+\S+\s+(\S+)", line, re.IGNORECASE)
                        if match:
                            file_ranks[match.group(1).lower()] = float(match.group(2))
                from larch.xafs import feffpath

                path_rows = []
                for path in generated:
                    parsed = feffpath(str(path))
                    symbols = [str(atom[0]).strip() for atom in parsed.geom]
                    scattering_path = " → ".join([*symbols, symbols[0]]) if symbols else path.stem
                    nleg = int(getattr(parsed, "nleg", max(2, len(symbols))))
                    reff = float(parsed.reff)
                    degen = float(parsed.degen)
                    path_rows.append(
                        {
                            "name": path.name,
                            "index": int(re.search(r"(\d+)", path.stem).group(1)),
                            "degen": degen,
                            "reff": reff,
                            "rank": file_ranks.get(path.name.lower()),
                            "nleg": nleg,
                            "type": "single scattering" if nleg == 2 else "multiple scattering",
                            "scattering_path": scattering_path,
                            "label": f"{path.stem} · {scattering_path}",
                            "feff_degeneracy": degen,
                            "cn": degen,
                            "cn_min": 0.0,
                            "cn_max": max(degen * 1.5, degen + 2.0),
                            "sigma2": 0.003 if reff <= 2.3 else (0.005 if reff <= 3.3 else 0.007),
                            "sigma2_min": 0.0,
                            "sigma2_max": 0.02,
                            "deltar": 0.0,
                            "deltar_min": -0.12,
                            "deltar_max": 0.12,
                            "vary_cn": True,
                            "vary_sigma2": True,
                            "vary_deltar": True,
                        }
                    )
                ordered_reff = sorted({round(item["reff"], 3) for item in path_rows})
                shell_by_reff: dict[float, int] = {}
                shell, previous = 0, None
                for reff in ordered_reff:
                    if previous is None or reff - previous > 0.45:
                        shell += 1
                    shell_by_reff[reff] = shell
                    previous = reff
                for item in path_rows:
                    item["shell"] = shell_by_reff[round(item["reff"], 3)]
                generated_bytes = {path.name: path.read_bytes() for path in generated}
            if request.form.get("response_mode") == "json":
                feff_id = uuid.uuid4().hex
                saved_feff = {
                    "archive": archive_bytes,
                    "download_name": f"{absorber}_{edge}_FEFF_paths.zip",
                    "path_files": generated_bytes,
                    "paths": path_rows,
                }
                with FEFF_RESULTS_LOCK:
                    FEFF_RESULTS[feff_id] = saved_feff
                    FEFF_RESULTS.move_to_end(feff_id)
                    while len(FEFF_RESULTS) > MAX_SAVED_FEFF:
                        FEFF_RESULTS.popitem(last=False)
                return jsonify({"feff_result_id": feff_id, "paths": path_rows, "download_url": f"/api/feff/results/{feff_id}/download", "count": len(path_rows)})
            return send_file(BytesIO(archive_bytes), mimetype="application/zip", as_attachment=True, download_name=f"{absorber}_{edge}_FEFF_paths.zip")
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/feff/results/<result_id>/download", methods=["GET"])
    def download_feff_result(result_id: str):
        with FEFF_RESULTS_LOCK:
            saved = FEFF_RESULTS.get(result_id)
        if saved is None:
            return jsonify({"error": "FEFF 结果不存在或服务已重启，请重新生成"}), 404
        return send_file(BytesIO(saved["archive"]), mimetype="application/zip", as_attachment=True, download_name=saved["download_name"])

    @app.route("/api/analyze", methods=["POST"])
    def analyze():
        try:
            spec = spectrum_from_request()
            cfg = config_from_mapping(dict(request.form))
            sample = process_spectrum_demeter(spec, cfg)
            reference_names = json.loads(request.form.get("reference_names", '["Ir-foil", "IrO2_foil.xdi"]'))
            references = []
            for name in reference_names:
                ref_spec = read_spectrum_file(bundled_path(str(name)), signal_mode="auto")
                references.append((str(name), process_spectrum_demeter(ref_spec, cfg)))
            emin = float(request.form.get("lcf_emin", sample["e0"] - 15.0))
            emax = float(request.form.get("lcf_emax", sample["e0"] + 70.0))
            lcf = linear_combination_fit(sample, references, emin, emax, request.form.get("sum_to_one", "on") == "on")
            return jsonify(
                {
                    "source_name": spec.source_name,
                    "e0": sample["e0"],
                    "edge_step": sample["edge_step"],
                    "white_line_energy": sample["white_line_energy"],
                    "white_line_height": sample["white_line_height"],
                    "energy": serializable_result({"energy": sample["energy"]})["energy"],
                    "norm": serializable_result({"norm": sample["display_norm"]})["norm"],
                    "dmude": serializable_result({"dmude": sample["dmude"]})["dmude"],
                    "lcf": lcf,
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/batch", methods=["POST"])
    def batch():
        try:
            cfg = config_from_mapping(dict(request.form))
            names = json.loads(request.form.get("datasets", "[]"))
            rows = []
            for name in names:
                spec = read_spectrum_file(bundled_path(str(name)), signal_mode="auto")
                result = process_spectrum_demeter(spec, cfg)
                rows.append(
                    {
                        "sample": str(name),
                        "E0_eV": result["e0"],
                        "edge_step": result["edge_step"],
                        "white_line_energy_eV": result["white_line_energy"],
                        "white_line_height": result["white_line_height"],
                        "kmax_used_A-1": result["kmax_used"],
                        "removed_points": result["removed_points"],
                        "energy_shift_eV": result["energy_shift"],
                    }
                )
            return jsonify({"rows": rows})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/batch/export", methods=["POST"])
    def export_standardized_batch():
        try:
            cfg = config_from_mapping(dict(request.form))
            names = json.loads(request.form.get("datasets", "[]"))
            if not names:
                raise ValueError("请至少选择一个批量样品")
            archive = BytesIO()
            summaries = []
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                for name in names:
                    spec = read_spectrum_file(bundled_path(str(name)), signal_mode="auto")
                    result = process_spectrum_demeter(spec, cfg)
                    keys = ("energy", "mu", "norm", "flat", "display_norm", "pre_edge", "post_edge", "dmude")
                    output = StringIO(newline="")
                    writer = csv.writer(output)
                    writer.writerow(keys)
                    writer.writerows(zip(*(result[key] for key in keys)))
                    safe_name = Path(str(name)).name
                    zf.writestr(f"processed/{safe_name}_standardized.csv", "\ufeff" + output.getvalue())
                    summary = {
                        "sample": safe_name,
                        "energy_shift_eV": result["energy_shift"],
                        "E0_eV": result["e0"],
                        "edge_step": result["edge_step"],
                        "white_line_energy_eV": result["white_line_energy"],
                        "white_line_height": result["white_line_height"],
                        "kmax_used_A-1": result["kmax_used"],
                    }
                    summaries.append(summary)
                    zf.writestr(
                        f"projects/{safe_name}_processing.json",
                        json.dumps({"config": asdict(cfg), "summary": summary}, ensure_ascii=False, indent=2),
                    )
                summary_output = StringIO(newline="")
                writer = csv.DictWriter(summary_output, fieldnames=list(summaries[0]))
                writer.writeheader()
                writer.writerows(summaries)
                zf.writestr("batch_summary.csv", "\ufeff" + summary_output.getvalue())
            archive.seek(0)
            return send_file(archive, mimetype="application/zip", as_attachment=True, download_name="xafs_standardized_batch.zip")
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/api/edges/<symbol>", methods=["GET"])
    def edges(symbol: str):
        try:
            return jsonify(edge_lookup(symbol))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    return app


def main() -> None:
    app = create_app()
    app.run(host="127.0.0.1", port=8765, debug=False)


if __name__ == "__main__":
    main()
