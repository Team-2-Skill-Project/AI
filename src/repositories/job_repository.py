"""Abstract interface for the Job Repository.

Defines the generic job catalog contract. The repository is completely
candidate-agnostic and knows only about job postings and catalog status.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from src.schemas.job import JobPosting


class JobRepository(ABC):
    """Abstract base class for job data access."""

    @abstractmethod
    def get_active_jobs(
        self,
        work_mode: Optional[str] = None,
        location: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[JobPosting]:
        """
        Retrieves all currently active, non-expired job postings from the catalog.
        
        Args:
            work_mode: Optional filter by work mode (e.g. 'remote', 'hybrid', 'onsite')
            location: Optional filter substring by location
            limit: Maximum number of jobs to return (None for all)
            offset: Number of items to skip
        """
        pass

    @abstractmethod
    def get_job_by_id(self, job_id: str) -> Optional[JobPosting]:
        """
        Retrieves a single job posting by its unique identifier.
        
        Args:
            job_id: Unique job identifier
        """
        pass
