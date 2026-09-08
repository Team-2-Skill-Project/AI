import pytest
from src.utils.text_cleaner import TextCleaner


def test_clean_text():
    dirty = "Ahmed   Hassan\n\n\n\x00Email: ahmed@test.com\r\nLocation: Mansoura"
    cleaned = TextCleaner.clean_text(dirty)
    assert "\x00" not in cleaned
    assert "   " not in cleaned
    assert "\r" not in cleaned
    assert "Ahmed Hassan" in cleaned


def test_segment_sections():
    cv_sample = """
John Doe
john@test.com

EDUCATION
BSc in Computer Science
Mansoura University

TECHNICAL SKILLS
Python, SQL, Machine Learning

PROJECTS
Customer Churn Prediction
Built using Python and Pandas.
"""
    sections = TextCleaner.segment_sections(cv_sample)
    assert "education" in sections
    assert "skills" in sections
    assert "projects" in sections
    assert "Mansoura University" in sections["education"]
    assert "Python" in sections["skills"]
    assert "Customer Churn Prediction" in sections["projects"]
