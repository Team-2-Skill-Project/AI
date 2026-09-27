from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..models.taxonomy import SkillTaxonomyItem

logger = logging.getLogger(__name__)


# Terms that are never meaningful standalone skills.  This intentionally excludes
# cross-profession terms (for example, management, law, clinical, backend, and
# architecture): when the LLM explicitly extracts those labels, they are kept as
# open-world skills unless the label itself is structural noise.
STOPWORDS_BLACKLIST = {
    # English articles, prepositions, conjunctions, pronouns
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with", "by", "from",
    "of", "as", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "but", "if", "so", "than", "that", "this", "these", "those",
    "it", "its", "you", "your", "he", "she", "we", "they", "i", "me", "my", "our",

    # Generic resume action verbs and adjectives
    "advanced", "intermediate", "beginner", "expert", "senior", "junior", "lead",
    "developed", "building", "built", "engineered", "managing", "managed", "designed",
    "implemented", "applied", "applied advanced", "applied algorithms", "created", "led",
    "facilitate", "support", "automate", "automated", "featuring", "include", "including",
    "selected", "specializing", "focus", "focusing", "collaborated", "architected",
    "sophisticated", "accurate", "comprehensive", "intelligent", "high", "low", "real",

    # Resume headers and structural labels
    "experience", "education", "skills", "certifications", "summary",
    "overview", "tools", "languages", "frameworks", "technologies", "responsibilities",
    "activities", "courses", "coursework",

    # Noise and punctuation residues
    "etc", "eg", "ie", "nan", "null", "none", "true", "false", "string", "item", "items"
}


# Retained as a public compatibility export for callers that import it.  Generic
# professional terms are not blacklisted; explicit extraction preserves them.
LEGITIMATE_EXPLICIT_SKILLS: frozenset[str] = frozenset()


