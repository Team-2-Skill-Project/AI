from typing import Optional
from pydantic import BaseModel, Field


class ExtractTextRequest(BaseModel):
    text: str = Field(..., description="Raw text of the CV to extract")
    candidate_id: Optional[str] = Field(None, description="Optional custom candidate ID")


class ExtractionErrorResponse(BaseModel):
    detail: str = Field(..., description="Description of the error that occurred")
    error_code: str = Field(
        ...,
        description="Standardized error code",
        json_schema_extra={"example": "UNSUPPORTED_FILE_TYPE"}
    )
