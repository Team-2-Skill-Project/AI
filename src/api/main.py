"""FastAPI application entry point for the unified SkillMatch service."""

import logging
from contextlib import asynccontextmanager

import groq
import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routers.cv_router import router as cv_router
from src.api.schemas.cv_schemas import ExtractionErrorResponse
from src.api.security import check_rate_limit, verify_api_key
from src.api.v1.routers import (
    matches_router,
    review_queue_router,
    router as interview_router,
)
from src.core.config import get_app_settings, settings
from src.core.redis import is_redis_available, redis_manager
from src.db.base import init_db
from src.middleware.llm_middleware import DynamicLLMMiddleware
from src.middleware.rate_limit_middleware import RateLimitMiddleware

load_dotenv()
logger = logging.getLogger(__name__)
app_settings = get_app_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize persistence and release shared resources on shutdown."""
    init_db()
    if is_redis_available():
        logger.info("Redis is available at %s", settings.REDIS_URL)
    else:
        logger.warning("Redis is unavailable; using local fallbacks where supported")
    yield
    redis_manager.close()


app = FastAPI(
    title="SkillMatch AI Services API",
    description=(
        "Production AI Services API for SkillMatch. The canonical AI-Serv5 CV "
        "extraction pipeline powers CV, matching, interview, and review features."
    ),
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Dynamic LLM request overrides are scoped to one request and never leak.
app.add_middleware(DynamicLLMMiddleware)

# Rate-limit feature endpoints centrally. The canonical CV router keeps its
# existing dependency-based limiter so its original contract remains intact.
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_allowed_origins,
    allow_credentials=app_settings.cors_allow_credentials,
    allow_methods=app_settings.cors_allowed_methods,
    allow_headers=app_settings.cors_allowed_headers,
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        detail = str(exc.detail.get("detail", exc.detail))
        error_code = str(exc.detail.get("error_code", "HTTP_ERROR"))
    else:
        detail = str(exc.detail)
        status_code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            413: "FILE_TOO_LARGE",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMIT_EXCEEDED",
            500: "INTERNAL_SERVER_ERROR",
        }
        error_code = status_code_map.get(exc.status_code, "HTTP_ERROR")

    return JSONResponse(
        status_code=exc.status_code,
        content=ExtractionErrorResponse(detail=detail, error_code=error_code).model_dump(),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    detail = "; ".join(
        f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()
    )
    return JSONResponse(
        status_code=422,
        content=ExtractionErrorResponse(detail=detail, error_code="VALIDATION_ERROR").model_dump(),
    )


@app.exception_handler(groq.AuthenticationError)
async def groq_auth_exception_handler(_: Request, __: groq.AuthenticationError):
    return JSONResponse(
        status_code=401,
        content={
            "error": "LLM_AUTHENTICATION_ERROR",
            "detail": "Invalid or expired Groq API key. Configure GROQ_API_KEY or provide a request-level LLM token.",
        },
    )


@app.exception_handler(groq.RateLimitError)
async def groq_rate_limit_exception_handler(_: Request, __: groq.RateLimitError):
    return JSONResponse(
        status_code=429,
        content={
            "error": "LLM_RATE_LIMIT_ERROR",
            "detail": "Groq rate limit exceeded. Please retry after a brief delay.",
        },
    )


@app.exception_handler(groq.GroqError)
async def groq_gateway_exception_handler(_: Request, exc: groq.GroqError):
    return JSONResponse(
        status_code=502,
        content={
            "error": "LLM_GATEWAY_ERROR",
            "detail": f"Error communicating with LLM provider: {exc}",
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "error_code": "INTERNAL_SERVER_ERROR",
            "detail": "An unexpected internal server error occurred.",
        },
    )


# CV routes already carry the stable /api/v1/cv prefix from AI-Serv5.
app.include_router(cv_router, dependencies=[Depends(check_rate_limit), Depends(verify_api_key)])

# The rest of the feature routes use the shared version prefix and inherit the
# global rate limiter. API-key protection is applied consistently here too.
for feature_router in (interview_router, matches_router, review_queue_router):
    app.include_router(
        feature_router,
        prefix=settings.API_V1_STR,
        dependencies=[Depends(verify_api_key)],
    )


# Ensure database-backed feature routes work for TestClient and simple local
# runs even when the server lifespan is not explicitly entered.
init_db()


@app.get("/health", tags=["System Health"], summary="Health Check")
async def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "active_model": settings.LLM_MODEL,
        "redis": {
            "status": "connected" if is_redis_available() else "unavailable",
            "url": settings.REDIS_URL,
        },
        "features": {
            "cv_profile_extraction": "active",
            "skill_gap_analysis": "active",
            "interview_coach": "active",
            "review_queue": "active",
        },
    }


@app.get("/", tags=["Root"], summary="API Root")
async def root():
    return {
        "message": "Welcome to SkillMatch AI Services API",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
        "version": settings.VERSION,
    }


if __name__ == "__main__":
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
