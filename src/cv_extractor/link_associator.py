from __future__ import annotations

import logging
import re
from typing import Any

from ..utils.url_normalizer import extract_web_url_candidates, normalize_web_url

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
        found_urls = extract_web_url_candidates(full_text)
        if document_urls:
            found_urls.extend(document_urls)

        candidates: list[str] = []
        for raw_url in found_urls:
            clean = normalize_web_url(raw_url)
            if not clean:
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
    def _assign_url(cls, project: dict[str, Any], url: str) -> None:
        """Store a project URL in exactly one semantically appropriate URL field."""
        if "github.com" in url.lower():
            project["github_url"] = url
            project["project_url"] = None
        else:
            project["project_url"] = url
            project["github_url"] = None

    @classmethod
    def _clean_slug(cls, text: str | None) -> str:
        """Lowercases and strips non-alphanumeric characters for slug matching."""
        if not text:
            return ""
        return re.sub(r"[^a-z0-9]", "", text.lower())

    @classmethod
    def _extract_tokens(cls, text: str | None) -> set[str]:
        """Extracts distinctive word tokens splitting CamelCase and punctuation."""
        if not text:
            return set()
        s = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
        words = re.findall(r"[a-z0-9]+", s.lower())
        return {w for w in words if len(w) >= 3 and w not in cls.GENERIC_STOP_WORDS}

    @classmethod
    def _calculate_association_confidence(cls, project_title: str, project_desc: str, url: str) -> float:
        """
        Calculates match confidence (0.0 to 1.0) between project metadata and a candidate URL.
        Strong evidence requires >= 0.60.
        """
        safe_title = project_title or ""
        safe_desc = project_desc or ""
        title_slug = cls._clean_slug(safe_title)
        title_tokens = cls._extract_tokens(safe_title)

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
        if len(repo_slug) >= 5 and repo_slug in cls._clean_slug(safe_desc):
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
            title = (proj.get("title") or "").strip()
            desc = proj.get("description") or ""
            raw_url = proj.get("github_url") or proj.get("project_url") or proj.get("link")

            clean_raw = normalize_web_url(raw_url)

            # If an existing link is invalid or a non-project domain (e.g. LinkedIn), clear it
            if clean_raw and any(d in clean_raw.lower() for d in cls.NON_PROJECT_DOMAINS):
                clean_raw = None

            # If existing link is a pure user profile (https://github.com/user), clear it
            if clean_raw and re.match(r"^https?://github\.com/[^/]+/?$", clean_raw, flags=re.IGNORECASE):
                clean_raw = None

            # Check if clean_raw is already a valid project repository/live URL present in the document
            if clean_raw and clean_raw not in claimed_urls and clean_raw in candidate_urls:
                cls._assign_url(proj, clean_raw)
                claimed_urls.add(clean_raw)
                proj.pop("link", None)
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
                cls._assign_url(proj, best_url)
                claimed_urls.add(best_url)
            else:
                proj["github_url"] = None
                proj["project_url"] = None

            proj.pop("link", None)

        return projects
