from src.cv_extractor.confidence_scorer import ConfidenceScorer
from src.models.candidate import EvidenceItem
from src.models.common import SkillLevel


def test_confidence_scoring_formula():
    # Only skills section -> medium/low base
    ev_skills = [EvidenceItem(type="skills_section", text="Python", source="cv", section="skills")]
    score_skills = ConfidenceScorer.calculate_confidence(ev_skills)
    assert 0.50 <= score_skills <= 0.70

    # Skills section + Project -> high (>= 0.75)
    ev_project = [
        EvidenceItem(type="skills_section", text="Python", source="cv", section="skills"),
        EvidenceItem(type="project", text="Built customer churn model using Python", source="cv", section="projects")
    ]
    score_project = ConfidenceScorer.calculate_confidence(ev_project)
    assert score_project >= 0.75

    # Experience + Project + Skills -> very high (>= 0.90)
    ev_all = [
        EvidenceItem(type="skills_section", text="Python", source="cv", section="skills"),
        EvidenceItem(type="project", text="Built customer churn model using Python", source="cv", section="projects"),
        EvidenceItem(type="experience", text="Wrote Python data extraction pipelines", source="cv", section="experience")
    ]
    score_all = ConfidenceScorer.calculate_confidence(ev_all)
    assert score_all >= 0.90


def test_level_inference():
    ev_project = [EvidenceItem(type="project", text="Built churn model", source="cv", section="projects")]
    level = ConfidenceScorer.infer_level(ev_project)
    assert level == SkillLevel.INTERMEDIATE

    ev_exp = [
        EvidenceItem(type="experience", text="Senior Dev", source="cv", section="experience"),
        EvidenceItem(type="project", text="Proj 1", source="cv", section="projects"),
        EvidenceItem(type="project", text="Proj 2", source="cv", section="projects")
    ]
    level_adv = ConfidenceScorer.infer_level(ev_exp)
    assert level_adv == SkillLevel.ADVANCED


def test_raw_level_precedence_and_synonyms():
    # Only skills section normally yields BEGINNER
    ev_skills = [EvidenceItem(type="skills_section", text="Python", source="cv", section="skills")]

    # Without raw_level -> BEGINNER
    assert ConfidenceScorer.infer_level(ev_skills) == SkillLevel.BEGINNER

    # With raw_level="expert" -> EXPERT
    assert ConfidenceScorer.infer_level(ev_skills, raw_level="expert") == SkillLevel.EXPERT
    assert ConfidenceScorer.infer_level(ev_skills, raw_level="Expert") == SkillLevel.EXPERT
    assert ConfidenceScorer.infer_level(ev_skills, raw_level="master") == SkillLevel.EXPERT

    # With raw_level="advanced" / "senior" -> ADVANCED
    assert ConfidenceScorer.infer_level(ev_skills, raw_level="advanced") == SkillLevel.ADVANCED
    assert ConfidenceScorer.infer_level(ev_skills, raw_level="senior") == SkillLevel.ADVANCED

    # With raw_level="intermediate" -> INTERMEDIATE
    assert ConfidenceScorer.infer_level(ev_skills, raw_level="intermediate") == SkillLevel.INTERMEDIATE

    # With raw_level="unknown" or empty -> falls back to evidence
    assert ConfidenceScorer.infer_level(ev_skills, raw_level="unknown") == SkillLevel.BEGINNER
    assert ConfidenceScorer.infer_level(ev_skills, raw_level="") == SkillLevel.BEGINNER

