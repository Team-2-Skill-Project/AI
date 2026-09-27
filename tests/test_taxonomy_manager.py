from __future__ import annotations
import os

import pytest

from src.taxonomy.taxonomy_manager import TaxonomyManager


def test_taxonomy_seed_loading():
    tax = TaxonomyManager()
    skills = tax.get_all_skills()
    assert len(skills) >= 10

    # Check Python
    py_skill = tax.find_skill("Python")
    assert py_skill is not None
    assert py_skill.skill_id == "skill_python"
    assert py_skill.canonical_name == "Python"


def test_alias_resolution():
    tax = TaxonomyManager()

    # sklearn -> Scikit-learn
    sklearn_match = tax.find_skill("sklearn")
    assert sklearn_match is not None
    assert sklearn_match.skill_id == "skill_sklearn"
    assert sklearn_match.canonical_name == "Scikit-learn"

    # Python 3 -> Python
    py3_match = tax.find_skill("Python 3")
    assert py3_match is not None
    assert py3_match.skill_id == "skill_python"

    # Postgres -> PostgreSQL
    pg_match = tax.find_skill("Postgres")
    assert pg_match is not None
    assert pg_match.skill_id == "skill_postgresql"

    js_match = tax.find_skill("JS")
    assert js_match is not None
    assert js_match.skill_id == "skill_javascript"


@pytest.mark.parametrize(
    ("raw_skill", "related_skill_id"),
    [
        ("OpenAI API", "skill_llms"),
        ("GPT-4o", "skill_llms"),
        ("GPT-4o-mini", "skill_llms"),
        ("Prompt Engineering", "skill_llms"),
        ("HuggingFace", "skill_transformers"),
        ("DistilBERT", "skill_transformers"),
        ("BERT", "skill_transformers"),
        ("T5", "skill_transformers"),
        ("OpenCV", "skill_computer_vision"),
        ("Keras", "skill_tensorflow"),
        ("Agentic AI", "skill_ai"),
        ("Real-time Data Pipelines", "skill_kafka"),
        ("Full Stack", "skill_mern"),
        ("SSE", "skill_websockets"),
        ("Vector Database", "skill_chromadb"),
        ("XAMPP", "skill_mysql"),
        ("GitHub", "skill_git"),
        ("GitHub Actions", "skill_cicd"),
        ("Docker Compose", "skill_docker"),
        ("Firestore", "skill_firebase"),
    ],
)
def test_distinct_explicit_terms_are_not_collapsed_into_related_skills(
    raw_skill: str, related_skill_id: str,
):
    tax = TaxonomyManager()

    skill_id, name = tax.resolve(raw_skill)

    assert skill_id is None
    assert name == raw_skill
    assert skill_id != related_skill_id


def test_open_world_resolution_preserves_unknowns_without_fake_ids():
    tax = TaxonomyManager()

    assert tax.resolve("NewsAPI") == (None, "NewsAPI")
    assert tax.resolve("Unlisted-Explicit-Tool") == (None, "Unlisted-Explicit-Tool")
    assert tax.normalize_skill("NewsAPI", strict=True) == (None, None, None)
    assert tax.normalize_skill("NewsAPI", strict=False) == (None, None, None)


def test_csharp_does_not_collapse_into_dotnet():
    tax = TaxonomyManager()

    assert tax.resolve("C#") == ("skill_csharp", "C#")
    assert tax.resolve(".NET") == (None, ".NET")


@pytest.mark.parametrize(
    "raw_skill",
    [
        "management", "architecture", "engineering", "legal", "law", "clinical",
        "development", "backend", "frontend", "databases",
    ],
)
def test_explicit_cross_profession_terms_are_not_blacklisted(raw_skill: str):
    tax = TaxonomyManager()

    assert tax.resolve(raw_skill) == (None, raw_skill)


@pytest.mark.parametrize(
    "garbage",
    [
        "https://example.com/skills", "candidate@example.com", "Experience",
        "developed", "2024", "---",
    ],
)
def test_blacklist_still_rejects_obvious_garbage(garbage: str):
    tax = TaxonomyManager()

    assert tax.is_blacklisted(garbage, is_explicit=True)
    assert tax.resolve(garbage) == (None, "")


def test_unseen_skill_normalization():
    tax = TaxonomyManager()
    skill_id, canonical_name, category = tax.normalize_skill("FastAPI Framework", strict=True)
    assert skill_id is not None
    assert "fastapi" in skill_id
    assert category in ["Tools", "Frameworks"]


def test_zero_fake_skills_strict_normalization():
    """Verify that random strings and names cannot create synthetic fake skills under strict mode."""
    tax = TaxonomyManager()

    # Random non-existent skills
    assert tax.normalize_skill("John Doe", strict=True) == (None, None, None)
    assert tax.normalize_skill("notarealskill", strict=True) == (None, None, None)
    assert tax.normalize_skill("random tool xyz", strict=True) == (None, None, None)
    assert tax.normalize_skill("Lorem Ipsum", strict=True) == (None, None, None)

    # Direct find_skill checks
    assert tax.find_skill("John Doe") is None
    assert tax.find_skill("notarealskill") is None
    assert tax.find_skill("John Python") is None  # "John" is not a recognized tech modifier
    assert tax.find_skill("Fake Docker") is None  # "Fake" is not a recognized tech modifier


def test_recognized_modifier_skill_matching():
    """Verify that legitimate modifier + skill pairs resolve properly while bogus pairs do not."""
    tax = TaxonomyManager()

    # Legitimate modifier + skill
    res = tax.find_skill("Python Developer")
    assert res is not None
    assert res.skill_id == "skill_python"

    res = tax.find_skill("FastAPI Framework")
    assert res is not None
    assert res.skill_id == "skill_fastapi"

    res = tax.find_skill("Docker Platform")
    assert res is not None
    assert res.skill_id == "skill_docker"

    # Bogus modifier + skill
    assert tax.find_skill("Smith Python") is None
    assert tax.find_skill("Alpha Docker") is None


def test_relative_taxonomy_path_resolution_from_any_cwd(monkeypatch, tmp_path):
    """P2 Test: Relative taxonomy paths must resolve against project root even when CWD is changed."""
    from src.core.config import get_app_settings

    # 1. Check default settings resolve to an existing absolute file
    app_settings = get_app_settings()
    assert os.path.isabs(app_settings.taxonomy_path)
    assert os.path.exists(app_settings.taxonomy_path)

    # 2. Change CWD to a different directory (like tmp_path)
    monkeypatch.chdir(tmp_path)

    # Verify relative string path still correctly loads full taxonomy from project root
    tax = TaxonomyManager(seed_file_path="docs/ai-contract/skills_seed.json")
    skills = tax.get_all_skills()
    assert len(skills) >= 20  # Full seed has many skills, not the 8-item fallback

    # Test skill lookup works
    py_skill = tax.find_skill("Python")
    assert py_skill is not None
    assert py_skill.skill_id == "skill_python"


