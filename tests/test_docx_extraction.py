from __future__ import annotations
from pathlib import Path
from src.cv_extractor.document_loader import DocumentLoader


def test_docx_extraction():
    loader = DocumentLoader()
    docx_path = Path(__file__).parent / "samples" / "yousef_hatem_cv.docx"
    assert docx_path.exists(), "Sample docx file missing"

    extracted_text, doc_format = loader.load_text(str(docx_path))
    assert doc_format == "docx"
    assert isinstance(extracted_text, str)
    assert len(extracted_text.strip()) > 0

