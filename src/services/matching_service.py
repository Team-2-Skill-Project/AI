from __future__ import annotations
import json
import re
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
        1. Guarantees 100% requirement coverage in skill_breakdown:
           - Iterates over all declared required_skills.
           - Matches items returned by the LLM (by exact name, lowercased name, or taxonomy canonical ID).
           - If any requirement was omitted by the LLM/chain, synthesizes a missing SkillMatchItem
             with match_score=0.0 and is_matched=False. Critical gaps can NEVER be hidden.
           - Retains any additional skills evaluated by the LLM that were not in required_skills.
        2. Score & match rules:
           - Bounds every score in [0, 100].
           - Enforces is_matched == True if score >= 70.0, else False.
        3. Critical skills:
           - Identifies all critical skills (tagged is_critical=True or all requirements if none tagged).
           - All critical skills with score < 70 added to missing_critical_skills.
        4. Overall match score:
           - Arithmetic mean across ALL evaluated skills (including 0.0 for omitted requirements).
        5. Overall Qualification verdict:
           - 'Qualified': Candidate matches >= 80% of critical skills with an overall average score >= 75.0.
           - 'Partially Qualified': Meets >= 50% of requirements and >= 50% of critical skills (or avg >= 50.0).
           - 'Not Qualified': Fails core requirements (< 50% critical match or < 50% total match or < 50.0 avg).
        6. Upskilling recommendations:
           - Guarantees every missing critical skill is present in recommended_upskilling_path.
        """
        from src.taxonomy.taxonomy_manager import get_taxonomy_manager
        taxonomy = get_taxonomy_manager()

        # Build index of items returned in the raw response
        # Keyed by lowercased skill name and canonical taxonomy ID
        returned_items_by_key: Dict[str, tuple[int, SkillMatchItem]] = {}
        matched_item_ids: Set[int] = set()

        for idx, item in enumerate(response.skill_breakdown):
            key = item.skill_name.lower().strip()
            returned_items_by_key[key] = (idx, item)
            cid, _, _ = taxonomy.normalize_skill(item.skill_name, strict=True)
            if cid:
                returned_items_by_key[cid.lower().strip()] = (idx, item)

        # Build map of critical skill identifiers
        critical_skill_keys: Set[str] = set()
        for req in required_skills:
            if req.is_critical:
                critical_skill_keys.add(req.skill_name.lower().strip())
                cid, _, _ = taxonomy.normalize_skill(req.skill_name, strict=True)
                if cid:
                    critical_skill_keys.add(cid.lower().strip())

        # If no skills were explicitly tagged is_critical, treat all required skills as core
        if not critical_skill_keys and required_skills:
            for req in required_skills:
                critical_skill_keys.add(req.skill_name.lower().strip())
                cid, _, _ = taxonomy.normalize_skill(req.skill_name, strict=True)
                if cid:
                    critical_skill_keys.add(cid.lower().strip())

        updated_items: List[SkillMatchItem] = []
        missing_critical: List[str] = []
        matched_count = 0
        critical_total = 0
        critical_matched = 0

        # 1. Guarantee every required skill from required_skills is present and evaluated
        for req in required_skills:
            req_name = req.skill_name.strip()
            req_key = req_name.lower()
            req_cid, _, _ = taxonomy.normalize_skill(req_name, strict=True)
            cid_key = req_cid.lower().strip() if req_cid else None

            found_tuple = returned_items_by_key.get(req_key) or (returned_items_by_key.get(cid_key) if cid_key else None)

            if found_tuple:
                orig_idx, orig_item = found_tuple
                matched_item_ids.add(orig_idx)
                score = max(0.0, min(100.0, float(orig_item.match_score)))
                is_matched = score >= 70.0
                cand_prof = orig_item.candidate_proficiency if orig_item.candidate_proficiency else ("None" if score == 0.0 else "Intermediate")
                feedback = orig_item.skill_feedback if orig_item.skill_feedback else (f"Matches requirement for {req_name}." if is_matched else f"Gap in {req_name}.")
                evidence = orig_item.evidence_found if orig_item.evidence_found else ("Demonstrated in profile." if is_matched else "No matching evidence found in candidate profile.")

                eval_item = SkillMatchItem(
                    skill_name=req_name,
                    required_proficiency=orig_item.required_proficiency or req.proficiency or "Intermediate",
                    candidate_proficiency=cand_prof,
                    match_score=score,
                    is_matched=is_matched,
                    skill_feedback=feedback,
                    evidence_found=evidence,
                    resources=getattr(orig_item, "resources", []),
                )
            else:
                # Requirement was omitted by the LLM! Synthesize with 0.0 score so gap is never hidden
                eval_item = SkillMatchItem(
                    skill_name=req_name,
                    required_proficiency=req.proficiency or "Intermediate",
                    candidate_proficiency="Missing",
                    match_score=0.0,
                    is_matched=False,
                    skill_feedback=f"Missing required skill: {req_name}.",
                    evidence_found="No matching evidence found in candidate profile.",
                    resources=[],
                )

            # Check critical status
            is_crit = req_key in critical_skill_keys or (cid_key in critical_skill_keys if cid_key else False)
            if is_crit:
                critical_total += 1
                if eval_item.is_matched:
                    critical_matched += 1
                else:
                    if req_name not in missing_critical:
                        missing_critical.append(req_name)

            if eval_item.is_matched:
                matched_count += 1

            updated_items.append(eval_item)

        # 2. Append any extra skills returned by the LLM that were not in required_skills
        for orig_idx, item in enumerate(response.skill_breakdown):
            if orig_idx not in matched_item_ids:
                score = max(0.0, min(100.0, float(item.match_score)))
                is_matched = score >= 70.0
                extra_item = SkillMatchItem(
                    skill_name=item.skill_name,
                    required_proficiency=item.required_proficiency,
                    candidate_proficiency=item.candidate_proficiency,
                    match_score=score,
                    is_matched=is_matched,
                    skill_feedback=item.skill_feedback,
                    evidence_found=item.evidence_found,
                    resources=getattr(item, "resources", []),
                )
                if is_matched:
                    matched_count += 1
                updated_items.append(extra_item)

        # 3. Calculate scores & rates across ALL evaluated requirements
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

        # 4. Determine qualification verdict
        if crit_match_rate >= 0.80 and avg_score >= 75.0:
            verdict = QualificationStatus.QUALIFIED.value
        elif total_match_rate >= 0.50 or (50.0 <= avg_score < 75.0):
            verdict = QualificationStatus.PARTIALLY_QUALIFIED.value
        else:
            verdict = QualificationStatus.NOT_QUALIFIED.value

        # 5. Ensure missing critical skills are addressed in recommended_upskilling_path
        upskilling = list(response.recommended_upskilling_path) if response.recommended_upskilling_path else []
        upskilling_text = " ".join(upskilling).lower()
        for missing_skill in missing_critical:
            if missing_skill.lower() not in upskilling_text:
                upskilling.append(
                    f"Prioritize building foundational and practical experience in {missing_skill}."
                )

        response.skill_breakdown = updated_items
        response.overall_match_score = avg_score
        response.qualification_status = verdict
        response.missing_critical_skills = missing_critical
        response.recommended_upskilling_path = upskilling

        return response

    def evaluate_match(
        self,
        candidate_profile: Any,
        job_requirements: Any,
        job_id: str = "job_default",
        candidate_id: str = "cand_default",
        taxonomy_manager: Optional[Any] = None,
        job_title: Optional[str] = None,
        canonical_role: Optional[str] = None,
        min_years_experience: Optional[float] = None,
        work_mode: Optional[str] = None,
        location: Optional[str] = None,
        employment_type: Optional[str] = None,
        preferred_skills: Optional[List[Any]] = None,
    ) -> SkillGapAnalysisResponse:
        """
        Fast, deterministic skill gap analysis for a candidate profile against job requirements.
        Reuses normalize_job_requirements(), canonical taxonomy skill mapping, and
        apply_evaluation_rules() without making an external LLM call.
        """
        # pyrefly: ignore [missing-import]
        from src.taxonomy.taxonomy_manager import TaxonomyManager
        taxonomy = taxonomy_manager or TaxonomyManager()

        parsed_reqs = self.normalize_job_requirements(job_requirements)

        # Extract candidate skills into a structured map: skill_id / clean_name -> candidate_skill
        cand_skills_map: Dict[str, Dict[str, Any]] = {}
        cand_id_str = candidate_id

        # Determine skills container from candidate_profile
        skills_list = []
        if hasattr(candidate_profile, "candidate_skills"):
            skills_list = candidate_profile.candidate_skills
            if hasattr(candidate_profile, "candidate_id") and candidate_profile.candidate_id:
                cand_id_str = candidate_profile.candidate_id
        elif hasattr(candidate_profile, "skills"):
            skills_list = candidate_profile.skills
            if hasattr(candidate_profile, "candidate_id") and candidate_profile.candidate_id:
                cand_id_str = candidate_profile.candidate_id
        elif isinstance(candidate_profile, dict):
            skills_list = candidate_profile.get("candidate_skills") or candidate_profile.get("skills", [])
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
            req_canonical_id = req.skill_id
            if not req_canonical_id:
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

        # Apply standard qualification and threshold rules and return
        # (Explainable enrichment is only done by explain_job_match, not this fast-path)
        return self.apply_evaluation_rules(raw_response, parsed_reqs)


    def enrich_explainable_dimensions(
        self,
        response: SkillGapAnalysisResponse,
        request: SkillGapAnalysisRequest,
        parsed_reqs: List[SkillRequirement],
        is_explain: bool = False,
    ) -> SkillGapAnalysisResponse:
        """
        Enriches a skill gap analysis response with explainable match dimensions:
        - Role Alignment (candidate target roles vs job title / canonical role)
        - Experience Fit (candidate years of experience vs job min_years_experience)
        - Preference Fit (candidate work mode, location, and employment type vs job)
        - Preferred Skills Fit (evaluation of nice-to-have / preferred skills)
        - Categorization of weak skills, non-negotiable blockers, and nice-to-have gaps
        - Composite match scoring across all 5 dimensions
        - Synthesized executive rationale and hiring priority level
        """
        from src.services.recommendation_scoring import calculate_role_fit, calculate_preference_fit
        from src.taxonomy.taxonomy_manager import TaxonomyManager

        taxonomy = TaxonomyManager()

        candidate_profile = request.candidate_profile
        target_roles: List[str] = []
        preferences: Any = None
        cand_years: Optional[float] = None
        work_history: List[Any] = []
        candidate_skills: List[Any] = []

        if isinstance(candidate_profile, CandidateProfilePayload):
            target_roles = list(candidate_profile.target_roles or [])
            preferences = candidate_profile.preferences
            cand_years = candidate_profile.total_years_experience
            work_history = list(candidate_profile.work_history or [])
            candidate_skills = list(candidate_profile.skills or [])
        elif isinstance(candidate_profile, dict):
            target_roles = list(candidate_profile.get("target_roles") or [])
            preferences = candidate_profile.get("preferences")
            cand_years = candidate_profile.get("total_years_experience") or candidate_profile.get("years_of_experience")
            work_history = list(candidate_profile.get("work_history") or [])
            candidate_skills = list(candidate_profile.get("skills") or [])
        elif isinstance(candidate_profile, str):
            try:
                data = json.loads(candidate_profile)
                if isinstance(data, dict):
                    target_roles = list(data.get("target_roles") or [])
                    preferences = data.get("preferences")
                    cand_years = data.get("total_years_experience") or data.get("years_of_experience")
                    work_history = list(data.get("work_history") or [])
                    candidate_skills = list(data.get("skills") or [])
            except Exception:
                pass

        # If cand_years is not set, extract from work history text/fields
        if cand_years is None:
            total_extracted = 0.0
            for item in work_history:
                if isinstance(item, dict):
                    y = item.get("years") or item.get("duration_years")
                    if y is not None:
                        try:
                            total_extracted += float(y)
                            continue
                        except (ValueError, TypeError):
                            pass
                    text = f"{item.get('title', '')} {item.get('role', '')} {item.get('description', '')} {item.get('duration', '')}"
                else:
                    text = str(item)
                matches = re.findall(r"(\d+(?:\.\d+)?)\s*(?:year|yr)", text, re.IGNORECASE)
                for m in matches:
                    try:
                        total_extracted += float(m)
                    except ValueError:
                        pass
            if total_extracted > 0:
                cand_years = total_extracted

        # Fallback target_roles from work_history if empty
        if not target_roles and work_history:
            for item in work_history:
                if isinstance(item, dict):
                    title = item.get("title") or item.get("role")
                    if title and isinstance(title, str):
                        target_roles.append(title)
                elif isinstance(item, str) and len(item) < 60:
                    target_roles.append(item)

        # Build candidate skill map
        cand_skills_map: Dict[str, Dict[str, Any]] = {}
        for s in candidate_skills:
            s_name = ""
            s_level = "intermediate"
            if isinstance(s, str):
                s_name = s
            elif isinstance(s, dict):
                s_name = s.get("name") or s.get("skill_name") or ""
                s_level = s.get("level") or s.get("proficiency") or "intermediate"
            else:
                s_name = getattr(s, "name", None) or getattr(s, "skill_name", "")
                lvl = getattr(s, "level", None) or getattr(s, "proficiency", "intermediate")
                s_level = getattr(lvl, "value", str(lvl))
            if not s_name:
                continue
            canonical_id, _, _ = taxonomy.normalize_skill(s_name, strict=True)
            entry = {"name": s_name, "level": str(s_level).lower()}
            if canonical_id:
                cand_skills_map[canonical_id.lower()] = entry
            cand_skills_map[s_name.lower().strip()] = entry

        # 1. Preferred skills evaluation
        preferred_skills_breakdown: List[SkillMatchItem] = []
        nice_to_have_gaps: List[str] = []
        preferred_scores: List[float] = []

        raw_preferred = request.preferred_skills or []
        preferred_reqs = self.normalize_job_requirements(raw_preferred)
        for pref in preferred_reqs:
            pref_name = pref.skill_name
            pref_canonical_id, _, _ = taxonomy.normalize_skill(pref_name, strict=True)
            matched = False
            matched_entry = None
            if pref_canonical_id and pref_canonical_id.lower() in cand_skills_map:
                matched_entry = cand_skills_map[pref_canonical_id.lower()]
                matched = True
            elif pref_name.lower().strip() in cand_skills_map:
                matched_entry = cand_skills_map[pref_name.lower().strip()]
                matched = True

            if matched:
                score = 100.0
                is_matched = True
                feedback = f"Demonstrated proficiency in preferred skill: {pref_name}."
                evidence = f"Evidence of {pref_name} present in profile."
                preferred_scores.append(100.0)
            else:
                score = 0.0
                is_matched = False
                feedback = f"Preferred skill not found: {pref_name}."
                evidence = "No matching evidence found in candidate profile."
                nice_to_have_gaps.append(pref_name)
                preferred_scores.append(0.0)

            preferred_skills_breakdown.append(
                SkillMatchItem(
                    skill_name=pref_name,
                    required_proficiency=pref.proficiency or "Intermediate",
                    candidate_proficiency=matched_entry["level"].title() if matched_entry else "Missing",
                    match_score=score,
                    is_matched=is_matched,
                    skill_feedback=feedback,
                    evidence_found=evidence,
                )
            )

        preferred_skills_score = round(sum(preferred_scores) / len(preferred_scores), 1) if preferred_scores else 100.0

        # 2. Weak skills (0 < score < 70)
        weak_skills: List[str] = []
        for item in response.skill_breakdown:
            if 0.0 < item.match_score < 70.0 and item.skill_name not in weak_skills:
                weak_skills.append(item.skill_name)

        # 3. Blockers
        blockers: List[str] = []
        for s in response.missing_critical_skills:
            msg = f"Missing critical skill: {s}"
            if msg not in blockers:
                blockers.append(msg)

        # 4. Experience Score
        min_years = request.min_years_experience
        if min_years is not None and min_years > 0:
            actual_years = cand_years if cand_years is not None else 0.0
            if actual_years >= min_years:
                experience_score = 100.0
            elif actual_years >= min_years * 0.8:
                experience_score = 80.0
            elif actual_years >= min_years * 0.5:
                experience_score = 50.0
            else:
                experience_score = max(10.0, round((actual_years / min_years) * 100.0, 1))

            if actual_years < min_years * 0.5:
                blockers.append(f"Insufficient experience: {actual_years:.1f} years vs {min_years:.1f} years required")
        else:
            experience_score = 100.0

        # 5. Role Alignment Score
        if request.job_title or request.canonical_role:
            role_alignment_score = calculate_role_fit(
                candidate_target_roles=target_roles,
                job_title=request.job_title or "",
                job_canonical_role=request.canonical_role,
                candidate_experience=work_history,
            )
        else:
            role_alignment_score = 100.0

        # 6. Preference Fit Score
        norm_prefs = preferences
        if isinstance(preferences, dict):
            norm_prefs = {}
            wm = preferences.get("work_mode") or preferences.get("work_modes")
            norm_prefs["work_mode"] = [wm] if isinstance(wm, str) else wm or []
            loc = preferences.get("locations") or preferences.get("location")
            norm_prefs["locations"] = [loc] if isinstance(loc, str) else loc or []
            emp = preferences.get("employment_type") or preferences.get("employment_types")
            norm_prefs["employment_type"] = [emp] if isinstance(emp, str) else emp or []

        if request.work_mode or request.location or request.employment_type or norm_prefs:
            preference_fit_score = calculate_preference_fit(
                candidate_preferences=norm_prefs,
                job_work_mode=request.work_mode,
                job_location=request.location,
                job_employment_type=request.employment_type,
            )
        else:
            preference_fit_score = 100.0

        # 7. Core Skills Match Score
        skills_match_score = response.overall_match_score

        # 8. Check if multi-dimensional context is present
        has_explainable_context = bool(
            request.job_title
            or request.canonical_role
            or (request.min_years_experience is not None and request.min_years_experience > 0)
            or request.work_mode
            or request.location
            or request.employment_type
            or raw_preferred
        )

        if has_explainable_context:
            overall_composite = round(
                (skills_match_score * 0.50)
                + (role_alignment_score * 0.20)
                + (experience_score * 0.15)
                + (preference_fit_score * 0.10)
                + (preferred_skills_score * 0.05),
                1,
            )
            response.overall_match_score = min(100.0, max(0.0, overall_composite))

            if len(blockers) > 0 and response.qualification_status == QualificationStatus.QUALIFIED.value:
                response.qualification_status = QualificationStatus.PARTIALLY_QUALIFIED.value
            if len(blockers) >= 2 or overall_composite < 50.0:
                response.qualification_status = QualificationStatus.NOT_QUALIFIED.value

        # Priority calculation
        if response.qualification_status == QualificationStatus.QUALIFIED.value and len(blockers) == 0:
            priority = "high"
        elif response.qualification_status == QualificationStatus.NOT_QUALIFIED.value or len(blockers) >= 2:
            priority = "low"
        else:
            priority = "medium"

        # Rationale synthesis
        rationale_parts = [
            f"Skills Match: {skills_match_score:.1f}%",
            f"Role Alignment: {role_alignment_score:.1f}%",
            f"Experience Fit: {experience_score:.1f}%",
            f"Preference Fit: {preference_fit_score:.1f}%",
        ]
        if raw_preferred:
            rationale_parts.append(f"Preferred Skills: {preferred_skills_score:.1f}%")

        status_note = f"Candidate evaluated as {response.qualification_status} with {priority} hiring priority."
        if blockers:
            status_note += f" Key blockers: {'; '.join(blockers)}."
        rationale = f"{status_note} Dimension breakdown: {', '.join(rationale_parts)}."

        # Assign enriched fields to response
        response.preferred_skills_breakdown = preferred_skills_breakdown
        response.weak_skills = weak_skills
        response.blockers = blockers
        response.nice_to_have_gaps = nice_to_have_gaps
        response.role_alignment_score = role_alignment_score
        response.experience_score = experience_score
        response.preference_fit_score = preference_fit_score
        response.skills_match_score = skills_match_score
        response.score_breakdown = {
            "skills_match": skills_match_score,
            "role_alignment": role_alignment_score,
            "experience": experience_score,
            "preference_fit": preference_fit_score,
            "preferred_skills": preferred_skills_score,
        }
        response.rationale = rationale
        response.priority = priority

        return response

    async def _run_llm_evaluation(
        self,
        request: SkillGapAnalysisRequest,
        parsed_reqs: List[SkillRequirement],
    ) -> SkillGapAnalysisResponse:
        """Internal: runs the LLM chain and applies deterministic evaluation rules. No enrichment."""
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

        # Apply deterministic rule enforcement (scoring, thresholds, missing-skill synthesis)
        return self.apply_evaluation_rules(llm_response, parsed_reqs)

    async def analyze_skill_gap(
        self,
        request: SkillGapAnalysisRequest
    ) -> SkillGapAnalysisResponse:
        """
        Executes end-to-end skill gap analysis for a candidate profile against job requirements.
        Returns a SkillGapAnalysisResponse with all required skills evaluated.
        """
        parsed_reqs = self.normalize_job_requirements(request.job_requirements)
        return await self._run_llm_evaluation(request, parsed_reqs)

    async def explain_job_match(
        self,
        request: SkillGapAnalysisRequest
    ) -> SkillGapAnalysisResponse:
        """
        Executes an explainable job match evaluation covering all 5 dimensions:
        1. Core Technical Skills Match
        2. Role Alignment (target roles vs job title / canonical role)
        3. Experience Fit (years vs min_years_experience)
        4. Preference Fit (work mode, location, employment type)
        5. Preferred / Nice-to-have Skills Fit

        Also categorizes weak skills, non-negotiable blockers, and nice-to-have gaps,
        and provides natural-language rationale and hiring priority.
        Enrichment is performed exactly once, after the base LLM evaluation.
        """
        parsed_reqs = self.normalize_job_requirements(request.job_requirements)
        base_response = await self._run_llm_evaluation(request, parsed_reqs)
        return self.enrich_explainable_dimensions(base_response, request, parsed_reqs, is_explain=True)

matching_service = MatchingService()
