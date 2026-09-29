# SkillMatch AI Service — Backend Integration API

## 1. Overview

SkillMatch AI Service extracts persisted candidate profiles from CVs, understands job descriptions, produces personalized job feeds, records recommendation interactions, and analyzes a persisted CV against a selected job.

- Base URL: `{AI_SERVICE_BASE_URL}`. Local default: `http://127.0.0.1:8001`.
- API prefix: `/api/v1`.
- JSON endpoints use `application/json`; CV file endpoints use `multipart/form-data`.
- Timestamps in JSON are ISO 8601 strings. All timestamps returned by recommendation APIs are UTC.
- IDs are opaque strings. Laravel must store its own authenticated-user-to-`candidate_id` mapping; a `candidate_id` is not proof of ownership.

### Service authentication

All `/api/v1` routes use the application API-key dependency when `ENABLE_API_KEY_AUTH=true`. Send either `X-API-Key: {key}` or `Authorization: Bearer {key}`. When that flag is disabled, the general API-key check is not enforced.

`POST /api/v1/recommendations/events` is stricter: it always requires the configured service key, even if general API-key authentication is disabled. Do not put real keys in browser code.

### Common error shape

Handled errors use:

```json
{
  "detail": "Human-readable explanation.",
  "error_code": "MACHINE_READABLE_CODE"
}
```

The global unhandled-error response also includes `"error": "INTERNAL_SERVER_ERROR"`. FastAPI validation errors are normalized to `error_code: "VALIDATION_ERROR"`.

## 2. Recommended Integration Flow

1. Laravel receives a user CV and calls CV Extraction. Store the returned `candidate_id` against the authenticated Laravel user.
2. Laravel sends a job description to Job Description Understanding, including a `job_id` only when the structured profile should be persisted against that job record.
3. Laravel resolves its authenticated user's `candidate_id` and requests Personalized Recommendations.
4. After a user action, Laravel authorizes ownership and calls the recommendation interaction endpoint with its service key.
5. For CV Improvement, Laravel sends `candidate_id` with either the selected persisted `job_id` or one external pasted `job_description`.

## 3. CV Profile Extraction

All three endpoints persist the extracted `Candidate`. If `candidate_id` is supplied, it is passed into extraction and is the persisted ID; otherwise the service generates an opaque ID such as `cand_a1b2c3d4`.

### Candidate success object

Direct file and text extraction return this current `Candidate` structure. Arrays default to `[]`; nullable scalar fields may be `null` when not stated in the CV.

```json
{
  "candidate_id": "cand_demo_001",
  "user": {"name": "Example User", "email": "user@example.test"},
  "candidate_profile": {
    "headline": null, "bio": null, "phone": null, "location": null,
    "linkedin_url": null, "github_url": null, "portfolio_url": null
  },
  "educations": [{"institution": null, "degree": null, "field_of_study": null, "start_date": null, "end_date": null, "description": null}],
  "experiences": [{"company_name": null, "job_title": "Engineer", "employment_type": null, "start_date": null, "end_date": null, "is_current": null, "description": null, "technologies": []}],
  "projects": [{"title": "Example project", "description": null, "project_url": null, "github_url": null, "start_date": null, "end_date": null, "project_date": null, "technologies": []}],
  "certificates": [{"name": "Example certificate", "issuing_organization": null, "platform": null, "issue_date": null, "expiration_date": null, "status": null, "credential_url": null}],
  "languages": [{"language": "English", "proficiency": null}],
  "candidate_skills": [{"skill_id": "skill_python", "name": "Python", "proficiency": null, "years_of_experience": null, "confidence": 0.85, "evidence": [{"type": "skills_section", "text": "Python", "source": "cv", "section": null}]}],
  "target_roles": [],
  "preferences": {"employment_type": [], "work_mode": [], "locations": [], "industries": []}
}
```

Date fields preserve source precision as `YYYY`, `YYYY-MM`, or `YYYY-MM-DD`; ambiguous or unsupported dates are `null`. Candidate skill IDs are shared Skill Registry identities when resolved, otherwise `null`.

### `POST /api/v1/cv/extract-file`

Purpose: direct file extraction. It runs on a worker thread but responds only after extraction completes.

