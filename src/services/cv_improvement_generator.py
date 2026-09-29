"""Evidence-grounded CV presentation improvements with post-LLM validation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from src.ai.chains.cv_improvement import CVImprovementChain
from src.job_extractor.models import JobRequirementProfile
from src.models.candidate import Candidate
from src.models.cv_improvement import (
    CVImprovementResult,
    CVImprovementSuggestion,
    EvidenceCatalogItem,
    LLMImprovementDraft,
    LLMImprovementSuggestion,
    RewriteOpportunity,
    TargetReferenceCatalogItem,
)
from src.models.cv_job_gap import CVJobGapResult, EvidenceReference, SkillGapItem
from src.models.target_job import ResolvedTargetJob
from src.schemas.job import JobPosting
from src.services.cv_rewrite_opportunity_planner import RewriteOpportunityPlanner


class CVImprovementGenerationError(RuntimeError):
    """Raised after the centralized LLM draft fails twice."""


@dataclass(frozen=True)
class ValidationIssue:
    """A machine-readable reason a positive draft cannot be accepted."""

    code: str
    category: str


@dataclass(frozen=True)
class ResolvedDraftSuggestion:
    """A catalog-resolved draft plus its pre-validation contract issues."""

    suggestion: CVImprovementSuggestion
    issues: tuple[ValidationIssue, ...]


class CVImprovementValidator:
    """Conservatively accept only drafts anchored to candidate facts."""

    _NUMBER = re.compile(r"\b\d+(?:[,.]\d+)?%?\b")
    _DURATION = re.compile(r"\b\d+(?:[,.]\d+)?\s+(?:years?|months?)\b", re.IGNORECASE)
    _DATE = re.compile(r"\b(?:\d{4}(?:-\d{2}(?:-\d{2})?)?|\d{1,2}[/-]\d{1,2}[/-]\d{4})\b")
    _CAMEL_CASE = re.compile(r"(?<![A-Za-z])[a-z]+[A-Z][A-Za-z0-9]*\b")
    _PASCAL_CASE = re.compile(r"(?<![A-Za-z])[A-Z][a-z]+[A-Z][A-Za-z0-9]*\b")
    _ORG_SUFFIX = re.compile(r"\b[A-Z][A-Za-z0-9-]*(?:Corp|Inc|LLC|Ltd|Company)\b")

    def __init__(
        self,
        candidate: Candidate,
        target_job: JobPosting | JobRequirementProfile | ResolvedTargetJob,
        gap_result: CVJobGapResult,
    ):
        self.candidate = candidate
        self.target_job = target_job
        self.gap_result = gap_result
        self._references = self._candidate_references()
        self._reference_keys = {self._reference_key(item) for item in self._references}
        self._candidate_text = "\n".join(self._candidate_strings(candidate.model_dump(mode="json")))
        self._candidate_words = {
            token.strip(".").casefold()
            for token in re.findall(r"[\w+#.-]+", self._candidate_text)
            if token.strip(".")
        }
        self._candidate_numbers = set(self._NUMBER.findall(self._candidate_text))
        self._matched_requirements = self._requirement_names(item for item in self._all_skill_gaps() if item.matched)
        self._missing_requirements = self._requirement_names(item for item in self._all_skill_gaps() if not item.matched)
        self._job_responsibilities = {
            value.strip() for value in getattr(target_job, "responsibilities", []) if isinstance(value, str) and value.strip()
        }

    @staticmethod
    def _reference_key(reference: EvidenceReference) -> tuple[str, int | None, str | None, str]:
        return (reference.source_type, reference.source_index, reference.source_field, reference.text)

    @staticmethod
    def _candidate_strings(value: object) -> Iterable[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from CVImprovementValidator._candidate_strings(child)
        elif isinstance(value, list):
            for child in value:
                yield from CVImprovementValidator._candidate_strings(child)

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

    def _candidate_references(self) -> list[EvidenceReference]:
        references: list[EvidenceReference] = []
        for evidence in self.gap_result.candidate_evidence:
            references.extend(evidence.evidence)
        profile = self.candidate.candidate_profile
        for field_name, text in (("headline", profile.headline), ("bio", profile.bio)):
            reference = self._reference("profile", None, field_name, text)
            if reference:
                references.append(reference)
        for index, experience in enumerate(self.candidate.experiences):
            for field_name, text in (("job_title", experience.job_title), ("description", experience.description)):
                reference = self._reference("experience", index, field_name, text)
                if reference:
                    references.append(reference)
            for technology in experience.technologies:
                reference = self._reference("experience", index, "technologies", technology)
                if reference:
                    references.append(reference)
        for index, project in enumerate(self.candidate.projects):
            for field_name, text in (("title", project.title), ("description", project.description)):
                reference = self._reference("project", index, field_name, text)
                if reference:
                    references.append(reference)
            for technology in project.technologies:
                reference = self._reference("project", index, "technologies", technology)
                if reference:
                    references.append(reference)
        for index, certificate in enumerate(self.candidate.certificates):
            reference = self._reference("certificate", index, "name", certificate.name)
            if reference:
                references.append(reference)
        for index, skill in enumerate(self.candidate.candidate_skills):
            fallback = self._reference("skills_section", index, "candidate_skills", skill.name)
            if fallback:
                references.append(fallback)
            for evidence in skill.evidence:
                reference = self._reference(evidence.type, index, evidence.section or "evidence", evidence.text)
                if reference:
                    references.append(reference)
        unique: dict[tuple[str, int | None, str | None, str], EvidenceReference] = {}
        for reference in references:
            unique.setdefault(self._reference_key(reference), reference)
        return list(unique.values())

    @property
    def references(self) -> list[EvidenceReference]:
        """Return the exact references eligible for catalog construction."""
        return list(self._references)

    def _all_skill_gaps(self) -> list[SkillGapItem]:
        return [*self.gap_result.required_skill_gaps, *self.gap_result.preferred_skill_gaps]

    @staticmethod
    def _requirement_names(items: Iterable[SkillGapItem]) -> set[str]:
        values: set[str] = set()
        for item in items:
            values.add(item.canonical_name)
            values.add(item.raw_requirement)
        return {value for value in values if value.strip()}

    @staticmethod
    def _contains_term(text: str, term: str) -> bool:
        return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags=re.IGNORECASE))

    def _contains_missing_requirement(self, text: str) -> bool:
        return any(self._contains_term(text, term) for term in self._missing_requirements)

    def _has_unprovided_numeric_fact(self, text: str) -> bool:
        if any(number not in self._candidate_numbers for number in self._NUMBER.findall(text)):
            return True
        return any(match.group(0) not in self._candidate_text for match in self._DURATION.finditer(text)) or any(
            match.group(0) not in self._candidate_text for match in self._DATE.finditer(text)
        )

    def _has_unanchored_named_entity(self, text: str) -> bool:
        # This generic guard catches invented vendor/employer-like names without
        # treating ordinary sentence casing as a factual claim.
        suspect_tokens = [
            *self._CAMEL_CASE.findall(text),
            *self._PASCAL_CASE.findall(text),
            *self._ORG_SUFFIX.findall(text),
        ]
        return any(token.casefold() not in self._candidate_words for token in suspect_tokens)

    def _references_are_known(self, references: list[EvidenceReference]) -> bool:
        return bool(references) and all(self._reference_key(item) in self._reference_keys for item in references)

    def _related_item_is_known(self, suggestion: CVImprovementSuggestion) -> bool:
        if suggestion.related_job_requirement is None:
            return True
        return (
            suggestion.related_job_requirement in self._matched_requirements
            or suggestion.related_job_requirement in self._job_responsibilities
        )

    @staticmethod
    def _meaningful_tokens(text: str) -> set[str]:
        return {token.casefold() for token in re.findall(r"\w+", text) if len(token) >= 4}

    def _responsibility_has_evidence_anchor(self, suggestion: CVImprovementSuggestion) -> bool:
        if suggestion.related_job_requirement not in self._job_responsibilities:
            return True
        target_tokens = self._meaningful_tokens(suggestion.related_job_requirement or "")
        evidence_tokens = set().union(
            *(self._meaningful_tokens(reference.text) for reference in suggestion.source_evidence_refs)
        )
        return bool(target_tokens & evidence_tokens)

    def validation_issues(self, suggestion: CVImprovementSuggestion) -> list[ValidationIssue]:
        """Classify rejection reasons without relaxing the acceptance rules."""
        issues: list[ValidationIssue] = []
        if suggestion.suggestion_type == "missing_requirement":
            issues.append(ValidationIssue("positive_missing_requirement", "grounding"))
        if not self._references_are_known(suggestion.source_evidence_refs):
            issues.append(ValidationIssue("unknown_evidence_reference", "grounding"))
        if suggestion.current_text is None:
            issues.append(ValidationIssue("missing_current_text", "format"))
        elif suggestion.current_text not in {
            reference.text for reference in suggestion.source_evidence_refs
        }:
            issues.append(ValidationIssue("current_text_mismatch", "format"))
        if not self._related_item_is_known(suggestion):
            issues.append(ValidationIssue("unsupported_target_reference", "grounding"))
        if not self._responsibility_has_evidence_anchor(suggestion):
            issues.append(ValidationIssue("unsupported_responsibility_alignment", "grounding"))
        if suggestion.grounding_status != "grounded":
            issues.append(ValidationIssue("not_marked_grounded", "format"))
        if suggestion.suggested_text is None or not suggestion.suggested_text.strip():
            issues.append(ValidationIssue("missing_suggested_text", "format"))
        else:
            if self._contains_missing_requirement(suggestion.suggested_text):
                issues.append(ValidationIssue("missing_requirement_inserted", "fabrication"))
            if self._has_unprovided_numeric_fact(suggestion.suggested_text):
                issues.append(ValidationIssue("unprovided_numeric_fact", "fabrication"))
            if self._has_unanchored_named_entity(suggestion.suggested_text):
                issues.append(ValidationIssue("unanchored_named_entity", "fabrication"))
        return issues

    def validate(self, suggestion: CVImprovementSuggestion) -> CVImprovementSuggestion | None:
        """Return a safe normalized suggestion, or reject it outright."""
        if self.validation_issues(suggestion):
            return None
        return suggestion.model_copy(update={"priority": self._priority(suggestion)})

    def _priority(self, suggestion: CVImprovementSuggestion) -> str:
        if suggestion.related_job_requirement in self._matched_requirements:
            matched = next(
                (
                    item
                    for item in self._all_skill_gaps()
                    if suggestion.related_job_requirement in {item.canonical_name, item.raw_requirement}
                ),
                None,
            )
            if matched and matched.requirement_type == "required" and matched.evidence_strength in {"listed", "unknown"}:
                return "high"
            if matched and matched.requirement_type == "required":
                return "medium"
        if suggestion.suggestion_type == "responsibility_alignment":
            return "high"
        return "low"


class CVImprovementCatalogBuilder:
    """Build deterministic, current-input-only catalogs for the LLM contract."""

    @staticmethod
    def evidence_catalog(
        validator: CVImprovementValidator, gap_result: CVJobGapResult
    ) -> list[EvidenceCatalogItem]:
        skills_by_reference: dict[tuple[str, int | None, str | None, str], set[str]] = {}
        for skill in gap_result.candidate_evidence:
            for reference in skill.evidence:
                key = validator._reference_key(reference)
                skills_by_reference.setdefault(key, set()).add(skill.canonical_name)
        return [
            EvidenceCatalogItem(
                evidence_id=f"E{index}",
                source_section=reference.source_type,
                source_index=reference.source_index,
                source_field=reference.source_field,
                text=reference.text,
                supported_skills=sorted(skills_by_reference.get(validator._reference_key(reference), set())),
            )
            for index, reference in enumerate(validator.references, start=1)
        ]

    @staticmethod
    def target_catalog(gap_result: CVJobGapResult) -> list[TargetReferenceCatalogItem]:
        entries: list[TargetReferenceCatalogItem] = []
        entries.extend(
            TargetReferenceCatalogItem(
                reference_id=f"R{index}",
                reference_type="required_skill",
                text=item.raw_requirement,
                canonical_name=item.canonical_name,
                matched=item.matched,
            )
            for index, item in enumerate(gap_result.required_skill_gaps, start=1)
        )
        entries.extend(
            TargetReferenceCatalogItem(
                reference_id=f"P{index}",
                reference_type="preferred_skill",
                text=item.raw_requirement,
                canonical_name=item.canonical_name,
                matched=item.matched,
            )
            for index, item in enumerate(gap_result.preferred_skill_gaps, start=1)
        )
        entries.extend(
            TargetReferenceCatalogItem(
                reference_id=f"RESP{index}",
                reference_type="responsibility",
                text=item.responsibility,
                canonical_name=item.responsibility,
            )
            for index, item in enumerate(gap_result.responsibility_alignment, start=1)
        )
        return entries


class CatalogDraftResolver:
    """Resolve opaque LLM IDs into the existing strict validator input model."""

    def __init__(
        self,
        evidence_catalog: list[EvidenceCatalogItem],
        target_catalog: list[TargetReferenceCatalogItem],
    ) -> None:
        self._evidence = {
            item.evidence_id: EvidenceReference(
                source_type=item.source_section,
                source_index=item.source_index,
                source_field=item.source_field,
                text=item.text,
            )
            for item in evidence_catalog
        }
        self._target = {item.reference_id: item for item in target_catalog}

    def resolve(self, draft: LLMImprovementSuggestion) -> ResolvedDraftSuggestion:
        issues: list[ValidationIssue] = []
        references: list[EvidenceReference] = []
        if draft.evidence_ids:
            for evidence_id in draft.evidence_ids:
                reference = self._evidence.get(evidence_id)
                if reference is None:
                    issues.append(ValidationIssue("invalid_evidence_id", "grounding"))
                else:
                    references.append(reference)
        elif draft.source_evidence_refs:
            references = list(draft.source_evidence_refs)
        else:
            issues.append(ValidationIssue("missing_evidence_id", "format"))

        related_requirement = draft.related_job_requirement
        if draft.target_requirement_ids:
            if len(draft.target_requirement_ids) != 1:
                issues.append(ValidationIssue("ambiguous_target_reference", "format"))
            else:
                target = self._target.get(draft.target_requirement_ids[0])
                if target is None:
                    issues.append(ValidationIssue("invalid_target_reference_id", "grounding"))
                elif target.reference_type != "responsibility" and not target.matched:
                    issues.append(ValidationIssue("unsupported_target_reference", "grounding"))
                else:
                    related_requirement = target.canonical_name or target.text

        suggestion = CVImprovementSuggestion(
            suggestion_type=draft.suggestion_type,
            priority=draft.priority,
            target_section=draft.target_section,
            source_evidence_refs=references,
            current_text=draft.current_text,
            suggested_text=draft.suggested_text,
            reason=draft.reason,
            related_job_requirement=related_requirement,
            grounding_status=draft.grounding_status,
        )
        return ResolvedDraftSuggestion(suggestion=suggestion, issues=tuple(issues))

    def has_exact_current_text(self, draft: LLMImprovementSuggestion) -> bool:
        return bool(draft.current_text) and any(reference.text == draft.current_text for reference in self._evidence.values())


class CVImprovementUsefulnessFilter:
    """Reject generic low-value rewrites after factual validation."""

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[\w+#.-]+", text.casefold())

    def is_useful(self, suggestion: CVImprovementSuggestion, validator: CVImprovementValidator) -> bool:
        if not suggestion.current_text or not suggestion.suggested_text:
            return False
        current = self._tokens(suggestion.current_text)
        proposed = self._tokens(suggestion.suggested_text)
        if current == proposed:
            return False
        current_terms, proposed_terms = set(current), set(proposed)
        added, removed = proposed_terms - current_terms, current_terms - proposed_terms
        requirement = suggestion.related_job_requirement
        if requirement and validator._contains_term(suggestion.suggested_text, requirement) and not validator._contains_term(
            suggestion.current_text, requirement
        ):
            return True
        if len(added) >= 2:
            return True
        if not added and not removed and len(current) >= 5:
            return SequenceMatcher(a=current, b=proposed).ratio() < 0.85
        return False


class OpportunityDraftBoundary:
    """Enforce a selected opportunity's local candidate-fact envelope."""

    _NUMBER = re.compile(r"\b\d+(?:[,.]\d+)?%?\b")
    _WORD = re.compile(r"[A-Za-z0-9+#]+(?:[.-][A-Za-z0-9+#]+)*")
    # These are language glue and generic presentation-verb forms, not role- or
    # skill-specific vocabulary. Concrete terms must still appear in the selected
    # source text or its allowed concepts.
    _NONFACTUAL_WORDS = frozenset(
        {
            "a", "an", "the", "and", "or", "to", "of", "in", "on", "for", "with", "by", "from", "as", "at", "into", "through", "using", "while",
            "build", "built", "building", "develop", "developed", "developing",
        }
    )

    def __init__(
        self,
        opportunities: list[RewriteOpportunity],
        target_catalog: list[TargetReferenceCatalogItem],
    ) -> None:
        self._opportunities = {item.opportunity_id: item for item in opportunities}
        self._targets = {item.reference_id: item for item in target_catalog}

    def validation_issues(
        self,
        raw: LLMImprovementSuggestion,
        suggestion: CVImprovementSuggestion,
    ) -> list[ValidationIssue]:
        # Legacy in-process drafts are retained for the existing internal test doubles.
        if raw.source_evidence_refs:
            return []
        if not raw.opportunity_id:
            return [ValidationIssue("missing_opportunity_id", "format")]
        opportunity = self._opportunities.get(raw.opportunity_id)
        if opportunity is None:
            return [ValidationIssue("invalid_opportunity_id", "grounding")]
        issues: list[ValidationIssue] = []
        if raw.evidence_ids != [opportunity.evidence_id]:
            issues.append(ValidationIssue("opportunity_evidence_mismatch", "grounding"))
        allowed_targets = {*opportunity.target_requirement_ids, *opportunity.responsibility_ids}
        if any(value not in allowed_targets for value in raw.target_requirement_ids):
            issues.append(ValidationIssue("opportunity_target_mismatch", "grounding"))
        if suggestion.current_text != opportunity.current_text:
            issues.append(ValidationIssue("opportunity_current_text_mismatch", "format"))
        if suggestion.suggested_text:
            local_numbers = set(self._NUMBER.findall(opportunity.current_text))
            if any(value not in local_numbers for value in self._NUMBER.findall(suggestion.suggested_text)):
                issues.append(ValidationIssue("opportunity_unprovided_numeric_fact", "fabrication"))
            if self._has_unsupported_local_content(suggestion.suggested_text, opportunity):
                issues.append(ValidationIssue("opportunity_unsupported_local_fact", "fabrication"))
            allowed_concepts = {value.casefold() for value in opportunity.allowed_supported_concepts}
            for target in self._targets.values():
                if not target.canonical_name or not CVImprovementValidator._contains_term(suggestion.suggested_text, target.canonical_name):
                    continue
                if CVImprovementValidator._contains_term(opportunity.current_text, target.canonical_name):
                    continue
                if target.canonical_name.casefold() not in allowed_concepts:
                    issues.append(ValidationIssue("opportunity_unsupported_target_fact", "fabrication"))
                    break
        return issues

    @classmethod
    def _stem(cls, value: str) -> str:
        token = value.casefold()
        for suffix in ("ing", "ed", "es", "s"):
            if token.endswith(suffix) and len(token) > len(suffix) + 3:
                return token[: -len(suffix)]
        return token

    @classmethod
    def _content_words(cls, text: str) -> set[str]:
        return {
            cls._stem(value)
            for value in cls._WORD.findall(text)
            if len(value) >= 4 and value.casefold() not in cls._NONFACTUAL_WORDS
        }

    def _has_unsupported_local_content(self, suggested_text: str, opportunity: RewriteOpportunity) -> bool:
        allowed_text = "\n".join([*opportunity.allowed_fact_texts, *opportunity.allowed_supported_concepts])
        allowed = self._content_words(allowed_text)
        return bool(self._content_words(suggested_text) - allowed)

    def has_exact_current_text(self, raw: LLMImprovementSuggestion) -> bool:
        return bool(raw.current_text) and any(item.current_text == raw.current_text for item in self._opportunities.values())


