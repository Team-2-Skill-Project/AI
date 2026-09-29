from __future__ import annotations

import re
from collections.abc import Callable

from sqlalchemy.orm import Session

from src.db.base import SessionLocal
from .taxonomy_manager import TaxonomyManager


class SkillRegistryResolver:
    """Resolve trusted taxonomy names and persist valid open-world skills."""

    def __init__(
        self,
        taxonomy: TaxonomyManager,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self.taxonomy = taxonomy
        self._session_factory = session_factory
        self._bootstrapped = False

    @staticmethod
    def normalized_name(name: str) -> str:
        """Conservative case/spelling key; this performs no semantic matching."""
        # Preserve programming-language punctuation before removing harmless
        # spacing and separator differences (C++ must not collide with C#).
        normalized = name.casefold().replace("+", " plus ").replace("#", " sharp ")
        return re.sub(r"[^\w]+", "", normalized)

    def resolve(
        self,
        raw_name: str,
        *,
        create_unknown: bool,
        source_declared_aliases: tuple[str, ...] = (),
    ) -> tuple[str | None, str, str | None]:
        """Return stable identity for a safe explicit term, creating only on request."""
        if self.taxonomy.is_blacklisted(raw_name, is_explicit=True):
            return None, "", None

        cleaned = self.taxonomy.clean_skill_label(raw_name)
        normalized = self.normalized_name(cleaned)
        if not cleaned or not normalized or self.taxonomy.is_blacklisted(cleaned, is_explicit=True):
            return None, "", None

        from src.db.repositories.skill_registry_repository import SkillRegistryRepository

        session = self._session_factory()
        try:
            repository = SkillRegistryRepository(session)
            if not self._bootstrapped:
                repository.bootstrap_seed(self.taxonomy.get_all_skills(), self.normalized_name)
                self._bootstrapped = True

            existing = repository.find_by_normalized_name(normalized)
            if existing:
                skill_id_str = str(existing.skill_id)
                repository.add_trusted_aliases(
                    skill_id_str,
                    source_declared_aliases,
                    self.normalized_name,
                )
                category = str(existing.category) if existing.category else None
                return skill_id_str, str(existing.canonical_name), category

            # A known taxonomy item must retain the legacy, stable seed ID even
            # if the bootstrap database was initialized after this resolver.
            known = self.taxonomy.find_skill(cleaned)
            if known:
                repository.add_trusted_aliases(
                    known.skill_id,
                    source_declared_aliases,
                    self.normalized_name,
                )
                return known.skill_id, known.canonical_name, known.category

            if not create_unknown:
                return None, cleaned, None

            record = repository.create_observed(cleaned, normalized)
            rec_id_str = str(record.skill_id)
            repository.add_trusted_aliases(
                rec_id_str,
                source_declared_aliases,
                self.normalized_name,
            )
            rec_category = str(record.category) if record.category else None
            return rec_id_str, str(record.canonical_name), rec_category
        finally:
            session.close()
