from __future__ import annotations
"""
Skill normalization layer for the Job Description Understanding pipeline.

Wraps TaxonomyManager to map raw LLM-extracted skill tokens to canonical
skill_id / canonical_name / category from the platform skill taxonomy.

Reuses the singleton TaxonomyManager injected at pipeline construction time
to avoid a duplicate seed-file load.
"""

import logging
from typing import Any

from src.taxonomy.taxonomy_manager import TaxonomyManager
from src.taxonomy.skill_registry_resolver import SkillRegistryResolver

from .models import NormalizedSkill

logger = logging.getLogger(__name__)


def normalize_skills(
    raw_skills: list[dict[str, Any]],
    taxonomy: TaxonomyManager,
    skill_registry_resolver: SkillRegistryResolver | None = None,
) -> list[NormalizedSkill]:
    """
    Resolve a list of raw skill dicts (from LLM extraction) into NormalizedSkill objects.

    Each raw dict is expected to have keys: name, importance, required_level.

    When a registry resolver is supplied, each safe explicit term receives the
    shared persistent identity used by CV extraction. Without it, this remains
    compatible with taxonomy-only callers and leaves unknown terms unassigned.

    Args:
        raw_skills: List of raw skill dicts from _validate_raw().
        taxonomy:   Injected TaxonomyManager singleton.

    Returns:
        List of NormalizedSkill with skill_id and category populated where resolvable.
    """
    normalized: list[NormalizedSkill] = []

    for raw in raw_skills:
        raw_name: str = raw.get("name", "").strip()
        if not raw_name:
            continue

        # Drop blacklisted tokens (stop-words, URLs, noise)
        if taxonomy.is_blacklisted(raw_name):
            logger.debug("Dropped blacklisted skill token: '%s'", raw_name)
            continue

        if skill_registry_resolver:
            skill_id, canonical_name, category = skill_registry_resolver.resolve(
                raw_name,
                create_unknown=True,
            )
        else:
            skill_id, canonical_name, category = taxonomy.normalize_skill(raw_name, strict=True)

        normalized.append(
            NormalizedSkill(
                skill_id=skill_id,
                canonical_name=canonical_name or raw_name.strip(),
                category=category,
                raw_extracted=raw_name,
                importance=raw.get("importance", "important"),
                required_level=raw.get("required_level"),
            )
        )

    # Deduplicate by skill_id (or raw_extracted when skill_id is None)
    seen: set[str] = set()
    deduped: list[NormalizedSkill] = []
    for skill in normalized:
        dedup_key = skill.skill_id if skill.skill_id else skill.raw_extracted.lower()
        if dedup_key not in seen:
            seen.add(dedup_key)
            deduped.append(skill)

    logger.debug(
        "Normalized %d raw skills → %d unique skills (%d resolved to taxonomy)",
        len(raw_skills),
        len(deduped),
        sum(1 for s in deduped if s.skill_id is not None),
    )
    return deduped
