from pydantic import BaseModel, Field


class ExtractionErrorResponse(BaseModel):
    detail: str = Field(..., description="Description of the error that occurred")
    error_code: str = Field(
        ...,
        description="Standardized error code",
        json_schema_extra={"example": "UNSUPPORTED_FILE_TYPE"}
    )
