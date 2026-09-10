import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from src.api.dependencies import get_cv_pipeline
from src.api.schemas.cv_schemas import CVJobResponse, ExtractionErrorResponse, JobStatus
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.models.candidate import Candidate
from src.schemas.cv import ExtractTextRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cv", tags=["CV Profile Extraction"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit

# In-memory background job store for pollable CV extraction jobs
_cv_jobs: dict[str, dict[str, Any]] = {}


def _run_cv_background_extraction(
    job_id: str,
    temp_file_path: str,
    temp_dir: str,
    candidate_id: str | None,
    pipeline: CVExtractionPipeline,
):
    """Worker task that executes CV extraction in a background thread."""
    try:
        _cv_jobs[job_id]["status"] = JobStatus.PROCESSING
        candidate_profile = pipeline.extract_from_file(
            file_path=temp_file_path,
            candidate_id=candidate_id
        )
        _cv_jobs[job_id]["status"] = JobStatus.COMPLETED
        _cv_jobs[job_id]["result"] = candidate_profile
    except ValueError as ve:
        logger.warning(f"Background CV extraction value error for job {job_id}: {ve}")
        _cv_jobs[job_id]["status"] = JobStatus.FAILED
        _cv_jobs[job_id]["error"] = str(ve)
        _cv_jobs[job_id]["error_code"] = "EXTRACTION_FAILED"
    except Exception as e:
        logger.error(f"Background CV extraction error for job {job_id}: {e}", exc_info=True)
        _cv_jobs[job_id]["status"] = JobStatus.FAILED
        _cv_jobs[job_id]["error"] = f"An error occurred while processing the CV: {e!s}"
        _cv_jobs[job_id]["error_code"] = "INTERNAL_SERVER_ERROR"
    finally:
        try:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


@router.post(
    "/extract-file",
    response_model=Candidate,
    status_code=status.HTTP_200_OK,
    summary="Extract Structured Profile from CV File (Direct)",
    description=(
        "Upload a digital CV/Resume file (PDF, DOCX, or TXT). "
        "Processes the file without blocking the FastAPI event loop via background thread pool."
    ),
    responses={
        200: {"description": "Successfully extracted and normalized candidate profile", "model": Candidate},
        400: {"description": "Invalid or unsupported file format", "model": ExtractionErrorResponse},
        413: {"description": "File size exceeds allowed limit", "model": ExtractionErrorResponse},
        422: {"description": "Validation error in file input", "model": ExtractionErrorResponse},
        500: {"description": "Internal processing error during extraction", "model": ExtractionErrorResponse},
    },
)
async def extract_cv_file(
    file: UploadFile = File(..., description="CV file to upload (PDF, DOCX, or TXT)"),
    candidate_id: str | None = Form(None, description="Optional custom candidate ID (e.g. cand_001)"),
    pipeline: CVExtractionPipeline = Depends(get_cv_pipeline),
):
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "No filename provided in upload request.", "error_code": "NO_FILENAME"}
        )

    # Sanitize and extract extension
    raw_filename = Path(file.filename).name
    ext = Path(raw_filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        if ext == ".doc":
            detail_msg = "Legacy '.doc' format is not supported. Please convert your CV to modern '.docx' or '.pdf' before uploading."
        else:
            detail_msg = f"Unsupported file format: '{ext}'. Allowed formats are: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": detail_msg, "error_code": "UNSUPPORTED_FILE_TYPE"}
        )

    # Prevent path traversal by generating a secure server-side random filename inside temp_dir
    temp_dir = tempfile.mkdtemp(prefix="cv_upload_")
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    temp_file_path = os.path.join(temp_dir, safe_filename)

    try:
        # Enforce upload size limit using chunked reading
        CHUNK_SIZE = 1024 * 1024  # 1 MB chunk
        total_bytes = 0

        with open(temp_file_path, "wb") as buffer:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail={
                            "detail": f"File size exceeds maximum allowed limit of {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB.",
                            "error_code": "FILE_TOO_LARGE"
                        }
                    )
                buffer.write(chunk)

        # Ensure file is not empty
        if total_bytes == 0 or os.path.getsize(temp_file_path) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"detail": "The uploaded file is empty (0 bytes).", "error_code": "EMPTY_FILE"}
            )

        # Execute extraction non-blockingly on worker thread pool
        candidate_profile = await asyncio.to_thread(
            pipeline.extract_from_file,
            file_path=temp_file_path,
            candidate_id=candidate_id
        )
        return candidate_profile

    except HTTPException:
        raise
    except ValueError as ve:
        logger.warning(f"CV extraction value error: {ve}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": str(ve), "error_code": "EXTRACTION_FAILED"}
        )
    except Exception as e:
        logger.error(f"Unexpected error during CV extraction: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"detail": f"An error occurred while processing the CV: {e!s}", "error_code": "INTERNAL_SERVER_ERROR"}
        )
    finally:
        # Secure cleanup of temporary files
        try:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


