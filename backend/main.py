from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Open XAFS Workbench API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.get("/")
def root():
    return {
        "name": "Open XAFS Workbench API",
        "status": "running",
        "version": "0.1"
    }

@app.post("/upload")
async def upload_xafs(file: UploadFile = File(...)):
    data = await file.read()
    return {
        "filename": file.filename,
        "size": len(data),
        "message": "XAFS upload endpoint ready"
    }

@app.post("/process")
def process():
    return {
        "message": "XAFS processing API placeholder",
        "next": ["normalization", "chi(k)", "FT(R)"]
    }

@app.post("/fit")
def fit():
    return {
        "message": "EXAFS fitting API placeholder",
        "parameters": ["CN", "R", "sigma2", "DeltaE0"]
    }
