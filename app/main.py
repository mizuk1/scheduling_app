from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.db.init_db import init_db

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title="Scheduling App API")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


app.include_router(api_router)

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/weekly")
def weekly_page() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")
