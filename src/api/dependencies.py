from __future__ import annotations
from functools import lru_cache

from src.core.config import settings
from src.cv_extractor.document_loader import DocumentLoader
from src.cv_extractor.llm_extractor import LLMExtractor
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.job_extractor.pipeline import JobExtractionPipeline
from src.taxonomy.taxonomy_manager import TaxonomyManager
from src.taxonomy.skill_registry_resolver import SkillRegistryResolver


@lru_cache
def get_cv_pipeline() -> CVExtractionPipeline:
    """
    Returns a cached singleton instance of the CVExtractionPipeline.
    Injects the centralized TaxonomyManager and DocumentLoader.
    """
    taxonomy = TaxonomyManager(seed_file_path=settings.TAXONOMY_PATH)
    registry = SkillRegistryResolver(taxonomy)
    loader = DocumentLoader()
    extractor = LLMExtractor()

    return CVExtractionPipeline(
        taxonomy_manager=taxonomy,
        document_loader=loader,
        llm_extractor=extractor,
        skill_registry_resolver=registry,
    )


@lru_cache
def get_job_pipeline() -> JobExtractionPipeline:
    """
    Returns a cached singleton instance of the JobExtractionPipeline.
    Reuses the same TaxonomyManager singleton — no duplicate loads.
    """
    taxonomy = TaxonomyManager(seed_file_path=settings.TAXONOMY_PATH)
    return JobExtractionPipeline(
        taxonomy_manager=taxonomy,
        skill_registry_resolver=SkillRegistryResolver(taxonomy),
    )
