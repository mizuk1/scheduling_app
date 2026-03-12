from fastapi import FastAPI

from app.api.router import api_router
from app.db.init_db import init_db

app = FastAPI(title="Scheduling App API")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


app.include_router(api_router)
