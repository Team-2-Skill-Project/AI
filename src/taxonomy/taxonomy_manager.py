import json
import logging
import re
from pathlib import Path

from ..models.taxonomy import SkillTaxonomyItem

logger = logging.getLogger(__name__)


# Blacklist of common stopwords, noise words, URLs, and generic non-skill tokens
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

    # Generic business and resume headers
    "system", "systems", "features", "processes", "platform", "platforms", "projects",
    "project", "experience", "education", "skills", "certifications", "summary",
    "overview", "tools", "languages", "frameworks", "technologies", "responsibilities",
    "activities", "courses", "coursework", "management", "lifecycle", "architecture",
    "solutions", "workflows", "ecosystems", "decision", "decisions", "choices",
    "document", "documents", "archiving", "notifications", "judicial", "legal",
    "law", "firm", "health", "clinical", "patient", "nutritionists", "saudi", "arabia",
    "egypt", "cairo", "mansoura", "live", "ar", "en", "stack", "fullstack", "full",
    "backend", "frontend", "engineering", "programming", "databases", "development",

    # Noise and punctuation residues
    "etc", "eg", "ie", "nan", "null", "none", "true", "false", "string", "item", "items"
}


class TaxonomyManager:
    """
    Manages canonical skills taxonomy, aliases, and normalizations for SkillMatch.
    Ensures all extracted skills map strictly to standard skill IDs and filters out garbage noise.
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
                f"Taxonomy seed file not found at '{file_path}' (resolved: '{path_obj}'). Loading fallback seed."
            )
            self._load_fallback_seed()


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

    def is_blacklisted(self, raw_name: str) -> bool:
        """Checks if a string is a stopword, URL, punctuation noise, or purely numerical."""
        if not raw_name:
            return True

        cleaned = self._clean_string(raw_name)
        if not cleaned or len(cleaned) < 2:
            return True

        # Reject URLs or file paths
        if any(indicator in cleaned for indicator in ["http", "://", ".com", ".sa", ".org", ".net", ".io", "www.", "/"]):
            return True

        # Purely numeric or single characters
        if re.match(r"^\d+$", cleaned) or len(cleaned) <= 1:
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
        If strict=False: creates a normalized slug only if not blacklisted.
        """
        matched = self.find_skill(raw_name)
        if matched:
            return matched.skill_id, matched.canonical_name, matched.category

        if strict or self.is_blacklisted(raw_name):
            return None, None, None

        # Filter out multi-word sentence fragments or feature descriptions
        words = raw_name.strip().split()
        if len(words) > 2 or len(raw_name) > 25:
            return None, None, None

        # Non-strict fallback for validated technical entities only
        clean_id = self._clean_string(raw_name).replace(" ", "_").replace(".", "_").replace("+", "p").replace("#", "sharp")
        clean_id = re.sub(r"[^\w_]", "", clean_id)
        if len(clean_id) < 2:
            return None, None, None

        skill_id = f"skill_{clean_id}"
        canonical_name = raw_name.strip().title()
        category = "Tools"
        return skill_id, canonical_name, category

    def get_all_skills(self) -> list[SkillTaxonomyItem]:
        return list(self._by_id.values())

    def _load_fallback_seed(self) -> None:
        """Default seed if JSON file is not found."""
        defaults = [
            {"skill_id": "skill_python", "canonical_name": "Python", "category": "Programming Languages", "aliases": ["Python 3"]},
            {"skill_id": "skill_sql", "canonical_name": "SQL", "category": "Databases", "aliases": ["PostgreSQL", "MySQL"]},
            {"skill_id": "skill_machine_learning", "canonical_name": "Machine Learning", "category": "AI & Machine Learning", "aliases": ["ML"]},
            {"skill_id": "skill_llms", "canonical_name": "Large Language Models", "category": "AI & Machine Learning", "aliases": ["LLMs", "LLM"]},
            {"skill_id": "skill_react", "canonical_name": "React", "category": "Frameworks", "aliases": ["React.js"]},
            {"skill_id": "skill_fastapi", "canonical_name": "FastAPI", "category": "Frameworks", "aliases": ["FastAPI Framework"]},
            {"skill_id": "skill_docker", "canonical_name": "Docker", "category": "DevOps", "aliases": []},
            {"skill_id": "skill_git", "canonical_name": "Git", "category": "Tools", "aliases": ["GitHub"]},
        ]
        for item in defaults:
            self.register_skill(SkillTaxonomyItem(**item))
