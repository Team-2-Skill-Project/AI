from __future__ import annotations
import logging
from typing import Optional
from functools import lru_cache

from src.models.candidate import Candidate
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.taxonomy.taxonomy_manager import TaxonomyManager
from src.cv_extractor.document_loader import DocumentLoader
from src.cv_extractor.llm_extractor import LLMExtractor
from src.core.config import settings

logger = logging.getLogger(__name__)


class CVService:
    """
    Service layer facade for CV Profile Extraction and Normalization.
    """

    def __init__(self, pipeline: Optional[CVExtractionPipeline] = None):
        if pipeline:
            self.pipeline = pipeline
        else:
            taxonomy = TaxonomyManager(seed_file_path=settings.TAXONOMY_PATH)
            loader = DocumentLoader()
            extractor = LLMExtractor()
            self.pipeline = CVExtractionPipeline(
                taxonomy_manager=taxonomy,
                document_loader=loader,
                llm_extractor=extractor,
            )

    def extract_from_file(self, file_path: str, candidate_id: Optional[str] = None) -> Candidate:
        """Extracts structured candidate profile from a local file path."""
        result = self.pipeline.extract_from_file(file_path=file_path, candidate_id=candidate_id)
        if isinstance(result, tuple):
            return result[0]
        return result

    async def extract_from_file_async(self, file_path: str, candidate_id: Optional[str] = None) -> Candidate:
        """Asynchronously extracts structured candidate profile from a local file path without blocking event loop."""
        import asyncio
        return await asyncio.to_thread(self.extract_from_file, file_path=file_path, candidate_id=candidate_id)

    def extract_from_text(self, raw_text: str, candidate_id: Optional[str] = None) -> Candidate:
        """Extracts structured candidate profile directly from raw text."""
        result = self.pipeline.extract_from_text(raw_text=raw_text, candidate_id=candidate_id)
        if isinstance(result, tuple):
            return result[0]
        return result

    async def extract_from_text_async(self, raw_text: str, candidate_id: Optional[str] = None) -> Candidate:
        """Asynchronously extracts structured candidate profile directly from raw text without blocking event loop."""
        import asyncio
        return await asyncio.to_thread(self.extract_from_text, raw_text=raw_text, candidate_id=candidate_id)


@lru_cache()
def get_cv_service() -> CVService:
    return CVService()


cv_service = get_cv_service()
