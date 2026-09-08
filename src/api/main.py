import os
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.routers.cv_router import router as cv_router

load_dotenv()

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

# Enable CORS for frontend/API consumers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Feature Routers
app.include_router(cv_router)


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
