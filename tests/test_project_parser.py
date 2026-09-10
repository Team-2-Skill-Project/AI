import pytest

from src.cv_extractor.llm_extractor import LLMExtractor


@pytest.fixture
def extractor():
    return LLMExtractor()


class TestHeuristicProjectParser:
    def test_standalone_title_with_bullets(self, extractor):
        """P0 Failing Case: Normal project titles on their own line followed by bullets."""
        text = """
Customer Churn Prediction Model
• Developed an end-to-end customer churn prediction pipeline using Python and Scikit-learn on a telecom dataset of 7,000+ records.
• Applied data preprocessing with Pandas and NumPy, achieving an 86% F1-score with Random Forest.
• Containerized the deployment workflow using Docker and managed version control with Git.

Automated SQL Financial Reporting Pipeline
• Built an automated ETL pipeline extracting transactional data using PostgreSQL and SQL queries.
• Optimized query performance and generated automated summary analytics.
"""
        projects = extractor._parse_projects(text)
        assert len(projects) == 2

        p1 = projects[0]
        assert p1["title"] == "Customer Churn Prediction Model"
        assert "telecom dataset" in p1["description"]
        assert "Random Forest" in p1["description"]
        assert "Python" in p1["technologies"]
        assert "Docker" in p1["technologies"]
        assert "Git" in p1["technologies"]

        p2 = projects[1]
        assert p2["title"] == "Automated SQL Financial Reporting Pipeline"
        assert "ETL pipeline" in p2["description"]
        assert "PostgreSQL" in p2["technologies"]
        assert "SQL" in p2["technologies"]

    def test_pipe_separated_title(self, extractor):
        text = """
TruthStream [GitHub Repo] (https://github.com/user/truthstream) | FastAPI, React, Docker | 2024
• Real-time fact verification system.
• Integrated OpenAI API for verification.
"""
        projects = extractor._parse_projects(text)
        assert len(projects) == 1
        p = projects[0]
        assert p["title"] == "TruthStream"
        assert p["link"] == "https://github.com/user/truthstream"
        assert "FastAPI" in p["technologies"]
        assert "React" in p["technologies"]
        assert "Docker" in p["technologies"]
        assert "Real-time fact verification" in p["description"]

    def test_colon_title_and_description(self, extractor):
        text = """
AI Video Summarizer: Built a Python tool using LangChain and Whisper to transcribe and summarize videos.
• Added support for multi-language export.
"""
        projects = extractor._parse_projects(text)
        assert len(projects) == 1
        p = projects[0]
        assert p["title"] == "AI Video Summarizer"
        assert "LangChain" in p["description"] or "LangChain" in p["technologies"]
        assert "Whisper" in p["description"] or "Whisper" in p["technologies"]
        assert "multi-language export" in p["description"]

    def test_numbered_and_markdown_project_titles(self, extractor):
        text = """
1. Smart Health Assistant
• Built a diagnostic bot in Python and FastAPI.

### 2. Autonomous Drone Navigation
• Computer vision system using PyTorch and OpenCV.
"""
        projects = extractor._parse_projects(text)
        assert len(projects) == 2
        assert projects[0]["title"] == "Smart Health Assistant"
        assert "Python" in projects[0]["technologies"]

        assert "Autonomous Drone Navigation" in projects[1]["title"]
        assert "PyTorch" in projects[1]["technologies"]

    def test_projects_with_technologies_metadata_line(self, extractor):
        text = """
E-Commerce Recommendation Engine
Technologies: Python, Pandas, Scikit-learn, FastAPI
• Implemented collaborative filtering algorithm.
• Deployed microservice to AWS.
"""
        projects = extractor._parse_projects(text)
        assert len(projects) == 1
        p = projects[0]
        assert p["title"] == "E-Commerce Recommendation Engine"
        assert "Python" in p["technologies"]
        assert "Scikit-learn" in p["technologies"]
        assert "FastAPI" in p["technologies"]
        assert "collaborative filtering" in p["description"]

    def test_projects_with_date_lines(self, extractor):
        text = """
Portfolio Management System
Jan 2024 - Mar 2024
• Developed risk analysis dashboard with React and TypeScript.
"""
        projects = extractor._parse_projects(text)
        assert len(projects) == 1
        p = projects[0]
        assert p["title"] == "Portfolio Management System"
        assert "React" in p["technologies"]
        assert "TypeScript" in p["technologies"]

    def test_empty_and_whitespace_text(self, extractor):
        assert extractor._parse_projects("") == []
        assert extractor._parse_projects("   \n\n  ") == []

    def test_numbered_and_prefixed_project_titles_extract_real_title(self, extractor):
        """P0-2 Regression: 'Project 2: Data Pipeline' and '3. Analytics Dashboard' must extract substantive titles."""
        text = """
Project 2: Data Pipeline
Built data ingestion pipeline.

3. Analytics Dashboard
Built real-time metrics dashboard.
"""
        projects = extractor._parse_projects(text)
        assert len(projects) == 2
        assert projects[0]["title"] == "Data Pipeline"
        assert "Built data ingestion pipeline" in projects[0]["description"]
        assert projects[1]["title"] == "Analytics Dashboard"
        assert "Built real-time metrics dashboard" in projects[1]["description"]

    def test_markdown_h3_subheading_project_extracted(self, extractor):
        """P0-2 Regression: '### Cloud Deployer' inside projects text parses with title 'Cloud Deployer'."""
        text = """
### Cloud Deployer
Automated AWS deployment tool.
"""
        projects = extractor._parse_projects(text)
        assert len(projects) == 1
        assert projects[0]["title"] == "Cloud Deployer"
        assert "Automated AWS deployment tool" in projects[0]["description"]