class CVImprovementGenerator:
    """Generate validated presentation suggestions from current candidate/job facts."""

    def __init__(self, chain: CVImprovementChain | None = None) -> None:
        self._chain = chain or CVImprovementChain()

    async def generate(
        self,
        candidate: Candidate,
        target_job: JobPosting | JobRequirementProfile | ResolvedTargetJob,
        gap_result: CVJobGapResult,
    ) -> CVImprovementResult:
        validator = CVImprovementValidator(candidate, target_job, gap_result)
        evidence_catalog = CVImprovementCatalogBuilder.evidence_catalog(validator, gap_result)
        target_catalog = CVImprovementCatalogBuilder.target_catalog(gap_result)
        opportunities = RewriteOpportunityPlanner().plan(gap_result, evidence_catalog, target_catalog)
        if not opportunities:
            return CVImprovementResult(
                candidate_id=candidate.candidate_id,
                job_id=getattr(target_job, "job_id", None),
                suggestions=self._missing_requirement_suggestions(gap_result),
            )
        resolver = CatalogDraftResolver(evidence_catalog, target_catalog)
        opportunity_boundary = OpportunityDraftBoundary(opportunities, target_catalog)
        usefulness_filter = CVImprovementUsefulnessFilter()
        try:
            draft = await self._chain.generate_draft(
                candidate, target_job, gap_result, evidence_catalog, target_catalog, opportunities
            )
        except Exception:
            try:
                draft = await self._chain.generate_draft(
                    candidate, target_job, gap_result, evidence_catalog, target_catalog, opportunities
                )
            except Exception as retry_error:
                raise CVImprovementGenerationError("CV improvement draft generation failed") from retry_error

        accepted: list[CVImprovementSuggestion] = []
        repairable: list[LLMImprovementSuggestion] = []
        repair_errors: list[dict[str, object]] = []
        rejected_for_fabrication = 0
        rejected_for_low_value = 0
        for index, raw_suggestion in enumerate(draft.suggestions):
            resolved = resolver.resolve(raw_suggestion)
            issues = [
                *resolved.issues,
                *opportunity_boundary.validation_issues(raw_suggestion, resolved.suggestion),
                *validator.validation_issues(resolved.suggestion),
            ]
            if any(issue.category == "fabrication" for issue in issues):
                rejected_for_fabrication += 1
                continue
            validated = validator.validate(resolved.suggestion) if not issues else None
            if validated is not None:
                if usefulness_filter.is_useful(validated, validator):
                    accepted.append(validated)
                else:
                    rejected_for_low_value += 1
                continue
            if self._is_repairable(raw_suggestion, issues, resolver, opportunity_boundary):
                repairable.append(raw_suggestion)
                repair_errors.append(
                    {"suggestion_index": index, "errors": [issue.code for issue in issues]}
                )

        initial_accepted_count = len(accepted)
        repaired_accepted_count = 0
        repair_attempt_count = 0
        if repairable:
            repair_attempt_count = 1
            repaired_draft = await self._repair_once(
                LLMImprovementDraft(suggestions=repairable), repair_errors, evidence_catalog, target_catalog, opportunities
            )
            for raw_suggestion in repaired_draft.suggestions[: len(repairable)]:
                resolved = resolver.resolve(raw_suggestion)
                issues = [
                    *resolved.issues,
                    *opportunity_boundary.validation_issues(raw_suggestion, resolved.suggestion),
                    *validator.validation_issues(resolved.suggestion),
                ]
                if any(issue.category == "fabrication" for issue in issues):
                    rejected_for_fabrication += 1
                    continue
                validated = validator.validate(resolved.suggestion) if not issues else None
                if validated is None:
                    continue
                if usefulness_filter.is_useful(validated, validator):
                    accepted.append(validated)
                    repaired_accepted_count += 1
                else:
                    rejected_for_low_value += 1

        missing = self._missing_requirement_suggestions(gap_result)
        return CVImprovementResult(
            candidate_id=candidate.candidate_id,
            job_id=getattr(target_job, "job_id", None),
            suggestions=[*missing, *accepted],
            rejected_suggestion_count=len(draft.suggestions) - initial_accepted_count - repaired_accepted_count,
            raw_draft_count=len(draft.suggestions),
            initial_accepted_count=initial_accepted_count,
            repair_attempt_count=repair_attempt_count,
            repaired_accepted_count=repaired_accepted_count,
            rejected_for_fabrication_count=rejected_for_fabrication,
            rejected_for_low_value_count=rejected_for_low_value,
        )

    async def _repair_once(
        self,
        draft: LLMImprovementDraft,
        validation_errors: list[dict[str, object]],
        evidence_catalog: list[EvidenceCatalogItem],
        target_catalog: list[TargetReferenceCatalogItem],
        opportunities: list[RewriteOpportunity],
    ) -> LLMImprovementDraft:
        try:
            return await self._chain.repair_draft(
                draft, validation_errors, evidence_catalog, target_catalog, opportunities
            )
        except Exception:
            return LLMImprovementDraft()

    @staticmethod
    def _is_repairable(
        raw_suggestion: LLMImprovementSuggestion,
        issues: list[ValidationIssue],
        resolver: CatalogDraftResolver,
        opportunity_boundary: OpportunityDraftBoundary,
    ) -> bool:
        if not issues or any(issue.category == "fabrication" for issue in issues):
            return False
        permitted = {"format"}
        safely_recoverable_grounding = {
            "unknown_evidence_reference",
            "invalid_evidence_id",
            "opportunity_evidence_mismatch",
        }
        if any(issue.category not in permitted and issue.code not in safely_recoverable_grounding for issue in issues):
            return False
        return resolver.has_exact_current_text(raw_suggestion) and opportunity_boundary.has_exact_current_text(raw_suggestion)

    @staticmethod
    def _missing_requirement_suggestions(gap_result: CVJobGapResult) -> list[CVImprovementSuggestion]:
        suggestions: list[CVImprovementSuggestion] = []
        for item in [*gap_result.required_skill_gaps, *gap_result.preferred_skill_gaps]:
            if item.matched:
                continue
            required = item.requirement_type == "required"
            requirement_kind = "required" if required else "preferred"
            suggestions.append(
                CVImprovementSuggestion(
                    suggestion_type="missing_requirement",
                    priority="high" if required else "medium",
                    target_section="skills",
                    reason=(
                        f"{item.canonical_name} is {requirement_kind} by the target job but is not evidenced in the current CV. "
                        "If you genuinely have this experience, add truthful evidence from a real role or project."
                    ),
                    related_job_requirement=item.canonical_name,
                    grounding_status="gap",
                )
            )
        return suggestions