- Authentication: general API key only when enabled.
- Content type: `multipart/form-data`.
- Form fields: `file` (required upload) and `candidate_id` (optional string).
- Supported extensions: `.pdf`, `.docx`, `.txt`, `.md`; legacy `.doc` is rejected.
- Maximum upload size: 10 MiB. Empty files are rejected.
- Success: `200 OK`, `Candidate` above. Header `X-CV-Extraction-Mode` reports the extraction mode.

```bash
curl -X POST "$AI_SERVICE_BASE_URL/api/v1/cv/extract-file" \
  -H "X-API-Key: $AI_SERVICE_KEY" \
  -F "candidate_id=cand_demo_001" \
  -F "file=@resume.pdf"
```

Errors: `400 NO_FILENAME`, `UNSUPPORTED_FILE_TYPE`, `EMPTY_FILE`, or `EXTRACTION_FAILED`; `413 FILE_TOO_LARGE`; `422 VALIDATION_ERROR`; `503` with the extractor's public error code; and `500 INTERNAL_SERVER_ERROR`.

### `POST /api/v1/cv/extract-file-async`

Purpose: queue a file extraction and return a pollable in-memory job.

- Authentication, content type, file rules, optional `candidate_id`, extensions, and 10 MiB limit are identical to direct file extraction.
- Success: `202 Accepted`:

```json
{"job_id":"job_cv_abc123def456","status":"queued","result":null,"error":null,"error_code":null}
```

The job state is one of `queued`, `processing`, `completed`, or `failed`. The job store is process-memory only; Laravel should poll promptly and must not treat it as durable workflow storage.

### `GET /api/v1/cv/jobs/{job_id}`

Purpose: poll an async extraction job.

- Path parameter: `job_id` (required).
- Success: `200 OK` with `{job_id, status, result, error, error_code}`. `result` is the full `Candidate` only for a completed job; failures populate `error` and `error_code`.
- `404 JOB_NOT_FOUND` means that job ID is absent from the in-memory store.

### `POST /api/v1/cv/extract-text`

Purpose: extract and persist directly from raw CV text.

- Authentication: general API key only when enabled.
- Content type: `application/json`.
- Body: `{"text":"...", "candidate_id":"cand_demo_001"}`. `text` is required; `candidate_id` is optional.
- Success: `200 OK` with the full `Candidate` and `X-CV-Extraction-Mode` header.
- Errors: `400 EMPTY_PAYLOAD` or `EXTRACTION_FAILED`; extractor `503`; `500 INTERNAL_SERVER_ERROR`; standard `422` for malformed JSON/body.

Backend note: CV content is sensitive. Laravel should obtain user consent, protect the returned profile, and record the returned candidate ID only after a successful response.

## 4. Job Description Understanding

### `POST /api/v1/jobs/analyze`

Purpose: convert a raw job description into a normalized requirement profile.

- Authentication: general API key only when enabled.
- Content type: `application/json`.
- Body fields:
  - `job_description` — required string, 50–20,000 characters.
  - `job_id` — optional string. If present, the service attempts to upsert the extracted profile under this ID.

```json
{
  "job_description": "We need a Senior Backend Engineer with Python and FastAPI experience...",
  "job_id": "job_laravel_123"
}
```

Success is `200 OK`:

```json
{
  "job_id": "job_laravel_123",
  "profile": {
    "role_family": "Engineering",
    "seniority": "Senior",
    "canonical_role": "Backend Engineer",
    "required_skills": [{
      "skill_id": "skill_python",
      "canonical_name": "Python",
      "category": "Programming Languages",
      "raw_extracted": "Python",
      "importance": "critical",
      "required_level": null
    }],
    "preferred_skills": [],
    "responsibilities": ["Build backend services"],
    "min_years_experience": 5,
    "max_years_experience": null,
    "constraints": [],
    "extraction_confidence": 0.75
  },
  "persisted": true
}
```

`role_family`, `seniority`, and `canonical_role` are nullable. Skill `skill_id`, `category`, and `required_level` are nullable. `importance` is exactly `critical`, `important`, or `nice_to_have`; `required_level` is `beginner`, `intermediate`, `advanced`, `expert`, or `null`. Experience bounds are integer years or `null`.

`persisted` is true only when a supplied `job_id` was successfully upserted. It is false when no `job_id` was supplied, the record is unavailable, or persistence fails; persistence failure is logged but does not turn a successful extraction into an error. The response echoes the submitted `job_id` (or `null`).

