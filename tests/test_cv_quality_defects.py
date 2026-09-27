from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from src.cv_extractor.document_loader import DocumentLoader
from src.cv_extractor.evidence_linker import EvidenceLinker
from src.cv_extractor.link_associator import ProjectLinkAssociator
from src.cv_extractor.llm_extractor import LLMExtractor
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.utils.text_cleaner import TextCleaner

FIXTURE = Path(__file__).parent / "fixtures" / "cv_quality_regression.txt"


class FakeAnnotationRef:
    def __init__(self, value: dict):
        self.value = value

    def get_object(self) -> dict:
        return self.value


class FakePdfPage:
    def __init__(self, layout_text: str, standard_text: str, urls: list[str]):
        self.layout_text = layout_text
        self.standard_text = standard_text
        self.calls: list[str | None] = []
        self.annotations = [
            FakeAnnotationRef({"/Subtype": "/Link", "/A": {"/URI": url}})
            for url in urls
        ]

    def extract_text(self, extraction_mode: str | None = None) -> str:
        self.calls.append(extraction_mode)
        return self.layout_text if extraction_mode == "layout" else self.standard_text


def test_pdf_prefers_clean_layout_text_and_preserves_annotation_urls(monkeypatch, tmp_path):
    url = "https://github.com/example/TruthStream-Platform"
    page = FakePdfPage(
        layout_text="Avery Example\nProjects\nTruthStream Platform\n• Built with NewsAPI",
        standard_text="Avery Example\nProjects\nT ruthStream Platform\n• Built with NewsAPI",
        urls=[url],
    )
    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=lambda _: SimpleNamespace(pages=[page])))

    text, links = DocumentLoader()._extract_pdf(tmp_path / "quality.pdf")
    projects = [{"title": "TruthStream Platform", "description": None, "github_url": None, "project_url": None}]
    ProjectLinkAssociator.associate_projects_with_links(projects, text, links)

    assert "TruthStream Platform" in text
    assert "T ruthStream" not in text
    assert page.calls == ["layout", None]
    assert links == [url]
    assert projects[0]["github_url"] == url


def test_pdf_falls_back_when_layout_loses_material_content(monkeypatch, tmp_path):
    page = FakePdfPage(
        layout_text="Too short",
        standard_text="A complete standard extraction with substantially more readable content.",
        urls=[],
    )
    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=lambda _: SimpleNamespace(pages=[page])))

    text, links = DocumentLoader()._extract_pdf(tmp_path / "fallback.pdf")

    assert text == page.standard_text
    assert links == []


def test_section_detection_keeps_sentence_and_page_continuation_in_projects():
    source = FIXTURE.read_text(encoding="utf-8")

    sections = TextCleaner.segment_sections(source)
    evidence = EvidenceLinker.link_evidence("Plotly", None, sections, source)

    assert "manage session history." in sections["projects"]
    assert "Customer Insight Tool" in sections["projects"]
    assert "Customer Insight Tool" not in sections["education"]
    assert "Example University" in sections["education"]
    assert "Languages: Python, SQL" in sections["skills"]
    assert TextCleaner.detect_section_header("history.") == (None, False)
    assert TextCleaner.detect_section_header("Education:") == ("education", True)
    assert any(item.section == item.type == "projects" for item in evidence)
    assert all(item.section != "education" for item in evidence)


class CapturingLLM:
    def __init__(self, response: dict):
        self.response = response
        self.system_prompt = ""
        self.prompt = ""

    def is_available(self) -> bool:
        return True

    def generate_json(self, prompt: str, system_prompt: str) -> dict:
        self.prompt = prompt
        self.system_prompt = system_prompt
        return self.response


def test_single_extraction_prompt_requires_explicit_technology_completeness_and_preserves_unknown_skills():
    source = FIXTURE.read_text(encoding="utf-8")
    url = "https://github.com/example/TruthStream-Platform"
    llm = CapturingLLM(
        {
            "projects": [
                {
                    "title": "TruthStream Platform",
                    "technologies": ["Python", "NewsAPI", "GNews"],
                    "start_date": "May 2026",
                }
            ],
            "raw_skills": [
                {"name": "NewsAPI"},
                {"name": "GNews"},
                {"name": "WidgetFlow"},
            ],
        }
    )
    pipeline = CVExtractionPipeline(extractor=LLMExtractor(llm=llm))

    candidate = pipeline.extract_from_text(source, document_urls=[url])
    skills = {skill.name: skill for skill in candidate.candidate_skills}

    assert "Technology and skill completeness is required" in llm.system_prompt
    assert "taxonomy as a whitelist" in llm.system_prompt
    assert "DOCUMENT HYPERLINKS (source annotations)" in llm.prompt
    assert skills["NewsAPI"].skill_id is None
    assert skills["GNews"].skill_id is None
    assert skills["WidgetFlow"].skill_id is None
    assert candidate.projects[0].technologies == ["Python", "NewsAPI", "GNews"]
    assert candidate.projects[0].start_date == "2026-05"
    assert candidate.projects[0].github_url == url
