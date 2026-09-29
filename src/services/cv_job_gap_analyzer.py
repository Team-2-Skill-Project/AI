"""Deterministic, evidence-first CV-to-job gap analysis.

The service intentionally consumes existing structured candidate and job data.
It does not call an LLM, mutate the Skill Registry, or produce candidate-facing
rewrite suggestions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Protocol

from src.job_extractor.models import JobRequirementProfile, NormalizedSkill
from src.models.candidate import Candidate, CandidateSkill, ExperienceItem
from src.models.cv_job_gap import (
    CVJobGapResult,
    EvidenceReference,
    ExperienceAlignment,
    ResponsibilityAlignment,
    RoleAlignment,
    SkillEvidence,
    SkillGapItem,
)
from src.models.target_job import ResolvedTargetJob
from src.schemas.job import JobPosting, SkillRequirement
from src.taxonomy.skill_registry_resolver import SkillRegistryResolver
from src.taxonomy.taxonomy_manager import TaxonomyManager


class SkillResolver(Protocol):
    def resolve(
        self,
        raw_name: str,
        *,
        create_unknown: bool,
        source_declared_aliases: tuple[str, ...] = (),
    ) -> tuple[str | None, str, str | None]: ...


@dataclass(frozen=True)
class _SkillIdentity:
    key: str
    skill_id: str | None
    canonical_name: str
    category: str | None


@dataclass
class _EvidenceAccumulator:
    identity: _SkillIdentity
    proficiency: str | None = None
    evidence: list[EvidenceReference] = field(default_factory=list)

    def add(self, reference: EvidenceReference) -> None:
        if reference not in self.evidence:
            self.evidence.append(reference)


class CVJobGapAnalyzer:
    """Compare a structured candidate with a structured job conservatively.

    A supplied Skill Registry ID is always the primary key.  If it is absent,
    the shared resolver is queried without creating registry records; unresolved
    terms fall back only to a normalized exact-name key.
    """

    def __init__(
        self,
        registry_resolver: SkillResolver | None = None,
        today_provider: Callable[[], date] = date.today,
    ) -> None:
        self._resolver = registry_resolver or SkillRegistryResolver(TaxonomyManager())
        self._today_provider = today_provider

    def analyze(
        self,
        candidate: Candidate,
        target_job: JobPosting | JobRequirementProfile | ResolvedTargetJob,
    ) -> CVJobGapResult:
        """Return internal comparison facts without modifying either input."""
        evidence_map = self._build_candidate_evidence(candidate)
        required = self._skill_gaps(getattr(target_job, "required_skills", []), "required", evidence_map)
        preferred = self._skill_gaps(getattr(target_job, "preferred_skills", []), "preferred", evidence_map)

        target_keys: set[str] = set()
        for skill in [*getattr(target_job, "required_skills", []), *getattr(target_job, "preferred_skills", [])]:
            identity = self._identity_for_requirement(skill)
            if identity is not None:
                target_keys.add(identity.key)
        candidate_evidence = [self._as_skill_evidence(item) for item in evidence_map.values()]
        extras = [
            self._as_skill_evidence(item)
            for key, item in evidence_map.items()
            if key not in target_keys
        ]

        return CVJobGapResult(
            candidate_id=candidate.candidate_id,
            job_id=getattr(target_job, "job_id", None),
            required_skill_gaps=required,
            preferred_skill_gaps=preferred,
            extra_candidate_skills=extras,
            candidate_evidence=candidate_evidence,
            experience_alignment=self._experience_alignment(candidate.experiences, target_job),
            role_alignment=self._role_alignment(candidate, target_job),
            responsibility_alignment=self._responsibility_alignment(candidate, target_job),
        )

    def _identity(self, name: str | None, skill_id: str | None, category: str | None = None) -> _SkillIdentity | None:
        clean_name = (name or "").strip()
        clean_id = str(skill_id).strip() if skill_id is not None and str(skill_id).strip() else None
        if clean_id:
            return _SkillIdentity(f"id:{clean_id.casefold()}", clean_id, clean_name or clean_id, category)
        if not clean_name:
            return None

        resolved_id, canonical_name, resolved_category = self._resolver.resolve(clean_name, create_unknown=False)
        if resolved_id:
            return _SkillIdentity(
                f"id:{resolved_id.casefold()}",
                resolved_id,
                canonical_name or clean_name,
                resolved_category or category,
            )
        normalized = SkillRegistryResolver.normalized_name(clean_name)
        if not normalized:
            return None
        return _SkillIdentity(f"name:{normalized}", None, canonical_name or clean_name, category)

    def _identity_for_requirement(self, requirement: object) -> _SkillIdentity | None:
        if isinstance(requirement, SkillRequirement):
            return self._identity(requirement.skill_name, requirement.skill_id, requirement.category)
        if isinstance(requirement, NormalizedSkill):
            return self._identity(requirement.canonical_name, requirement.skill_id, requirement.category)
        return self._identity(
            getattr(requirement, "canonical_name", None) or getattr(requirement, "skill_name", None),
            getattr(requirement, "skill_id", None),
            getattr(requirement, "category", None),
        )

    @staticmethod
    def _exact_term_in_text(term: str, text: str | None) -> bool:
        if not term or not text:
            return False
        return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags=re.IGNORECASE))

    @staticmethod
    def _reference(source_type: str, source_index: int | None, source_field: str, text: str | None) -> EvidenceReference | None:
        if not isinstance(text, str) or not text.strip():
            return None
        return EvidenceReference(
            source_type=source_type,
            source_index=source_index,
            source_field=source_field,
            text=text,
        )

    def _add_candidate_skill(
        self,
        evidence_map: dict[str, _EvidenceAccumulator],
        skill: CandidateSkill,
        index: int,
    ) -> None:
        identity = self._identity(skill.name, skill.skill_id)
        if identity is None:
            return
        item = evidence_map.setdefault(identity.key, _EvidenceAccumulator(identity, skill.proficiency))
        if item.proficiency is None:
            item.proficiency = skill.proficiency
        if skill.evidence:
            for evidence in skill.evidence:
                reference = self._reference(
                    evidence.type or "skills_section",
                    index,
                    evidence.section or "evidence",
                    evidence.text,
                )
                if reference:
                    item.add(reference)
        else:
            reference = self._reference("skills_section", index, "candidate_skills", skill.name)
            if reference:
                item.add(reference)

    def _add_declared_technology(
        self,
        evidence_map: dict[str, _EvidenceAccumulator],
        name: str,
        source_type: str,
        source_index: int,
        description: str | None,
    ) -> None:
        identity = self._identity(name, None)
        if identity is None:
            return
        item = evidence_map.setdefault(identity.key, _EvidenceAccumulator(identity))
        reference = self._reference(source_type, source_index, "technologies", name)
        if reference:
            item.add(reference)
        if self._exact_term_in_text(name, description):
            contextual = self._reference(source_type, source_index, "description", description)
            if contextual:
                item.add(contextual)

    def _add_contextual_references(
        self, candidate: Candidate, evidence_map: dict[str, _EvidenceAccumulator]
    ) -> None:
        """Attach only exact declared skill terms to existing free-text facts."""
        text_sources: list[tuple[str, int | None, str, str | None]] = [
            ("profile", None, "headline", candidate.candidate_profile.headline),
            ("profile", None, "bio", candidate.candidate_profile.bio),
        ]
        text_sources.extend(
            ("experience", index, "description", experience.description)
            for index, experience in enumerate(candidate.experiences)
        )
        text_sources.extend(
            ("project", index, "description", project.description)
            for index, project in enumerate(candidate.projects)
        )
        text_sources.extend(
            ("certificate", index, "name", certificate.name)
            for index, certificate in enumerate(candidate.certificates)
        )
        text_sources.extend(
            ("education", index, "field_of_study", education.field_of_study)
            for index, education in enumerate(candidate.educations)
        )

        for accumulator in evidence_map.values():
            for source_type, source_index, source_field, text in text_sources:
                if self._exact_term_in_text(accumulator.identity.canonical_name, text):
                    reference = self._reference(source_type, source_index, source_field, text)
                    if reference:
                        accumulator.add(reference)

    def _build_candidate_evidence(self, candidate: Candidate) -> dict[str, _EvidenceAccumulator]:
        evidence_map: dict[str, _EvidenceAccumulator] = {}
        for index, skill in enumerate(candidate.candidate_skills):
            self._add_candidate_skill(evidence_map, skill, index)
        for index, experience in enumerate(candidate.experiences):
            for technology in experience.technologies:
                self._add_declared_technology(
                    evidence_map, technology, "experience", index, experience.description
                )
        for index, project in enumerate(candidate.projects):
            for technology in project.technologies:
                self._add_declared_technology(evidence_map, technology, "project", index, project.description)
        self._add_contextual_references(candidate, evidence_map)
        return evidence_map

    @staticmethod
    def _evidence_strength(evidence: list[EvidenceReference]) -> str:
        if not evidence:
            return "unknown"
        contextual = [item for item in evidence if item.source_type in {"experience", "project"}]
        if contextual and any(re.search(r"\d[\d,.]*%?", item.text) for item in contextual):
            return "measured_context"
        distinct_sources = {(item.source_type, item.source_index) for item in evidence}
        if len(distinct_sources) >= 2:
            return "corroborated"
        if contextual:
            return "contextual"
        return "listed"

    def _as_skill_evidence(self, item: _EvidenceAccumulator) -> SkillEvidence:
        return SkillEvidence(
            skill_id=item.identity.skill_id,
            canonical_name=item.identity.canonical_name,
            category=item.identity.category,
            evidence=item.evidence,
            strength=self._evidence_strength(item.evidence),
        )

    def _skill_gaps(
        self,
        requirements: list[SkillRequirement] | list[NormalizedSkill],
        requirement_type: str,
        evidence_map: dict[str, _EvidenceAccumulator],
    ) -> list[SkillGapItem]:
        results: list[SkillGapItem] = []
        for requirement in requirements:
            identity = self._identity_for_requirement(requirement)
            if identity is None:
                continue
            candidate_item = evidence_map.get(identity.key)
            raw_requirement = getattr(requirement, "raw_extracted", None) or getattr(
                requirement, "skill_name", None
            ) or identity.canonical_name
            results.append(
                SkillGapItem(
                    skill_id=identity.skill_id,
                    canonical_name=identity.canonical_name,
                    category=identity.category,
                    raw_requirement=raw_requirement,
                    requirement_type=requirement_type,  # type: ignore[arg-type]
                    matched=candidate_item is not None,
                    candidate_proficiency=candidate_item.proficiency if candidate_item else None,
                    evidence_strength=self._evidence_strength(candidate_item.evidence) if candidate_item else "unknown",
                    evidence=candidate_item.evidence if candidate_item else [],
                )
            )
        return results

    @staticmethod
    def _year_month(value: str | None) -> tuple[int, int] | None:
        if not isinstance(value, str):
            return None
        match = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", value)
        if not match:
            return None
        year, month = (int(part) for part in match.groups())
        if not 1 <= month <= 12:
            return None
        return year, month

    @staticmethod
    def _merge_intervals(intervals: list[tuple[int, int]]) -> int:
        if not intervals:
            return 0
        total = 0
        current_start, current_end = sorted(intervals)[0]
        for start, end in sorted(intervals)[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
                continue
            total += current_end - current_start
            current_start, current_end = start, end
        return total + current_end - current_start

    @staticmethod
    def _number(value: object) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return None

    def _experience_alignment(
        self, experiences: list[ExperienceItem], target_job: JobPosting | JobRequirementProfile | ResolvedTargetJob
    ) -> ExperienceAlignment:
        minimum = self._number(getattr(target_job, "min_years_experience", None))
        maximum = self._number(getattr(target_job, "max_years_experience", None))
        intervals: list[tuple[int, int]] = []
        evidence: list[EvidenceReference] = []
        incomplete = False
        current_month = self._today_provider().year * 12 + self._today_provider().month

        for index, experience in enumerate(experiences):
            start = self._year_month(experience.start_date)
            end = self._year_month(experience.end_date)
            if start is None:
                incomplete = True
                continue
            if experience.is_current is True:
                end_month = current_month
            elif end is not None:
                end_month = end[0] * 12 + end[1]
            else:
                incomplete = True
                continue
            start_month = start[0] * 12 + start[1]
            if end_month <= start_month:
                incomplete = True
                continue
            bounded_end_month = min(end_month, current_month)
            if bounded_end_month <= start_month:
                incomplete = True
                continue
            intervals.append((start_month, bounded_end_month))
            for field_name, text in (("job_title", experience.job_title), ("start_date", experience.start_date), ("end_date", experience.end_date)):
                reference = self._reference("experience", index, field_name, text)
                if reference:
                    evidence.append(reference)

        known_years = round(self._merge_intervals(intervals) / 12, 2) if intervals else None
        coverage = "unavailable" if not experiences or not intervals else ("partial" if incomplete else "complete")
        if minimum is None and maximum is None:
            status = "not_specified"
        elif known_years is None:
            status = "unknown"
        elif maximum is not None and known_years > maximum:
            status = "above_maximum"
        elif minimum is not None and known_years < minimum:
            status = "unknown" if incomplete else "below_minimum"
        elif incomplete:
            status = "meets_minimum"
        elif maximum is not None:
            status = "within_range"
        else:
            status = "meets_minimum"
        return ExperienceAlignment(
            minimum_years=minimum,
            maximum_years=maximum,
            known_years=known_years,
            date_coverage=coverage,
            status=status,
            evidence=evidence,
        )

    @staticmethod
    def _normalized_role(value: str | None) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (value or "").casefold())).strip()

    def _role_alignment(
        self, candidate: Candidate, target_job: JobPosting | JobRequirementProfile | ResolvedTargetJob
    ) -> RoleAlignment:
        target_role = next(
            (
                value
                for value in (
                    getattr(target_job, "canonical_role", None),
                    getattr(target_job, "role", None),
                    getattr(target_job, "title", None),
                )
                if isinstance(value, str) and value.strip()
            ),
            None,
        )
        target_key = self._normalized_role(target_role)
        if not target_key:
            return RoleAlignment()
        candidates: list[tuple[str, int | None, str, str]] = []
        candidates.extend(("target_role", index, "target_roles", value) for index, value in enumerate(candidate.target_roles))
        candidates.extend(
            ("experience", index, "job_title", experience.job_title)
            for index, experience in enumerate(candidate.experiences)
        )
        if candidate.candidate_profile.headline:
            candidates.append(("profile", None, "headline", candidate.candidate_profile.headline))
        matching = [
            self._reference(source_type, index, field_name, value)
            for source_type, index, field_name, value in candidates
            if self._normalized_role(value) == target_key
        ]
        evidence = [item for item in matching if item]
        return RoleAlignment(
            target_role=target_role,
            status="aligned" if evidence else ("not_aligned" if candidates else "unknown"),
            evidence=evidence,
        )

    @staticmethod
    def _normalized_text(value: str | None) -> str:
        return re.sub(r"\s+", " ", (value or "").casefold()).strip()

    def _responsibility_alignment(
        self, candidate: Candidate, target_job: JobPosting | JobRequirementProfile | ResolvedTargetJob
    ) -> list[ResponsibilityAlignment]:
        responsibilities = getattr(target_job, "responsibilities", [])
        if not isinstance(responsibilities, list):
            return []
        source_texts: list[EvidenceReference] = []
        for index, experience in enumerate(candidate.experiences):
            reference = self._reference("experience", index, "description", experience.description)
            if reference:
                source_texts.append(reference)
        for index, project in enumerate(candidate.projects):
            reference = self._reference("project", index, "description", project.description)
            if reference:
                source_texts.append(reference)
        for index, skill in enumerate(candidate.candidate_skills):
            for evidence in skill.evidence:
                reference = self._reference(evidence.type, index, evidence.section or "evidence", evidence.text)
                if reference:
                    source_texts.append(reference)

        results: list[ResponsibilityAlignment] = []
        for responsibility in responsibilities:
            if not isinstance(responsibility, str) or not responsibility.strip():
                continue
            key = self._normalized_text(responsibility)
            matches = [reference for reference in source_texts if self._normalized_text(reference.text) == key]
            results.append(
                ResponsibilityAlignment(
                    responsibility=responsibility,
                    status="supported" if matches else "unknown",
                    evidence=matches,
                )
            )
        return results
