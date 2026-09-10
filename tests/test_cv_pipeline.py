from pathlib import Path
from unittest.mock import patch

from src.core.llm_service import LLMService
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.models.candidate import Candidate


@patch.object(LLMService, "is_available", return_value=False)
def test_full_pipeline_with_sample_cv(mock_llm):
    sample_path = Path(__file__).parent / "samples" / "sample_ahmed_hassan_cv.txt"
    assert sample_path.exists()

    pipeline = CVExtractionPipeline()
    candidate = pipeline.extract_from_file(str(sample_path), candidate_id="cand_ahmed_001")

    # 1. Verify Candidate Object
    assert isinstance(candidate, Candidate)
    assert candidate.candidate_id == "cand_ahmed_001"

    # 2. Verify Profile
    assert "Ahmed" in candidate.profile.name
    assert candidate.profile.email == "ahmed.hassan@example.com"
    assert "Mansoura" in candidate.profile.location
    assert len(candidate.profile.education) > 0
    assert "Mansoura University" in candidate.profile.education[0].institution

    # 3. Verify Extracted Skills
    skill_ids = [s.skill_id for s in candidate.skills]
    assert "skill_python" in skill_ids
    assert "skill_sql" in skill_ids
    assert "skill_sklearn" in skill_ids
    assert "skill_machine_learning" in skill_ids

    # 4. Verify Evidence & Confidence on Python
    py_skill = next(s for s in candidate.skills if s.skill_id == "skill_python")
    assert py_skill.confidence >= 0.85
    assert len(py_skill.evidence) > 0
    # Must have exact quote snippet
    assert any("churn" in e.text.lower() or "python" in e.text.lower() for e in py_skill.evidence)
    assert any(e.source == "cv" for e in py_skill.evidence)

    # 5. Verify Experience Extraction
    assert len(candidate.experience) > 0
    assert "Mansoura Tech Solutions" in candidate.experience[0].company
    assert "Data Science Intern" in candidate.experience[0].role

    # 6. Verify Project Extraction (P0 Fix: Normal project titles extracted)
    assert len(candidate.projects) >= 2
    project_titles = [p.title for p in candidate.projects]
    assert any("Churn" in t for t in project_titles)
    assert any("Financial" in t or "SQL" in t for t in project_titles)

    churn_proj = next(p for p in candidate.projects if "Churn" in p.title)
    assert len(churn_proj.description) > 0
    assert "telecom dataset" in churn_proj.description.lower() or "pipeline" in churn_proj.description.lower()
    assert any(t in churn_proj.technologies for t in ["Python", "Scikit-learn", "Pandas", "NumPy", "Docker", "Git"])

    sql_proj = next(p for p in candidate.projects if "Financial" in p.title or "SQL" in p.title)
    assert len(sql_proj.description) > 0
    assert any(t in sql_proj.technologies for t in ["PostgreSQL", "SQL"])

    # 7. Verify JSON Serialization strictly complies with Day 1 Candidate Schema
    candidate_dict = candidate.model_dump()
    assert "candidate_id" in candidate_dict
    assert "profile" in candidate_dict
    assert "skills" in candidate_dict
    assert "experience" in candidate_dict
    assert "projects" in candidate_dict

