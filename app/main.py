"""
PersonSearch API — application entrypoint.

Run locally:
    uvicorn app.main:app --reload --port 8000

With workenv:
    /home/samba/workenv/bin/python3 -m uvicorn app.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router
from app.config import settings
from app.middleware.audit import AuditMiddleware

# ── Structured logging setup ───────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        20 if not settings.debug else 10  # INFO or DEBUG
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger(__name__)

# ── Lifespan ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: "FastAPI"):
    logger.info(
        "app.startup",
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        ai_provider=settings.ai_provider,
    )
    yield
    logger.info("app.shutdown")


# ── App factory ────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Evidence-first professional profile discovery platform. "
        "Every claim is sourced, every output is labelled 'possible match'."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ── Middleware (order matters — outermost runs first) ──────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)

# ── Routes ─────────────────────────────────────────────────────────────────────
app.include_router(api_router, prefix="/api")


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/health", tags=["ops"], summary="Health check")
async def health() -> dict:
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
    }