class TaxonomyManager:
    """
    Manages canonical skills taxonomy, aliases, and normalizations for SkillMatch.
    Resolves known name-level aliases and filters structural noise while preserving
    unknown explicit skills without assigning a taxonomy ID.
    """

    def __init__(self, seed_file_path: str | Path | None = None):
        self._by_id: dict[str, SkillTaxonomyItem] = {}
        self._lookup: dict[str, str] = {}  # lowercase alias/name -> skill_id

        base_dir = Path(__file__).resolve().parent.parent.parent
        if seed_file_path is None:
            resolved_seed = base_dir / "docs" / "ai-contract" / "skills_seed.json"
        else:
            path_obj = Path(seed_file_path)
            if path_obj.is_absolute() or path_obj.exists():
                resolved_seed = path_obj.resolve()
            else:
                resolved_seed = base_dir / path_obj

        self.load_from_json(resolved_seed)

    def load_from_json(self, file_path: str | Path) -> None:
        """Loads canonical skills and aliases from JSON."""
        path_obj = Path(file_path)
        if not path_obj.is_absolute() and not path_obj.exists():
            base_dir = Path(__file__).resolve().parent.parent.parent
            resolved = base_dir / path_obj
            if resolved.exists():
                path_obj = resolved

        if path_obj.exists():
            with open(path_obj, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    skill = SkillTaxonomyItem(**item)
                    self.register_skill(skill)
            logger.info(f"Loaded {len(self._by_id)} canonical skills from taxonomy seed '{path_obj}'")
        else:
            logger.warning(
                f"Taxonomy seed file not found at '{file_path}' (resolved: '{path_obj}'). Starting with empty taxonomy."
            )


    def register_skill(self, skill: SkillTaxonomyItem) -> None:
        """Registers a canonical skill item and indexes all its aliases."""
        self._by_id[skill.skill_id] = skill

        # Index canonical name
        self._index_term(skill.canonical_name, skill.skill_id)

        # Index raw skill_id without 'skill_' prefix
        clean_id = skill.skill_id.replace("skill_", "").replace("_", " ")
        self._index_term(clean_id, skill.skill_id)

        # Index all aliases
        for alias in skill.aliases:
            self._index_term(alias, skill.skill_id)

    def _index_term(self, term: str, skill_id: str) -> None:
        normalized = self._clean_string(term)
        if normalized and normalized not in STOPWORDS_BLACKLIST:
            self._lookup[normalized] = skill_id

    @staticmethod
    def _clean_string(text: str) -> str:
        """Lowercases and strips common punctuation for robust key matching."""
        if not text:
            return ""
        cleaned = text.lower().strip()
        # Keep alphanumeric, +, #, ., -
        cleaned = re.sub(r"[^\w\s+#.-]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    @staticmethod
    def clean_skill_label(text: str) -> str:
        """Remove list punctuation without damaging balanced punctuation in a skill label."""
        if not isinstance(text, str):
            return ""

        cleaned = re.sub(r"^[•\u2022\u25e6*\-]+\s*", "", text.strip())
        cleaned = re.sub(r"[,;:]+$", "", cleaned).rstrip()
        pairs = {")": "(", "]": "[", "}": "{"}

        while cleaned and cleaned[-1] in pairs:
            closing = cleaned[-1]
            if cleaned.count(closing) <= cleaned.count(pairs[closing]):
                break
            cleaned = cleaned[:-1].rstrip()

        return cleaned

    def is_blacklisted(self, raw_name: str, is_explicit: bool = False) -> bool:
        """Checks structural noise; ``is_explicit`` is retained for caller compatibility."""
        if not raw_name:
            return True

        raw_trimmed = raw_name.strip()
        if not raw_trimmed or len(raw_trimmed) < 2:
            return True

        # Reject standalone emails
        if "@" in raw_trimmed and re.search(r"[\w\.-]+@[\w\.-]+\.\w+", raw_trimmed):
            return True

        # Reject URLs or domain links
        lower_raw = raw_trimmed.lower()
        if (
            lower_raw.startswith(("http://", "https://", "www."))
            or "://" in lower_raw
            or re.search(r"\b\w+\.(?:com|org|net|io|sa|edu|gov)(?:/|\s|$)", lower_raw)
        ):
            return True

        cleaned = self._clean_string(raw_trimmed)
        if not cleaned or len(cleaned) < 2:
            return True

        # Purely numeric, punctuation-only, or single-character noise.
        # C++, C#, and .NET remain valid because they contain letters.
        if (
            re.fullmatch(r"\d[\d., -]*", cleaned)
            or not any(character.isalpha() for character in cleaned)
            or len(cleaned) <= 1
        ):
            return True

        # Exact match in blacklist
        if cleaned in STOPWORDS_BLACKLIST:
            return True

        return False

    def find_skill(self, raw_name: str) -> SkillTaxonomyItem | None:
        """
        Attempts to resolve a raw skill string to a canonical SkillTaxonomyItem.
        Returns None if not found in the taxonomy or blacklisted.
        """
        if self.is_blacklisted(raw_name):
            return None

        cleaned = self._clean_string(raw_name)

        # 1. Direct Lookup
        if cleaned in self._lookup:
            return self._by_id.get(self._lookup[cleaned])

        # 2. Strip trailing dots or brackets (e.g. "React.js)" -> "react.js", "NLP." -> "nlp")
        stripped_dots = re.sub(r"[\.\,\)\(\:]+$", "", cleaned).strip()
        if stripped_dots in self._lookup:
            return self._by_id.get(self._lookup[stripped_dots])

        # 3. Strip descriptor suffixes (e.g. "FastAPI Framework" -> "fastapi", "PyTorch Library" -> "pytorch")
        desc_stripped = re.sub(r"\s+(framework|library|database|tool|language|programming|tech|stack|api|apis)$", "", cleaned).strip()
        if desc_stripped in self._lookup:
            return self._by_id.get(self._lookup[desc_stripped])

        # 4. Strip version suffixes (e.g. "Python 3.10" -> "python", "Java 17" -> "java")
        version_stripped = re.sub(r"\s+v?\d+(\.\d+)*.*$", "", cleaned).strip()
        if version_stripped in self._lookup:
            return self._by_id.get(self._lookup[version_stripped])

        # 5. Exact hyphen/space substitution (e.g. "Scikit-learn" vs "scikit learn")
        alt_hyphen = cleaned.replace("-", " ")
        if alt_hyphen in self._lookup:
            return self._by_id.get(self._lookup[alt_hyphen])

        # 6. Substring / Token matching for multi-word phrases with recognized technical modifiers only
        tokens = cleaned.split()
        if len(tokens) == 2:
            KNOWN_MODIFIERS = {
                "framework", "library", "database", "lang", "language", "programming",
                "tool", "tools", "stack", "api", "apis", "sdk", "platform", "cloud",
                "server", "core", "js", "ts", "developer", "engineer", "specialist",
                "development", "architecture", "technologies", "technology"
            }
            if tokens[0] in self._lookup and tokens[1] in KNOWN_MODIFIERS:
                matched_item = self._by_id.get(self._lookup[tokens[0]])
                if matched_item and matched_item.skill_id not in ("skill_communication", "skill_management", "skill_leadership"):
                    return matched_item
            elif tokens[1] in self._lookup and tokens[0] in KNOWN_MODIFIERS:
                matched_item = self._by_id.get(self._lookup[tokens[1]])
                if matched_item and matched_item.skill_id not in ("skill_communication", "skill_management", "skill_leadership"):
                    return matched_item

        return None

    def normalize_skill(self, raw_name: str, strict: bool = True) -> tuple[str | None, str | None, str | None]:
        """
        Returns (skill_id, canonical_name, category).
        If strict=True: returns (None, None, None) if not found in taxonomy or blacklisted.
        Unknown skills never receive synthetic taxonomy IDs.  Call resolve() for
        open-world extraction, where an unknown explicit label is preserved.
        """
        matched = self.find_skill(raw_name)
        if matched:
            return matched.skill_id, matched.canonical_name, matched.category

        return None, None, None

    def resolve(self, raw_skill: str) -> tuple[str | None, str]:
        """
        Non-destructive resolution for open-world skill extraction.
        Returns (skill_id, canonical_name).

        KNOWN:
            -> (canonical skill_id, canonical name)
        UNKNOWN:
            -> (None, cleaned original name)

        Taxonomy lookup failure never drops the skill.
        Pure stopwords, URLs, and numeric noise return (None, "").
        """
        if not raw_skill or not raw_skill.strip():
            return None, ""

        if self.is_blacklisted(raw_skill, is_explicit=True):
            return None, ""

        matched = self.find_skill(raw_skill)
        if matched:
            return matched.skill_id, matched.canonical_name

        cleaned = self.clean_skill_label(raw_skill)
        if not cleaned or len(cleaned) < 2 or self.is_blacklisted(cleaned, is_explicit=True):
            return None, ""

        return None, cleaned

    def get_all_skills(self) -> list[SkillTaxonomyItem]:
        return list(self._by_id.values())
