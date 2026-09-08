import os
import shutil
import tempfile
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from src.models.candidate import Candidate
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.api.dependencies import get_cv_pipeline
from src.api.schemas.cv_schemas import ExtractionErrorResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cv", tags=["CV Profile Extraction"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}


@router.post(
    "/extract-file",
    response_model=Candidate,
    status_code=status.HTTP_200_OK,
    summary="Extract Structured Profile from CV File",
    description=(
        "Upload a digital CV/Resume file (PDF, DOCX, or TXT). "
        "The pipeline extracts text directly, normalizes skills against the SkillMatch Taxonomy, "
        "links supporting evidence, computes confidence scores, and returns a verified candidate profile adhering to the DAY 1 Candidate Schema."
    ),
    responses={
        200: {"description": "Successfully extracted and normalized candidate profile", "model": Candidate},
        400: {"description": "Invalid or unsupported file format", "model": ExtractionErrorResponse},
        422: {"description": "Validation error in file input", "model": ExtractionErrorResponse},
        500: {"description": "Internal processing error during extraction", "model": ExtractionErrorResponse},
    },
)
async def extract_cv_file(
    file: UploadFile = File(..., description="CV file to upload (PDF, DOCX, or TXT)"),
    candidate_id: Optional[str] = Form(None, description="Optional custom candidate ID (e.g. cand_001)"),
    pipeline: CVExtractionPipeline = Depends(get_cv_pipeline),
):
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided in upload request."
        )

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format: '{ext}'. Allowed formats are: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Save uploaded file to a temporary file
    temp_dir = tempfile.mkdtemp(prefix="cv_upload_")
    temp_file_path = os.path.join(temp_dir, file.filename)

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Ensure file is not empty
        if os.path.getsize(temp_file_path) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded file is empty (0 bytes)."
            )

        # Run extraction pipeline
        candidate_profile = pipeline.extract_from_file(
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
            detail=str(ve)
        )
    except Exception as e:
        logger.error(f"Unexpected error during CV extraction: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while processing the CV: {str(e)}"
        )
    finally:
        # Cleanup temporary files
        try:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
