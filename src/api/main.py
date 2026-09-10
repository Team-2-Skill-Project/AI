import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routers.cv_router import router as cv_router
from src.api.schemas.cv_schemas import ExtractionErrorResponse
from src.api.security import check_rate_limit, verify_api_key
from src.core.config import get_app_settings

load_dotenv()

app_settings = get_app_settings()

app = FastAPI(
    title="SkillMatch AI Services API",
    description=(
        "Production AI Services API for SkillMatch platform.\n\n"
        "### Available Capabilities:\n"
        "- 📄 **CV Profile Extraction** (`/api/v1/cv/extract-file`)\n"
        "  Upload a digital CV document (PDF, DOCX, TXT) and extract structured candidate profiles adhering to the **DAY 1 Candidate Schema** with evidence linking and confidence scores."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Exception handlers ensuring all error responses adhere to ExtractionErrorResponse schema
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        detail = exc.detail.get("detail", str(exc.detail))
        error_code = exc.detail.get("error_code", "HTTP_ERROR")
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
        headers=getattr(exc, "headers", None)
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    detail = "; ".join([f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in errors])
    return JSONResponse(
        status_code=422,
        content=ExtractionErrorResponse(detail=detail, error_code="VALIDATION_ERROR").model_dump()
    )


# Secure, configurable CORS middleware for frontend / API consumers
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_allowed_origins,
    allow_credentials=app_settings.cors_allow_credentials,
    allow_methods=app_settings.cors_allowed_methods,
    allow_headers=app_settings.cors_allowed_headers,
)

# Register Feature Routers with rate limiting and API protection dependencies
app.include_router(
    cv_router,
    dependencies=[Depends(check_rate_limit), Depends(verify_api_key)]
)



@app.get("/health", tags=["System Health"], summary="Health Check")
async def health_check():
    return {
        "status": "healthy",
        "service": "SkillMatch AI Services",
        "version": "1.0.0",
        "features": {
            "cv_profile_extraction": "active"
        }
    }


@app.get("/", tags=["Root"], summary="API Root")
async def root():
    return {
        "message": "Welcome to SkillMatch AI Services API",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health"
    }


if __name__ == "__main__":
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
