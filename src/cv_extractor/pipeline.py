import os
import uuid
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Set

from ..models.candidate import (
    Candidate,
    CandidateProfileDetails,
    CandidatePreferences,
    CandidateSkill,
    EducationItem,
    ExperienceItem,
    ProjectItem,
    CertificationItem,
)
from ..taxonomy.taxonomy_manager import TaxonomyManager
from ..utils.text_cleaner import TextCleaner
from .document_loader import DocumentLoader
from .llm_extractor import LLMExtractor
from .evidence_linker import EvidenceLinker
from .confidence_scorer import ConfidenceScorer
from .link_associator import ProjectLinkAssociator

logger = logging.getLogger(__name__)


class CVExtractionPipeline:
    """
    End-to-end CV Profile Extraction Pipeline.
    Strict 9-Step Flow with Hybrid Open-World Taxonomy:
      1. Extract raw text from document (PDF / DOCX / TXT).
      2. Clean & segment text into structured sections.
      3. LLM / heuristic extracts candidate profile, education, experience, projects.
      4. Collect candidate skill mentions (explicit skills + experience/project tech stacks).
      5. Match mentions against TaxonomyManager (Canonical mapping + Dynamic Open-World Tech Discovery).
      6. Reject non-skills / stopwords / URLs / generic noise.
      7. Verify evidence exists in the original CV text.
      8. Deduplicate skills & calculate contextual confidence & level scoring.
      9. Assemble and return validated Candidate object.
    """

    def __init__(
        self,
        taxonomy_manager: Optional[TaxonomyManager] = None,
        document_loader: Optional[DocumentLoader] = None,
        llm_extractor: Optional[LLMExtractor] = None,
    ):
        self.taxonomy = taxonomy_manager or TaxonomyManager()
        self.loader = document_loader or DocumentLoader()
        self.extractor = llm_extractor or LLMExtractor()

    def extract_from_file(self, file_path: str, candidate_id: Optional[str] = None) -> Candidate:
        """
        Executes full extraction pipeline on a CV file path.
        """
        raw_text, doc_format = self.loader.load_text(file_path)
        if not raw_text.strip():
            raise ValueError(f"Could not extract any readable text from document: {file_path}")

        return self.extract_from_text(
            raw_text=raw_text,
            file_name=Path(file_path).name,
            candidate_id=candidate_id or f"cand_{uuid.uuid4().hex[:8]}"
        )

    def extract_from_text(
        self,
        raw_text: str,
        file_name: Optional[str] = None,
        candidate_id: Optional[str] = None
    ) -> Candidate:
        """
        Executes strict 9-step pipeline on raw text.
        """
        cid = candidate_id or f"cand_{uuid.uuid4().hex[:8]}"
        
        # Step 1 & 2: Clean text and segment sections
        cleaned_text = TextCleaner.clean_text(raw_text)
        sections = TextCleaner.segment_sections(cleaned_text)

        # Step 3: LLM / structured entity extraction
        document_urls = getattr(self.loader, "extracted_links", [])
        entities = self.extractor.extract_entities(cleaned_text, sections, document_urls=document_urls)

        # Apply strict 7-rule project-to-link association
        if "projects" in entities and isinstance(entities["projects"], list):
            ProjectLinkAssociator.associate_projects_with_links(
                projects=entities["projects"],
                full_text=cleaned_text,
                document_urls=document_urls
            )

        # Step 4: Collect candidate skill mentions
        skill_candidates: Set[str] = set()

        # A) Explicit skills from extractor
        for s in entities.get("raw_skills", []):
            if isinstance(s, dict) and s.get("name"):
                skill_candidates.add(s["name"])
            elif isinstance(s, str) and s.strip():
                skill_candidates.add(s.strip())

        # B) Technologies mentioned in experiences
        for exp in entities.get("experience", []):
            if isinstance(exp, dict):
                for tech in exp.get("technologies", []):
                    if isinstance(tech, str) and tech.strip():
                        skill_candidates.add(tech.strip())

        # C) Technologies mentioned in projects
        for proj in entities.get("projects", []):
            if isinstance(proj, dict):
                for tech in proj.get("technologies", []):
                    if isinstance(tech, str) and tech.strip():
                        skill_candidates.add(tech.strip())

        # D) Discover canonical skills and high-confidence aliases in text
        for item in self.taxonomy.get_all_skills():
            if len(item.canonical_name) >= 3 and item.canonical_name.lower() in cleaned_text.lower():
                skill_candidates.add(item.canonical_name)
            for alias in item.aliases:
                if len(alias) >= 3 and alias.lower() in cleaned_text.lower():
                    skill_candidates.add(item.canonical_name)

        # Step 5, 6, 7, 8: Match against taxonomy (with open-world dynamic fallback), Reject garbage, Link evidence, Deduplicate & Score
        final_skills: List[CandidateSkill] = []
        processed_skill_ids: Set[str] = set()

        for raw_mention in skill_candidates:
            if not raw_mention or len(raw_mention.strip()) < 2:
                continue

            # Hybrid Open-World Taxonomy: Match known or dynamically normalize novel technologies, reject stopwords
            skill_id, canonical_name, category = self.taxonomy.normalize_skill(raw_mention, strict=False)
            if not skill_id or not canonical_name:
                continue

            # Deduplication
            if skill_id in processed_skill_ids:
                continue

            taxonomy_item = self.taxonomy.find_skill(raw_mention)

            # Evidence Verification (Must find verifiable proof in the CV text)
            evidence_items = EvidenceLinker.link_evidence(
                skill_name=canonical_name,
                taxonomy_item=taxonomy_item,
                sections=sections,
                full_text=cleaned_text
            )

            # If no supporting evidence exists anywhere in the text, reject false positive
            if not evidence_items:
                continue

            processed_skill_ids.add(skill_id)

            # Context-Aware Confidence & Proficiency Level Calculation
            confidence = ConfidenceScorer.calculate_confidence(evidence_items)
            level = ConfidenceScorer.infer_level(evidence_items)

            final_skills.append(
                CandidateSkill(
                    skill_id=skill_id,
                    name=canonical_name,
                    level=level,
                    confidence=confidence,
                    evidence=evidence_items
                )
            )

        # Sort skills by confidence descending
        final_skills.sort(key=lambda s: s.confidence, reverse=True)

        # Step 9: Assemble Validated Candidate Object
        education_items = [EducationItem(**item) for item in entities.get("education", [])]
        experience_items = [ExperienceItem(**item) for item in entities.get("experience", [])]
        project_items = [ProjectItem(**item) for item in entities.get("projects", [])]
        cert_items = [CertificationItem(**item) for item in entities.get("certifications", [])]

        target_roles = entities.get("target_roles", [])
        if not target_roles:
            target_roles = ["Agentic AI Developer"] if "Agentic" in cleaned_text or "AI" in cleaned_text else ["Software Engineer"]

        profile_details = CandidateProfileDetails(
            name=entities.get("name", "Candidate"),
            email=entities.get("email"),
            phone=entities.get("phone"),
            location=entities.get("location", "Egypt"),
            education=education_items,
            target_roles=target_roles,
            preferences=CandidatePreferences()
        )

        return Candidate(
            candidate_id=cid,
            profile=profile_details,
            skills=final_skills,
            experience=experience_items,
            projects=project_items,
            certifications=cert_items,
        )
