from functools import lru_cache

from src.core.config import get_app_settings
from src.core.llm_service import get_llm_service
from src.cv_extractor.document_loader import DocumentLoader
from src.cv_extractor.llm_extractor import LLMExtractor
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.taxonomy.taxonomy_manager import TaxonomyManager


@lru_cache
def get_cv_pipeline() -> CVExtractionPipeline:
    """
    Returns a cached singleton instance of the CVExtractionPipeline.
    Injects the centralized TaxonomyManager, DocumentLoader, and LLMService.
    """
    app_settings = get_app_settings()
    taxonomy = TaxonomyManager(seed_file_path=app_settings.taxonomy_path)
    loader = DocumentLoader()
    llm_service = get_llm_service()
    extractor = LLMExtractor(llm_service=llm_service)

    return CVExtractionPipeline(
        taxonomy_manager=taxonomy,
        document_loader=loader,
        llm_extractor=extractor,
    )