Errors: `400 JOB_EXTRACTION_FAILED`, `422 VALIDATION_ERROR`, and `500 INTERNAL_SERVER_ERROR`.

## 5. Personalized Job Recommendations

### 5.1 Recommendation Feed

#### `GET /api/v1/recommendations/feed`

Purpose: return an ordered, deterministic recommendation feed for an existing candidate.

- Authentication: general API key only when enabled.
- Query parameters:
  - `candidate_id` — required, non-empty string.
  - `page` — optional integer, default `1`, minimum `1`.
  - `limit` — optional integer, default `20`, range `1`–`50`.
  - `work_mode` — optional string filter.
  - `location` — optional location-substring filter.
  - `min_score` — optional number, default `0`, range `0`–`100`.
- `404 NOT_FOUND` if the candidate does not exist.

```text
GET /api/v1/recommendations/feed?candidate_id=cand_demo_001&page=1&limit=20&work_mode=remote&min_score=60
```

Success is `200 OK`:

```json
{
  "candidate_id": "cand_demo_001",
  "total_results": 1,
  "page": 1,
  "limit": 20,
  "has_more": false,
  "generated_at": "2026-09-29T12:00:00Z",
  "recommendations": [{
    "job_id": "jooble:example",
    "rank": 1,
    "score": 82.5,
    "reasons": ["Strong required-skill match"],
    "title": "Backend Engineer",
    "company": null,
    "location": null,
    "work_mode": "remote",
    "employment_type": "full_time",
    "experience_level": "Senior",
    "posted_at": null,
    "qualification_status": "Qualified",
    "score_breakdown": {"match_score": 85, "role_relevance_score": 80, "preference_fit_score": 90, "freshness_score": 75, "behavior_boost": 50},
    "explanation": {"headline": "Strong match", "reasons": [{"code": "SKILL_MATCH_HIGH", "category": "skills", "text": "Matched required skills", "weight": "primary"}], "matched_skills": ["Python"], "missing_skills": []},
    "is_saved": false,
    "is_applied": false
  }]
}
```

Reason categories are `skills`, `role`, `experience`, `preference`, `freshness`, or `behavior`; reason weights are `primary`, `secondary`, or `supporting`. Scores are 0–100. A valid response may have `total_results: 0` and `recommendations: []`; that is a successful empty feed, not an error. `candidate_id` is required; the service supplies no fallback identity.

### 5.2 Recommendation Interaction Events

#### `POST /api/v1/recommendations/events`

Purpose: persist a behavior event used for recommendation personalization.

- Authentication: **required trusted service-to-service key** (`X-API-Key` or Bearer key). This is enforced even when general API-key auth is disabled.
- Content type: `application/json`.
- Body:

```json
{"candidate_id":"cand_demo_001","job_id":"jooble:example","event_type":"save","metadata":{"surface":"recommendation_feed"}}
```

`candidate_id`, `job_id`, and `event_type` are non-empty strings. Canonical event types are `view`, `click`, `save`, `unsave`, `apply`, `dismiss`, and `undismiss`; accepted aliases are normalized (for example, `clicked` → `click`, `bookmark` → `save`, and `hide` → `dismiss`). `metadata` is an optional JSON object.

Success is `201 Created`:

```json
{"success":true,"candidate_id":"cand_demo_001","job_id":"jooble:example","event_type":"save","recorded_at":"2026-09-29T12:00:00Z","message":"Interaction 'save' recorded successfully."}
```

The service validates candidate and job existence at the write boundary and persists the event. Laravel must authenticate the end user and verify the user's ownership/authorization for `candidate_id` before calling this endpoint. The AI service does not implement user ownership checks.

Current state and later-feed semantics:

- `view` and `click` are appended on every call and add the job to view history without duplicates. They do not hide the job, change the current behavior score, or expose a separate public feed-state field.
- `save` is idempotent while saved, clears a previous dismissal, makes the later feed item's `is_saved` field true, and gives that same job the current saved-job behavior score of 100 (instead of the neutral 50).
- `unsave` clears the saved state; it does not hide the job.
- `apply` is idempotent while applied, clears a previous dismissal, and removes the job from later recommendation-feed visibility.
- `dismiss` is idempotent while dismissed, clears saved state, and removes the job from later recommendation-feed visibility. An already-applied job cannot become dismissed.
- `undismiss` restores visibility for a dismissed job unless another filter excludes it.

