import pytest

from src.cv_extractor.llm_extractor import LLMExtractor


@pytest.fixture
def extractor():
    return LLMExtractor()


class TestExperienceParser:
    def test_company_clean_of_trailing_parenthesis(self, extractor):
        """P0 Test: Company parsing must NOT produce 'Acme Corp (' for a header containing dates in parens."""
        text = """
Software Engineer | Acme Corp (Jan 2021 - Present)
• Built scalable REST APIs using FastAPI and PostgreSQL.
• Deployed services using Docker and Kubernetes.
"""
        items = extractor._parse_experience(text)
        assert len(items) == 1
        exp = items[0]

        # MUST NOT have trailing parenthesis
        assert exp["company"] == "Acme Corp", f"Expected 'Acme Corp', got '{exp['company']}'"
        assert exp["role"] == "Software Engineer"
        assert exp["start_date"] == "Jan 2021"
        assert exp["end_date"] == "Present"
        assert exp["is_current"] is True

    def test_sample_cv_experience_format(self, extractor):
        """Sample CV format: Data Science Intern | Mansoura Tech Solutions (July 2024 – September 2024)."""
        text = """
Data Science Intern | Mansoura Tech Solutions (July 2024 – September 2024)
• Collaborated with senior engineers to analyze datasets and build machine learning prototypes in Python.
• Wrote SQL queries to extract data and clean client transaction records.
"""
        items = extractor._parse_experience(text)
        assert len(items) == 1
        exp = items[0]

        assert exp["company"] == "Mansoura Tech Solutions"
        assert exp["role"] == "Data Science Intern"
        assert exp["start_date"] == "July 2024"
        assert exp["end_date"] == "September 2024"
        assert exp["is_current"] is False
        assert "Python" in exp["technologies"]
        assert "SQL" in exp["technologies"]

    def test_multiline_experience_header(self, extractor):
        """Multiline format: Role on line 1, Company on line 2, Date on line 3."""
        text = """
Machine Learning Engineer
Google LLC
Jan 2022 - Present
• Designed and trained deep learning models in PyTorch.
"""
        items = extractor._parse_experience(text)
        assert len(items) == 1
        exp = items[0]

        assert exp["role"] == "Machine Learning Engineer"
        assert exp["company"] == "Google LLC"
        assert exp["start_date"] == "Jan 2022"
        assert exp["end_date"] == "Present"
        assert exp["is_current"] is True
        assert "PyTorch" in exp["technologies"]

    def test_no_hardcoded_default_dates_when_dates_missing(self, extractor):
        """P0 Test: Experience without dates must NOT return hardcoded start_date='2025' or end_date='2026'."""
        text = """
Backend Developer | Startup Hub
• Developed microservices using Python and Flask.
"""
        items = extractor._parse_experience(text)
        assert len(items) == 1
        exp = items[0]

        assert exp["company"] == "Startup Hub"
        assert exp["role"] == "Backend Developer"
        assert exp["start_date"] is None
        assert exp["end_date"] is None
        assert exp["is_current"] is False

    def test_year_only_date_range(self, extractor):
        """Year-only date format: 2019 - 2023."""
        text = """
Data Analyst | Telecom Egypt (2019 - 2023)
• Built automated dashboards using Power BI and SQL.
"""
        items = extractor._parse_experience(text)
        assert len(items) == 1
        exp = items[0]

        assert exp["company"] == "Telecom Egypt"
        assert exp["start_date"] == "2019"
        assert exp["end_date"] == "2023"
        assert exp["is_current"] is False

    def test_experience_header_parenthetical_date_range_no_dangling_bracket(self, extractor):
        """P0-2 Regression: Role at Company (2021 - 2023) must not leave dangling '(2021 -' in role or company."""
        text = """
Software Engineer at Acme Corp (2021 - 2023)
• Developed microservices using Python and Docker.
"""
        items = extractor._parse_experience(text)
        assert len(items) == 1
        exp = items[0]
        assert exp["role"] == "Software Engineer"
        assert exp["company"] == "Acme Corp"
        assert exp["start_date"] == "2021"
        assert exp["end_date"] == "2023"
        assert "(" not in exp["role"]
        assert "(" not in exp["company"]

    def test_responsibility_action_sentence_never_populates_company(self, extractor):
        """P0-2 Regression: Responsibility sentence starting with action verb must NEVER populate company."""
        text = """
Software Engineer
Developed microservices.
Maintained legacy API.
"""
        items = extractor._parse_experience(text)
        assert len(items) == 1
        exp = items[0]
        assert exp["role"] == "Software Engineer"
        assert exp["company"] != "Developed microservices."
        assert "Developed microservices." not in exp["company"]
        assert "Developed microservices." in exp["responsibilities"]
        assert "Maintained legacy API." in exp["responsibilities"]

