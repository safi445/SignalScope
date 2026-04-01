from __future__ import annotations

import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.orchestrator import ScannerOrchestrator
from app.routes import register_routes

def create_app(*, db_path: str) -> FastAPI:
    app = FastAPI(title="SignalScope", version="0.1.0")
    orchestrator = ScannerOrchestrator(db_path=db_path)
    templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "web", "templates"))

    static_dir = os.path.join(os.path.dirname(__file__), "..", "web", "static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.on_event("startup")
    async def _startup() -> None:
        await orchestrator.start()

    register_routes(app=app, orchestrator=orchestrator, templates=templates)

    return app

