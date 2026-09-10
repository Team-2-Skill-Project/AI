import logging
import re
from typing import Any

from src.core.llm_service import LLMService, get_llm_service
from src.models import CVExtractionSchema
from src.taxonomy.taxonomy_manager import STOPWORDS_BLACKLIST

from .link_associator import ProjectLinkAssociator

logger = logging.getLogger(__name__)


class LLMExtractor:
    """
    Candidate Profile & Entity Extractor.
    Delegates contextual LLM inference to the centralized LLMService,
    with an intelligent rule-based heuristic parser when LLM is unavailable.
    Strictly validates outputs with Pydantic CVExtractionSchema.
    """


    SYSTEM_PROMPT = """You are an expert AI Resume Parser. Analyze the following CV/Resume text and output a valid JSON object strictly matching this schema:
{
  "name": "Candidate Full Name",
  "email": "candidate@email.com",
  "phone": "+201234567890",
  "location": "Candidate's personal location from header/contact info (e.g. 'Cairo, Egypt', 'Egypt', 'Dubai, UAE', 'Remote')",
  "target_roles": ["Role Title inferred from experience/header"],
  "education": [
    {
      "degree": "BSc / MSc / Bachelor of Computer Science / etc.",
      "field": "Field of study / Major",
      "institution": "University / Institution name",
      "start_year": 2020,
      "end_year": 2024,
      "status": "completed or current"
    }
  ],
  "experience": [
    {
      "company": "Company / Organization Name",
      "role": "Job Title / Role",
      "location": "City, Country or Remote",
      "start_date": "YYYY-MM or YYYY",
      "end_date": "YYYY-MM or Present",
      "is_current": false,
      "responsibilities": ["Detailed responsibility or impact bullet 1", "Detailed responsibility bullet 2"],
      "technologies": ["Tech1", "Tech2"]
    }
  ],
  "projects": [
    {
      "title": "Project Title",
      "description": "Detailed summary of what the project does, architecture, and impact",
      "technologies": ["Tech1", "Tech2"],
      "link": "MUST be an exact valid HTTP/HTTPS URL (e.g. 'https://github.com/user/repo' or 'https://...') or null. NEVER return placeholder text like 'GitHub Repo' or 'Repo' or '[GitHub Repo]'. If no actual URL is present, return null."
    }
  ],
  "certifications": [
    {
      "name": "Certification Name",
      "issuer": "Issuing organization",
      "issue_date": "YYYY",
      "credential_id": null
    }
  ],
  "raw_skills": [
    {"name": "Python", "level": "advanced"},
    {"name": "React", "level": "intermediate"}
  ]
}

IMPORTANT INSTRUCTIONS:
1. LOCATION: Extract candidate's personal location strictly from the contact/header section. Do NOT confuse university location or previous company location with the candidate's personal location. If only a country (e.g. 'Egypt') is specified in header, return 'Egypt'.
2. PROJECTS: Extract ALL projects mentioned in the CV. For each project, extract its full title, detailed description from all bullet points, full list of technologies, and repository/live URL if present. The 'link' MUST be a valid clickable URL starting with 'http' or null; never output placeholder text like 'GitHub Repo'.
3. RAW SKILLS: Include explicit technical skills, programming languages, frameworks, libraries, databases, and developer tools.
4. Separate distinct work experiences and distinct projects into separate list items.
5. Return ONLY a valid JSON object. DO NOT wrap with markdown backticks (```json).
"""

    def __init__(self, llm_service: LLMService | None = None):
        self.llm_service = llm_service or get_llm_service()

    def extract_entities(
        self,
        full_text: str,
        sections: dict[str, str],
        document_urls: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Extracts structured entities from CV text using the centralized LLMService if available,
        or intelligent heuristic extraction otherwise.
        Strictly validates and coerces outputs using Pydantic CVExtractionSchema.
        """
        if self.llm_service.is_available():
            try:
                prompt = f"RESUME TEXT:\n{full_text[:12000]}"
                raw_result = self.llm_service.generate_json(
                    prompt=prompt,
                    system_prompt=self.SYSTEM_PROMPT
                )
                if raw_result and isinstance(raw_result, dict) and raw_result.get("name"):
                    validated = CVExtractionSchema.model_validate(raw_result).model_dump()
                    logger.info("Successfully extracted and schema-validated entities using centralized LLM service.")
                    self._sanitize_and_resolve_project_links(validated.get("projects", []), full_text, document_urls)
                    return validated
            except Exception as e:
                logger.error(f"Centralized LLM service error or validation failure: {e}. Falling back to heuristic parser.")

        heur_result = self._extract_heuristically(full_text, sections)
        validated_heur = CVExtractionSchema.model_validate(heur_result).model_dump()
        self._sanitize_and_resolve_project_links(validated_heur.get("projects", []), full_text, document_urls)
        return validated_heur


    def _sanitize_and_resolve_project_links(
        self,
        projects: list[dict[str, Any]],
        full_text: str,
        document_urls: list[str] | None = None
    ) -> None:
        """
        Applies strict 7-rule project-to-URL association via ProjectLinkAssociator.
        """
        ProjectLinkAssociator.associate_projects_with_links(
            projects=projects,
            full_text=full_text,
            document_urls=document_urls
        )

    def _extract_heuristically(self, full_text: str, sections: dict[str, str]) -> dict[str, Any]:
        """
        Regex & section-based parser used when LLM service is offline or unconfigured.
        """
        header_text = sections.get("header", "") or full_text[:400]
        lines = [line_str.strip() for line_str in header_text.split("\n") if line_str.strip()]

        # 1. Name extraction
        name = "Candidate"
        for line in lines:
            if not re.search(r"[@\+0-9\:\/\|]", line) and len(line.split()) in [2, 3, 4]:
                raw_name = line.strip()
                # Fix PDF kerning glitches like "Mostaf A" -> "Mostafa"
                raw_name = re.sub(r"([A-Za-z]+)\s+([A-Za-z])$", r"\1\2", raw_name)
                name = raw_name.title()
                break

        # 2. Email extraction
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", full_text)
        email = email_match.group(0) if email_match else None

        # 3. Phone extraction
        phone_match = re.search(r"(?:\+?\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}", full_text)
        phone = phone_match.group(0) if phone_match else None

        # 4. Location extraction (strictly from header / contact info first)
        location = None
        for line in lines:
            if "@" in line or any(k in line.lower() for k in ["linkedin", "github", "+20", "+1", "+966", "phone", "tel"]):
                parts = [p.strip() for p in re.split(r"[\|\•\·]", line)]
                for part in parts:
                    if not re.search(r"[@\+0-9]|linkedin|github|portfolio|http|\.com", part, flags=re.IGNORECASE):
                        if 2 <= len(part) <= 30 and len(part.split()) <= 4:
                            if any(c in part.lower() for c in ["egypt", "cairo", "giza", "alexandria", "mansoura", "benha", "tanta", "assiut", "riyadh", "dubai", "remote", "saudi", "uae", "germany", "usa", "uk"]):
                                location = part.strip()
                                break
                if location:
                    break

        if not location:
            header_city = re.search(r"\b(Cairo|Giza|Alexandria|Mansoura|Benha|Tanta|Assiut|Sharqia|Ismailia|Suez|Riyadh|Dubai|Jeddah)\b(?:\s*,\s*(Egypt|KSA|UAE))?", header_text, flags=re.IGNORECASE)
            if header_city:
                location = header_city.group(0).strip()
            else:
                country_match = re.search(r"\b(Egypt|Saudi Arabia|UAE|United States|Germany|United Kingdom)\b", header_text, flags=re.IGNORECASE)
                location = country_match.group(0).strip() if country_match else "Egypt"
                location = country_match.group(0).strip() if country_match else None

        # 5. Education extraction
        education_list = self._parse_education(sections.get("education", full_text))
        # 5. Education extraction (only parse if education section exists or education keywords are present)
        edu_text = sections.get("education", "")
        if not edu_text and any(k in full_text.lower() for k in ["bachelor", "master", "bsc", "msc", "phd", "university", "faculty", "college", "degree"]):
            edu_text = full_text
        education_list = self._parse_education(edu_text)

        # 6. Experience & Projects extraction (Disentangled)
        experience_text = sections.get("experience", "")
        projects_text = sections.get("projects", "")

        # If experience section contains project subheaders, split them
        if not projects_text and "projects" in experience_text.lower():
            exp_parts = re.split(r"(?:Selected AI & Research Projects|Key Projects|Live Projects|Personal Projects)", experience_text, flags=re.IGNORECASE)
            if len(exp_parts) > 1:
                experience_text = exp_parts[0]
                projects_text = exp_parts[1]

        experience_list = self._parse_experience(experience_text)
        projects_list = self._parse_projects(projects_text)

        # 7. Target role extraction
        target_roles = []
        if experience_list:
            target_roles.append(experience_list[0]["role"])
        else:
            role_patterns = [
                r"\b(Agentic AI Developer|AI Solutions Architect|AI Engineer|Machine Learning Engineer|Data Scientist|Data Analyst|Backend Developer|Backend Engineer|Frontend Developer|Full Stack Developer|Software Engineer|Mobile Developer|Flutter Developer|DevOps Engineer|Data Engineer)\b"
            ]
            for pat in role_patterns:
                matches = re.findall(pat, full_text[:1000], flags=re.IGNORECASE)
                for m in matches:
                    title = m.strip().title()
                    if title not in target_roles:
                        target_roles.append(title)

        # 8. Raw skills extraction (strict token filtering)
        raw_skills = self._parse_skills(sections.get("skills", ""))

        return {
            "name": name,
            "email": email,
            "phone": phone,
            "location": location,
            "target_roles": target_roles,
            "education": education_list,
            "experience": experience_list,
            "projects": projects_list,
            "certifications": [],
            "raw_skills": raw_skills,
        }

    def _parse_education(self, text: str) -> list[dict[str, Any]]:
        edu_items = []
        if not text:
            return edu_items

        degree_patterns = [
            (r"\b(BSc|B\.Sc|Bachelor of Science|Bachelor of Computer Science|Bachelor of Engineering|Bachelor of Arts|Bachelor of Business|Bachelor|Undergraduate|Licentiate)\b.*?(?:Computer Science|Information Technology|Software Engineering|Artificial Intelligence|Data Science|Engineering|Business|Economics|Science)?", "Bachelor"),
            (r"\b(MSc|M\.Sc|Master of Science|Master of Computer Science|Master of Engineering|Master of Business Administration|MBA|Master)\b.*", "Master"),
            (r"\b(PhD|Ph\.D|Doctor of Philosophy|Doctorate)\b.*", "Doctor of Philosophy"),
            (r"\b(Associate Degree|Diploma|High School Diploma)\b.*", "Diploma"),
        ]

        found_degree = None
        for pattern, _ in degree_patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                found_degree = m.group(0).strip().title()
                found_degree = re.sub(r"[\(\)\|\,\.]+$", "", found_degree).strip()
                break

        lines = [line_str.strip() for line_str in text.split("\n") if line_str.strip()]

        # Extract university name prioritizing University/Institute/Faculty/College on a line basis
        institution = None
        for line in lines:
            univ_m = re.search(r"\b([A-Za-z\t\s,\.-]+(?:University|Institute|College|Faculty|Academy)[A-Za-z\t\s,\.-]*)\b", line, flags=re.IGNORECASE)
            if univ_m:
                inst_candidate = univ_m.group(0).strip(" ,.-")
                inst_candidate = re.sub(r"^(?:Bachelor|Master|BSc|MSc|Degree|Of|Science|In|And|Ai|Cs|From|At|The|From The|Github|Education)\s+", "", inst_candidate, flags=re.IGNORECASE).strip(" ,.-")
                if any(k in inst_candidate.lower() for k in ["university", "institute", "college", "faculty", "academy"]):
                    institution = inst_candidate.title()
                    # If line has "University", it's the strongest institutional indicator
                    if "university" in inst_candidate.lower():
                        break

        # If NEITHER a degree NOR an institution was found, do NOT fabricate an education record!
        if not found_degree and not institution:
            return edu_items




        degree = found_degree or "Degree"
        inst = institution or "University"

        years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", text)]
        has_grad_hint = bool(re.search(r"(?:graduat|expected|class of)", text, re.IGNORECASE))
        start_year = min(years) if len(years) >= 2 else (years[0] if len(years) == 1 and not has_grad_hint else None)
        end_year = max(years) if len(years) >= 2 else (years[0] if len(years) == 1 and has_grad_hint else None)

        # Accurate field extraction using word boundaries to prevent substring collisions (e.g. 'ai' in 'email')
        if re.search(r"\b(?:Artificial Intelligence|AI|Machine Learning)\b", text, flags=re.IGNORECASE):
            field = "Artificial Intelligence"
        elif re.search(r"\b(?:Computer Science|CS|Software Engineering|Informatics)\b", text, flags=re.IGNORECASE):
            field = "Computer Science"
        elif re.search(r"\b(?:Information Technology|IT|Information Systems)\b", text, flags=re.IGNORECASE):
            field = "Information Technology"
        elif re.search(r"\b(?:Data Science|Data Analytics|Statistics)\b", text, flags=re.IGNORECASE):
            field = "Data Science"
        elif re.search(r"\b(?:Electrical Engineering|Mechanical Engineering|Civil Engineering|Engineering)\b", text, flags=re.IGNORECASE):
            field = "Engineering"
        elif re.search(r"\b(?:Business Administration|Management|Finance|Accounting|Marketing|Economics)\b", text, flags=re.IGNORECASE):
            field = "Business"
        else:
            field = None

        status = "completed"
        if end_year and end_year >= 2026 or re.search(r"\b(expected|present|current|undergraduate|studying|in progress)\b", text, flags=re.IGNORECASE):
            status = "current"

        edu_items.append({
            "degree": degree,
            "field": field,
            "institution": inst,
            "start_year": start_year,
            "end_year": end_year,
            "status": status
        })
        return edu_items



    def _parse_projects(self, text: str) -> list[dict[str, Any]]:
        projects = []
        if not text:
            return projects

        lines = [line_str.strip() for line_str in text.split("\n") if line_str.strip()]
        current_project: dict[str, Any] | None = None

        SYMBOL_BULLET_RE = re.compile(r"^[•\-\*\u2022\u25e6\ufffd]")
        NUMBERED_PREFIX_RE = re.compile(r"^\d+[.\)]\s+")
        DATE_ONLY_RE = re.compile(
            r"^(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?(?:19|20)\d{2}\s*(?:[–—\-to]+\s*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?(?:19|20)\d{2}|present|current)?$",
            re.IGNORECASE
        )
        TECH_LINE_RE = re.compile(r"^(?:technologies|tech\s+stack|tools|skills|built\s+with|built\s+using|stack):\s*(.*)", re.IGNORECASE)
        SENTENCE_END_RE = re.compile(r"[.!?]$")

        def _clean_project_title(raw: str) -> str:
            t = raw.strip()
            # 1. Strip markdown links [Text](url), brackets [GitHub], and parenthesized URLs
            t = re.sub(r"\[.*?\]", "", t)
            t = re.sub(r"\(https?://[^\)]*\)", "", t)
            t = re.sub(r"https?://\S+", "", t)
            # 2. Strip leading markdown headers and numbering (e.g. ### 1. Project -> Project)
            t = re.sub(r"^[#\*\_\=\-\~\+\[\]\(\)\|\>\s]+", "", t)
            t = re.sub(r"^(?:project\s*\d*[\:\.\-\)]*|\d+[\.\)\:\-\s]+)\s*", "", t, flags=re.IGNORECASE)
            # 3. Strip trailing markdown formatting and punctuation
            t = re.sub(r"[#\*\_\=\-\~\+\[\]\(\)\|\>\:\;\.\s]+$", "", t)
            # 4. Fix PDF kerning glitches (e.g. "T ruthStream" -> "TruthStream")
            t = re.sub(r"\b([A-Z])\s+([a-z])", r"\1\2", t).strip()
            return t or raw.strip()

        for i, line in enumerate(lines):
            has_pipe = "|" in line
            link = self._extract_url(line)

            # Check next non-empty line for lookahead
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            next_is_symbol_bullet = bool(SYMBOL_BULLET_RE.match(next_line))
            next_is_tech = bool(TECH_LINE_RE.match(next_line))
            next_is_date = bool(DATE_ONLY_RE.match(next_line))
            next_is_bullet = next_is_symbol_bullet or bool(NUMBERED_PREFIX_RE.match(next_line))

            # Distinguish symbol bullets vs numbered titles vs numbered bullets
            is_symbol_bullet = bool(SYMBOL_BULLET_RE.match(line))
            is_numbered_prefix = bool(NUMBERED_PREFIX_RE.match(line))

            # A numbered line like "1. Smart Health Assistant" followed by "• ..." is a TITLE, not a bullet
            if is_numbered_prefix and (next_is_symbol_bullet or next_is_tech or next_is_date or len(line.split()) <= 6):
                is_bullet = False
            else:
                is_bullet = is_symbol_bullet or is_numbered_prefix

            # ── Metadata line: Technologies / Tech Stack ──────────────────────────
            tech_match = TECH_LINE_RE.match(line)
            if tech_match and current_project:
                tech_str = tech_match.group(1)
                explicit_techs = [t.strip() for t in re.split(r"[,\|;/]+", tech_str) if t.strip()]
                extracted_techs = self._extract_inline_technologies(tech_str)
                all_t = list(dict.fromkeys(current_project["technologies"] + explicit_techs + extracted_techs))
                current_project["technologies"] = all_t
                continue

            # ── Metadata line: Standalone Date line ───────────────────────────────
            if DATE_ONLY_RE.match(line):
                continue

            # ── Metadata line: Standalone URL line ────────────────────────────────
            if link and (line == link or line.lower().startswith("http") or line.lower().startswith("www.") or line.lower().startswith("github.com")):
                if current_project and not current_project.get("link"):
                    current_project["link"] = link
                continue

            # ── Pattern A: Pipe syntax ("Title [GitHub] (url) | Techs Date") ──────
            if has_pipe and not is_bullet:
                parts = line.split("|", 1)
                clean_title = _clean_project_title(parts[0])
                tech_and_date = parts[1].strip() if len(parts) > 1 else ""
                techs = self._extract_inline_technologies(tech_and_date) or self._extract_inline_technologies(line)

                if clean_title:
                    if current_project:
                        projects.append(current_project)
                    current_project = {
                        "title": clean_title,
                        "description": "",
                        "technologies": techs,
                        "link": link
                    }
                    continue

            # ── Pattern B: Prefix / Colon syntax ────────────────────────────────
            # Case 1: "Project 2: Data Pipeline" or "Project: Data Pipeline" or "1. Analytics Dashboard"
            proj_prefix_match = re.match(r"^(?:project\s*\d*|\d+)[\:\.\-\)]\s*(.*)", line, flags=re.IGNORECASE)
            if proj_prefix_match and not is_bullet:
                sub_title = proj_prefix_match.group(1).strip()
                if sub_title and len(sub_title.split()) <= 8:
                    if current_project:
                        projects.append(current_project)
                    clean_title = _clean_project_title(sub_title)
                    current_project = {
                        "title": clean_title,
                        "description": "",
                        "technologies": self._extract_inline_technologies(line),
                        "link": link
                    }
                    continue

            # Case 2: "AI Video Summarizer: Built a Python tool..."
            colon_match = re.match(r"^([A-Za-z0-9\s\-\&]+):\s*(.*)", line)
            if (
                colon_match
                and len(colon_match.group(1).split()) <= 6
                and not is_bullet
                and not has_pipe
                and colon_match.group(1).lower().strip() not in ["technologies", "tech stack", "tools", "skills", "built with", "description", "note"]
            ):
                prefix = colon_match.group(1).strip()
                if re.match(r"^project\s*\d*$", prefix, re.IGNORECASE):
                    actual_title = _clean_project_title(colon_match.group(2))
                    desc = ""
                else:
                    actual_title = _clean_project_title(prefix)
                    desc = colon_match.group(2).strip()

                if actual_title:
                    if current_project:
                        projects.append(current_project)
                    current_project = {
                        "title": actual_title,
                        "description": desc,
                        "technologies": self._extract_inline_technologies(line),
                        "link": link
                    }
                    continue

            # ── Pattern C / D: Standalone or Markdown project title line ─────────
            # E.g. "Customer Churn Prediction Model", "Automated SQL Financial Reporting Pipeline", or "### 2. Drone Navigation"
            is_title_candidate = (
                not is_bullet
                and not has_pipe
                and len(line) <= 80
                and len(line.split()) <= 10
                and not (SENTENCE_END_RE.search(line) and len(line.split()) > 2)
            )

            is_new_project_boundary = is_title_candidate and (
                next_is_bullet
                or next_is_tech
                or next_is_date
                or line.startswith(("#", "**", "__"))
                or is_numbered_prefix
                or current_project is None
                or (current_project and bool(current_project.get("description")))
            )

            if is_new_project_boundary:
                clean_title = _clean_project_title(line)
                if clean_title:
                    if current_project:
                        projects.append(current_project)
                    current_project = {
                        "title": clean_title,
                        "description": "",
                        "technologies": self._extract_inline_technologies(line),
                        "link": link
                    }
                    continue

            # ── Bullet / Description accumulation ─────────────────────────────────
            if current_project:
                clean_bullet = re.sub(r"^(?:[•\-\*\u2022\u25e6\ufffd]|\d+[.\)]\s*)\s*", "", line).strip()
                if clean_bullet:
                    if current_project["description"]:
                        current_project["description"] += " " + clean_bullet
                    else:
                        current_project["description"] = clean_bullet
                new_techs = self._extract_inline_technologies(line)
                if new_techs:
                    current_project["technologies"] = list(dict.fromkeys(current_project["technologies"] + new_techs))
                if not current_project.get("link") and link:
                    current_project["link"] = link

        if current_project:
            projects.append(current_project)

        return projects

    def _parse_experience(self, text: str) -> list[dict[str, Any]]:
        exp_items = []
        if not text:
            return exp_items

        lines = [line_str.strip() for line_str in text.split("\n") if line_str.strip()]
        current_exp: dict[str, Any] | None = None

        DATE_RANGE_RE = re.compile(
            r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(?:19|20)\d{2}|\b(?:19|20)\d{2})\s*(?:[–—\-to\s]+\s*(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(?:19|20)\d{2}|\b(?:19|20)\d{2}|Present|Current|Ongoing|Now))?",
            re.IGNORECASE
        )

        ROLE_TITLE_RE = re.compile(
            r"^([A-Za-z0-9\s\(\)\-\&]+?\b(?:Developer|Engineer|Architect|Specialist|Analyst|Internship|Intern|Scientist|Lead|Manager|Consultant|Officer|Director|Coordinator|Instructor|Administrator|Designer|Researcher)\b[A-Za-z0-9\s\(\)\-\&]*?)(?:\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{4}).*)?$",
            re.IGNORECASE
        )

        ACTION_VERB_RE = re.compile(
            r"^(?:Developed|Built|Created|Designed|Implemented|Maintained|Managed|Led|Engineered|"
            r"Spearheaded|Architected|Collaborated|Assisted|Worked|Contributed|Integrated|"
            r"Researched|Optimized|Deployed|Automated|Configured|Trained|Evaluated|Conducted|"
            r"Participated|Handled|Provided|Supported|Wrote|Produced)\b",
            re.IGNORECASE
        )

        def _clean_role_title(raw: str) -> str:
            t = raw.strip()
            # Remove parenthesized date/location expressions e.g. "(2021 - 2023)" or dangling "(2021 -"
            t = re.sub(r"\([^\)]*(?:19|20)\d{2}[^\)]*\)?", "", t, flags=re.IGNORECASE)
            t = re.sub(r"\b(?:19|20)\d{2}.*", "", t, flags=re.IGNORECASE)
            t = re.sub(r"[\(\[\{]\s*$", "", t)
            t = re.sub(r"^[,\s\-\(\)\[\]\|]+|[,\s\-\(\)\[\]\|]+$", "", t).strip()
            return t

        def _clean_company_name(raw: str) -> str:
            t = raw.strip()
            # 1. Remove parenthesized date/location expressions e.g. "(July 2024 – September 2024)" or "(2021 - 2023)" or dangling "(2021 -"
            t = re.sub(r"\([^\)]*(?:19|20)\d{2}[^\)]*\)?", "", t, flags=re.IGNORECASE)
            # 2. Remove date patterns without parens
            t = re.sub(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(?:19|20)\d{2}.*", "", t, flags=re.IGNORECASE)
            t = re.sub(r"\b(?:19|20)\d{2}\s*(?:[–—\-to]+\s*(?:(?:19|20)\d{2}|Present|Current))?", "", t, flags=re.IGNORECASE)
            # 3. Remove trailing location suffixes like ', Cairo, Egypt' or ' - Remote'
            t = re.sub(r"[,\|\-]\s*(?:Cairo|Giza|Alexandria|Mansoura|Benha|Tanta|Assiut|Egypt|Saudi Arabia|UAE|Remote|USA|UK|Germany)\b.*", "", t, flags=re.IGNORECASE)
            # 4. Strip dangling unclosed opening brackets
            t = re.sub(r"[\(\[\{]\s*$", "", t)
            # 5. Strip trailing/leading punctuation, parens, brackets, dashes
            t = re.sub(r"^[,\s\-\(\)\[\]\|]+|[,\s\-\(\)\[\]\|]+$", "", t).strip()
            return t

        def _extract_dates_from_text(t: str) -> tuple[str | None, str | None, bool]:
            m = DATE_RANGE_RE.search(t)
            if not m:
                return None, None, False
            start_d = m.group(1).strip() if m.group(1) else None
            end_d = m.group(2).strip() if m.group(2) else None
            is_curr = bool(end_d and re.search(r"present|current|ongoing|now", end_d, re.IGNORECASE))
            return start_d, end_d, is_curr

        i = 0
        while i < len(lines):
            line = lines[i]
            is_bullet = bool(re.match(r"^[•\-\*\u2022\u25e6\ufffd]|\d+[.\)]\s", line)) or line.startswith("•") or line.startswith("-") or line.startswith("\ufffd")
            has_pipe = "|" in line and any(k in line.lower() for k in ["developer", "engineer", "intern", "scientist", "analyst", "specialist", "manager", "lead", "architect", "consultant", "officer"])
            role_date_match = ROLE_TITLE_RE.match(line)

            is_role_header = (role_date_match and not is_bullet) or has_pipe

            if is_role_header:
                if current_exp:
                    exp_items.append(current_exp)

                start_date, end_date, is_current = _extract_dates_from_text(line)

                # Strip dates and parentheses from line before splitting role / company
                line_no_dates = re.sub(r"\([^\)]*(?:19|20)\d{2}[^\)]*\)?", "", line, flags=re.IGNORECASE)
                line_no_dates = re.sub(r"\b(?:19|20)\d{2}\s*(?:[–—\-to]+\s*(?:(?:19|20)\d{2}|Present|Current))?", "", line_no_dates, flags=re.IGNORECASE).strip()
                line_no_dates = re.sub(r"[\(\[\{]\s*$", "", line_no_dates).strip()

                company = None
                location = None

                if "|" in line_no_dates:
                    parts = re.split(r"\|", line_no_dates)
                    role = _clean_role_title(parts[0])
                    company_raw = parts[1].strip() if len(parts) > 1 else ""
                    company = _clean_company_name(company_raw) if company_raw else None
                    loc_m = re.search(r"\b(Cairo|Giza|Alexandria|Mansoura|Benha|Tanta|Assiut|Sharqia|Ismailia|Suez|Riyadh|Dubai|Jeddah|Egypt|Saudi Arabia|UAE|Remote)\b(?:\s*,\s*(Egypt|KSA|UAE))?", company_raw, flags=re.IGNORECASE)
                    location = loc_m.group(0).strip() if loc_m else None
                elif re.search(r"\s+(?:at|@)\s+", line_no_dates, flags=re.IGNORECASE):
                    parts = re.split(r"\s+(?:at|@)\s+", line_no_dates, maxsplit=1, flags=re.IGNORECASE)
                    role = _clean_role_title(parts[0])
                    company_raw = parts[1].strip()
                    company = _clean_company_name(company_raw) if company_raw else None
                    loc_m = re.search(r"\b(Cairo|Giza|Alexandria|Mansoura|Benha|Tanta|Assiut|Sharqia|Ismailia|Suez|Riyadh|Dubai|Jeddah|Egypt|Saudi Arabia|UAE|Remote)\b(?:\s*,\s*(Egypt|KSA|UAE))?", company_raw, flags=re.IGNORECASE)
                    location = loc_m.group(0).strip() if loc_m else None
                elif re.search(r"\s+[\-–—]\s+", line_no_dates):
                    parts = re.split(r"\s+[\-–—]\s+", line_no_dates, maxsplit=1)
                    role = _clean_role_title(parts[0])
                    company_raw = parts[1].strip()
                    company = _clean_company_name(company_raw) if company_raw else None
                    loc_m = re.search(r"\b(Cairo|Giza|Alexandria|Mansoura|Benha|Tanta|Assiut|Sharqia|Ismailia|Suez|Riyadh|Dubai|Jeddah|Egypt|Saudi Arabia|UAE|Remote)\b(?:\s*,\s*(Egypt|KSA|UAE))?", company_raw, flags=re.IGNORECASE)
                    location = loc_m.group(0).strip() if loc_m else None
                else:
                    role = _clean_role_title(line_no_dates)

                # Check next line for company ONLY if company was not found on the same line
                if not company and i + 1 < len(lines):
                    next_line = lines[i + 1]
                    next_is_bullet = bool(re.match(r"^[•\-\*\u2022\u25e6\ufffd]|\d+[.\)]\s", next_line)) or next_line.startswith("•") or next_line.startswith("-")
                    next_is_meta = bool(re.match(r"^(?:Responsibilities|Technologies|Tech Stack|Tools):", next_line, flags=re.IGNORECASE))
                    next_is_verb = bool(ACTION_VERB_RE.match(next_line))
                    next_ends_sentence = next_line.endswith(".") and len(next_line.split()) > 2

                    if not next_is_bullet and not next_is_meta and not next_is_verb and not next_ends_sentence and len(next_line.split()) <= 6:
                        cleaned_next = _clean_company_name(next_line)
                        if cleaned_next and not DATE_RANGE_RE.fullmatch(cleaned_next):
                            company = cleaned_next
                            i += 1  # consume company line

                        # Extract dates from next line if not found yet
                        if not start_date:
                            s_d, e_d, is_c = _extract_dates_from_text(next_line)
                            if s_d:
                                start_date, end_date, is_current = s_d, e_d, is_c

                current_exp = {
                    "company": company or "Organization",
                    "role": role,
                    "location": location,
                    "start_date": start_date,
                    "end_date": end_date,
                    "is_current": is_current,
                    "responsibilities": [],
                    "technologies": self._extract_inline_technologies(line)
                }
                i += 1
                continue

            if current_exp:
                # Check for standalone date line if start_date is still None
                if not current_exp["start_date"]:
                    s_d, e_d, is_c = _extract_dates_from_text(line)
                    if s_d and not is_bullet:
                        current_exp["start_date"] = s_d
                        current_exp["end_date"] = e_d
                        current_exp["is_current"] = is_c
                        i += 1
                        continue

                # Check for Technologies: line
                tech_match = re.match(r"^Technologies:\s*(.*)", line, flags=re.IGNORECASE)
                if tech_match:
                    tech_tokens = [t.strip() for t in tech_match.group(1).split(",") if t.strip()]
                    current_exp["technologies"] = list(dict.fromkeys(current_exp["technologies"] + tech_tokens))
                else:
                    clean_bullet = re.sub(r"^(?:[•\-\*\u2022\u25e6\ufffd]|\d+[.\)]\s*)\s*", "", line).strip()
                    if clean_bullet:
                        current_exp["responsibilities"].append(clean_bullet)
                        current_exp["technologies"] = list(dict.fromkeys(current_exp["technologies"] + self._extract_inline_technologies(line)))

            i += 1

        if current_exp:
            exp_items.append(current_exp)

        return exp_items


    def _parse_skills(self, text: str) -> list[dict[str, str]]:
        skills = []
        if not text:
            return skills

        clean_text = re.sub(r"[A-Za-z\s\&]+:\s*", ", ", text)
        tokens = re.split(r"[,\|\n;/]+", clean_text)

        for token in tokens:
            clean_token = token.strip()
            clean_token = re.sub(r"^[\(\[\{]+|[\)\]\}\.]+$", "", clean_token).strip()

            if (
                clean_token
                and len(clean_token) >= 2
                and len(clean_token) <= 30
                and clean_token.lower() not in STOPWORDS_BLACKLIST
                and not any(u in clean_token.lower() for u in ["http", "://", ".com", ".sa"])
            ):
                skills.append({
                    "name": clean_token,
                    "level": "intermediate"
                })
        return skills

    @staticmethod
    def _extract_inline_technologies(text: str) -> list[str]:
        known = [
            "Python", "TypeScript", "JavaScript", "C++", "SQL", "PostgreSQL", "MySQL", "MongoDB", "NoSQL",
            "Pandas", "NumPy", "Matplotlib", "Seaborn", "Plotly", "Scikit-learn", "scikit-learn", "XGBoost",
            "PyTorch", "TensorFlow", "FastAPI", "Next.js", "React", "Node.js", "Express.js", "Tailwind CSS",
            "Docker", "Git", "GitHub Actions", "CI/CD", "Linux", "Apache Kafka", "Kafka", "Apache Spark", "Spark",
            "LangChain", "LangGraph", "LangSmith", "LangServe", "CrewAI", "RAG", "LLMs", "Transformers",
            "DistilBERT", "HuggingFace", "Streamlit", "MLflow", "Optuna", "ChromaDB", "Chroma", "FAISS", "Pinecone",
            "NLP", "Computer Vision", "WebSockets", "WebRTC", "n8n", "Gradio", "OpenAI API", "GPT-4o", "MLOps"
        ]
        found = []
        for k in known:
            pattern = rf"\b{re.escape(k)}\b"
            if re.search(pattern, text, flags=re.IGNORECASE):
                found.append(k)
        return found

    @staticmethod
    def _extract_url(text: str) -> str | None:
        # 1. Markdown link format: [Text](URL)
        md_match = re.search(r"\[.*?\]\((https?://[^\s\)]+)\)", text)
        if md_match:
            return md_match.group(1)

        # 2. Standard HTTP/HTTPS URL
        url_match = re.search(r"https?://[^\s\)]+", text)
        if url_match:
            return url_match.group(0).rstrip(".,)]")

        # 3. Bare GitHub / GitLab / Portfolio URL: github.com/...
        domain_match = re.search(r"\b(?:www\.)?(github\.com/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?)\b", text, flags=re.IGNORECASE)
        if domain_match:
            return f"https://{domain_match.group(1)}"

        return None
