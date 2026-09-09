import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from backend.main import app as xafs_api

app = FastAPI(title="Open XAFS Workbench HF Demo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

app.mount("/api", xafs_api)

if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
