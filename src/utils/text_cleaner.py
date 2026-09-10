import logging
import re

logger = logging.getLogger(__name__)


class TextCleaner:
    """
    Cleans raw text extracted from PDFs, OCR, DOCX, and splits into candidate sections.
    """

    # Comprehensive CV Section Header Regex Patterns (matched against normalized headers)
    SECTION_HEADERS = {
        "summary": (
            r"^(?:professional\s+|career\s+|executive\s+|personal\s+)?(?:summary|profile|overview|statement|bio|biography|objective|about\s+me|about|introduction|background)$"
        ),
        "education": (
            r"^(?:educational\s+|academic\s+)?(?:education|background|history|qualifications?|studies|degrees?|schooling|credentials?|records?|training)(?:\s+(?:and\s+training|and\s+qualifications|background|history|qualifications?|credentials?|records?))?$"
        ),
        "experience": (
            r"^(?:(?:work|professional|employment|career|job|industry|practical|relevant|internship)\s+(?:and\s+|&\s+)?(?:internships?|employment|work|experience)?\s*)?(?:experience|experiences|history|background|employment|internships?|work\s+history)$"
            r"^(?:(?:work|professional|employment|career|job|industry|practical|relevant|internship|customer\s+service|research|teaching|leadership)\s+(?:and\s+|&\s+)?(?:internships?|employment|work|experience)?\s*)?(?:experience|experiences|history|background|employment|internships?|work\s+history)$"
        ),
        "projects": (
            r"^(?:key\s+|selected\s+|personal\s+|academic\s+|technical\s+|software\s+|engineering\s+|featured\s+|major\s+|recent\s+|relevant\s+|capstone\s+|open\s+source\s+|coursework\s+|github\s+)?(?:projects?|portfolio|project\s+work|project\s+experience)$"
        ),
        "skills": (
            r"^(?:technical\s+|core\s+|key\s+|professional\s+|programming\s+|software\s+|computer\s+|it\s+|developer\s+)?(?:skills?|technologies|tech\s+stack|technology\s+stack|competencies|expertise|proficiencies|tools?|languages\s+and\s+(?:frameworks|technologies|tools)|specializations)(?:\s+(?:and\s+|&\s+)(?:competencies|tools?|technologies|abilities|frameworks|(?:tech\s+)?stack))?$"
        ),
        "certifications": (
            r"^(?:professional\s+)?(?:certifications?|certificates?|licenses?|courses?|training|achievements?|awards?|honors?|accreditations?|credentials|publications?|patents?)(?:\s+(?:and\s+|&\s+)(?:licenses?|certifications?|courses?|training|achievements?|awards?|honors?|patents?))?$"
        ),
        "other": (
            r"^(?:foreign\s+)?(?:languages?|language\s+skills?|volunteer(?:ing)?|volunteer\s+(?:experience|work)|community\s+service|extracurricular(?:s|\s+activities)?|activities|leadership(?:\s+activities)?|interests|hobbies(?:\s+and\s+interests)?|references(?:\s+available\s+upon\s+request)?|affiliations|memberships|contact(?:\s+info(?:rmation)?)?|personal\s+details|additional\s+information|miscellaneous)$"
        ),
    }

    # Keyword weights for fuzzy/partial matching fallback
    SECTION_KEYWORDS = {
        "experience": {
            "primary": {"experience", "experiences", "employment", "internship", "internships", "work", "career", "job", "jobs", "employer", "employers", "practicum"},
            "secondary": {"professional", "history", "positions", "industry", "practical", "relevant", "corporate", "hands-on", "working", "background"},
        },
        "education": {
            "primary": {"education", "academic", "academics", "degree", "degrees", "university", "college", "school", "schooling", "qualifications", "studies", "diploma", "bachelor", "master", "phd", "gpa"},
            "secondary": {"background", "history", "records", "credentials", "training", "educational"},
        },
        "projects": {
            "primary": {"project", "projects", "portfolio", "capstone", "codebase", "hackathon", "sideproject"},
            "secondary": {"selected", "personal", "academic", "technical", "key", "featured", "software", "github"},
        },
        "skills": {
            "primary": {"skill", "skills", "technologies", "technology", "competencies", "competency", "stack", "proficiencies", "proficiency", "expertise", "tools", "languages", "frameworks"},
            "secondary": {"technical", "programming", "core", "software", "specializations", "strengths"},
        },
        "certifications": {
            "primary": {"certification", "certifications", "certificate", "certificates", "license", "licenses", "award", "awards", "honor", "honors", "achievement", "achievements", "accreditation", "accreditations", "publication", "publications", "patent", "patents"},
            "secondary": {"courses", "training", "credentials", "accomplishments"},
        },
        "summary": {
            "primary": {"summary", "profile", "objective", "biography", "bio", "overview", "statement", "intro", "introduction"},
            "secondary": {"professional", "career", "personal", "executive", "about", "me"},
        },
        "other": {
            "primary": {"languages", "language", "volunteer", "volunteering", "extracurricular", "activities", "interests", "hobbies", "hobby", "references", "affiliations", "memberships", "contact"},
            "secondary": {"community", "service", "involvement", "leadership", "personal", "additional"},
        },
    }

    # Suffixes and indicators that mark a content line (job title, company, project product) rather than a section header
    CONTENT_DISQUALIFIERS = {
        "engineer", "developer", "trainer", "specialist", "manager", "analyst",
        "lead", "consultant", "intern", "officer", "director", "assistant",
        "coordinator", "technician", "designer", "scientist", "architect",
        "instructor", "administrator", "representative", "associate", "expert",
        "app", "application", "platform", "website", "system", "tool",
        "dashboard", "pipeline", "service", "bot", "model", "classifier",
        "detector", "api", "portal", "tracker", "engine", "plugin",
        "web", "mobile", "frontend", "backend", "cloud", "fullstack",
        "llc", "inc", "ltd", "corp", "corporation", "company", "co",
        "solutions", "technologies", "labs", "studio", "group", "enterprises",
        "consulting", "partners", "agency", "holdings", "gmbh", "sae", "pvt",
    }

    DATE_PATTERN = re.compile(
        r"(\b(?:19|20)\d{2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(?:19|20)\d{2}\b)",
        re.IGNORECASE
    )

    STOPWORDS = {"and", "or", "the", "of", "in", "for", "with", "to", "my", "our", "a", "an", "&"}

    # Modifiers that identify a software component or technical product when preceding 'service(s)'
    TECH_SERVICE_MODIFIERS = {
        "web", "cloud", "micro", "api", "rest", "software", "network",
        "system", "database", "backend", "frontend", "customer", "it",
    }

    @staticmethod
    def _header_to_key(normalized_text: str) -> str:
        """
        Converts a normalized header string to a valid snake_case dict key (max 40 chars).
        Used to name dynamic sections for unrecognized CV headers.
        Example: "military service" → "military_service"
                 "open source contributions" → "open_source_contributions"
        """
        key = re.sub(r"\s+", "_", normalized_text.strip())
        key = re.sub(r"[^a-z0-9_]", "", key)
        return key[:40] if key else "other"

    @staticmethod
    def clean_text(raw_text: str) -> str:
        """Removes null bytes, excessive spaces, and fixes strange line breaks."""
        if not raw_text:
            return ""

        # Remove null characters
        text = raw_text.replace("\x00", " ")
        # Normalize non-breaking spaces
        text = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
        # Collapse multiple spaces on a single line
        text = re.sub(r"[ \t]+", " ", text)
        # Remove any metadata link blocks
        text = re.sub(r"\[Document Embedded Links & URLs\][\s\S]*?(?=\n\n|\Z)", "", text, flags=re.IGNORECASE)
        # Collapse excessive newlines (max 2 consecutive)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def _normalize_header(cls, text: str) -> str:
        """Normalizes header text by removing symbols, numbering, and punctuation."""
        t = text.strip()
        # Strip markdown markers and decorations
        t = re.sub(r"^[#\*\_\=\-\~\+\[\]\(\)\|\>\s]+|[#\*\_\=\-\~\+\[\]\(\)\|\>\s]+$", "", t)
        # Strip leading section numbering (e.g. 1., I., Section 1:) requiring punctuation for Roman numerals/letters
        t = re.sub(r"^(?:section\s+)?(?:\d+[\.\)\:\-\s]+|[ivxlcdm]+[\.\)\:\-]+|[a-z][\.\)\:\-]+)\s*", "", t, flags=re.IGNORECASE)
        # Strip trailing colons / dashes
        t = re.sub(r"[\:\-\.\;]+$", "", t)
        # Standardize symbols
        t = re.sub(r"&", " and ", t)
        t = re.sub(r"/", " and ", t)
        t = re.sub(r"[^\w\s]", " ", t)
        t = re.sub(r"\s+", " ", t)
        return t.strip().lower()

    @classmethod
    def detect_section_header(
        cls,
        line_str: str,
        is_paragraph_boundary: bool = False,
        prev_line_is_entry_content: bool = False
    ) -> tuple[str | None, bool]:
        """
        Detects if a given line is a CV section header.
        Returns (section_name, is_header_like).
        """
        line = line_str.strip()
        if not line or len(line) > 55 or len(line.split()) > 7:
            return None, False

        if (
            "@" in line
            or "http" in line
            or "github.com" in line
            or "linkedin.com" in line
            or "|" in line
            or line.startswith("•")
            or line.startswith("- ")
            or line.startswith("* ")
            or line.startswith("+ ")
            or (line.endswith(".") and len(line.split()) > 2)
            or cls.DATE_PATTERN.search(line)
        ):
            return None, False

        is_h3_plus = bool(re.match(r"^#{3,}\s+", line))
        is_markdown_header = line.startswith(("#", "==", "--", "**", "__", "["))

        norm = cls._normalize_header(line)
        if not norm:
            return None, False

        tokens = set(norm.split())
        meaningful_tokens = tokens - cls.STOPWORDS

        disqualifiers_hit = meaningful_tokens.intersection(cls.CONTENT_DISQUALIFIERS)
        # 'military service' is a legitimate section title, not a software service or generic job title
        if "service" in disqualifiers_hit and "military" in meaningful_tokens:
            disqualifiers_hit = disqualifiers_hit - {"service"}
        # Content disqualifiers like 'service' can collide with legitimate civic/institutional section titles
        # (e.g. 'Military Service', 'Community Service', 'Civil Service', 'Public Service', 'National Service').
        # If 'service' is the final head noun of a short phrase (<= 2 tokens) and is NOT modified by
        # technical or customer-support modifiers, it represents a legitimate civic/service section header.
        if "service" in disqualifiers_hit:
            norm_tokens = norm.split()
            if (
                len(norm_tokens) <= 2
                and norm_tokens[-1] in ("service", "services")
                and not any(t in cls.TECH_SERVICE_MODIFIERS for t in norm_tokens[:-1])
            ):
                disqualifiers_hit = disqualifiers_hit - {"service"}

        # ALL-CAPS lines, colon-terminated lines, and top-level markdown headers at paragraph boundaries
        # are structurally unambiguous section-header patterns.
        # Level-3+ markdown headers (###) containing content disqualifiers (e.g. '### Cloud Deployer',
        # '### Senior Backend Developer') are entry sub-headings within a section and do NOT bypass
        # the disqualifiers gate unless ALL-CAPS (e.g. '### MILITARY SERVICE').
        is_strong_structural_header = (
            is_paragraph_boundary
            and not prev_line_is_entry_content
            and 1 <= len(meaningful_tokens) <= 4
            and (line.isupper() or line.endswith(":") or (is_markdown_header and not (is_h3_plus and disqualifiers_hit)))
        )

        if disqualifiers_hit and not is_strong_structural_header:
            if not any(re.fullmatch(p, norm, flags=re.IGNORECASE) for p in cls.SECTION_HEADERS.values()):
                return None, False

        for sec_name, pattern in cls.SECTION_HEADERS.items():
            if re.fullmatch(pattern, norm, flags=re.IGNORECASE):
                return sec_name, True

        if is_paragraph_boundary and len(meaningful_tokens) <= 4 and not disqualifiers_hit:
            best_section = None
            best_score = 0.0
            primary_hits = 0
            total_hits = 0
            for sec_name, kw_dict in cls.SECTION_KEYWORDS.items():
                p_hits = sum(1 for w in meaningful_tokens if w in kw_dict["primary"])
                s_hits = sum(1 for w in meaningful_tokens if w in kw_dict["secondary"])
                score = (p_hits * 3.0) + (s_hits * 1.0)
                if score > best_score:
                    best_score = score
                    best_section = sec_name
                    primary_hits = p_hits
                    total_hits = p_hits + s_hits

            if best_section:
                if total_hits >= 2 or (primary_hits >= 1 and (line.isupper() or is_markdown_header)):
                    return best_section, True

        # Tier 3: Any structurally unambiguous header line (ALL-CAPS, colon-terminated, or
        # markdown header at paragraph boundary) that reached this point is an unrecognized
        # section. Create a dynamic section key from the normalized header text.
        # Note: is_strong_structural_header already includes is_markdown_header in its
        # condition, so this single check handles all Tier 3 cases.
        if is_markdown_header or is_strong_structural_header:
            dynamic_key = cls._header_to_key(norm) if norm else "other"
            logger.warning(
                "Unrecognized CV section header '%s' → dynamic section '%s'.",
                line_str,
                dynamic_key,
            )
            return dynamic_key, True

        return None, False

    @classmethod
    def segment_sections(cls, full_text: str) -> dict[str, str]:
        """
        Splits clean text into standard CV sections:
        header, education, experience, projects, skills, certifications, summary, other.
        """
        cleaned = cls.clean_text(full_text)
        lines = cleaned.split("\n")

        sections: dict[str, list[str]] = {
            "header": [],
            "summary": [],
            "education": [],
            "experience": [],
            "projects": [],
            "skills": [],
            "certifications": [],
            "other": [],
        }

        current_section = "header"
        prev_line_is_entry = False

        for idx, line in enumerate(lines):
            line_str = line.strip()
            if not line_str:
                prev_line_is_entry = False
                continue

            is_paragraph_boundary = (idx == 0) or (not lines[idx - 1].strip())

            detected_header, _ = cls.detect_section_header(
                line_str=line_str,
                is_paragraph_boundary=is_paragraph_boundary,
                prev_line_is_entry_content=prev_line_is_entry
            )

            if detected_header:
                # Create the section bucket on first encounter (handles dynamic keys)
                if detected_header not in sections:
                    sections[detected_header] = []
                current_section = detected_header
                prev_line_is_entry = False

            else:
                sections[current_section].append(line_str)
                prev_line_is_entry = (
                    line_str.startswith("•")
                    or line_str.startswith("- ")
                    or line_str.startswith("* ")
                    or "|" in line_str
                    or bool(cls.DATE_PATTERN.search(line_str))
                )

        # Convert lists of lines back to single string per section
        return {sec: "\n".join(content_lines) for sec, content_lines in sections.items() if content_lines}
