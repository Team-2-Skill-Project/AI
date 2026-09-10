import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class ProjectLinkAssociator:
    """
    Precision Project-to-URL Association Engine.

    Adheres strictly to the 7 project-link association rules:
      1. Extract all URLs/hyperlinks from the CV.
      2. Associate a URL with a project ONLY when there is strong evidence.
      3. Use the project's surrounding text/section and title similarity.
      4. Do not assign a URL from another project just because it is nearby.
      5. If a project's URL cannot be confidently associated with it, return None (null).
      6. Prefer the GitHub repository URL explicitly associated with the project.
      7. Never reuse the same URL for multiple unrelated projects unless explicitly indicated.
    """

    NON_PROJECT_DOMAINS = {
        "linkedin.com",
        "twitter.com",
        "x.com",
        "facebook.com",
        "instagram.com",
        "medium.com",
        "kaggle.com/u/",
    }

    GENERIC_STOP_WORDS = {
        "ai", "project", "system", "app", "application", "repo", "repository",
        "github", "assistant", "the", "a", "an", "engine", "tool", "model",
        "service", "platform", "web", "pipeline", "bot"
    }

    @classmethod
    def extract_candidate_urls(cls, full_text: str, document_urls: list[str] | None = None) -> list[str]:
        """
        Extracts and filters all potential project URLs from raw text and document annotations.
        Rejects LinkedIn, social profiles, and pure GitHub user account URLs.
        """
        found_urls = re.findall(r"https?://[^\s\)\],\"'<>]+", full_text)
        if document_urls:
            found_urls.extend(document_urls)

        candidates: list[str] = []
        for raw_url in found_urls:
            clean = raw_url.strip().rstrip(".,)]\"'")
            if not (clean.startswith("http://") or clean.startswith("https://")):
                continue

            lower_url = clean.lower()

            # Rule 1 & 6: Reject personal/social profiles
            if any(domain in lower_url for domain in cls.NON_PROJECT_DOMAINS):
                continue

            # Reject pure GitHub user profile: e.g. https://github.com/username (must have repo slug)
            if re.match(r"^https?://github\.com/[^/]+/?$", clean, flags=re.IGNORECASE):
                continue

            if clean not in candidates:
                candidates.append(clean)

        return candidates

    @classmethod
    def _clean_slug(cls, text: str) -> str:
        """Lowercases and strips non-alphanumeric characters for slug matching."""
        return re.sub(r"[^a-z0-9]", "", text.lower())

    @classmethod
    def _extract_tokens(cls, text: str) -> set[str]:
        """Extracts distinctive word tokens splitting CamelCase and punctuation."""
        s = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
        words = re.findall(r"[a-z0-9]+", s.lower())
        return {w for w in words if len(w) >= 3 and w not in cls.GENERIC_STOP_WORDS}

    @classmethod
    def _calculate_association_confidence(cls, project_title: str, project_desc: str, url: str) -> float:
        """
        Calculates match confidence (0.0 to 1.0) between project metadata and a candidate URL.
        Strong evidence requires >= 0.60.
        """
        title_slug = cls._clean_slug(project_title)
        title_tokens = cls._extract_tokens(project_title)

        # Extract repo name or last path component
        if "github.com/" in url:
            parts = url.split("github.com/")[-1].split("/")
            repo_name = parts[1] if len(parts) > 1 else parts[0]
        else:
            repo_name = url.rstrip("/").split("/")[-1]

        repo_slug = cls._clean_slug(repo_name)
        repo_tokens = cls._extract_tokens(repo_name)

        if not title_slug or not repo_slug:
            return 0.0

        # Exact slug match (e.g. TruthStream AI vs Truth-Stream-AI -> truthstreamai == truthstreamai)
        if title_slug == repo_slug:
            return 1.0

        # Substring slug match if significant length (>= 5 chars)
        if len(repo_slug) >= 5 and (repo_slug in title_slug or title_slug in repo_slug):
            return 0.95

        # Distinctive token overlap
        if title_tokens and repo_tokens:
            common = title_tokens & repo_tokens
            if common:
                # If all significant repo tokens are present in title
                if common == repo_tokens:
                    return 0.90
                # Overlap ratio
                overlap = len(common) / max(len(title_tokens), len(repo_tokens))
                if overlap >= 0.5:
                    return 0.70 + (overlap * 0.20)

        # Check if repo name is mentioned directly in project description
        if len(repo_slug) >= 5 and repo_slug in cls._clean_slug(project_desc):
            return 0.75

        return 0.0

    @classmethod
    def associate_projects_with_links(
        cls,
        projects: list[dict[str, Any]],
        full_text: str,
        document_urls: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """
        Assigns URLs to projects adhering to the 7 strict rules.
        """
        candidate_urls = cls.extract_candidate_urls(full_text, document_urls)
        claimed_urls: set[str] = set()

        for proj in projects:
            title = proj.get("title", "").strip()
            desc = proj.get("description", "")
            raw_link = proj.get("link")

            # Clean any invalid placeholder text like "GitHub Repo"
            clean_raw = raw_link.strip().rstrip(".,)]\"'") if isinstance(raw_link, str) else None
            is_valid_url = clean_raw and (clean_raw.startswith("http://") or clean_raw.startswith("https://"))

            # If an existing link is invalid or a non-project domain (e.g. LinkedIn), clear it
            if is_valid_url and any(d in clean_raw.lower() for d in cls.NON_PROJECT_DOMAINS):
                clean_raw = None
                is_valid_url = False

            # If existing link is a pure user profile (https://github.com/user), clear it
            if is_valid_url and re.match(r"^https?://github\.com/[^/]+/?$", clean_raw, flags=re.IGNORECASE):
                clean_raw = None
                is_valid_url = False

            # Check if clean_raw is already a valid project repository/live URL present in the document
            if is_valid_url and clean_raw not in claimed_urls and clean_raw in candidate_urls:
                proj["link"] = clean_raw
                claimed_urls.add(clean_raw)
                continue

            # Otherwise, search among available candidate URLs for strong evidence
            best_url: str | None = None
            best_score = 0.0

            for candidate in candidate_urls:
                # Rule 7: Never reuse the same URL for multiple unrelated projects
                if candidate in claimed_urls:
                    continue

                conf = cls._calculate_association_confidence(title, desc, candidate)
                if conf > best_score:
                    best_score = conf
                    best_url = candidate

            # Rule 5: If cannot be confidently associated (>= 0.60), return null
            if best_url and best_score >= 0.60:
                proj["link"] = best_url
                claimed_urls.add(best_url)
            else:
                proj["link"] = None

        return projects
