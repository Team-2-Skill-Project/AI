import logging

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


def test_segment_sections_with_work_and_internship_experience():
    cv_sample = """
John Doe
john@test.com

PROJECTS
Customer Churn Prediction Model
• Developed an end-to-end customer churn prediction pipeline using Python.
• Containerized with Docker.

WORK & INTERNSHIP EXPERIENCE
Data Science Intern | Mansoura Tech Solutions
July 2024 – September 2024
• Collaborated with senior engineers to build ML models in Python.
• Wrote SQL queries to extract data.

SKILLS
Python, SQL, Docker
"""
    sections = TextCleaner.segment_sections(cv_sample)
    assert "projects" in sections
    assert "experience" in sections
    assert "skills" in sections
    # Ensure projects only contains project content
    assert "Customer Churn Prediction Model" in sections["projects"]
    assert "Mansoura Tech Solutions" not in sections["projects"]
    # Ensure experience contains internship content
    assert "Data Science Intern" in sections["experience"]
    assert "Mansoura Tech Solutions" in sections["experience"]
    # Ensure skills contains skills
    assert "Python, SQL, Docker" in sections["skills"]


def test_detect_section_header_variants():
    positive_cases = [
        ("WORK & INTERNSHIP EXPERIENCE", "experience"),
        ("Work & Internship Experience", "experience"),
        ("WORK EXPERIENCE", "experience"),
        ("Professional Experience", "experience"),
        ("Work History", "experience"),
        ("Employment History", "experience"),
        ("INTERNSHIPS", "experience"),
        ("Internship Experience", "experience"),
        ("Relevant Experience", "experience"),
        ("EDUCATION", "education"),
        ("Academic Background", "education"),
        ("Education & Qualifications", "education"),
        ("Academic History", "education"),
        ("TECHNICAL SKILLS", "skills"),
        ("Core Competencies & Tech Stack", "skills"),
        ("Programming Skills", "skills"),
        ("Tools & Technologies", "skills"),
        ("PROJECTS", "projects"),
        ("Key Projects", "projects"),
        ("Academic Projects", "projects"),
        ("Selected Projects", "projects"),
        ("Portfolio", "projects"),
        ("PROFESSIONAL SUMMARY", "summary"),
        ("Career Objective", "summary"),
        ("About Me", "summary"),
        ("Executive Summary", "summary"),
        ("LICENSES & CERTIFICATIONS", "certifications"),
        ("Honors & Awards", "certifications"),
        ("Courses & Certifications", "certifications"),
        ("VOLUNTEER EXPERIENCE", "other"),
        ("Languages", "other"),
        ("1. EDUCATION", "education"),
        ("## EXPERIENCE", "experience"),
        ("### TECHNICAL SKILLS", "skills"),
    ]

    for header_str, expected_section in positive_cases:
        sec, is_hdr = TextCleaner.detect_section_header(header_str, is_paragraph_boundary=True)
        assert sec == expected_section, f"Failed for '{header_str}': got '{sec}', expected '{expected_section}'"
        assert is_hdr is True


def test_negative_content_lines_not_misclassified_as_headers():
    cv_sample = """
John Doe
john@test.com

PROJECTS
Web Development Project
• Developed a responsive web app using React and Node.js.
• Integrated REST APIs.

Skill Certification App
• Built an app for tracking skill certifications.

WORK & INTERNSHIP EXPERIENCE
Senior Software Engineer
GOOGLE LLC
Jan 2021 - Present
• Built backend pipelines in Python.

Skills Trainer
Acme Corp | 2022 - 2023
• Trained junior developers in Python and SQL.

Certification Specialist
Tech Global | 2021 - 2022
• Managed AWS certification programs.
"""
    sections = TextCleaner.segment_sections(cv_sample)

    assert "projects" in sections
    assert "experience" in sections

    # Negative test 1: Project titles containing keywords should stay in projects
    assert "Web Development Project" in sections["projects"]
    assert "Skill Certification App" in sections["projects"]

    # Negative test 2: Standalone all-caps company name should stay in experience
    assert "GOOGLE LLC" in sections["experience"]

    # Negative test 3: Job titles containing section keywords should stay in experience
    assert "Skills Trainer" in sections["experience"]
    assert "Certification Specialist" in sections["experience"]


def test_unrecognized_header_logging_and_routing(caplog):
    cv_sample = """
John Doe
john@test.com

PROJECTS
Churn Prediction
Built with Python.

### MILITARY SERVICE
Sergeant in Cyber Defense
2018 - 2020

SKILLS
Python, SQL
"""
    with caplog.at_level(logging.WARNING):
        sections = TextCleaner.segment_sections(cv_sample)

    assert "projects" in sections
    assert "skills" in sections

    # ### MILITARY SERVICE is a markdown header → creates dynamic key 'military_service'
    assert "military_service" in sections, (
        "Expected '### MILITARY SERVICE' to create a dynamic 'military_service' section"
    )
    assert "Sergeant in Cyber Defense" in sections["military_service"]

    # Must not bleed into other standard sections
    assert "Sergeant in Cyber Defense" not in sections.get("projects", "")
    assert "Sergeant in Cyber Defense" not in sections.get("skills", "")
    assert "Sergeant in Cyber Defense" not in sections.get("other", "")

    # A warning must always be emitted when creating a dynamic section
    assert any("Unrecognized CV section header" in record.message for record in caplog.records)


def test_markdown_h3_subheading_in_projects_stays_content_not_section():
    """P0-2 / P1-1 Regression: '### Cloud Deployer' inside PROJECTS stays as project content and does not create dynamic section."""
    cv = """
John Doe
john@test.com

PROJECTS
SkillMatch | AI Platform
Detailed architecture for AI matching system.

### Cloud Deployer
Automated AWS deployment tool.

SKILLS
Python, Docker
"""
    sections = TextCleaner.segment_sections(cv)
    assert "projects" in sections
    assert "Cloud Deployer" in sections["projects"]
    assert "Automated AWS deployment tool." in sections["projects"]
    assert "cloud_deployer" not in sections
    assert "skills" in sections
    assert "Python, Docker" in sections["skills"]


def test_mixed_case_markdown_headers_routing():
    """Confirms mixed-case H3 '### Volunteer Work' routes to 'other' and mixed-case dynamic headers are not swallowed."""
    cv = """
Sara Ali
sara@example.com

EXPERIENCE
Software Engineer at Acme

### Volunteer Work
Volunteered at community food bank.

### Speaking Engagements
Keynote speaker at PyCon 2023.

SKILLS
Python, SQL
"""
    sections = TextCleaner.segment_sections(cv)
    assert "experience" in sections
    assert "other" in sections
    assert "Volunteered at community food bank" in sections["other"]
    assert "speaking_engagements" in sections
    assert "Keynote speaker at PyCon 2023" in sections["speaking_engagements"]
    assert "skills" in sections


