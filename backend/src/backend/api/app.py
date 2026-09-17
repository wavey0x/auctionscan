from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .db import Database, load_cors_origins
from .routes.auctions import router as auctions_router
from .routes.health import router as health_router
from .routes.reference import router as reference_router
from .routes.rounds import router as rounds_router
from .routes.search import router as search_router
from .routes.takers import router as takers_router
from .routes.takes import router as takes_router
from .routes.tx import router as tx_router


def create_app(*, db_path: str | None = None) -> FastAPI:
    app = FastAPI(
        title="Auctionscan API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.db = Database(db_path=db_path)
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=load_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_router = APIRouter(prefix="/api")
    api_router.include_router(health_router)
    api_router.include_router(reference_router)
    api_router.include_router(rounds_router)
    api_router.include_router(auctions_router)
    api_router.include_router(takes_router)
    api_router.include_router(takers_router)
    api_router.include_router(search_router)
    api_router.include_router(tx_router)
    app.include_router(api_router)
    return app


app = create_app()
