from enum import Enum

from pydantic import BaseModel, Field

from src.models.candidate import Candidate


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class CVJobResponse(BaseModel):
    job_id: str = Field(..., description="Unique background job identifier")
    status: JobStatus = Field(default=JobStatus.QUEUED, description="Current status of the background extraction job")
    result: Candidate | None = Field(default=None, description="Extracted Candidate profile if status is completed")
    error: str | None = Field(default=None, description="Error message if status is failed")
    error_code: str | None = Field(default=None, description="Standardized error code if status is failed")


class ExtractionErrorResponse(BaseModel):
    detail: str = Field(..., description="Description of the error that occurred")
    error_code: str = Field(
        ...,
        description="Standardized error code",
        json_schema_extra={"example": "UNSUPPORTED_FILE_TYPE"}
    )