Errors: `400` for an unsupported event type; `404 NOT_FOUND` for missing candidate/job; `422 VALIDATION_ERROR`; `503 SERVICE_AUTH_NOT_CONFIGURED` when no service key is configured; and `401 UNAUTHORIZED` for missing/invalid service key.

## 6. CV Improvement Assistant

### `POST /api/v1/cv-improvement/analyze`

Purpose: compare a persisted candidate profile with exactly one target job and return evidence-grounded gaps and safe improvement suggestions.

- Authentication: general API key only when enabled. Laravel remains responsible for end-user ownership authorization.
- Content type: `application/json`.
- Required: `candidate_id`, non-empty after trimming.
- Exactly one target is required:

Persisted Job Feed target:

```json
{"candidate_id":"cand_demo_001","job_id":"jooble:example"}
```

External pasted description target:

```json
{"candidate_id":"cand_demo_001","job_description":"A job description containing at least fifty characters of text..."}
```

Supplying both target fields or neither is `422 VALIDATION_ERROR`. External descriptions are trimmed and require at least 50 characters. A `job_id` target reuses the existing persisted job and its structured profile where present. A `job_description` target goes through the existing job extraction pipeline but is **ephemeral**: it is not persisted.

Success is `200 OK` with this public shape:

```json
{
  "candidate_id": "cand_demo_001",
  "target_job": {"source":"persisted_job","job_id":"jooble:example","title":"Backend Engineer","company":null,"provider":"jooble","source_url":null,"canonical_role":"Backend Engineer","role_family":"Engineering","seniority":"Senior"},
  "gap_analysis": {
    "experience_alignment": {"minimum_years":5,"maximum_years":null,"known_years":null,"date_coverage":"partial","status":"unknown"},
    "role_alignment": {"target_role":"Backend Engineer","status":"unknown"},
    "responsibility_alignment": [{"responsibility":"Build services","status":"unknown"}]
  },
  "grounded_strengths": [{"skill_id":"skill_python","canonical_name":"Python","evidence_strength":"contextual","evidence":[{"source_type":"experience","source_index":0,"source_field":"description","text":"Built Python services."}]}],
  "missing_required_skills": [{"skill_id":null,"canonical_name":"FastAPI","category":null,"requirement_type":"required","evidence_strength":"unknown"}],
  "missing_preferred_skills": [],
  "improvement_suggestions": [{"suggestion_type":"missing_requirement","priority":"high","target_section":"skills","evidence":[],"current_text":null,"suggested_text":null,"reason":"Not evidenced in the CV.","related_job_requirement":"FastAPI","grounding_status":"gap"}],
  "safe_rewrites": [],
  "limitations": ["The AI service does not independently verify candidate ownership; upstream callers must authorize access."]
}
```

`target_job.source` is `persisted_job` or `external_description`; all other target reference fields can be null. Gap skills retain `skill_id`, `canonical_name`, `category`, `requirement_type` (`required` or `preferred`), and `evidence_strength`. Citations carry the exact candidate-provided `source_type`, optional `source_index`, optional `source_field`, and `text`.

Suggestion priority is `high`, `medium`, or `low`; grounding status is `grounded`, `gap`, or `unknown`. `safe_rewrites` is the subset of `improvement_suggestions` with non-null `suggested_text`. Internal evidence/catalog IDs, prompt text, and retry telemetry are not public fields.

A missing job skill is a gap, not a claim that the candidate owns that skill. The service does not invent skills, experience, or metrics.

Errors: `404 CANDIDATE_NOT_FOUND` or `JOB_NOT_FOUND`; `400 JOB_EXTRACTION_FAILED` for an external target extraction failure; `400 CV_IMPROVEMENT_FAILED` for generation failure; and `422 VALIDATION_ERROR` for body/XOR/length validation.

## 7. Common Error Handling

