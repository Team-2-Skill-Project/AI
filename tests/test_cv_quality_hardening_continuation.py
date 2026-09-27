from __future__ import annotations

import pytest

from src.cv_extractor.evidence_linker import EvidenceLinker
from src.cv_extractor.link_associator import ProjectLinkAssociator
from src.cv_extractor.llm_extractor import LLMExtractor
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.models.candidate import CandidateProfile
from src.models.taxonomy import SkillTaxonomyItem
from src.taxonomy.taxonomy_manager import TaxonomyManager
from src.utils.url_normalizer import normalize_web_url


class SequencedLLM:
    def __init__(self, responses: list[dict]):
        self.responses = iter(responses)

    def is_available(self) -> bool:
        return True

    def generate_json(self, prompt: str, system_prompt: str) -> dict:
        return next(self.responses)


def _complete() -> dict:
    return {"complete": True, "missing_paths": [], "unsupported_paths": [], "fidelity_paths": []}


@pytest.mark.parametrize(
    ("skill_name", "expected_name"),
    [
        ("color management (CMYK)", "color management (CMYK)"),
        ("Finite Element Analysis (FEA)", "Finite Element Analysis"),
        ("notation [A, B]", "notation [A, B]"),
        ("C++", "C++"),
        ("C#", "C#"),
        (".NET", ".NET"),
        ("Node.js", "Node.js"),
        ("Next.js", "Next.js"),
        ("scikit-learn", "scikit-learn"),
        ("CI/CD", "CI/CD"),
    ],
)
def test_raw_skill_cleanup_preserves_balanced_and_punctuation_heavy_labels(skill_name: str, expected_name: str):
    source = f"Candidate\n{skill_name}"
    pipeline = CVExtractionPipeline(
        extractor=LLMExtractor(llm=SequencedLLM([{"raw_skills": [{"name": skill_name}]}, _complete()]))
    )

    candidate = pipeline.extract_from_text(source)

    assert any(skill.name.lower() == expected_name.lower() for skill in candidate.candidate_skills)


def test_evidence_does_not_match_a_short_term_inside_a_longer_token():
    evidence = EvidenceLinker.link_evidence(
        "Git",
        None,
        {"skills": "GitHub"},
        "GitHub",
    )

    assert evidence == []


def test_git_taxonomy_does_not_use_github_only_text_or_urls_as_evidence():
    taxonomy = TaxonomyManager()
    git = taxonomy.find_skill("Git")

    evidence = EvidenceLinker.link_evidence(
        "Git",
        git,
        {"skills": "GitHub\nhttps://github.com/example/repository"},
        "GitHub\nhttps://github.com/example/repository",
    )

    assert evidence == []


def test_git_taxonomy_keeps_separate_git_evidence_when_github_also_exists():
    taxonomy = TaxonomyManager()
    git = taxonomy.find_skill("Git")

    evidence = EvidenceLinker.link_evidence(
        "Git",
        git,
        {"skills": "Git\nGitHub\nhttps://github.com/example/repository"},
        "Git\nGitHub\nhttps://github.com/example/repository",
    )

    assert len(evidence) == 1
    assert evidence[0].text == "Git"


@pytest.mark.parametrize("skill_name", ["C++", "C#", ".NET", "Node.js", "Next.js", "scikit-learn", "CI/CD"])
def test_evidence_matches_exact_punctuation_heavy_terms(skill_name: str):
    evidence = EvidenceLinker.link_evidence(skill_name, None, {"skills": skill_name}, skill_name)

    assert evidence
    assert evidence[0].text == skill_name


def test_evidence_accepts_only_an_explicitly_configured_taxonomy_alias():
    taxonomy_item = SkillTaxonomyItem(
        skill_id="skill_version_control",
        canonical_name="Version Control",
        category="Tools",
        aliases=["VC"],
    )

    evidence = EvidenceLinker.link_evidence(
        taxonomy_item.canonical_name,
        taxonomy_item,
        {"skills": "VC"},
        "VC",
    )

    assert evidence
    assert evidence[0].text == "VC"


def test_evidence_type_and_section_use_the_same_normalized_metadata():
    sections = {
        "skills": "AlphaTool",
        "certifications": "BetaTool",
        "research": "GammaTool",
    }

    for skill_name, section in (("AlphaTool", "skills"), ("BetaTool", "certifications"), ("GammaTool", "research")):
        evidence = EvidenceLinker.link_evidence(skill_name, None, sections, "\n".join(sections.values()))
        item = next(value for value in evidence if value.section == section)
        assert item.type == item.section == section


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        ("linkedin.com/path?view=full", "https://linkedin.com/path?view=full"),
        ("behance.net/path", "https://behance.net/path"),
        ("https://example.org/path?key=value", "https://example.org/path?key=value"),
        ("not a url", None),
    ],
)
def test_url_normalization_is_generic_and_preserves_explicit_paths(raw_url: str, expected: str | None):
    assert normalize_web_url(raw_url) == expected


def test_candidate_profile_urls_use_the_shared_normalizer():
    profile = CandidateProfile(
        linkedin_url="example.net/a",
        github_url="https://example.net/b?x=1",
        portfolio_url="example.net/c#work",
    )

    assert profile.linkedin_url == "https://example.net/a"
    assert profile.github_url == "https://example.net/b?x=1"
    assert profile.portfolio_url == "https://example.net/c#work"


def test_project_link_association_normalizes_a_source_url_once_without_cross_field_duplication():
    projects = [{"title": "Demo", "description": None, "github_url": "example.org/demo", "project_url": "example.org/demo"}]

    ProjectLinkAssociator.associate_projects_with_links(projects, "Demo\nexample.org/demo")

    assert projects[0]["project_url"] == "https://example.org/demo"
    assert projects[0]["github_url"] is None


def test_explicit_supported_proficiency_is_preserved_without_inference():
    source = "Candidate\nTool-Alpha (Advanced)"
    pipeline = CVExtractionPipeline(
        extractor=LLMExtractor(
            llm=SequencedLLM([{"raw_skills": [{"name": "Tool-Alpha", "proficiency": "Advanced"}]}, _complete()])
        )
    )

    candidate = pipeline.extract_from_text(source)

    skill = next(value for value in candidate.candidate_skills if value.name == "Tool-Alpha")
    assert skill.proficiency == "advanced"


def test_absent_proficiency_remains_null():
    pipeline = CVExtractionPipeline(
        extractor=LLMExtractor(llm=SequencedLLM([{"raw_skills": [{"name": "Tool-Alpha"}]}, _complete()]))
    )

    candidate = pipeline.extract_from_text("Candidate\nTool-Alpha")

    skill = next(value for value in candidate.candidate_skills if value.name == "Tool-Alpha")
    assert skill.proficiency is None
