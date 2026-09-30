from __future__ import annotations
"""FastAPI application entry point for the unified SkillMatch service."""

import logging
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core.security import verify_api_key
from src.api.v1.routers import api_router
from src.core.config import settings
from src.core.logging import setup_logging
from src.core.redis import is_redis_available, redis_manager
from src.db.base import init_db
from src.middleware.rate_limit_middleware import RateLimitMiddleware
from src.schemas.cv import ExtractionErrorResponse

load_dotenv()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize logging, persistence, and release shared resources on shutdown."""
    setup_logging()
    logger.info("Initializing SkillMatch service components...")

    init_db()

    yield

    logger.info("Releasing shared connection pools...")
    try:
        res = redis_manager.close()
        import inspect
        if inspect.isawaitable(res):
            await res
    except Exception as e:
        logger.warning(f"Error closing redis connection pool: {e}")
    logger.info("SkillMatch service shutdown completed.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Unified API server for CV profile extraction, job matching, interview coaching, and recommendations.",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

from fastapi.responses import RedirectResponse

@app.get(f"{settings.API_V1_STR}/docs", include_in_schema=False)
async def redirect_api_v1_docs():
    return RedirectResponse(url="/docs")

@app.get(f"{settings.API_V1_STR}/redoc", include_in_schema=False)
async def redirect_api_v1_redoc():
    return RedirectResponse(url="/redoc")

@app.get(f"{settings.API_V1_STR}/openapi.json", include_in_schema=False)
async def redirect_api_v1_openapi():
    return RedirectResponse(url="/openapi.json")

# Single Rate Limit Middleware instance
app.add_middleware(RateLimitMiddleware)

# CORS Middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=getattr(settings, "CORS_ORIGINS", ["*"]),
    allow_credentials=getattr(settings, "cors_allow_credentials", True),
    allow_methods=getattr(settings, "cors_allowed_methods", ["*"]),
    allow_headers=getattr(settings, "cors_allowed_headers", ["*"]),
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    first_err = exc.errors()[0] if exc.errors() else {}
    msg = first_err.get("msg", "Validation error")
    field = ".".join(str(loc) for loc in first_err.get("loc", []) if loc != "body")

    detail_msg = f"{msg} (field: {field})" if field else msg

    return JSONResponse(
        status_code=422,
        content=ExtractionErrorResponse(
            error="VALIDATION_ERROR",
            error_code="VALIDATION_ERROR",
            detail=detail_msg,
        ).model_dump(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        422: "UNPROCESSABLE_ENTITY",
        429: "RATE_LIMIT_EXCEEDED",
    }
    detail = exc.detail
    detail_error_code = detail.get("error_code") if isinstance(detail, dict) else None
    detail_message = detail.get("detail", detail) if isinstance(detail, dict) else detail
    error_code = detail_error_code or code_map.get(exc.status_code, "HTTP_ERROR")

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": error_code,
            "error_code": error_code,
            "detail": detail_message,
        },
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled Exception caught by global handler: %s", exc, exc_info=True)

    if isinstance(exc, ValueError):
        return JSONResponse(
            status_code=400,
            content={
                "error": "BAD_REQUEST",
                "error_code": "BAD_REQUEST",
                "detail": str(exc),
            },
        )

    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "error_code": "INTERNAL_SERVER_ERROR",
            "detail": "An unexpected internal server error occurred.",
        },
    )


# Mount aggregated API v1 router. All /api/v1 endpoints inherit API-key verification.
app.include_router(
    api_router,
    prefix=settings.API_V1_STR,
    dependencies=[Depends(verify_api_key)],
)

# Ensure database tables are initialized
init_db()



@app.get("/", tags=["System Health"], summary="Root Endpoint")
async def root():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs_url": "/docs",
    }


@app.get("/health", tags=["System Health"], summary="Health Check")
async def health_check():
    redis_avail = is_redis_available()
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "active_model": settings.parse_provider_and_model()[1],
        "features": {
            "job_description_understanding": "active",
        },
        "redis_connected": redis_avail,
        "redis": {
            "status": "connected" if redis_avail else "unavailable",
            "url": settings.REDIS_URL,
        },
    }


if __name__ == "__main__":
    uvicorn.run("src.api.main:app", host="127.0.0.1", port=8001, reload=True)
