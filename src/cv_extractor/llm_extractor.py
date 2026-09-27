from __future__ import annotations

import json
import logging
import re
import types
from dataclasses import dataclass
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.llm import get_llm, parse_json_response
from src.models import CVExtractionSchema, normalize_backend_date

logger = logging.getLogger(__name__)


def _canonicalize_schema_path(path: str) -> str:
    """Normalize dotted list indices without interpreting field names."""
    return re.sub(r"(?<=\w)\.(\d+)(?=\.|$)", r"[\1]", path)


class ValidationFinding(BaseModel):
    """Internal semantic finding returned by the source-fidelity reviewer."""

    kind: str
    path: str
    reason: str | None = None
    source_evidence: str | None = None
    expected_path: str | None = None

    @field_validator("path", "expected_path", mode="before")
    @classmethod
    def canonicalize_path(cls, value):
        if value is None:
            return None
        return _canonicalize_schema_path(str(value))


@dataclass(frozen=True)
class GuardOutcome:
    validation: "CoverageValidationResult"
    rejected: tuple[tuple[ValidationFinding, str], ...] = ()


class CVExtractionError(Exception):
    """Safe, operational failure raised when a CV cannot be reliably extracted."""

    public_message = "CV extraction is temporarily unavailable. Please try again later."
    error_code = "CV_EXTRACTION_FAILED"


class CVExtractionIncompleteError(CVExtractionError):
    """Legacy offline source-fidelity failure; production extraction does not raise it."""

    public_message = "The CV could not be extracted reliably. Please try again later."


class CoverageValidationResult(BaseModel):
    """Internal, schema-driven source-fidelity assessment of one extraction attempt."""

    complete: bool
    missing_paths: list[str] = Field(default_factory=list)
    unsupported_paths: list[str] = Field(default_factory=list)
    fidelity_paths: list[str] = Field(default_factory=list)
    finding_reasons: dict[str, str] = Field(default_factory=dict)
    findings: list[ValidationFinding] = Field(default_factory=list)

    @staticmethod
    def _canonicalize_path(path: str) -> str:
        """Normalize generic dotted list indices without interpreting the field name."""
        return _canonicalize_schema_path(path)

    @model_validator(mode="after")
    def canonicalize_paths(self) -> CoverageValidationResult:
        self.missing_paths = [self._canonicalize_path(path) for path in self.missing_paths]
        self.unsupported_paths = [self._canonicalize_path(path) for path in self.unsupported_paths]
        self.fidelity_paths = [self._canonicalize_path(path) for path in self.fidelity_paths]
        self.finding_reasons = {
            self._canonicalize_path(path): reason
            for path, reason in self.finding_reasons.items()
        }
        return self


