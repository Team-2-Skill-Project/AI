"""Manual CV Extraction Test Runner.

Runs a CV document through the SkillMatch extraction pipeline and evaluates
the extracted output against the criteria in:
docs/cv-extraction-offline-comparison-checklist.md

Usage:
    # Run source extraction analysis only (offline, no LLM required):
    python scripts/test_manual_cv.py --source-only

    # Run full extraction on a specific CV document:
    python scripts/test_manual_cv.py tests/samples/yousef_hatem_cv.docx

    # Save output to custom path:
    python scripts/test_manual_cv.py tests/samples/yousef_hatem_cv.docx -o my_result.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv

load_dotenv()

from src.core.config import settings
from src.cv_extractor.document_loader import DocumentLoader
from src.cv_extractor.pipeline import CVExtractionPipeline
from src.utils.text_cleaner import TextCleaner


def print_banner(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def check_environment() -> tuple[bool, str]:
    llm_settings = settings.get_llm_settings()
    provider = llm_settings.provider or ""
    model = llm_settings.model_name or ""
    api_key = llm_settings.api_key or ""

    print_banner("1. Environment & Model Configuration")
    print(f"  * LLM Provider : {provider or '[NOT SET]'}")
    print(f"  * LLM Model    : {model or '[NOT SET]'}")
    print(f"  * API Key      : {'[CONFIGURED]' if api_key else '[MISSING]'}")
    print(f"  * Taxonomy File: {settings.taxonomy_path}")

    if not provider or not api_key:
        msg = (
            "LLM provider or API key is not configured in .env.\n"
            "To enable live extraction, set in your .env:\n"
            "  LLM_PROVIDER=groq  # or gemini, openai\n"
            "  LLM_MODEL=llama-3.3-70b-versatile  # or your preferred model\n"
            "  LLM_API_KEY=your_key_here\n"
        )
        return False, msg
    return True, "Configured"


def inspect_source(file_path: Path) -> tuple[str, str, list[str], dict[str, str]]:
    print_banner("2. Source Extraction Analysis")
    loader = DocumentLoader()
    raw_text, doc_format, doc_urls = loader.load_text(str(file_path))

    cleaned_text = TextCleaner.clean_text(raw_text)
    sections = TextCleaner.segment_sections(cleaned_text)

    print(f"  * File Path         : {file_path}")
    print(f"  * Document Format   : {doc_format.upper()}")
    print(f"  * Extracted Length  : {len(raw_text)} chars ({len(cleaned_text)} cleaned)")
    print(f"  * Hyperlinks Found  : {len(doc_urls)}")
    for url in doc_urls:
        print(f"      - {url}")

    print(f"  * Detected Sections : {', '.join(k for k, v in sections.items() if v)}")
    for sec_name, sec_content in sections.items():
        if sec_content:
            first_line = sec_content.strip().split("\n")[0][:80]
            print(f"      [{sec_name}] {len(sec_content)} chars -> '{first_line}...'")

    return raw_text, doc_format, doc_urls, sections


def evaluate_candidate(candidate_dict: dict, doc_urls: list[str]) -> list[tuple[str, bool, str]]:
    """Runs automated checklist audits corresponding to the offline checklist."""
    results: list[tuple[str, bool, str]] = []

    user = candidate_dict.get("user") or {}
    name = user.get("name")
    email = user.get("email")
    phone = user.get("phone")

    # Check 1: Identity & contact
    has_contact = bool(name and (email or phone))
    results.append((
        "Contact Preservation",
        has_contact,
        f"Name: {name or 'N/A'}, Email: {email or 'N/A'}, Phone: {phone or 'N/A'}"
    ))

    # Check 2: Experiences
    experiences = candidate_dict.get("experiences") or []
    results.append((
        "Experience Records",
        len(experiences) > 0,
        f"{len(experiences)} experience record(s) extracted"
    ))

    # Check 3: Projects & URLs
    projects = candidate_dict.get("projects") or []
    has_projects = len(projects) > 0
    project_urls_linked = sum(1 for p in projects if p.get("github_url") or p.get("project_url"))
    results.append((
        "Project Records & Link Association",
        has_projects,
        f"{len(projects)} project(s), {project_urls_linked} URL association(s)"
    ))

    # Check 4: Technologies in projects
    proj_techs = [tech for p in projects for tech in (p.get("technologies") or [])]
    results.append((
        "Project Technologies Completeness",
        len(proj_techs) > 0,
        f"{len(proj_techs)} technology reference(s) across projects"
    ))

    # Check 5: Skills taxonomy & open-world
    skills = candidate_dict.get("candidate_skills") or []
    canonical = [s for s in skills if s.get("skill_id")]
    unknown = [s for s in skills if not s.get("skill_id")]
    results.append((
        "Skills Extraction & Taxonomy",
        len(skills) > 0,
        f"{len(skills)} total skills: {len(canonical)} canonical taxonomy matches, {len(unknown)} open-world (skill_id=null)"
    ))

    # Check 6: Date formats
    date_issues = []
    import re
    date_pattern = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
    for exp in experiences:
        s = exp.get("start_date")
        e = exp.get("end_date")
        if s and not date_pattern.match(s):
            date_issues.append(f"exp start: {s}")
        if e and not date_pattern.match(e):
            date_issues.append(f"exp end: {e}")
    for proj in projects:
        s = proj.get("start_date")
        e = proj.get("end_date")
        if s and not date_pattern.match(s):
            date_issues.append(f"proj start: {s}")
        if e and not date_pattern.match(e):
            date_issues.append(f"proj end: {e}")

    results.append((
        "Date Precision (YYYY, YYYY-MM, or YYYY-MM-DD)",
        len(date_issues) == 0,
        "All dates strictly conform" if not date_issues else f"Non-conforming: {', '.join(date_issues)}"
    ))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run manual CV extraction test and audit against the offline checklist."
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="tests/samples/yousef_hatem_cv.docx",
        help="Path to CV file to test (default: tests/samples/yousef_hatem_cv.docx)",
    )
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Analyze document loading, text cleaning, links, and sections without calling LLM",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="manual_cv_test_output.json",
        help="Path to save candidate JSON output (default: manual_cv_test_output.json)",
    )
    args = parser.parse_args()

    target_path = Path(args.file)
    if not target_path.is_absolute():
        target_path = BASE_DIR / target_path

    if not target_path.exists():
        print(f"Error: CV file not found at '{target_path}'", file=sys.stderr)
        return 1

    # Step 1: Environment check
    llm_ok, llm_msg = check_environment()

    # Step 2: Source inspection
    try:
        raw_text, doc_format, doc_urls, sections = inspect_source(target_path)
    except Exception as exc:
        print(f"\n[FAIL] Document extraction failed: {exc}", file=sys.stderr)
        return 1

    if args.source_only:
        print_banner("Source Inspection Completed (--source-only mode)")
        print("Document parsed cleanly without LLM invocation.")
        return 0

    if not llm_ok:
        print_banner("Manual Test Halted: LLM Not Configured")
        print(llm_msg)
        print("To run offline automated tests without an API key, execute:")
        print("  pytest tests/test_cv_quality_defects.py tests/test_cv_pipeline_regression.py")
        print("\nTo inspect source text & hyperlinks only, run:")
        print(f"  python scripts/test_manual_cv.py \"{target_path}\" --source-only")
        return 2

    # Step 3: Pipeline execution
    print_banner("3. Executing Live CV Extraction Pipeline")
    pipeline = CVExtractionPipeline()
    try:
        candidate, metadata = pipeline.extract_from_file_with_metadata(str(target_path))
    except Exception as exc:
        print(f"\n[FAIL] Pipeline extraction failed: {exc}", file=sys.stderr)
        return 1

    candidate_dict = candidate.model_dump()

    # Step 4: Checklist evaluation
    print_banner("4. Offline Checklist Evaluation")
    eval_results = evaluate_candidate(candidate_dict, doc_urls)
    for title, passed, detail in eval_results:
        status_tag = "[PASS]" if passed else "[WARN]"
        print(f"  {status_tag:6} {title:<40} : {detail}")

    # Step 5: Save output
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(candidate_dict, f, indent=2, ensure_ascii=False)

    print_banner("5. Test Output")
    print(f"  * Saved full Candidate JSON to: {output_path}")
    print(f"  * Extraction mode: {metadata.extraction_mode}")
    print("\nManual verification complete. Compare details with docs/cv-extraction-offline-comparison-checklist.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
