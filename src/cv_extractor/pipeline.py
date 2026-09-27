from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models.candidate import (
    Candidate,
    CandidatePreferences,
    CandidateProfile,
    CandidateSkill,
    CertificateItem,
    EducationItem,
    ExperienceItem,
    LanguageItem,
    ProjectItem,
    UserProfile,
)
from ..taxonomy.skill_registry_resolver import SkillRegistryResolver
from ..taxonomy.taxonomy_manager import (
    LEGITIMATE_EXPLICIT_SKILLS,
    STOPWORDS_BLACKLIST,
    TaxonomyManager,
)
from ..utils.text_cleaner import TextCleaner
from .confidence_scorer import ConfidenceScorer
from .document_loader import DocumentLoader
from .evidence_linker import EvidenceLinker
from .link_associator import ProjectLinkAssociator
from .llm_extractor import LLMExtractor

logger = logging.getLogger(__name__)


@dataclass
class CVExtractionMetadata:
    """
    Internal request-local CV extraction execution metadata.
    Kept strictly separate from Candidate domain models.
    """
    extraction_mode: str = "llm"


class CVExtractionPipeline:
    """End-to-end, evidence-backed CV extraction using one structured LLM call."""

    _PROFICIENCY_PREFIXES = (
        "basic",
        "beginner",
        "intermediate",
        "advanced",
        "expert",
        "proficient",
        "familiar with",
    )

    @staticmethod
    def _skill_key(value: str) -> str:
        normalized = value.casefold().replace("+", " plus ").replace("#", " sharp ")
        return re.sub(r"[^\w]+", "", normalized)

    @classmethod
    def _acronym_full_name(cls, phrase: str, acronym: str) -> str | None:
        compact_acronym = re.sub(r"[^A-Za-z0-9]", "", acronym).casefold()
        if not 2 <= len(compact_acronym) <= 12:
            return None

        words = re.findall(r"[A-Za-z][A-Za-z0-9]*", phrase)
        for start in range(len(words)):
            candidate_words = words[start:]
            initials = "".join(word[0] for word in candidate_words).casefold()
            if initials == compact_acronym:
                return " ".join(candidate_words)
        return None

    @classmethod
    def _source_declared_acronyms(cls, source_text: str) -> dict[str, tuple[str, str]]:
        """Read explicit ``Full Name (ACRONYM)`` declarations without mining skills."""
        declarations: dict[str, tuple[str, str]] = {}
        pattern = re.compile(
            r"(?P<phrase>[A-Za-z][A-Za-z0-9&/.,'’\-\s]{2,80}?)\s*"
            r"\(\s*(?P<acronym>[A-Z][A-Z0-9&./\-]{1,11})\s*\)"
        )
        for match in pattern.finditer(source_text):
            full_name = cls._acronym_full_name(match.group("phrase"), match.group("acronym"))
            if not full_name:
                continue
            acronym = match.group("acronym")
            pair = (full_name, acronym)
            declarations[cls._skill_key(full_name)] = pair
            declarations[cls._skill_key(acronym)] = pair
        return declarations

    @classmethod
    def _split_proficiency_modifier(cls, mention: str) -> tuple[str, str | None]:
        """Remove only an explicit generic proficiency modifier from a skill label."""
        prefix = "|".join(re.escape(value) for value in cls._PROFICIENCY_PREFIXES)
        prefix_match = re.match(rf"^\s*(?P<level>{prefix})\s+(?P<name>.+?)\s*$", mention, re.IGNORECASE)
        if prefix_match:
            core_name = re.split(
                r"\s+(?:for|used to|applied to|supporting)\s+",
                prefix_match.group("name"),
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            return core_name, prefix_match.group("level").casefold()

        suffix_match = re.match(
            rf"^\s*(?P<name>.+?)\s*\(\s*(?P<level>{prefix})\b[^)]*\)\s*$",
            mention,
            re.IGNORECASE,
        )
        if suffix_match:
            return suffix_match.group("name"), suffix_match.group("level").casefold()
        return mention, None

    @classmethod
    def _normalize_skill_mention(
        cls,
        raw_mention: str,
        declarations: dict[str, tuple[str, str]],
    ) -> tuple[str, str | None, tuple[str, ...]]:
        """Normalize only source-declared acronyms and generic proficiency syntax."""
        mention = TaxonomyManager.clean_skill_label(raw_mention)
        if not mention:
            return "", None, ()

        aliases: tuple[str, ...] = ()
        direct_pair = re.match(r"^(?P<phrase>.+?)\s*\(\s*(?P<acronym>[A-Z][A-Z0-9&./\-]{1,11})\s*\)$", mention)
        if direct_pair:
            full_name = cls._acronym_full_name(direct_pair.group("phrase"), direct_pair.group("acronym"))
            if full_name:
                mention = full_name
                aliases = (direct_pair.group("acronym"),)

        mention, proficiency = cls._split_proficiency_modifier(mention)
        declared = declarations.get(cls._skill_key(mention))
        if declared:
            mention, acronym = declared
            aliases = tuple(dict.fromkeys((*aliases, acronym)))
        return mention.strip(), proficiency, aliases

    @staticmethod
    def _is_contextual_only_mention(mention: str, source_text: str) -> bool:
        """Reject an LLM-listed noun phrase when every occurrence is a qualifier context."""
        if len(mention.split()) < 2:
            return False
        matches = list(re.finditer(rf"(?<!\w){re.escape(mention)}(?!\w)", source_text, re.IGNORECASE))
        if not matches:
            return False
        for match in matches:
            line_start = source_text.rfind("\n", 0, match.start()) + 1
            context = source_text[line_start:match.start()]
            if not re.search(r"\b(for|used to|applied to|supporting)\b[^.;:\n]{0,48}$", context, re.IGNORECASE):
                return False
        return True

    def __init__(
        self,
        taxonomy_manager: TaxonomyManager | None = None,
        document_loader: DocumentLoader | None = None,
        extractor: LLMExtractor | None = None,
        llm_extractor: LLMExtractor | None = None,
        skill_registry_resolver: SkillRegistryResolver | None = None,
    ):
        if taxonomy_manager is not None:
            self.taxonomy = taxonomy_manager
        else:
            try:
                self.taxonomy = TaxonomyManager()
            except Exception as e:
                logger.warning(f"Failed to initialize TaxonomyManager: {e}. Degrading gracefully without taxonomy.")
                self.taxonomy = None
        self.loader = document_loader or DocumentLoader()
        self.extractor = extractor or llm_extractor or LLMExtractor()
        self.skill_registry = skill_registry_resolver

    def extract_from_file(
        self,
        file_path: str,
        candidate_id: str | None = None,
        return_metadata: bool = False,
    ) -> Candidate | tuple[Candidate, CVExtractionMetadata]:
        """
        Executes full extraction pipeline on a CV file path.
        """
        raw_text, doc_format, document_urls = self.loader.load_text(file_path)
        if not raw_text.strip():
            raise ValueError(f"Could not extract any readable text from document: {file_path}")

        return self.extract_from_text(
            raw_text=raw_text,
            file_name=Path(file_path).name,
            candidate_id=candidate_id or f"cand_{uuid.uuid4().hex[:8]}",
            document_urls=document_urls,
            return_metadata=return_metadata,
        )

    def extract_from_file_with_metadata(
        self,
        file_path: str,
        candidate_id: str | None = None,
    ) -> tuple[Candidate, CVExtractionMetadata]:
        """
        Executes file extraction returning (Candidate, CVExtractionMetadata).
        """
        return self.extract_from_file(
            file_path=file_path,
            candidate_id=candidate_id,
            return_metadata=True,
        )

    def extract_from_text(
        self,
        raw_text: str,
        file_name: str | None = None,
        candidate_id: str | None = None,
        document_urls: list[str] | None = None,
        return_metadata: bool = False,
    ) -> Candidate | tuple[Candidate, CVExtractionMetadata]:
        """
        Executes strict 9-step pipeline on raw text.
        """
        cid = candidate_id or f"cand_{uuid.uuid4().hex[:8]}"
        doc_urls = document_urls if document_urls is not None else []

        # Step 1 & 2: Clean text and segment sections
        cleaned_text = TextCleaner.clean_text(raw_text)
        sections = TextCleaner.segment_sections(cleaned_text)

        # Step 3: centralized structured LLM extraction and Pydantic validation
        entities = self.extractor.extract_entities(cleaned_text, sections, document_urls=doc_urls)
        metadata = CVExtractionMetadata(extraction_mode="llm")

        # Apply strict 7-rule project-to-link association
        if "projects" in entities and isinstance(entities["projects"], list):
            ProjectLinkAssociator.associate_projects_with_links(
                projects=entities["projects"],
                full_text=cleaned_text,
                document_urls=doc_urls
            )

        # Step 4: Collect candidate skill mentions and raw proficiency levels
        skill_candidates: list[tuple[str, str | None]] = []
        raw_skill_levels: dict[str, str] = {}

        # A) Explicit skills from extractor
        for s in (entities.get("raw_skills") or []):
            skill_name = None
            skill_level = None
            if hasattr(s, "name"):
                skill_name = s.name
                skill_level = getattr(s, "level", None) or getattr(s, "proficiency", None)
            elif isinstance(s, dict):
                skill_name = s.get("name")
                skill_level = s.get("level") or s.get("proficiency") or s.get("proficiency_level") or s.get("raw_level")
            elif isinstance(s, str) and s.strip():
                skill_name = s.strip()

            if skill_name and isinstance(skill_name, str) and skill_name.strip():
                skill_candidates.append((skill_name.strip(), skill_level if isinstance(skill_level, str) else None))

        # B) Technologies mentioned in experiences
        for exp in (entities.get("experiences") or entities.get("experience") or []):
            if isinstance(exp, dict):
                for tech in (exp.get("technologies") or []):
                    if isinstance(tech, str) and tech.strip():
                        skill_candidates.append((tech.strip(), None))

        # C) Technologies mentioned in projects
        for proj in (entities.get("projects") or []):
            if isinstance(proj, dict):
                for tech in (proj.get("technologies") or []):
                    if isinstance(tech, str) and tech.strip():
                        skill_candidates.append((tech.strip(), None))


        # Step 5, 6, 7, 8: Non-destructive Taxonomy Resolution, Deduplication, Evidence Linking & Scoring
        resolved_skills_map: dict[str, dict[str, Any]] = {}

        declarations = self._source_declared_acronyms(cleaned_text)

        for raw_mention, supplied_level in skill_candidates:
            if not raw_mention or len(raw_mention.strip()) < 2:
                continue

            clean_mention, derived_level, source_declared_aliases = self._normalize_skill_mention(
                raw_mention,
                declarations,
            )
            if not clean_mention or len(clean_mention) < 2:
                continue

            skill_level = supplied_level or derived_level
            if skill_level and skill_level.strip():
                raw_skill_levels[clean_mention.lower()] = skill_level.strip()

            if self.taxonomy and self.taxonomy.is_blacklisted(clean_mention, is_explicit=True):
                continue
            elif clean_mention.lower() in STOPWORDS_BLACKLIST and clean_mention.lower() not in LEGITIMATE_EXPLICIT_SKILLS:
                continue

            # Candidate name and email must never be extracted as skills
            cand_name = entities.get("name") or (entities.get("user") or {}).get("name")
            cand_email = entities.get("email") or (entities.get("user") or {}).get("email")
            if cand_name and clean_mention.lower() == cand_name.strip().lower():
                continue
            if cand_email and clean_mention.lower() == cand_email.strip().lower():
                continue

            # Non-destructive taxonomy resolution:
            # KNOWN -> (canonical skill_id, canonical name)
            # UNKNOWN -> (None, cleaned original name)
            if self.skill_registry:
                skill_id, canonical_name, _ = self.skill_registry.resolve(
                    clean_mention,
                    create_unknown=False,
                )
            elif self.taxonomy:
                skill_id, canonical_name = self.taxonomy.resolve(clean_mention)
            else:
                skill_id, canonical_name = None, clean_mention

            if not canonical_name:
                continue

            # Deduplication key:
            # Known: dedup by canonical skill_id
            # Unknown: dedup by normalized lowercase name
            if skill_id is not None:
                dedup_key = f"id:{skill_id}"
            else:
                normalized_unknown = (
                    self.skill_registry.normalized_name(canonical_name)
                    if self.skill_registry
                    else canonical_name.strip().lower()
                )
                dedup_key = f"name:{normalized_unknown}"

            cand_level = (
                raw_skill_levels.get(clean_mention.lower().strip())
                or (self.taxonomy and raw_skill_levels.get(TaxonomyManager._clean_string(clean_mention)))
                or raw_skill_levels.get(canonical_name.lower().strip())
                or (self.taxonomy and raw_skill_levels.get(TaxonomyManager._clean_string(canonical_name)))
                or (skill_id and raw_skill_levels.get(skill_id))
                or ""
            )

            if dedup_key not in resolved_skills_map:
                resolved_skills_map[dedup_key] = {
                    "skill_id": skill_id,
                    "name": canonical_name,
                    "raw_level": cand_level,
                    "mentions": [TaxonomyManager.clean_skill_label(raw_mention)],
                    "source_declared_aliases": source_declared_aliases,
                }
            else:
                resolved_skills_map[dedup_key]["mentions"].append(TaxonomyManager.clean_skill_label(raw_mention))
                resolved_skills_map[dedup_key]["source_declared_aliases"] = tuple(
                    dict.fromkeys(
                        (*resolved_skills_map[dedup_key]["source_declared_aliases"], *source_declared_aliases)
                    )
                )
                if not resolved_skills_map[dedup_key]["raw_level"] and cand_level:
                    resolved_skills_map[dedup_key]["raw_level"] = cand_level

        final_skills: list[CandidateSkill] = []

        for item in resolved_skills_map.values():
            skill_id = item["skill_id"]
            canonical_name = item["name"]
            raw_level = item["raw_level"]
            mentions = item["mentions"]
            source_declared_aliases = item["source_declared_aliases"]

            taxonomy_item = self.taxonomy.find_skill(canonical_name) if self.taxonomy else None

            # Evidence Verification (Must find verifiable proof in the CV text)
            evidence_items = EvidenceLinker.link_evidence(
                skill_name=canonical_name,
                taxonomy_item=taxonomy_item,
                sections=sections,
                full_text=cleaned_text
            )

            # Fallback search using raw mentions if canonical name didn't catch evidence
            if not evidence_items:
                for m in mentions:
                    evidence_items = EvidenceLinker.link_evidence(
                        skill_name=m,
                        taxonomy_item=None,
                        sections=sections,
                        full_text=cleaned_text
                    )
                    if evidence_items:
                        break

            # If no supporting evidence exists anywhere in the text, reject false positive
            if not evidence_items:
                continue

            if self._is_contextual_only_mention(canonical_name, cleaned_text):
                continue

            # Unknown skills become persistent identities only after this CV has
            # supplied explicit, source-backed evidence for the mention.
            if self.skill_registry:
                skill_id, canonical_name, _ = self.skill_registry.resolve(
                    canonical_name,
                    create_unknown=skill_id is None,
                    source_declared_aliases=source_declared_aliases,
                )

            # Context-Aware Confidence Calculation (independent of proficiency)
            confidence = ConfidenceScorer.calculate_confidence(evidence_items)

            # Proficiency MUST be explicitly supported by CV mention, never inferred from evidence depth!
            explicit_proficiency = None
            if raw_level and str(raw_level).lower().strip() not in ("", "unknown", "none"):
                lvl_clean = str(raw_level).lower().strip()
                if lvl_clean in self._PROFICIENCY_PREFIXES:
                    explicit_proficiency = lvl_clean
                elif lvl_clean in ConfidenceScorer.LEVEL_SYNONYMS:
                    explicit_proficiency = ConfidenceScorer.LEVEL_SYNONYMS[lvl_clean].value

            final_skills.append(
                CandidateSkill(
                    skill_id=skill_id,
                    name=canonical_name,
                    proficiency=explicit_proficiency,
                    confidence=confidence,
                    evidence=evidence_items
                )
            )

        # Sort skills by confidence descending
        final_skills.sort(key=lambda s: s.confidence, reverse=True)

        # Step 9: Assemble Validated Candidate Object
        education_items = [EducationItem(**item) if isinstance(item, dict) else item for item in (entities.get("educations") or entities.get("education") or [])]
        experience_items = [ExperienceItem(**item) if isinstance(item, dict) else item for item in (entities.get("experiences") or entities.get("experience") or [])]
        project_items = [ProjectItem(**item) if isinstance(item, dict) else item for item in (entities.get("projects") or [])]
        cert_items = [CertificateItem(**item) if isinstance(item, dict) else item for item in (entities.get("certificates") or entities.get("certifications") or [])]
        language_items = [LanguageItem(**item) if isinstance(item, dict) else item for item in (entities.get("languages") or [])]

        target_roles = entities.get("target_roles") or []

        user_dict = entities.get("user") if isinstance(entities.get("user"), dict) else {}
        user = UserProfile(
            name=user_dict.get("name") or entities.get("name"),
            email=user_dict.get("email") or entities.get("email"),
        )

        cand_prof_dict = entities.get("candidate_profile") if isinstance(entities.get("candidate_profile"), dict) else {}
        candidate_profile = CandidateProfile(
            headline=cand_prof_dict.get("headline") or entities.get("headline"),
            bio=cand_prof_dict.get("bio") or entities.get("bio"),
            phone=cand_prof_dict.get("phone") or entities.get("phone"),
            location=cand_prof_dict.get("location") or entities.get("location"),
            linkedin_url=cand_prof_dict.get("linkedin_url") or entities.get("linkedin_url"),
            github_url=cand_prof_dict.get("github_url") or entities.get("github_url"),
            portfolio_url=cand_prof_dict.get("portfolio_url") or entities.get("portfolio_url"),
        )

        extracted_preferences = entities.get("preferences")
        preferences = (
            extracted_preferences
            if isinstance(extracted_preferences, CandidatePreferences)
            else CandidatePreferences.model_validate(extracted_preferences or {})
        )

        candidate = Candidate(
            candidate_id=cid,
            user=user,
            candidate_profile=candidate_profile,
            educations=education_items,
            experiences=experience_items,
            projects=project_items,
            certificates=cert_items,
            languages=language_items,
            candidate_skills=final_skills,
            target_roles=target_roles,
            preferences=preferences,
        )

        if return_metadata:
            return candidate, metadata
        return candidate

    def extract_from_text_with_metadata(
        self,
        raw_text: str,
        file_name: str | None = None,
        candidate_id: str | None = None,
        document_urls: list[str] | None = None,
    ) -> tuple[Candidate, CVExtractionMetadata]:
        """
        Executes text extraction and returns (Candidate, CVExtractionMetadata).
        """
        return self.extract_from_text(
            raw_text=raw_text,
            file_name=file_name,
            candidate_id=candidate_id,
            document_urls=document_urls,
            return_metadata=True,
        )
