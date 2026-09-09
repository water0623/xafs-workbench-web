from typing import Dict, List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np

from xafs_core.processing import find_e0, calibrate_energy, normalize, autobk_simple, ft_chi
from xafs_core.lcf import linear_combination_fit

app = FastAPI(title="Open XAFS Workbench API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def serial(obj):
    if isinstance(obj, np.ndarray): return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)): return obj.item()
    if isinstance(obj, dict): return {k: serial(v) for k, v in obj.items()}
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


@app.get("/")
def root():
    return {"name": "Open XAFS Workbench API", "status": "running", "version": "0.2.0",
            "features": ["E0", "calibration", "normalization", "background", "chi(k)", "FT(R)", "LCF"]}


@app.post("/upload")
async def upload_xafs(file: UploadFile = File(...)):
    data = await file.read()
    return {"filename": file.filename, "size": len(data), "message": "Upload received"}


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


@app.post("/process")
def process(req: NormalizeRequest):
    """Compatibility endpoint: normalize one spectrum."""
    return api_normalize(req)


@app.post("/fit")
def fit():
    return {"message": "FEFF-path EXAFS fitting is under active development",
            "parameters": ["S02", "CN", "R", "sigma2", "DeltaE0"]}
