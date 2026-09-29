"""Deterministic selection of local-evidence CV rewrite opportunities."""

from __future__ import annotations

import re

from src.models.cv_improvement import EvidenceCatalogItem, RewriteOpportunity, TargetReferenceCatalogItem
from src.models.cv_job_gap import CVJobGapResult, EvidenceReference


class RewriteOpportunityPlanner:
    """Select a small, current-job-specific set of safe rewrite candidates."""

    _METRIC = re.compile(r"\b\d+(?:[,.]\d+)?%")
    _STRENGTH_RANK = {
        "unknown": 0,
        "listed": 1,
        "contextual": 2,
        "corroborated": 3,
        "measured_context": 4,
    }
    _MAX_OPPORTUNITIES = 3

    @staticmethod
    def _reference_key(reference: EvidenceReference) -> tuple[str, int | None, str | None, str]:
        return (reference.source_type, reference.source_index, reference.source_field, reference.text)

    @staticmethod
    def _normalized(value: str) -> str:
        return re.sub(r"\s+", " ", value.casefold()).strip()

    @staticmethod
    def _contains_exact(text: str, term: str) -> bool:
        return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags=re.IGNORECASE))

    def plan(
        self,
        gap_result: CVJobGapResult,
        evidence_catalog: list[EvidenceCatalogItem],
        target_catalog: list[TargetReferenceCatalogItem],
    ) -> list[RewriteOpportunity]:
        """Return bounded opportunities based exclusively on current evidence."""
        strength_by_reference: dict[tuple[str, int | None, str | None, str], dict[str, str]] = {}
        for skill in gap_result.candidate_evidence:
            for reference in skill.evidence:
                strength_by_reference.setdefault(self._reference_key(reference), {})[skill.canonical_name.casefold()] = skill.strength

        matched_targets = [
            target
            for target in target_catalog
            if target.reference_type in {"required_skill", "preferred_skill"} and target.matched is True
        ]
        responsibility_evidence: dict[tuple[str, int | None, str | None, str], list[str]] = {}
        for index, alignment in enumerate(gap_result.responsibility_alignment, start=1):
            if alignment.status != "supported":
                continue
            for reference in alignment.evidence:
                responsibility_evidence.setdefault(self._reference_key(reference), []).append(f"RESP{index}")

        candidates: list[tuple[int, RewriteOpportunity]] = []
        seen_texts: set[str] = set()
        for evidence in evidence_catalog:
            reference = EvidenceReference(
                source_type=evidence.source_section,
                source_index=evidence.source_index,
                source_field=evidence.source_field,
                text=evidence.text,
            )
            key = self._reference_key(reference)
            supported = {value.casefold(): value for value in evidence.supported_skills}
            requirement_ids = [
                target.reference_id
                for target in matched_targets
                if target.canonical_name
                and target.canonical_name.casefold() in supported
                and self._contains_exact(evidence.text, target.canonical_name)
            ]
            responsibility_ids = responsibility_evidence.get(key, [])
            if not requirement_ids and not responsibility_ids:
                continue

            normalized_text = self._normalized(evidence.text)
            if normalized_text in seen_texts:
                continue
            source_is_contextual = (
                evidence.source_section in {"experience", "project"}
                and evidence.source_field in {"description", "technologies"}
            )
            is_bare_skill = normalized_text in {self._normalized(value) for value in supported.values()}
            if is_bare_skill or normalized_text.startswith("..."):
                continue

            relevant_strengths = strength_by_reference.get(key, {})
            strength = max(
                (relevant_strengths.get(value.casefold(), "listed") for value in supported.values()),
                key=lambda item: self._STRENGTH_RANK[item],
            )
            metrics = self._METRIC.findall(evidence.text)
            required_ids = [item.reference_id for item in matched_targets if item.reference_id in requirement_ids and item.reference_type == "required_skill"]
            preferred_ids = [item.reference_id for item in matched_targets if item.reference_id in requirement_ids and item.reference_type == "preferred_skill"]
            score = 0
            score += 40 if source_is_contextual else 8
            score += 30 if required_ids else 8 if preferred_ids else 0
            score += 20 if responsibility_ids else 0
            score += 15 if metrics else 0
            score += self._STRENGTH_RANK[strength] * 5
            if metrics:
                opportunity_type = "surface_existing_metric"
            elif evidence.source_section == "experience":
                opportunity_type = "clarify_existing_experience"
            elif evidence.source_section == "project":
                opportunity_type = "clarify_existing_project"
            elif source_is_contextual:
                opportunity_type = "strengthen_target_relevance"
            else:
                opportunity_type = "surface_supported_requirement"
            priority = (
                "high"
                if source_is_contextual and (required_ids or responsibility_ids)
                else "medium"
                if source_is_contextual or required_ids
                else "low"
            )
            concepts = sorted(
                value for name, value in supported.items() if any(
                    target.canonical_name and target.canonical_name.casefold() == name
                    for target in matched_targets
                )
            )
            reason = (
                "Contextual candidate evidence supports a current target requirement."
                if source_is_contextual
                else "A candidate skills-section entry contains a matched current target requirement."
            )
            if responsibility_ids:
                reason = "Candidate evidence deterministically supports a current target responsibility."
            elif metrics:
                reason = "Candidate evidence contains an existing measurable outcome relevant to the target."
            candidates.append(
                (
                    score,
                    RewriteOpportunity(
                        opportunity_id="",
                        evidence_id=evidence.evidence_id,
                        source_section=evidence.source_section,
                        source_index=evidence.source_index,
                        current_text=evidence.text,
                        target_requirement_ids=requirement_ids,
                        responsibility_ids=responsibility_ids,
                        evidence_strength=strength,  # type: ignore[arg-type]
                        opportunity_type=opportunity_type,  # type: ignore[arg-type]
                        priority=priority,  # type: ignore[arg-type]
                        reason=reason,
                        allowed_supported_concepts=concepts,
                        allowed_fact_texts=[evidence.text],
                        allowed_metrics=metrics,
                    ),
                )
            )
            seen_texts.add(normalized_text)

        ranked = sorted(candidates, key=lambda item: (-item[0], item[1].evidence_id))[: self._MAX_OPPORTUNITIES]
        return [opportunity.model_copy(update={"opportunity_id": f"O{index}"}) for index, (_, opportunity) in enumerate(ranked, start=1)]
