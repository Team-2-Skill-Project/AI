import re

from ..models.candidate import EvidenceItem
from ..models.taxonomy import SkillTaxonomyItem


class EvidenceLinker:
    """
    Finds exact textual evidence and quotes from the CV for each detected skill.
    Ensures explainability by answering: 'Why does the system say the user has this skill?'
    Handles special symbols like C++, C#, .NET gracefully.
    """

    @classmethod
    def link_evidence(
        cls,
        skill_name: str,
        taxonomy_item: SkillTaxonomyItem | None,
        sections: dict[str, str],
        full_text: str
    ) -> list[EvidenceItem]:
        evidence_list: list[EvidenceItem] = []

        # Build search keywords (canonical name, raw name, aliases)
        keywords = {skill_name.lower()}
        if taxonomy_item:
            keywords.add(taxonomy_item.canonical_name.lower())
            for alias in taxonomy_item.aliases:
                keywords.add(alias.lower())

        # Clean search terms (sorted by length descending to match compound terms first)
        sorted_terms = sorted([k for k in keywords if len(k) >= 2], key=len, reverse=True)
        if not sorted_terms:
            return evidence_list

        # Robust regex pattern handling C++, C#, .NET, Python, etc.
        escaped_terms = [re.escape(k) for k in sorted_terms]
        terms_regex = "|".join(escaped_terms)
        pattern = re.compile(rf"(?:^|[\s\(\[\{{,\/•\|\-\:])({terms_regex})(?:$|[\s\)\]\}},;•\|\-\:])", re.IGNORECASE)

        # 1. Search in structured sections (prioritize Projects & Experience first)
        priority_sections = ["projects", "experience", "skills", "certifications", "education", "summary", "other"]
        # Also search any dynamic sections created for unrecognized headers (e.g. "publications", "military_service")
        known_sections: set = set(priority_sections) | {"header"}
        for extra_sec in sections:
            if extra_sec not in known_sections:
                priority_sections.append(extra_sec)

        for sec in priority_sections:
            if sec not in sections:
                continue

            sec_text = sections[sec]
            # Split section text into sentences or bullet points
            snippets = [s.strip() for s in re.split(r"[\n\.\;•\-\|]+", sec_text) if s.strip()]

            for snippet in snippets:
                if pattern.search(snippet):
                    # Found matching evidence sentence
                    clean_snippet = re.sub(r"\s+", " ", snippet).strip()
                    if len(clean_snippet) > 120:
                        clean_snippet = clean_snippet[:120] + "..."

                    evidence_type = "project" if sec == "projects" else ("experience" if sec == "experience" else "skills_section")

                    # Avoid duplicate snippets
                    if not any(e.text == clean_snippet for e in evidence_list):
                        evidence_list.append(
                            EvidenceItem(
                                type=evidence_type,
                                text=clean_snippet,
                                source="cv",
                                section=sec
                            )
                        )

        # 2. Fallback: Search full text if no section match was found
        if not evidence_list:
            lines = [line_item.strip() for line_item in full_text.split("\n") if line_item.strip()]
            for line in lines:
                if pattern.search(line):
                    clean_line = re.sub(r"\s+", " ", line).strip()
                    evidence_list.append(
                        EvidenceItem(
                            type="skills_section",
                            text=clean_line[:120],
                            source="cv",
                            section="general"
                        )
                    )
                    break

        return evidence_list