@router.post(
    "/extract-file-async",
    response_model=CVJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit CV File for Async Background Extraction",
    description="Enqueues a CV extraction task as an async background job (as required by README.md:66). Returns a pollable job_id.",
    responses={
        202: {"description": "Job successfully queued", "model": CVJobResponse},
        400: {"description": "Invalid or unsupported file format", "model": ExtractionErrorResponse},
        413: {"description": "File size exceeds allowed limit", "model": ExtractionErrorResponse},
    },
)
async def extract_cv_file_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="CV file to upload (PDF, DOCX, or TXT)"),
    candidate_id: str | None = Form(None, description="Optional custom candidate ID (e.g. cand_001)"),
    pipeline: CVExtractionPipeline = Depends(get_cv_pipeline),
):
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "No filename provided in upload request.", "error_code": "NO_FILENAME"}
        )

    raw_filename = Path(file.filename).name
    ext = Path(raw_filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        if ext == ".doc":
            detail_msg = "Legacy '.doc' format is not supported. Please convert your CV to modern '.docx' or '.pdf' before uploading."
        else:
            detail_msg = f"Unsupported file format: '{ext}'. Allowed formats are: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": detail_msg, "error_code": "UNSUPPORTED_FILE_TYPE"}
        )

    temp_dir = tempfile.mkdtemp(prefix="cv_upload_async_")
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    temp_file_path = os.path.join(temp_dir, safe_filename)

    # Enforce size limit
    CHUNK_SIZE = 1024 * 1024
    total_bytes = 0

    with open(temp_file_path, "wb") as buffer:
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > MAX_UPLOAD_SIZE_BYTES:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail={
                        "detail": f"File size exceeds maximum allowed limit of {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB.",
                        "error_code": "FILE_TOO_LARGE"
                    }
                )
            buffer.write(chunk)

    if total_bytes == 0 or os.path.getsize(temp_file_path) == 0:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "The uploaded file is empty (0 bytes).", "error_code": "EMPTY_FILE"}
        )

    job_id = f"job_cv_{uuid.uuid4().hex[:12]}"
    _cv_jobs[job_id] = {
        "job_id": job_id,
        "status": JobStatus.QUEUED,
        "result": None,
        "error": None,
        "error_code": None,
    }

    background_tasks.add_task(
        _run_cv_background_extraction,
        job_id=job_id,
        temp_file_path=temp_file_path,
        temp_dir=temp_dir,
        candidate_id=candidate_id,
        pipeline=pipeline,
    )

    return CVJobResponse(job_id=job_id, status=JobStatus.QUEUED)


@router.get(
    "/jobs/{job_id}",
    response_model=CVJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll Background CV Extraction Job Status",
    description="Returns the status of a background CV extraction job (queued, processing, completed, failed) and candidate profile upon completion.",
    responses={
        200: {"description": "Current status of the job", "model": CVJobResponse},
        404: {"description": "Job not found", "model": ExtractionErrorResponse},
    },
)
async def get_job_status(job_id: str):
    job = _cv_jobs.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": f"Job '{job_id}' not found.", "error_code": "JOB_NOT_FOUND"}
        )
    return CVJobResponse(
        job_id=job["job_id"],
        status=job["status"],
        result=job.get("result"),
        error=job.get("error"),
        error_code=job.get("error_code"),
    )


@router.post(
    "/extract-text",
    response_model=Candidate,
    status_code=status.HTTP_200_OK,
    summary="Extract Structured Profile from Raw CV Text",
    description="Extracts a candidate profile from raw CV text using the canonical AI-Serv5 pipeline.",
    responses={
        200: {"description": "Successfully extracted candidate profile", "model": Candidate},
        400: {"description": "Invalid input text payload", "model": ExtractionErrorResponse},
        500: {"description": "Internal processing error during extraction", "model": ExtractionErrorResponse},
    },
)
async def extract_cv_text(
    payload: ExtractTextRequest,
    pipeline: CVExtractionPipeline = Depends(get_cv_pipeline),
):
    """Expose text extraction without introducing a second CV implementation."""
    if not payload.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "The CV text payload cannot be empty.", "error_code": "EMPTY_PAYLOAD"},
        )

    try:
        return await asyncio.to_thread(
            pipeline.extract_from_text,
            raw_text=payload.text,
            file_name=None,
            candidate_id=payload.candidate_id,
        )
    except ValueError as ve:
        logger.warning("CV text extraction value error: %s", ve)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": str(ve), "error_code": "EXTRACTION_FAILED"},
        ) from ve
    except Exception as exc:
        logger.error("Unexpected error during CV text extraction: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"detail": f"An error occurred while processing the CV text: {exc!s}", "error_code": "INTERNAL_SERVER_ERROR"},
        ) from exc
