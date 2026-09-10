import argparse
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows terminal
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.cv_extractor.pipeline import CVExtractionPipeline


def main():
    parser = argparse.ArgumentParser(description="SkillMatch AI — CV Profile Extraction CLI")
    parser.add_argument("--file", "-f", required=False, help="Path to CV file (PDF, DOCX, Image, TXT)")
    parser.add_argument("--output", "-o", required=False, help="Output JSON file path")
    args = parser.parse_args()

    # Default to sample CV if no file provided
    if not args.file:
        sample_path = Path(__file__).parent.parent / "tests" / "samples" / "sample_ahmed_hassan_cv.txt"
        file_path = str(sample_path)
        print(f"[INFO] No file specified. Running extraction on default sample CV: {file_path}\n")
    else:
        file_path = args.file

    print("[START] Initializing SkillMatch CV Extraction Pipeline...")
    pipeline = CVExtractionPipeline()

    print(f"[EXTRACT] Processing document: {file_path}")
    candidate = pipeline.extract_from_file(file_path)

    # Format JSON
    candidate_json = candidate.model_dump_json(indent=2)

    print("\n" + "="*70)
    print("EXTRACTED CANDIDATE PROFILE (DAY 1 SCHEMA)")
    print("="*70)
    print(candidate_json)
    print("="*70)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(candidate_json)
        print(f"\n[SAVED] Structured profile saved to: {args.output}")


if __name__ == "__main__":
    main()
