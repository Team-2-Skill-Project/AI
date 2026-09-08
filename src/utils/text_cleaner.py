import re
from typing import Dict, List, Tuple


class TextCleaner:
    """
    Cleans raw text extracted from PDFs, OCR, DOCX, and splits into candidate sections.
    """

    # Common CV Section Header Patterns (without inline flags, compiled with re.IGNORECASE)
    SECTION_HEADERS = {
        "education": r"\b(education|academic background|qualifications|academic history|studies)\b",
        "experience": r"\b(experience|work experience|employment history|professional experience|internships|work history)\b",
        "projects": r"\b(projects|academic projects|personal projects|key projects|portfolio)\b",
        "skills": r"\b(skills|technical skills|technologies|core competencies|programming skills|expertise|tech stack)\b",
        "certifications": r"\b(certifications|certificates|courses|training|licenses|achievements|awards)\b",
        "summary": r"\b(summary|profile|about me|objective|professional summary|biography)\b",
    }

    @staticmethod
    def clean_text(raw_text: str) -> str:
        """Removes null bytes, excessive spaces, and fixes strange line breaks."""
        if not raw_text:
            return ""
        
        # Remove null characters
        text = raw_text.replace("\x00", " ")
        # Normalize non-breaking spaces
        text = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
        # Collapse multiple spaces on a single line
        text = re.sub(r"[ \t]+", " ", text)
        # Remove any metadata link blocks
        text = re.sub(r"\[Document Embedded Links & URLs\][\s\S]*?(?=\n\n|\Z)", "", text, flags=re.IGNORECASE)
        # Collapse excessive newlines (max 2 consecutive)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def segment_sections(cls, full_text: str) -> Dict[str, str]:
        """
        Splits clean text into standard CV sections:
        header, education, experience, projects, skills, certifications, summary, other.
        """
        cleaned = cls.clean_text(full_text)
        lines = cleaned.split("\n")
        
        sections: Dict[str, List[str]] = {
            "header": [],
            "summary": [],
            "education": [],
            "experience": [],
            "projects": [],
            "skills": [],
            "certifications": [],
            "other": [],
        }
        
        current_section = "header"
        
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            
            # Check if line looks like a standalone section header
            # Usually short (< 45 chars) and matches one of the regex patterns
            detected_header = None
            if len(line_str) < 45:
                for sec_name, pattern in cls.SECTION_HEADERS.items():
                    if re.fullmatch(pattern, line_str, flags=re.IGNORECASE) or re.match(rf"^{pattern}\s*[:\-]?$", line_str, flags=re.IGNORECASE):
                        detected_header = sec_name
                        break
            
            if detected_header:
                current_section = detected_header
            else:
                sections[current_section].append(line_str)
        
        # Convert lists of lines back to single string per section
        return {sec: "\n".join(content_lines) for sec, content_lines in sections.items() if content_lines}
