from typing import Dict, List, Optional, Any

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np

from xafs_core.processing import find_e0, calibrate_energy, normalize, autobk_simple, ft_chi
from xafs_core.lcf import linear_combination_fit
from xafs_core.fit import fit_exafs
from xafs_core.feff import generate_feff_input, parse_feff_path
from xafs_core.wavelet import exafs_wavelet
from xafs_core.io import parse_ascii_xafs, merge_spectra

app = FastAPI(title="Open XAFS Workbench API", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def serial(obj):
    if isinstance(obj, np.ndarray): return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)): return obj.item()
    if isinstance(obj, dict): return {k: serial(v) for k, v in obj.items()}
    if isinstance(obj, list): return [serial(v) for v in obj]
    return obj


class Spectrum(BaseModel):
    energy: List[float]
    mu: List[float]


class NormalizeRequest(Spectrum):
    e0: Optional[float] = None
    pre1: float = -150
    pre2: float = -30
    norm1: float = 150
    norm2: Optional[float] = None
    flatten: bool = True


class AutobkRequest(Spectrum):
    e0: Optional[float] = None
    rbkg: float = 1.0
    kmin: float = 0.0
    kmax: Optional[float] = None
    kstep: float = 0.05


class FTRequest(BaseModel):
    k: List[float]
    chi: List[float]
    kmin: float = 2.0
    kmax: float = 12.0
    kweight: int = 2
    dk: float = 1.0
    window: str = "hanning"


class CalibrationRequest(BaseModel):
    energy: List[float]
    measured_e0: float
    reference_e0: float


class LCFRequest(Spectrum):
    references: Dict[str, List[float]]
    emin: Optional[float] = None
    emax: Optional[float] = None
    sum_to_one: bool = True


class EXAFSFitRequest(BaseModel):
    k: List[float]
    chi: List[float]
    paths: List[Dict[str, Any]]
    parameters: List[Dict[str, Any]]
    kmin: Optional[float] = None
    kmax: Optional[float] = None
    kweight: int = 2


class WaveletRequest(BaseModel):
    k: List[float]
    chi: List[float]
    widths: Optional[List[float]] = None


class FEFFInputRequest(BaseModel):
    atoms: List[Dict[str, Any]]
    absorber_index: int = 0
    edge: str = "K"
    title: str = "XAFS Workbench"


class FEFFParseRequest(BaseModel):
    text: str


class ASCIIParseRequest(BaseModel):
    text: str
    energy_col: int = 0
    mu_col: Optional[int] = 1
    i0_col: Optional[int] = None
    it_col: Optional[int] = None
    if_col: Optional[int] = None
    mode: str = "auto"


class MergeRequest(BaseModel):
    spectra: List[Dict[str, List[float]]]


@app.get("/")
def root():
    return {
        "name": "Open XAFS Workbench API",
        "status": "running",
        "version": "0.3.0",
        "features": [
            "ASCII import", "transmission/fluorescence conversion", "merge spectra",
            "E0", "calibration", "normalization", "background", "chi(k)",
            "FT(R)", "LCF", "wavelet", "FEFF path import", "EXAFS fitting"
        ],
    }


@app.post("/upload")
async def upload_xafs(file: UploadFile = File(...)):
    data = await file.read()
    try:
        text = data.decode("utf-8", errors="replace")
        parsed = parse_ascii_xafs(text)
        return {"filename": file.filename, "size": len(data), "parsed": serial(parsed)}
    except ValueError:
        return {"filename": file.filename, "size": len(data), "message": "Upload received; choose columns manually"}


@app.post("/xafs/import-ascii")
def api_import_ascii(req: ASCIIParseRequest):
    try:
        return serial(parse_ascii_xafs(req.text, req.energy_col, req.mu_col, req.i0_col, req.it_col, req.if_col, req.mode))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/xafs/merge")
def api_merge(req: MergeRequest):
    try: return serial(merge_spectra(req.spectra))
    except ValueError as exc: raise HTTPException(422, str(exc))


@app.post("/xafs/e0")
def api_e0(req: Spectrum):
    try: return {"e0": find_e0(req.energy, req.mu)}
    except ValueError as exc: raise HTTPException(422, str(exc))


@app.post("/xafs/calibrate")
def api_calibrate(req: CalibrationRequest):
    energy, shift = calibrate_energy(req.energy, req.measured_e0, req.reference_e0)
    return {"energy": energy.tolist(), "shift": shift}


@app.post("/xafs/normalize")
def api_normalize(req: NormalizeRequest):
    try: return serial(normalize(req.energy, req.mu, req.e0, req.pre1, req.pre2, req.norm1, req.norm2, req.flatten))
    except ValueError as exc: raise HTTPException(422, str(exc))


@app.post("/xafs/autobk")
def api_autobk(req: AutobkRequest):
    try: return serial(autobk_simple(req.energy, req.mu, req.e0, req.rbkg, req.kmin, req.kmax, req.kstep))
    except ValueError as exc: raise HTTPException(422, str(exc))


@app.post("/xafs/ft")
def api_ft(req: FTRequest):
    try: return serial(ft_chi(req.k, req.chi, req.kmin, req.kmax, req.kweight, req.dk, req.window))
    except ValueError as exc: raise HTTPException(422, str(exc))


@app.post("/xafs/lcf")
def api_lcf(req: LCFRequest):
    try: return serial(linear_combination_fit(req.energy, req.mu, req.references, req.emin, req.emax, req.sum_to_one))
    except ValueError as exc: raise HTTPException(422, str(exc))


@app.post("/xafs/wavelet")
def api_wavelet(req: WaveletRequest):
    try:
        widths = None if req.widths is None else np.asarray(req.widths, float)
        return serial(exafs_wavelet(req.k, req.chi, widths))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/feff/input")
def api_feff_input(req: FEFFInputRequest):
    try:
        return {"feff_inp": generate_feff_input(req.atoms, req.absorber_index, req.edge, req.title)}
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/feff/parse-path")
def api_feff_parse_path(req: FEFFParseRequest):
    try: return serial(parse_feff_path(req.text))
    except ValueError as exc: raise HTTPException(422, str(exc))


@app.post("/xafs/fit")
def api_fit(req: EXAFSFitRequest):
    try:
        return serial(fit_exafs(req.k, req.chi, req.paths, req.parameters, req.kmin, req.kmax, req.kweight))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/process")
def process(req: NormalizeRequest):
    return api_normalize(req)


@app.post("/fit")
def fit_compat(req: EXAFSFitRequest):
    return api_fit(req)
