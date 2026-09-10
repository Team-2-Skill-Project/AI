import pytest

from src.cv_extractor.llm_extractor import LLMExtractor
from src.utils.text_cleaner import TextCleaner


@pytest.fixture
def extractor():
    return LLMExtractor()


class TestFallbackNoDataFabrication:
    def test_minimal_cv_does_not_fabricate_education_role_or_location(self, extractor):
        """P0 Test: Minimal CV with only name and email must NOT return fabricated education, roles, or location."""
        minimal_cv = """
Sara Mohamed
Email: sara.mohamed@example.com
Phone: +20 100 000 0000
"""
        sections = TextCleaner.segment_sections(minimal_cv)
        result = extractor._extract_heuristically(minimal_cv, sections)

        assert result["name"] == "Sara Mohamed"
        assert result["email"] == "sara.mohamed@example.com"
        assert result["phone"] == "+20 100 000 0000"

        # MUST NOT fabricate location as Egypt
        assert result["location"] is None, f"Expected location=None, got {result['location']}"

        # MUST NOT fabricate target role as 'Agentic AI Developer'
        assert result["target_roles"] == [], f"Expected empty target_roles, got {result['target_roles']}"

        # MUST NOT fabricate Bachelor of Computer Science education
        assert result["education"] == [], f"Expected empty education, got {result['education']}"

        # MUST NOT fabricate experience or projects
        assert result["experience"] == []
        assert result["projects"] == []

    def test_substring_ai_in_email_does_not_corrupt_field(self, extractor):
        """P0 Test: Substring 'ai' in email or words (mai@domain.com) must NOT classify field as Artificial Intelligence."""
        cv_civil_eng = """
Mai Hassan
Email: mai.hassan@example.com
Location: Cairo, Egypt

EDUCATION
Bachelor of Science in Civil Engineering
Cairo University
2018 - 2023
"""
        sections = TextCleaner.segment_sections(cv_civil_eng)
        result = extractor._extract_heuristically(cv_civil_eng, sections)

        assert len(result["education"]) == 1
        edu = result["education"][0]
        assert "Civil Engineering" in edu["degree"] or edu["field"] == "Engineering"
        # MUST NOT be Artificial Intelligence just because email contains 'mai' or 'email' contains 'ai'
        assert edu["field"] != "Artificial Intelligence"

    def test_legitimate_education_parsed_correctly(self, extractor):
        """Legitimate education record is extracted with correct degree and institution."""
        cv_text = """
Ahmed Hassan
Email: ahmed@example.com
Location: Mansoura, Egypt

EDUCATION
Bachelor of Science in Computer Science
Faculty of Computers and Information, Mansoura University
2022 – 2026 (Expected Graduation: June 2026)
"""
        sections = TextCleaner.segment_sections(cv_text)
        result = extractor._extract_heuristically(cv_text, sections)

        assert len(result["education"]) == 1
        edu = result["education"][0]
        assert "Bachelor" in edu["degree"]
        assert "Computer Science" in edu["degree"] or edu["field"] == "Computer Science"
        assert "Mansoura University" in edu["institution"]
        assert edu["start_year"] == 2022
        assert edu["end_year"] == 2026
        assert edu["status"] == "current"

    def test_explicit_ai_education_recognized_with_word_boundary(self, extractor):
        """Explicit Artificial Intelligence degree is correctly identified using word boundaries."""
        cv_ai = """
Nour Ali
Email: nour@example.com

EDUCATION
BSc in Artificial Intelligence
Mansoura University
2020 - 2024
"""
        sections = TextCleaner.segment_sections(cv_ai)
        result = extractor._extract_heuristically(cv_ai, sections)

        assert len(result["education"]) == 1
        edu = result["education"][0]
        assert edu["field"] == "Artificial Intelligence"

    def test_experience_without_fabricated_dates(self, extractor):
        """Experience with no explicit date must not invent 2025-2026."""
        cv_exp = """
John Doe
john@test.com

EXPERIENCE
Software Engineer | Acme Corp
• Built backend APIs with FastAPI.
"""
        sections = TextCleaner.segment_sections(cv_exp)
        result = extractor._extract_heuristically(cv_exp, sections)

        assert len(result["experience"]) == 1
        exp = result["experience"][0]
        assert exp["role"] == "Software Engineer"
        assert exp["company"] == "Acme Corp"
        # Must not fabricate start_date="2025" or end_date="2026"
        assert exp["start_date"] is None
        assert exp["end_date"] is None
