import re
import json
import logging
from typing import Dict, Any, List, Optional

from src.core.llm_service import LLMService, get_llm_service
from src.taxonomy.taxonomy_manager import STOPWORDS_BLACKLIST
from .link_associator import ProjectLinkAssociator

logger = logging.getLogger(__name__)


class LLMExtractor:
    """
    Candidate Profile & Entity Extractor.
    Delegates contextual LLM inference to the centralized LLMService,
    with an intelligent rule-based heuristic parser when LLM is unavailable.
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

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service or get_llm_service()

    def extract_entities(
        self,
        full_text: str,
        sections: Dict[str, str],
        document_urls: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Extracts structured entities from CV text using the centralized LLMService if available,
        or intelligent heuristic extraction otherwise.
        """
        if self.llm_service.is_available():
            try:
                prompt = f"RESUME TEXT:\n{full_text[:12000]}"
                result = self.llm_service.generate_json(
                    prompt=prompt,
                    system_prompt=self.SYSTEM_PROMPT
                )
                if result and result.get("name"):
                    logger.info("Successfully extracted entities using centralized LLM service.")
                    self._sanitize_and_resolve_project_links(result.get("projects", []), full_text, document_urls)
                    return result
            except Exception as e:
                logger.error(f"Centralized LLM service error: {e}. Falling back to heuristic parser.")

        heur_result = self._extract_heuristically(full_text, sections)
        self._sanitize_and_resolve_project_links(heur_result.get("projects", []), full_text, document_urls)
        return heur_result

    def _sanitize_and_resolve_project_links(
        self,
        projects: List[Dict[str, Any]],
        full_text: str,
        document_urls: Optional[List[str]] = None
    ) -> None:
        """
        Applies strict 7-rule project-to-URL association via ProjectLinkAssociator.
        """
        ProjectLinkAssociator.associate_projects_with_links(
            projects=projects,
            full_text=full_text,
            document_urls=document_urls
        )

    def _extract_heuristically(self, full_text: str, sections: Dict[str, str]) -> Dict[str, Any]:
        """
        Regex & section-based parser used when LLM service is offline or unconfigured.
        """
        header_text = sections.get("header", "") or full_text[:400]
        lines = [l.strip() for l in header_text.split("\n") if l.strip()]
        
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

        # 5. Education extraction
        education_list = self._parse_education(sections.get("education", full_text))

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
            "target_roles": target_roles or ["Agentic AI Developer"],
            "education": education_list,
            "experience": experience_list,
            "projects": projects_list,
            "certifications": [],
            "raw_skills": raw_skills,
        }

    def _parse_education(self, text: str) -> List[Dict[str, Any]]:
        edu_items = []
        degree_patterns = [
            (r"\b(BSc|B\.Sc|Bachelor|Undergraduate|Bachelor of Science|Bachelor of Computer Science)\b.*?(Computer Science|Engineering|Information Technology|Statistics|Artificial Intelligence|AI)?", "Bachelor of Computer Science"),
            (r"\b(MSc|M\.Sc|Master|Master of Science)\b.*", "Master of Science in Computer Science"),
        ]
        
        found_degree = "Bachelor of Computer Science"
        for pattern, default_title in degree_patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                found_degree = m.group(0).strip().title()
                break

        # Extract university name prioritizing University/Institute
        univ_match = re.search(r"\b([A-Za-z\s]+(?:University|Institute|College|Faculty))\b", text, flags=re.IGNORECASE)
        if univ_match:
            institution = univ_match.group(0).strip().title()
            institution = re.sub(r"^(?:Bachelor|Master|BSc|MSc|Degree|Of|Science|In|And|Ai|Cs|From|At|The|From The|Github|Education)\s+", "", institution, flags=re.IGNORECASE).strip().title()
        else:
            institution = "University"

        years = [int(y) for y in re.findall(r"\b(201\d|202\d|203\d)\b", text)]
        start_year = min(years) if years else 2023
        end_year = max(years) if len(years) > 1 else (start_year + 4 if start_year else 2027)

        field = "Artificial Intelligence" if "artificial intelligence" in text.lower() or "ai" in text.lower() else "Computer Science"

        edu_items.append({
            "degree": found_degree,
            "field": field,
            "institution": institution,
            "start_year": start_year,
            "end_year": end_year,
            "status": "current" if end_year >= 2026 else "completed"
        })
        return edu_items

    def _parse_projects(self, text: str) -> List[Dict[str, Any]]:
        projects = []
        if not text:
            return projects

        lines = [l.strip() for l in text.split("\n") if l.strip()]
        current_project: Optional[Dict[str, Any]] = None

        for line in lines:
            is_bullet = bool(re.match(r"^[•\-\*\u2022\u25e6\ufffd\d+\.]\s*", line)) or line.startswith("•") or line.startswith("-") or line.startswith("\ufffd")
            has_pipe = "|" in line
            link = self._extract_url(line)

            # Check if line is a project title line (e.g. "Title [GitHub Repo] (URL) | Techs Date" or "Title: Description")
            if has_pipe and not is_bullet:
                parts = line.split("|", 1)
                raw_title = parts[0].strip()
                # Remove URLs, anchors like [GitHub Repo], and parentheses
                clean_title = re.sub(r"\(https?://[^\)]+\)", "", raw_title)
                clean_title = re.sub(r"\[.*?\]", "", clean_title).strip()
                # Fix PDF kerning glitches like "T ruthStream" -> "TruthStream"
                clean_title = re.sub(r"\b([A-Z])\s+([a-z])", r"\1\2", clean_title)

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

            # Pattern B: Title: Description
            colon_match = re.match(r"^([A-Za-z0-9\s\-\&]+):\s*(.*)", line)
            if colon_match and len(colon_match.group(1).split()) <= 6 and not is_bullet and not has_pipe:
                if current_project:
                    projects.append(current_project)
                title = colon_match.group(1).strip()
                title = re.sub(r"\b([A-Z])\s+([a-z])", r"\1\2", title)
                current_project = {
                    "title": title,
                    "description": colon_match.group(2).strip(),
                    "technologies": self._extract_inline_technologies(line),
                    "link": link
                }
                continue

            if current_project:
                clean_bullet = re.sub(r"^[•\-\*\\u2022\u25e6\d+\.]\s*", "", line).strip()
                if clean_bullet:
                    if current_project["description"]:
                        current_project["description"] += " " + clean_bullet
                    else:
                        current_project["description"] = clean_bullet
                new_techs = self._extract_inline_technologies(line)
                if new_techs:
                    current_project["technologies"] = list(dict.fromkeys(current_project["technologies"] + new_techs))
                if not current_project["link"] and link:
                    current_project["link"] = link

        if current_project:
            projects.append(current_project)

        return projects

    def _parse_experience(self, text: str) -> List[Dict[str, Any]]:
        exp_items = []
        if not text:
            return exp_items

        lines = [l.strip() for l in text.split("\n") if l.strip()]
        current_exp: Optional[Dict[str, Any]] = None

        i = 0
        while i < len(lines):
            line = lines[i]

            # Check if line is a role header (e.g. "Agentic AI Developer Aug 2025 – May 2026" or "AI Engineer | Khattab Web")
            role_date_match = re.search(r"^([A-Za-z0-9\s\(\)\-\&]+?\b(?:Developer|Engineer|Architect|Specialist|Analyst|Internship|Intern|Scientist|Lead)\b[A-Za-z0-9\s\(\)\-\&]*?)(?:\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{4}).*)?$", line, flags=re.IGNORECASE)
            has_pipe = "|" in line and any(k in line.lower() for k in ["developer", "engineer", "intern", "scientist", "analyst"])

            is_role_header = (role_date_match and not line.startswith("•") and not line.startswith("-")) or has_pipe

            if is_role_header:
                if current_exp:
                    exp_items.append(current_exp)

                if has_pipe:
                    parts = re.split(r"\|", line)
                    role = parts[0].strip()
                    company_raw = parts[1].strip() if len(parts) > 1 else "Tech Company"
                    company = re.sub(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{4}).*", "", company_raw, flags=re.IGNORECASE).strip()
                    location = "Egypt"
                else:
                    role = role_date_match.group(1).strip()
                    company = "Tech Organization"
                    location = "Egypt"
                    if i + 1 < len(lines) and not lines[i + 1].startswith("•") and not lines[i + 1].startswith("-") and not re.search(r"^(Responsibilities|Technologies):", lines[i + 1], flags=re.IGNORECASE):
                        next_line = lines[i + 1]
                        
                        # Check city in next line
                        city_m = re.search(r"\b(Cairo|Giza|Alexandria|Mansoura|Benha|Tanta|Assiut)\b", next_line, flags=re.IGNORECASE)
                        if city_m:
                            location = f"{city_m.group(0).title()}, Egypt"
                            comp_cleaned = re.sub(r"\b(Cairo|Giza|Alexandria|Mansoura|Benha|Tanta|Assiut|Egypt)\b", "", next_line, flags=re.IGNORECASE)
                            company = re.sub(r"^[,\s]+|[,\s]+$", "", comp_cleaned).strip()
                        else:
                            loc_split = re.split(r",|\s{2,}", next_line)
                            company = re.sub(r"^[,\s]+|[,\s]+$", "", loc_split[0]).strip()
                            if len(loc_split) > 1:
                                second_part = loc_split[1].strip()
                                location = second_part if "egypt" in second_part.lower() else f"{second_part}, Egypt"
                        i += 1  # Skip company line

                clean_company = re.sub(r"^[,\s]+|[,\s]+$", "", company or "Organization").strip()
                current_exp = {
                    "company": clean_company or "Organization",
                    "role": role,
                    "location": location,
                    "start_date": "2025",
                    "end_date": "2026",
                    "is_current": False,
                    "responsibilities": [],
                    "technologies": self._extract_inline_technologies(line)
                }
                i += 1
                continue

            if current_exp:
                # Check for Technologies: line
                tech_match = re.match(r"^Technologies:\s*(.*)", line, flags=re.IGNORECASE)
                if tech_match:
                    tech_tokens = [t.strip() for t in tech_match.group(1).split(",") if t.strip()]
                    current_exp["technologies"] = list(set(current_exp["technologies"] + tech_tokens))
                else:
                    clean_bullet = re.sub(r"^[•\-\*]\s*", "", line).strip()
                    current_exp["responsibilities"].append(clean_bullet)
                    current_exp["technologies"] = list(set(current_exp["technologies"] + self._extract_inline_technologies(line)))

            i += 1

        if current_exp:
            exp_items.append(current_exp)

        return exp_items

    def _parse_skills(self, text: str) -> List[Dict[str, str]]:
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
    def _extract_inline_technologies(text: str) -> List[str]:
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
    def _extract_url(text: str) -> Optional[str]:
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
