import pytest
from src.taxonomy.taxonomy_manager import TaxonomyManager
from src.models.taxonomy import SkillTaxonomyItem


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

    # PostgreSQL -> SQL / PostgreSQL
    pg_match = tax.find_skill("PostgreSQL")
    assert pg_match is not None
    assert pg_match.skill_id in ["skill_postgresql", "skill_sql"]


def test_unseen_skill_normalization():
    tax = TaxonomyManager()
    skill_id, canonical_name, category = tax.normalize_skill("FastAPI Framework")
    assert "fastapi" in skill_id
    assert category == "Tools" or category == "Frameworks"