| Status | Current code / error code | Meaning | Laravel action |
|---|---|---|---|
| 400 | `NO_FILENAME`, `UNSUPPORTED_FILE_TYPE`, `EMPTY_FILE`, `EMPTY_PAYLOAD`, `EXTRACTION_FAILED`, `JOB_EXTRACTION_FAILED`, `CV_IMPROVEMENT_FAILED`, or unsupported interaction text | Request or feature processing failure | Show actionable input error; retry only transient provider cases. |
| 401 | `UNAUTHORIZED` | General API key is invalid/missing when enabled, or interaction service key is invalid/missing | Fix server-to-server credentials; do not retry from the browser. |
| 404 | `NOT_FOUND`, `JOB_NOT_FOUND`, `CANDIDATE_NOT_FOUND` | Referenced candidate, job, or async CV job is absent | Refresh Laravel mapping/selection and show not-found state. |
| 413 | `FILE_TOO_LARGE` | Upload exceeds 10 MiB | Require a smaller file. |
| 422 | `VALIDATION_ERROR` | Pydantic/body/query validation failed | Correct fields, bounds, or CV Improvement XOR constraint. |
| 429 | `RATE_LIMIT_EXCEEDED` | Rate limiter rejected request | Respect `Retry-After` where supplied. |
| 500 | `INTERNAL_SERVER_ERROR` | Unexpected server failure | Log correlation context; retry only under Laravel policy. |
| 503 | extractor-specific code or `SERVICE_AUTH_NOT_CONFIGURED` | Extraction dependency unavailable, or interaction key absent | Alert operations; do not expose internals to users. |

## 8. Backend vs AI Responsibility Matrix

| Concern | Laravel Backend | AI Service |
|---|---|---|
| User login/authentication | Owns | Does not implement end-user identity |
| User → candidate ownership mapping | Owns and enforces | Receives opaque candidate IDs |
| Service-to-service API auth | Stores/sends server key | Validates configured API/service key |
| CV extraction | Sends CV with consent | Extracts normalized Candidate |
| Candidate AI profile persistence | Maps ID to user | Persists extracted Candidate |
| Job extraction | Sends JD/job ID | Extracts and optionally persists profile |
| Job ingestion | Owns external product workflow | Consumes persisted jobs for feed/target resolution |
| Recommendation matching/ranking | Displays results | Computes deterministic feed |
| Recommendation interaction authorization | Verifies user owns candidate | Requires trusted service caller, persists event |
| Interaction persistence | Initiates authorized event | Persists behavior history |
| CV improvement | Selects authorized candidate/job | Produces grounded analysis and safe rewrites |
| Redis recommendation cache | No direct dependency | Optimization; correctness degrades gracefully if unavailable |
| User-facing error handling | Maps service errors to UI | Returns normalized API errors |

## 9. End-to-End Integration Examples

**A — CV onboarding:** user uploads CV → Laravel calls `/cv/extract-file` → AI returns and persists Candidate → Laravel stores returned `candidate_id` against authenticated user.

**B — Analyze job:** Laravel sends JD to `/jobs/analyze`; include a job ID when the analysis should be persisted against that existing job.

**C — Recommendations:** Laravel resolves the authenticated user's candidate ID → calls `/recommendations/feed` → displays results, including a valid empty feed.

**D — Interaction:** user saves/clicks/applies/dismisses → Laravel authenticates and authorizes the user → Laravel posts the event with a service key.

**E — Improve CV from Job Feed:** user selects a recommended job → Laravel posts `{candidate_id, job_id}` to `/cv-improvement/analyze` → displays grounded gaps and safe rewrites.

**F — Improve CV from external JD:** user pastes JD → Laravel posts `{candidate_id, job_description}` → AI extracts an ephemeral target → displays improvement analysis; no job is persisted by this flow.

## 10. Current Integration Limitations

- Laravel ownership integration is not implemented in this service; Laravel must authorize every candidate-bound operation.
- A service API key must be configured before recommendation interaction writes are available.
- The async CV job store is in-memory and not durable across process restarts.
- External CV Improvement job descriptions are ephemeral.
- Redis caching is an availability/performance optimization, not a correctness prerequisite for recommendations.
- Production database migrations, deployment configuration, and Laravel-side user mapping remain environment/integration work.

## Source of Truth and Generated Contract

`docs/openapi.json` is generated directly from the current FastAPI application via `app.openapi()`. Use it for generated clients and exact schema constraints; this document is the scoped Laravel handoff for the four AI features above.
