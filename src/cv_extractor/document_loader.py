import os
import io
import logging
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


class DocumentLoader:
    """
    Direct document reader for CV files.
    Supports native digital text extraction from PDF, DOCX, and TXT files.
    """

    SUPPORTED_EXTENSIONS = {
        ".pdf": "pdf",
        ".docx": "docx",
        ".doc": "doc",
        ".txt": "text",
        ".md": "text",
    }

    def __init__(self):
        self.extracted_links: List[str] = []

    def load_text(self, file_path: str) -> Tuple[str, str]:
        """
        Loads and extracts text from supported digital CV documents.
        Returns: (extracted_text, document_format)
        """
        self.extracted_links = []
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
            return self._extract_pdf(path), "pdf"
        elif doc_type == "docx":
            return self._extract_docx(path), "docx"
        elif doc_type == "text":
            return self._extract_plain_text(path), "text"
        else:
            raise ValueError(f"No extractor available for format: {ext}")

    def _extract_pdf(self, path: Path) -> str:
        """Extracts digital text and injects clickable hyperlink URLs inline at their exact positions."""
        text_pages = []
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            for page in reader.pages:
                # 1. Collect link annotations with their bounding boxes
                page_links = []
                if hasattr(page, "annotations") and page.annotations:
                    for annot_ref in page.annotations:
                        try:
                            annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
                            if not annot or annot.get("/Subtype") != "/Link":
                                continue
                            rect = annot.get("/Rect")
                            action = annot.get("/A")
                            uri = None
                            if action and hasattr(action, "get"):
                                uri = action.get("/URI")
                            elif annot and hasattr(annot, "get") and "/URI" in annot:
                                uri = annot.get("/URI")

                            if uri and rect:
                                uri_str = str(uri).strip()
                                if uri_str:
                                    if uri_str not in self.extracted_links:
                                        self.extracted_links.append(uri_str)
                                    x1, y1, x2, y2 = [float(v) for v in rect]
                                    page_links.append({
                                        "uri": uri_str,
                                        "x1": min(x1, x2),
                                        "x2": max(x1, x2),
                                        "y1": min(y1, y2),
                                        "y2": max(y1, y2),
                                        "used": False
                                    })
                        except Exception:
                            continue

                # Sort links in reading order: top-to-bottom (descending y), left-to-right (ascending x)
                page_links.sort(key=lambda l: (-l["y2"], l["x1"]))

                # 2. Extract text and inject hyperlinks inline at their exact text position
                chunks = []
                def visitor_body(text, cm, tm, font_dict, font_size):
                    if not text:
                        return
                    x = tm[4]
                    y = tm[5]

                    matched_link = None
                    is_anchor = any(kw in text for kw in ["[GitHub", "Repo", "Demo", "Link", "LinkedIn", "GitHub", "Portfolio", "Website", "http"])

                    for link in page_links:
                        if link["used"]:
                            continue

                        # Check vertical alignment (within 8pt baseline band)
                        y_match = (link["y1"] - 8 <= y <= link["y2"] + 8)
                        if not y_match:
                            continue

                        # Check horizontal alignment
                        x_match = (link["x1"] - 30 <= x <= link["x2"] + 30)

                        if is_anchor:
                            if y_match:
                                # If multiple links on the same line, pick the horizontally matching link
                                nearby_links = [l for l in page_links if not l["used"] and l["y1"] - 8 <= y <= l["y2"] + 8]
                                if len(nearby_links) == 1 or (link["x1"] - 50 <= x <= link["x2"] + 100):
                                    matched_link = link
                                    break
                        elif x_match and y_match:
                            matched_link = link
                            break

                    clean_text = text.rstrip()
                    trailing_ws = text[len(clean_text):]

                    if matched_link and clean_text.strip():
                        matched_link["used"] = True
                        uri_to_inject = matched_link["uri"]
                        chunks.append(f"{clean_text} ({uri_to_inject}){trailing_ws}")
                    else:
                        chunks.append(text)

                try:
                    page.extract_text(visitor_text=visitor_body)
                    page_text = "".join(chunks).strip()
                except Exception as ve:
                    logger.warning(f"Visitor text extraction failed, falling back to standard extract_text: {ve}")
                    page_text = (page.extract_text() or "").strip()

                if page_text:
                    text_pages.append(page_text)

        except Exception as e:
            logger.error(f"pypdf extraction failed for {path}: {e}")
            raise ValueError(f"Failed to read PDF document '{path.name}': {str(e)}")

        full_text = "\n".join(text_pages).strip()
        if not full_text:
            raise ValueError(
                f"No readable text could be extracted from '{path.name}'. "
                "Please ensure the document contains digital selectable text (scanned image PDFs are not supported)."
            )
        return full_text

    def _extract_docx(self, path: Path) -> str:
        """Extracts paragraphs, hyperlinks, and table cells from DOCX files."""
        try:
            import docx
            from docx.oxml.ns import qn
            doc = docx.Document(str(path))
            lines = []
            for p in doc.paragraphs:
                p_text = ""
                for child in p._p:
                    if child.tag.endswith("hyperlink"):
                        r_id = child.get(qn("r:id"))
                        link_text = "".join(node.text for node in child.iter() if node.text)
                        if r_id and r_id in p.part.rels:
                            target = p.part.rels[r_id].target_ref
                            if target and target not in self.extracted_links:
                                self.extracted_links.append(target)
                            p_text += f" {link_text} ({target}) "
                        else:
                            p_text += f" {link_text} "
                    elif child.tag.endswith("r"):
                        p_text += "".join(node.text for node in child.iter() if node.text)
                clean_line = p_text.strip() or p.text.strip()
                if clean_line:
                    lines.append(clean_line)

            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if row_text:
                        lines.append(row_text)
            return "\n".join(lines)
        except ImportError:
            # Fallback direct zip XML extraction if python-docx isn't installed
            import zipfile
            import xml.etree.ElementTree as ET
            with zipfile.ZipFile(str(path)) as z:
                xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            text_nodes = tree.findall(".//w:t", namespaces)
            return " ".join(node.text for node in text_nodes if node.text)
        except Exception as e:
            logger.error(f"DOCX extraction error for {path}: {e}")
            raise ValueError(f"Failed to extract text from DOCX file '{path.name}': {str(e)}")

    def _extract_plain_text(self, path: Path) -> str:
        """Reads plain text files with UTF-8 encoding."""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
