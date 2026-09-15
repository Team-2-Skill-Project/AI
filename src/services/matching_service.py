import json
from typing import Optional, List, Dict, Any, Union, Set
from src.ai.chains.match_explanation import MatchExplanationChain
from src.schemas.job import SkillRequirement, JobRequirementsPayload, JobPosting
from src.schemas.match import (
    SkillGapAnalysisRequest,
    SkillGapAnalysisResponse,
    SkillMatchItem,
    CandidateProfilePayload,
    QualificationStatus,
)

class MatchingService:
    """
    Service responsible for orchestrating Skill Gap Analysis, applying
    scoring rules, verifying threshold boundaries, and returning structured evaluations.
    """

    def __init__(self, chains: Optional[MatchExplanationChain] = None):
        self.chains = chains or MatchExplanationChain()

    def normalize_job_requirements(
        self,
        raw_reqs: Union[List[Any], JobRequirementsPayload, JobPosting, Dict[str, Any]]
    ) -> List[SkillRequirement]:
        """Converts raw job requirements into a standardized list of SkillRequirement instances."""
        if isinstance(raw_reqs, JobPosting):
            return raw_reqs.required_skills
        if isinstance(raw_reqs, JobRequirementsPayload):
            return raw_reqs.skills
        if isinstance(raw_reqs, dict):
            # Check for nested keys
            skills_data = raw_reqs.get("required_skills") or raw_reqs.get("skills") or raw_reqs.get("job_requirements")
            if skills_data and isinstance(skills_data, list):
                return [SkillRequirement.from_any(item) for item in skills_data]
            # Single dictionary representing a requirement
            if "skill_name" in raw_reqs or "name" in raw_reqs:
                return [SkillRequirement.from_any(raw_reqs)]
            return []
        if isinstance(raw_reqs, list):
            return [SkillRequirement.from_any(item) for item in raw_reqs]
        return []

    def format_candidate_profile_text(
        self,
        profile: Union[CandidateProfilePayload, Dict[str, Any], str]
    ) -> str:
        """Serializes candidate profile into structured readable text for LLM ingestion."""
        if isinstance(profile, str):
            return profile
        if isinstance(profile, CandidateProfilePayload):
            profile_dict = profile.model_dump()
        elif isinstance(profile, dict):
            profile_dict = profile
        else:
            profile_dict = {"raw": str(profile)}

        return json.dumps(profile_dict, indent=2)

    def apply_evaluation_rules(
        self,
        response: SkillGapAnalysisResponse,
        required_skills: List[SkillRequirement]
    ) -> SkillGapAnalysisResponse:
        """
        Enforces strict evaluation rules:
        1. For EVERY skill:
           - score in [0, 100]
           - is_matched == True if score >= 70, otherwise False
        2. Critical skills:
           - Identifies critical skills (marked is_critical=True or detected as core)
           - Skills with score < 70 added to missing_critical_skills
        3. Overall match score:
           - Weighted / mean average across all evaluated skills
        4. Overall Qualification verdict:
           - 'Qualified': Candidate matches >= 80% of critical skills with an overall average score >= 75
           - 'Partially Qualified': Candidate meets 50%–79% of requirements
           - 'Not Qualified': Major skill gaps in core requirements (< 50% total match)
        """
        # Build map of critical skill names (case-insensitive)
        critical_skill_names: Set[str] = {
            req.skill_name.lower().strip() for req in required_skills if req.is_critical
        }

        # If no skills were explicitly tagged is_critical, treat all required skills as core
        if not critical_skill_names and required_skills:
            critical_skill_names = {req.skill_name.lower().strip() for req in required_skills}

        updated_items: List[SkillMatchItem] = []
        missing_critical: List[str] = []
        matched_count = 0
        critical_total = 0
        critical_matched = 0

        for item in response.skill_breakdown:
            # Bound score between 0 and 100
            score = max(0.0, min(100.0, float(item.match_score)))
            is_matched = score >= 70.0
            if is_matched:
                matched_count += 1

            skill_key = item.skill_name.lower().strip()
            is_crit = skill_key in critical_skill_names

            if is_crit:
                critical_total += 1
                if is_matched:
                    critical_matched += 1
                else:
                    if item.skill_name not in missing_critical:
                        missing_critical.append(item.skill_name)

            updated_items.append(
                SkillMatchItem(
                    skill_name=item.skill_name,
                    required_proficiency=item.required_proficiency,
                    candidate_proficiency=item.candidate_proficiency,
                    match_score=score,
                    is_matched=is_matched,
                    skill_feedback=item.skill_feedback,
                    evidence_found=item.evidence_found,
                )
            )

        total_skills = len(updated_items)
        if total_skills > 0:
            avg_score = round(sum(i.match_score for i in updated_items) / total_skills, 1)
            total_match_rate = matched_count / total_skills
        else:
            avg_score = 0.0
            total_match_rate = 0.0

        if critical_total > 0:
            crit_match_rate = critical_matched / critical_total
        else:
            crit_match_rate = total_match_rate

        # Determine qualification verdict
        if crit_match_rate >= 0.80 and avg_score >= 75.0:
            verdict = QualificationStatus.QUALIFIED.value
        elif total_match_rate >= 0.50 or (50.0 <= avg_score < 75.0):
            verdict = QualificationStatus.PARTIALLY_QUALIFIED.value
        else:
            verdict = QualificationStatus.NOT_QUALIFIED.value

        response.skill_breakdown = updated_items
        response.overall_match_score = avg_score
        response.qualification_status = verdict
        response.missing_critical_skills = missing_critical

        return response

    def evaluate_match(
        self,
        candidate_profile: Any,
        job_requirements: Any,
        job_id: str = "job_default",
        candidate_id: str = "cand_default",
        taxonomy_manager: Optional[Any] = None,
    ) -> SkillGapAnalysisResponse:
        """
        Fast, deterministic skill gap analysis for a candidate profile against job requirements.
        Reuses normalize_job_requirements(), canonical taxonomy skill mapping, and
        apply_evaluation_rules() without making an external LLM call.
        """
        from src.taxonomy.taxonomy_manager import TaxonomyManager
        taxonomy = taxonomy_manager or TaxonomyManager()

        parsed_reqs = self.normalize_job_requirements(job_requirements)

        # Extract candidate skills into a structured map: skill_id / clean_name -> candidate_skill
        cand_skills_map: Dict[str, Dict[str, Any]] = {}
        cand_id_str = candidate_id

        # Determine skills container from candidate_profile
        skills_list = []
        if hasattr(candidate_profile, "skills"):
            skills_list = candidate_profile.skills
            if hasattr(candidate_profile, "candidate_id") and candidate_profile.candidate_id:
                cand_id_str = candidate_profile.candidate_id
        elif isinstance(candidate_profile, dict):
            skills_list = candidate_profile.get("skills", [])
            cand_id_str = candidate_profile.get("candidate_id", candidate_id)

        for s in skills_list:
            s_name = ""
            s_level = "intermediate"
            s_id = None
            s_evidence = ""

            if isinstance(s, str):
                s_name = s
            elif isinstance(s, dict):
                s_name = s.get("name") or s.get("skill_name") or ""
                s_level = str(s.get("level") or s.get("proficiency") or "intermediate").lower()
                s_id = s.get("skill_id")
                evidence_items = s.get("evidence", [])
                if isinstance(evidence_items, list) and evidence_items:
                    s_evidence = str(evidence_items[0].get("text") if isinstance(evidence_items[0], dict) else evidence_items[0])
            elif hasattr(s, "name") or hasattr(s, "skill_name"):
                s_name = getattr(s, "name", None) or getattr(s, "skill_name", "")
                lvl = getattr(s, "level", None) or getattr(s, "proficiency", "intermediate")
                s_level = getattr(lvl, "value", str(lvl)).lower()
                s_id = getattr(s, "skill_id", None)
                ev = getattr(s, "evidence", [])
                if isinstance(ev, list) and ev:
                    s_evidence = getattr(ev[0], "text", str(ev[0]))

            if not s_name and not s_id:
                continue

            # Normalize candidate skill to canonical ID
            canonical_id = s_id
            if not canonical_id and s_name:
                canonical_id, _, _ = taxonomy.normalize_skill(s_name, strict=True)

            entry = {
                "name": s_name,
                "canonical_id": canonical_id,
                "level": s_level,
                "evidence": s_evidence or f"Extracted {s_name} with {s_level} proficiency."
            }

            if canonical_id:
                cand_skills_map[canonical_id.lower()] = entry
            if s_name:
                cand_skills_map[s_name.lower().strip()] = entry

        # Build skill breakdown items
        skill_breakdown_items: List[SkillMatchItem] = []

        for req in parsed_reqs:
            req_name = req.skill_name
            req_canonical_id, _, _ = taxonomy.normalize_skill(req_name, strict=True)

            # Check if candidate has matching skill
            matched_entry = None
            if req_canonical_id and req_canonical_id.lower() in cand_skills_map:
                matched_entry = cand_skills_map[req_canonical_id.lower()]
            elif req_name.lower().strip() in cand_skills_map:
                matched_entry = cand_skills_map[req_name.lower().strip()]

            if matched_entry:
                cand_lvl = matched_entry["level"].lower()
                req_prof = (req.proficiency or "intermediate").lower()

                cand_rank = {"expert": 4, "advanced": 3, "intermediate": 2, "mid": 2, "beginner": 1, "basic": 1, "entry": 1}.get(cand_lvl, 2)
                req_rank = {"expert": 4, "advanced": 3, "intermediate": 2, "mid": 2, "beginner": 1, "basic": 1, "entry": 1}.get(req_prof, 2)

                if cand_rank >= req_rank:
                    score = 100.0
                elif cand_rank == req_rank - 1:
                    score = 75.0
                elif cand_rank == req_rank - 2:
                    score = 50.0
                else:
                    score = 30.0

                cand_prof_str = cand_lvl.title()
                is_matched = score >= 70.0
                feedback = f"Matches requirement for {req_name}." if is_matched else f"Basic proficiency in {req_name}."
                evidence = matched_entry.get("evidence") or f"Demonstrated background in {req_name}."
            else:
                score = 0.0
                cand_prof_str = "Missing"
                is_matched = False
                feedback = f"Missing required skill: {req_name}."
                evidence = "No matching evidence found in candidate profile."

            skill_breakdown_items.append(
                SkillMatchItem(
                    skill_name=req_name,
                    required_proficiency=req.proficiency or "Intermediate",
                    candidate_proficiency=cand_prof_str,
                    match_score=score,
                    is_matched=is_matched,
                    skill_feedback=feedback,
                    evidence_found=evidence,
                )
            )

        # Construct raw response object
        raw_response = SkillGapAnalysisResponse(
            job_id=job_id,
            candidate_id=cand_id_str,
            overall_match_score=0.0,
            qualification_status=QualificationStatus.NOT_QUALIFIED.value,
            full_candidate_summary="Deterministic qualification assessment based on skill requirements and evidence.",
            skill_breakdown=skill_breakdown_items,
            missing_critical_skills=[],
            recommended_upskilling_path=[],
        )

        # Apply standard qualification and threshold rules
        return self.apply_evaluation_rules(raw_response, parsed_reqs)

    async def analyze_skill_gap(
        self,
        request: SkillGapAnalysisRequest
    ) -> SkillGapAnalysisResponse:
        """
        Executes end-to-end skill gap analysis for a candidate profile against job requirements.
        """
        parsed_reqs = self.normalize_job_requirements(request.job_requirements)

        # Prepare text representations for LLM
        reqs_repr = json.dumps([r.model_dump() for r in parsed_reqs], indent=2) if parsed_reqs else str(request.job_requirements)
        candidate_repr = self.format_candidate_profile_text(request.candidate_profile)

        # Call AI reasoning chain
        llm_response = await self.chains.analyze_skill_gap(
            job_id=request.job_id,
            candidate_id=request.candidate_id,
            job_requirements_str=reqs_repr,
            candidate_profile_str=candidate_repr,
        )

        # Apply deterministic rule enforcement
        final_assessment = self.apply_evaluation_rules(llm_response, parsed_reqs)
        return final_assessment

matching_service = MatchingService()
