from __future__ import annotations
from functools import lru_cache

from src.core.config import get_app_settings
from src.cv_extractor.document_loader import DocumentLoader
from src.cv_extractor.llm_extractor import LLMExtractor
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.job_extractor.pipeline import JobExtractionPipeline
from src.taxonomy.taxonomy_manager import TaxonomyManager


@lru_cache
def get_cv_pipeline() -> CVExtractionPipeline:
    """
    Returns a cached singleton instance of the CVExtractionPipeline.
    Injects the centralized TaxonomyManager and DocumentLoader.
    """
    app_settings = get_app_settings()
    taxonomy = TaxonomyManager(seed_file_path=app_settings.taxonomy_path)
    loader = DocumentLoader()
    extractor = LLMExtractor()

    return CVExtractionPipeline(
        taxonomy_manager=taxonomy,
        document_loader=loader,
        llm_extractor=extractor,
    )


@lru_cache
def get_job_pipeline() -> JobExtractionPipeline:
    """
    Returns a cached singleton instance of the JobExtractionPipeline.
    Reuses the same TaxonomyManager singleton — no duplicate loads.
    """
    app_settings = get_app_settings()
    taxonomy = TaxonomyManager(seed_file_path=app_settings.taxonomy_path)
    return JobExtractionPipeline(taxonomy_manager=taxonomy)
