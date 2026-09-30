from __future__ import annotations

from functools import lru_cache

from src.core.config import settings
from src.cv_extractor.document_loader import DocumentLoader
from src.cv_extractor.llm_extractor import LLMExtractor
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.db.repositories.candidate_repository import DatabaseCandidateRepository
from src.db.repositories.job_repository import DatabaseJobRepository
from src.job_extractor.pipeline import JobExtractionPipeline
from src.services.cv_improvement_generator import CVImprovementGenerator
from src.services.cv_job_gap_analyzer import CVJobGapAnalyzer
from src.taxonomy.skill_registry_resolver import SkillRegistryResolver
from src.taxonomy.taxonomy_manager import TaxonomyManager


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


def get_database_candidate_repository() -> DatabaseCandidateRepository:
    """Create the persisted-candidate repository used by candidate-bound flows."""
    return DatabaseCandidateRepository()


def get_database_job_repository() -> DatabaseJobRepository:
    """Create the persisted-job repository used by target-job resolution."""
    return DatabaseJobRepository()


def get_cv_job_gap_analyzer() -> CVJobGapAnalyzer:
    return CVJobGapAnalyzer()


def get_cv_improvement_generator() -> CVImprovementGenerator:
    return CVImprovementGenerator()
