from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class DocumentLoader:
    """
    Direct document reader for CV files.
    Supports native digital text extraction from PDF, DOCX, and TXT files.
    """

    SUPPORTED_EXTENSIONS = {
        ".pdf": "pdf",
        ".docx": "docx",
        ".txt": "text",
        ".md": "text",
    }

    def load_text(self, file_path: str) -> tuple[str, str, list[str]]:
        """
        Loads and extracts text and embedded hyperlinks from supported digital CV documents.
        Returns: (extracted_text, document_format, extracted_links)
        All extracted links are returned locally per call, avoiding shared mutable state.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"CV file not found: {file_path}")

        ext = path.suffix.lower()
        doc_type = self.SUPPORTED_EXTENSIONS.get(ext)

        if not doc_type:
            raise ValueError(
                f"Unsupported document format: '{ext}'. "
                f"Supported formats are: {', '.join(sorted(self.SUPPORTED_EXTENSIONS.keys()))}"
            )

        if doc_type == "pdf":
            text, links = self._extract_pdf(path)
            return text, "pdf", links
        elif doc_type == "docx":
            text, links = self._extract_docx(path)
            return text, "docx", links
        elif doc_type == "text":
            text, links = self._extract_plain_text(path)
            return text, "text", links
        else:
            raise ValueError(f"No extractor available for format: {ext}")

    def _extract_pdf(self, path: Path) -> tuple[str, list[str]]:
        """Extract readable PDF text while returning hyperlink annotations separately."""
        text_pages = []
        extracted_links: list[str] = []
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            for page in reader.pages:
                # 1. Collect link annotations. Project association receives these separately.
                if hasattr(page, "annotations") and page.annotations:
                    for annot_ref in page.annotations:
                        try:
                            annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
                            if not annot or annot.get("/Subtype") != "/Link":
                                continue
                            action = annot.get("/A")
                            uri = None
                            if action and hasattr(action, "get"):
                                uri = action.get("/URI")
                            elif annot and hasattr(annot, "get") and "/URI" in annot:
                                uri = annot.get("/URI")

                            if uri:
                                uri_str = str(uri).strip()
                                if uri_str:
                                    if uri_str not in extracted_links:
                                        extracted_links.append(uri_str)
                        except Exception:
                            continue

                # Layout extraction is substantially more reliable for glyph-positioned text.
                # Do not assume it is usable for every PDF: retain standard extraction as a
                # generic fallback when layout loses a material amount of textual content.
                try:
                    layout_text = (page.extract_text(extraction_mode="layout") or "").strip()
                except Exception as layout_error:
                    logger.warning("PDF layout extraction failed; using standard extraction: %s", type(layout_error).__name__)
                    layout_text = ""

                try:
                    standard_text = (page.extract_text() or "").strip()
                except Exception as standard_error:
                    logger.warning("PDF standard extraction failed: %s", type(standard_error).__name__)
                    standard_text = ""

                page_text = self._select_pdf_text(layout_text, standard_text)

                if page_text:
                    text_pages.append(page_text)

        except Exception as e:
            logger.error(f"pypdf extraction failed for {path}: {e}")
            raise ValueError(f"Failed to read PDF document '{path.name}': {e!s}")

        full_text = "\n".join(text_pages).strip()
        if not full_text:
            raise ValueError(
                f"No readable text could be extracted from '{path.name}'. "
                "Please ensure the document contains digital selectable text (scanned image PDFs are not supported)."
            )
        return full_text, extracted_links

    @staticmethod
    def _select_pdf_text(layout_text: str, standard_text: str) -> str:
        """Prefer layout text only when it retains enough readable content."""
        if not layout_text:
            return standard_text
        if not standard_text:
            return layout_text

        def visible_characters(value: str) -> int:
            return len(re.sub(r"\s+", "", value))

        layout_visible = visible_characters(layout_text)
        standard_visible = visible_characters(standard_text)
        if standard_visible and layout_visible < standard_visible * 0.8:
            logger.warning(
                "PDF layout extraction lost material text; using standard extraction instead: layout_chars=%d standard_chars=%d",
                layout_visible,
                standard_visible,
            )
            return standard_text
        return layout_text

    def _extract_docx(self, path: Path) -> tuple[str, list[str]]:
        """Extracts paragraphs, hyperlinks, and table cells from DOCX files."""
        lines: list[str] = []
        extracted_links: list[str] = []
        try:
            import docx
            from docx.oxml.ns import qn
            doc = docx.Document(str(path))
            for p in doc.paragraphs:
                p_text = ""
                for child in p._p:
                    if child.tag.endswith("hyperlink"):
                        r_id = child.get(qn("r:id"))
                        # In docx oxml, text is strictly in <w:t> nodes.
                        # Do NOT use child.iter() without filtering for w:t, because parent oxml elements
                        # return the same text as their children, causing duplicated/tripled words.
                        link_text = "".join(t.text for t in child.iter(qn("w:t")) if t.text)
                        target = None
                        if r_id and r_id in p.part.rels:
                            target = p.part.rels[r_id].target_ref
                            if target and target not in extracted_links:
                                extracted_links.append(target)
                        if target and target not in link_text:
                            p_text += f" {link_text} ({target}) "
                        else:
                            p_text += link_text
                    elif child.tag.endswith("r"):
                        # In docx oxml, text within a run <w:r> is strictly in <w:t> nodes.
                        run_text = "".join(t.text for t in child.iter(qn("w:t")) if t.text)
                        p_text += run_text
                clean_line = p_text.strip() or p.text.strip()
                if clean_line:
                    lines.append(clean_line)

            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if row_text:
                        lines.append(row_text)
            extracted = "\n\n".join(lines).strip()
            if not extracted:
                raise ValueError(
                    f"No readable text could be extracted from DOCX file '{path.name}'."
                )
            return extracted, extracted_links
        except ImportError:
            # Fallback direct zip XML extraction if python-docx isn't installed
            import xml.etree.ElementTree as ET
            import zipfile
            with zipfile.ZipFile(str(path)) as z:
                xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            text_nodes = tree.findall(".//w:t", namespaces)
            extracted = " ".join(node.text for node in text_nodes if node.text).strip()
            if not extracted:
                raise ValueError(
                    f"No readable text could be extracted from DOCX file '{path.name}'."
                )
            return extracted, []
        except Exception as e:
            logger.error(f"DOCX extraction error for {path}: {e}")
            raise ValueError(f"Failed to extract text from DOCX file '{path.name}': {e!s}")

    def _extract_plain_text(self, path: Path) -> tuple[str, list[str]]:
        """Reads plain text files with UTF-8 encoding."""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(), []
