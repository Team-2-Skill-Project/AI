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