class DeterministicValidationGuard:
    """Enforce schema contracts around semantic LLM validation findings."""

    _SOURCE_DATE_PATTERNS = (
        re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
        re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b"),
        re.compile(r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b"),
        re.compile(r"\b[A-Za-z]+\s+\d{1,2},?\s+\d{4}\b"),
        re.compile(r"\b\d{4}-\d{2}\b"),
        re.compile(r"\b(?:[A-Za-z]+)\s+\d{4}\b"),
        re.compile(r"\b\d{4}\b"),
    )

    @staticmethod
    def _unwrap(annotation: Any) -> Any:
        origin = get_origin(annotation)
        if origin in (Union, types.UnionType):
            non_null = [item for item in get_args(annotation) if item is not type(None)]
            return non_null[0] if len(non_null) == 1 else annotation
        return annotation

    @classmethod
    def _resolve_path(cls, path: str) -> tuple[bool, Any, Any, Any]:
        """Return (exists, final field, final annotation, collection annotation)."""
        current_type: Any = CVExtractionSchema
        final_field = None
        final_annotation = None
        collection_annotation = None

        for segment in _canonicalize_schema_path(path).split("."):
            match = re.fullmatch(r"([A-Za-z_]\w*)(?:\[(\d+)\])?", segment)
            if not match or not hasattr(current_type, "model_fields"):
                return False, None, None, None

            field_name, index = match.group(1), match.group(2)
            field = current_type.model_fields.get(field_name)
            if field is None:
                return False, None, None, None

            final_field = field
            final_annotation = field.annotation
            unwrapped = cls._unwrap(final_annotation)
            if index is not None:
                if get_origin(unwrapped) not in (list, tuple, set):
                    return False, None, None, None
                collection_annotation = unwrapped
                item_types = get_args(unwrapped)
                current_type = cls._unwrap(item_types[0]) if item_types else Any
            else:
                current_type = unwrapped

        return True, final_field, final_annotation, collection_annotation

    @classmethod
    def _value_at_path(cls, extraction: CVExtractionSchema, path: str) -> Any:
        value: Any = extraction.model_dump()
        for segment in _canonicalize_schema_path(path).split("."):
            match = re.fullmatch(r"([A-Za-z_]\w*)(?:\[(\d+)\])?", segment)
            if not match or not isinstance(value, dict):
                return None
            value = value.get(match.group(1))
            if match.group(2) is not None:
                if not isinstance(value, list):
                    return None
                index = int(match.group(2))
                value = value[index] if index < len(value) else None
        return value

    @staticmethod
    def _is_nullable(annotation: Any, field: Any) -> bool:
        origin = get_origin(annotation)
        if origin in (Union, types.UnionType) and type(None) in get_args(annotation):
            return True
        return getattr(field, "default", None) is None

    @staticmethod
    def _is_date_contract(field: Any) -> bool:
        description = getattr(field, "description", "") or ""
        return "YYYY-MM-DD" in description

    @staticmethod
    def _is_grounded(source_evidence: str | None, source_text: str) -> bool:
        if not source_evidence or not source_evidence.strip():
            return False

        def normalize(value: str) -> str:
            return " ".join(value.casefold().split())

        return normalize(source_evidence) in normalize(source_text)

    @classmethod
    def _contains_source_supported_date(cls, text: str) -> bool:
        for pattern in cls._SOURCE_DATE_PATTERNS:
            for match in pattern.finditer(text):
                if normalize_backend_date(match.group(0)) is not None:
                    return True
        return False

    @classmethod
    def _legacy_findings(cls, validation: CoverageValidationResult) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = list(validation.findings)
        known = {(item.kind, item.path) for item in findings}
        for kind, paths in (
            ("missing", validation.missing_paths),
            ("unsupported", validation.unsupported_paths),
            ("fidelity", validation.fidelity_paths),
        ):
            for path in paths:
                canonical = _canonicalize_schema_path(path)
                if (kind, canonical) not in known:
                    findings.append(
                        ValidationFinding(
                            kind=kind,
                            path=canonical,
                            reason=validation.finding_reasons.get(canonical),
                        )
                    )
        return findings

    @classmethod
    def apply(
        cls,
        source_text: str,
        extraction: CVExtractionSchema,
        validation: CoverageValidationResult,
    ) -> GuardOutcome:
        accepted: list[ValidationFinding] = []
        rejected: list[tuple[ValidationFinding, str]] = []
        structured_findings = bool(validation.findings)

        for finding in cls._legacy_findings(validation):
            path = _canonicalize_schema_path(finding.path)
            exists, field, annotation, collection_annotation = cls._resolve_path(path)
            if not exists:
                rejected.append((finding, "schema path does not exist"))
                continue

            if finding.expected_path and not cls._resolve_path(finding.expected_path)[0]:
                rejected.append((finding, "expected schema path does not exist"))
                continue

            if structured_findings and not cls._is_grounded(finding.source_evidence, source_text):
                rejected.append((finding, "structured finding source evidence is not grounded in source"))
                continue

            if finding.kind in {"wrong_field", "misplaced", "wrong_placement"} and not finding.expected_path:
                rejected.append((finding, "wrong-field finding has no valid expected schema path"))
                continue

            value = cls._value_at_path(extraction, path)
            if finding.kind == "missing":
                is_collection = get_origin(cls._unwrap(annotation)) in (list, tuple, set)
                if value not in (None, []) and not is_collection:
                    rejected.append((finding, "extraction already contains a value at this path"))
                    continue
                evidence = finding.source_evidence or source_text
                if value is None and cls._is_date_contract(field) and not cls._contains_source_supported_date(evidence):
                    rejected.append((finding, "date null is valid when source provides no date"))
                    continue
                if value is None and not cls._is_nullable(annotation, field):
                    rejected.append((finding, "null is not valid for this schema field"))
                    continue
                if value in (None, []) and structured_findings and not finding.source_evidence:
                    rejected.append((finding, "missing finding has no grounded source evidence"))
                    continue

            accepted.append(finding)

        accepted_result = CoverageValidationResult(
            complete=not accepted,
            missing_paths=[item.path for item in accepted if item.kind == "missing"],
            unsupported_paths=[item.path for item in accepted if item.kind == "unsupported"],
            fidelity_paths=[item.path for item in accepted if item.kind == "fidelity"],
            finding_reasons={item.path: item.reason for item in accepted if item.reason},
            findings=accepted,
        )
        return GuardOutcome(accepted_result, tuple(rejected))


class ExtractionResult(dict):
    """Request-local extraction result; operational metadata never enters Candidate."""

    def __init__(self, entities: dict[str, Any], extraction_mode: str = "llm"):
        super().__init__(entities)
        self.extraction_mode = extraction_mode

    @property
    def entities(self) -> dict[str, Any]:
        return dict(self)


class LLMExtractor:
    """Extract CV entities through the centralized, environment-configured LLM only."""

    EXTRACTION_SYSTEM_PROMPT = """You extract a structured candidate profile from source CV text.
Use only explicit source evidence. Populate every schema field and repeated record that
the source supports; leave a field null or empty only when the source does not support it.
Preserve explicit values faithfully, do not infer or fabricate facts, and return only JSON
matching the supplied schema.

Preserve source date precision: emit YYYY-MM-DD only when the source explicitly states a day;
emit YYYY-MM for a month/year source date and YYYY for a year-only source date. Never invent a
day, month boundary, or date component. A current-status boolean may still reflect explicit
current/ongoing language (true) or an explicitly ended range (false) even when an end date is null.

Keep each value in its semantically matching schema field. In particular, an employer name
contains only the organization name; do not append workplace location or address when the
schema provides no field for it. Extract explicit preferences into preferences, but never
infer preferences from other CV facts. When a source explicitly associates a proficiency
qualifier with a skill and raw_skills can represent it, preserve that qualifier; otherwise
leave raw_skills proficiency null. For education, field_of_study is the primary major;
place a separately stated minor, thesis, or honor in description only when it adds distinct
information, and do not repeat the same fact in both fields. target_roles represents explicit
desired roles or career tracks; do not infer it from a current or past job_title.

Technology and skill completeness is required, without inference. Before finalizing, perform one
internal coverage sweep without adding inferred facts: scan the
structured Skills lists; every experience description; every project description; and explicit
tools, technologies, methodologies, and professional capabilities in the summary or certificates.
For each explicit reusable language, framework, library, tool, platform, API, database, model,
protocol, standard, methodology, or professional skill, populate the relevant record-level
technologies and raw_skills. Project and experience technologies are not limited to a heading or
labeled list: include explicitly named items in the record description too. Do not use taxonomy as a whitelist
and do not add technologies merely because they are commonly used for a project type.

Skill precision is equally required. Add a raw skill only when the source presents it as a reusable
skill, technology, tool, platform, method, or professional capability. Do not turn candidate-created
components or products, datasets, outputs, artifacts, business results, company names, URLs, section
labels, sentence fragments, or contextual noun phrases into standalone skills. Do not list a
technology mentioned only as a comparison, alternative, or benchmark unless the source also states
the candidate used it. In phrases such as "Adobe Photoshop for ad creatives", include Adobe Photoshop
but not "ad creatives" unless that phrase is independently presented as a skill. Treat qualifiers
after "for", "used to", "applied to", or "supporting" as context unless the qualified phrase is
separately identified as a skill. When a source states Full Name (ACRONYM), use the full name as the
skill and preserve the acronym as its source-declared alternate mention.

For projects, use start_date and end_date only for an explicit date range. A single unlabeled project
date belongs in project_date and must not be assumed to be either a start or an end date. For
certificates, preserve an explicitly stated status. Distinguish a certificate issuer from a learning
or delivery platform: a parenthetical platform is platform, not issuing_organization, unless the
source explicitly identifies it as the issuer."""

    COVERAGE_SYSTEM_PROMPT = """You perform a source-fidelity validation of a structured CV extraction
against the supplied source and extraction schema. Evaluate only information the schema can
represent. Do not invent facts, rewrite the extraction, or require source details that have no
valid schema field.

Report every explicit source-supported omission in missing_paths. Report every value absent
from or contradicted by the source in unsupported_paths. Report materially altered explicit
values, incorrect semantic field placement, and date-precision inflation in fidelity_paths.
A YYYY-MM-DD value is precision inflation unless the source explicitly supplies its day-level
date; a month/year source date must correspond to YYYY-MM and a year-only source date must
correspond to YYYY. An employer-name field
must not contain a workplace location or address when the schema has no experience-location
field. Explicit preferences and skill proficiency qualifiers must be preserved when their
schema fields support them.

Only report a missing path when the source explicitly contains schema-representable information
sufficient to populate that path and the extraction omitted it. A nullable field with no such
source-supported value is correctly null, not missing. A collection with no source-supported
records is correctly empty, not missing. Apply these rules generically to every nullable field
and collection. Use bracket list-index paths consistently, for example records[0].field.
For every reported path, include a concise category reason in finding_reasons without quoting
source text or candidate values. Also return each report as a structured finding with kind,
path, reason, and a short exact source_evidence snippet. Use expected_path only when claiming
that a value belongs in another schema field; that path must exist in the supplied schema.

Mark complete true only when all three path lists and the structured findings list are empty.
Return only JSON matching the supplied validation-result schema."""

    def __init__(self, llm: Any = None):
        # Injection is for tests; production construction always resolves get_llm().
        self.llm = llm

    def _get_active_llm(self) -> Any:
        if self.llm is not None:
            if hasattr(self.llm, "is_available") and not self.llm.is_available():
                raise CVExtractionError("Injected LLM is unavailable")
            return self.llm
        try:
            return get_llm()
        except Exception as exc:
            logger.warning("Centralized LLM initialization failed: %s", type(exc).__name__)
            raise CVExtractionError("Centralized LLM initialization failed") from exc

    @staticmethod
    def _schema_contract(schema: type[BaseModel]) -> str:
        """Use Pydantic's existing schema as the only extraction-field contract."""
        return json.dumps(schema.model_json_schema(), separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _normalise_json_result(result: Any) -> dict[str, Any]:
        if isinstance(result, BaseModel):
            result = result.model_dump()
        elif isinstance(result, str):
            result = parse_json_response(result)
        if not isinstance(result, dict):
            raise ValueError(f"Expected a JSON object, got {type(result).__name__}")
        return result

    def _invoke_json(self, active_llm: Any, prompt: str, system_prompt: str, schema: type[BaseModel]) -> dict[str, Any]:
        """Invoke the one configured LLM with structured output when the runtime supports it."""
        if hasattr(active_llm, "generate_json"):
            return self._normalise_json_result(
                active_llm.generate_json(prompt=prompt, system_prompt=system_prompt)
            )

        messages = [("system", system_prompt), ("user", prompt)]
        if hasattr(active_llm, "with_structured_output"):
            structured_llm = active_llm.with_structured_output(schema)
            return self._normalise_json_result(structured_llm.invoke(messages))

        raise ValueError("The centralized LLM runtime does not support structured output")

    @staticmethod
    def _population_summary(model: CVExtractionSchema) -> tuple[int, dict[str, int]]:
        """Log shape metadata without logging CV contents or candidate values."""
        dumped = model.model_dump()
        collection_sizes = {
            key: len(value)
            for key, value in dumped.items()
            if isinstance(value, list)
        }

        def scalar_count(value: Any) -> int:
            if isinstance(value, dict):
                return sum(scalar_count(item) for item in value.values())
            if isinstance(value, list):
                return sum(scalar_count(item) for item in value)
            return int(value is not None and value != "")

        return scalar_count(dumped), collection_sizes

    def _extract_once(
        self,
        active_llm: Any,
        source_text: str,
        corrective_paths: list[str] | None = None,
        document_urls: list[str] | None = None,
    ) -> CVExtractionSchema:
        schema_contract = self._schema_contract(CVExtractionSchema)
        corrective_instruction = ""
        if corrective_paths is not None:
            corrective_instruction = (
                "\nA prior extraction failed source-fidelity validation. Re-extract the source carefully. "
                "The following schema paths may need attention, but source evidence remains the only truth:\n"
                + json.dumps(corrective_paths, ensure_ascii=False)
            )
        annotation_context = ""
        if document_urls:
            annotation_context = (
                "\n\nDOCUMENT HYPERLINKS (source annotations):\n"
                + json.dumps(document_urls, ensure_ascii=False)
            )
        prompt = (
            "SOURCE CV (normalized, complete):\n"
            f"{source_text}\n\n"
            "EXTRACTION SCHEMA (JSON Schema):\n"
            f"{schema_contract}"
            f"{corrective_instruction}"
            f"{annotation_context}"
        )
        logger.info("CV source chars=%d CV extraction prompt chars=%d", len(source_text), len(prompt))
        try:
            raw_result = self._invoke_json(active_llm, prompt, self.EXTRACTION_SYSTEM_PROMPT, CVExtractionSchema)
            model = CVExtractionSchema.model_validate(raw_result)
        except Exception as exc:
            logger.warning("Centralized LLM extraction failed: %s", type(exc).__name__)
            raise CVExtractionError("Centralized LLM extraction failed") from exc

        scalar_count, collection_sizes = self._population_summary(model)
        logger.info(
            "CV structured extraction populated scalar fields=%d collection sizes=%s",
            scalar_count,
            collection_sizes,
        )
        return model

    def _validate_coverage(
        self,
        active_llm: Any,
        source_text: str,
        extraction: CVExtractionSchema,
    ) -> CoverageValidationResult:
        """Run the optional semantic reviewer for diagnostics/offline evaluation only."""
        schema_contract = self._schema_contract(CVExtractionSchema)
        result_contract = self._schema_contract(CoverageValidationResult)
        prompt = (
            "SOURCE CV (normalized, complete):\n"
            f"{source_text}\n\n"
            "EXTRACTION SCHEMA (JSON Schema):\n"
            f"{schema_contract}\n\n"
            "STRUCTURED EXTRACTION (JSON):\n"
            f"{json.dumps(extraction.model_dump(), separators=(',', ':'), ensure_ascii=False)}\n\n"
            "VALIDATION RESULT SCHEMA (JSON Schema):\n"
            f"{result_contract}"
        )
        logger.info("CV source chars=%d CV coverage prompt chars=%d", len(source_text), len(prompt))
        try:
            raw_result = self._invoke_json(
                active_llm,
                prompt,
                self.COVERAGE_SYSTEM_PROMPT,
                CoverageValidationResult,
            )
            raw_validation = CoverageValidationResult.model_validate(raw_result)
        except Exception as exc:
            logger.warning("Centralized LLM coverage validation failed: %s", type(exc).__name__)
            raise CVExtractionError("Centralized LLM coverage validation failed") from exc

        guarded = DeterministicValidationGuard.apply(source_text, extraction, raw_validation)
        for finding, reason in guarded.rejected:
            logger.warning(
                "CV source-fidelity finding rejected by deterministic guard: path=%s reason=%s",
                finding.path,
                reason,
            )
        validation = guarded.validation

        logger.info(
            "CV source-fidelity validation complete=%s missing_paths=%d unsupported_paths=%d fidelity_paths=%d",
            validation.complete,
            len(validation.missing_paths),
            len(validation.unsupported_paths),
            len(validation.fidelity_paths),
        )
        if not self._is_faithful(validation):
            logger.warning(
                "CV source-fidelity findings complete=%s missing_paths=%s unsupported_paths=%s fidelity_paths=%s finding_reasons=%s",
                validation.complete,
                validation.missing_paths,
                validation.unsupported_paths,
                validation.fidelity_paths,
                validation.finding_reasons,
            )
        return validation

    def extract_entities(
        self,
        full_text: str,
        sections: dict[str, str] | None = None,
        document_urls: list[str] | None = None,
    ) -> ExtractionResult:
        """Extract through the centralized LLM, retrying once only for technical failure."""
        del sections  # Semantic interpretation belongs to the LLM; state is request-local.
        if not full_text or not full_text.strip():
            raise ValueError("CV text cannot be empty")

        active_llm = self._get_active_llm()
        try:
            extraction = self._extract_once(active_llm, full_text, document_urls=document_urls)
        except CVExtractionError as first_error:
            logger.warning(
                "Centralized CV extraction failed; retrying once without semantic coverage validation: %s",
                type(first_error).__name__,
            )
            try:
                extraction = self._extract_once(active_llm, full_text, document_urls=document_urls)
            except CVExtractionError as retry_error:
                logger.error("Centralized CV extraction failed after one retry: %s", type(retry_error).__name__)
                raise retry_error from first_error

        logger.info("Successfully extracted and schema-validated CV entities using centralized LLM service.")
        return ExtractionResult(extraction.model_dump())

    @staticmethod
    def _is_faithful(validation: CoverageValidationResult) -> bool:
        return (
            validation.complete
            and not validation.missing_paths
            and not validation.unsupported_paths
            and not validation.fidelity_paths
            and not validation.findings
        )

    @staticmethod
    def _corrective_paths(validation: CoverageValidationResult) -> list[str]:
        """Return every validator finding once, without interpreting its domain meaning."""
        return list(dict.fromkeys(
            validation.missing_paths
            + validation.unsupported_paths
            + validation.fidelity_paths
            + [finding.path for finding in validation.findings]
        ))
