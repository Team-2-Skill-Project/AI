# SkillMatch AI Services — API Reference Documentation

This document provides complete technical specifications for all API endpoints exposed by the **SkillMatch AI Services (AI-Serv5)** platform, including request headers, query parameters, input JSON schemas/payloads, and output JSON schemas/payloads.

A machine-readable JSON version of this document is available at [`docs/api_documentation.json`](api_documentation.json).

---

## Table of Contents
1. [General Information & Security](#1-general-information--security)
2. [Global Error Format](#2-global-error-format)
3. [System Health & Root Endpoints](#3-system-health--root-endpoints)
4. [CV Profile Extraction Endpoints](#4-cv-profile-extraction-endpoints)
5. [Job Description Understanding Endpoints](#5-job-description-understanding-endpoints)
6. [Interview Preparation Coach Endpoints](#6-interview-preparation-coach-endpoints)
7. [Skill Gap Analysis & Explainable Match Endpoints](#7-skill-gap-analysis--explainable-match-endpoints)
8. [Personalized Job Recommendation Endpoints](#8-personalized-job-recommendation-endpoints)
9. [Shared Review Queue Endpoints](#9-shared-review-queue-endpoints)
10. [Dynamic Career Roadmap Endpoints](#10-dynamic-career-roadmap-endpoints)

---

## 1. General Information & Security

* **Base URL**: `http://localhost:8000`
* **API Prefix**: `/api/v1` (for feature routers)
* **Authentication**: All protected endpoints require the API Key passed via header:
  ```http
  X-API-Key: <YOUR_API_KEY>
  ```
* **Rate Limiting**: Applied centrally via middleware to protect backend resources.

---

## 2. Global Error Format

All error responses (400 Bad Request, 401 Unauthorized, 413 File Too Large, 422 Validation Error, 429 Rate Limit Exceeded, 500 Internal Server Error) return a consistent JSON payload format:

```json
{
  "detail": "Detailed message describing the error condition",
  "error_code": "ERROR_CODE_IDENTIFIER"
}
```

Common `error_code` values:
* `UNAUTHORIZED` / `INVALID_API_KEY`
* `NO_FILENAME` / `UNSUPPORTED_FILE_TYPE` / `EMPTY_FILE` / `FILE_TOO_LARGE`
* `EXTRACTION_FAILED` / `JOB_EXTRACTION_FAILED` / `PIPELINE_FAILURE`
* `VALIDATION_ERROR` / `JOB_NOT_FOUND` / `RATE_LIMIT_EXCEEDED` / `INTERNAL_SERVER_ERROR`

---

## 3. System Health & Root Endpoints

### 3.1 `GET /health`
* **Summary**: Health Check
* **Tag**: `System Health`
* **Description**: Returns system operating status, active LLM model, Redis connection health, and status of enabled features.

#### Response Example (`200 OK`):
```json
{
  "status": "healthy",
  "service": "SkillMatch AI Services",
  "version": "1.0.0",
  "environment": "development",
  "active_model": "configured-model",
  "redis": {
    "status": "connected",
    "url": "redis://localhost:6379/0"
  },
  "features": {
    "cv_profile_extraction": "active",
    "skill_gap_analysis": "active",
    "interview_coach": "active",
    "review_queue": "active",
    "job_description_understanding": "active"
  }
}
```

---

## 4. CV Profile Extraction Endpoints

### 4.1 `POST /api/v1/cv/extract-file`
* **Summary**: Extract Structured Profile from CV File (Direct Sync)
* **Tag**: `CV Profile Extraction`
* **Content-Type**: `multipart/form-data`
* **Description**: Uploads a digital CV/Resume file (PDF, DOCX, TXT, MD) up to 10MB and synchronously returns a normalized candidate profile.

#### Request Form Data:
| Parameter | Type | Required | Description |
|---|---|---|---|
| `file` | Binary | Yes | File upload stream (`.pdf`, `.docx`, `.txt`, `.md`) |
| `candidate_id` | String | No | Custom candidate ID (e.g. `cand_12345`) |

#### Output Response (`200 OK`):
```json
{
  "candidate_id": "cand_12345",
  "name": "Jane Doe",
  "email": "jane.doe@example.com",
  "phone": "+1-555-0199",
  "summary": "Senior Software Engineer with 6+ years of experience specializing in Python, FastAPI, and Cloud Architecture.",
  "skills": [
    {
      "name": "Python",
      "category": "Languages",
      "proficiency": "Advanced",
      "confidence": 0.95,
      "source_text": "6 years of Python experience building backend services"
    },
    {
      "name": "FastAPI",
      "category": "Frameworks",
      "proficiency": "Advanced",
      "confidence": 0.92,
      "source_text": "Built high-throughput REST APIs using FastAPI"
    }
  ],
  "work_experience": [
    {
      "role": "Senior Backend Engineer",
      "company": "Tech Corp",
      "duration": "2021 - Present",
      "location": "San Francisco, CA",
      "description": "Led backend team building microservices and AI pipelines.",
      "highlights": [
        "Architected async API layer handling 10M daily requests",
        "Implemented Redis caching reducing latency by 40%"
      ]
    }
  ],
  "education": [
    {
      "degree": "B.S. in Computer Science",
      "institution": "University of California",
      "year": "2018"
    }
  ],
  "projects": [
    {
      "name": "AI Matcher Service",
      "description": "Automated CV parsing and job recommendation engine",
      "technologies": ["Python", "FastAPI", "PostgreSQL", "LlamaIndex"]
    }
  ]
}
```

---

### 4.2 `POST /api/v1/cv/extract-file-async`
* **Summary**: Submit CV File for Async Background Extraction
* **Tag**: `CV Profile Extraction`
* **Content-Type**: `multipart/form-data`
* **Description**: Enqueues CV processing as a background job and returns a pollable `job_id`.

#### Request Form Data:
| Parameter | Type | Required | Description |
|---|---|---|---|
| `file` | Binary | Yes | File upload stream |
| `candidate_id` | String | No | Custom candidate ID |

#### Output Response (`202 Accepted`):
```json
{
  "job_id": "job_cv_a1b2c3d4e5f6",
  "status": "queued",
  "result": null,
  "error": null,
  "error_code": null
}
```

---

### 4.3 `GET /api/v1/cv/jobs/{job_id}`
* **Summary**: Poll Background CV Extraction Job Status
* **Tag**: `CV Profile Extraction`
* **Description**: Checks status (`queued`, `processing`, `completed`, `failed`) of an async background CV extraction job.

#### Output Response (`200 OK`):
```json
{
  "job_id": "job_cv_a1b2c3d4e5f6",
  "status": "completed",
  "result": {
    "candidate_id": "cand_12345",
    "name": "Jane Doe",
    "email": "jane.doe@example.com",
    "skills": [
      { "name": "Python", "proficiency": "Advanced" },
      { "name": "FastAPI", "proficiency": "Advanced" }
    ]
  },
  "error": null,
  "error_code": null
}
```

---

### 4.4 `POST /api/v1/cv/extract-text`
* **Summary**: Extract Structured Profile from Raw CV Text
* **Tag**: `CV Profile Extraction`

#### Input JSON Payload:
```json
{
  "text": "Jane Doe\nEmail: jane@example.com\nSenior Python Developer with 5 years experience in FastAPI, PostgreSQL, and Docker.",
  "candidate_id": "cand_12345"
}
```

#### Output Response (`200 OK`):
```json
{
  "candidate_id": "cand_12345",
  "name": "Jane Doe",
  "email": "jane@example.com",
  "skills": [
    { "name": "Python", "proficiency": "Advanced" },
    { "name": "FastAPI", "proficiency": "Intermediate" },
    { "name": "PostgreSQL", "proficiency": "Intermediate" }
  ],
  "work_experience": [],
  "projects": []
}
```

---

## 5. Job Description Understanding Endpoints

### 5.1 `POST /api/v1/jobs/analyze`
* **Summary**: Analyze a Job Description
* **Tag**: `Job Description Understanding`
* **Description**: Extracts normalized skills, role family, seniority, responsibilities, and experience constraints. Optionally upserts the result into the jobs database if `job_id` is passed.

#### Input JSON Payload:
```json
{
  "job_description": "We are seeking a Senior Backend Engineer with 5+ years experience in Python and FastAPI. Strong knowledge of PostgreSQL and Redis required. Experience with Kubernetes is a plus.",
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### Output Response (`200 OK`):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "persisted": true,
  "profile": {
    "role_family": "Engineering",
    "seniority": "Senior",
    "canonical_role": "Backend Engineer",
    "required_skills": [
      {
        "skill_id": "skill_python",
        "canonical_name": "Python",
        "category": "Languages",
        "raw_extracted": "Python",
        "importance": "critical",
        "required_level": "advanced"
      },
      {
        "skill_id": "skill_fastapi",
        "canonical_name": "FastAPI",
        "category": "Frameworks",
        "raw_extracted": "FastAPI",
        "importance": "critical",
        "required_level": "intermediate"
      }
    ],
    "preferred_skills": [
      {
        "skill_id": "skill_k8s",
        "canonical_name": "Kubernetes",
        "category": "DevOps",
        "raw_extracted": "Kubernetes",
        "importance": "nice_to_have",
        "required_level": null
      }
    ],
    "responsibilities": [
      "Build scalable backend services",
      "Maintain relational databases and caches"
    ],
    "min_years_experience": 5,
    "max_years_experience": null,
    "constraints": [],
    "extraction_confidence": 0.95
  }
}
```

---

## 6. Interview Preparation Coach Endpoints

### 6.1 `POST /api/v1/interview/generate`
* **Summary**: Generate Tailored Interview Questions
* **Tag**: `Interview Preparation Coach`

#### Input JSON Payload:
```json
{
  "job_id": "job_9988",
  "target_role": "Senior Backend Engineer",
  "candidate_id": "cand_12345",
  "focus_skills": ["skill_redis", "skill_system_design"],
  "job_summary": "High-load microservice development with Redis caching and asynchronous queues.",
  "include_essay": true
}
```

#### Output Response (`200 OK`):
```json
{
  "job_id": "job_9988",
  "target_role": "Senior Backend Engineer",
  "questions": [
    {
      "question_id": "q_001",
      "skill_id": "skill_redis",
      "type": "technical",
      "question": "How would you handle cache stampede and thundering herd problems in Redis when key TTL expires under high traffic?",
      "context_or_scenario": "High concurrency user session lookup service",
      "key_points_to_cover": [
        "Mutex locking / Probabilistic early expiration",
        "Cache warming techniques",
        "Background worker refreshes"
      ],
      "security_focus_areas": ["Redis Authentication", "TLS in transit"]
    }
  ]
}
```

---

### 6.2 `POST /api/v1/interview/evaluate`
* **Summary**: Evaluate Interview Answer
* **Tag**: `Interview Preparation Coach`

#### Input JSON Payload:
```json
{
  "question_id": "q_001",
  "question_text": "How would you handle cache stampede in Redis?",
  "question_type": "technical",
  "skill_id": "skill_redis",
  "user_answer": "I would use a distributed lock using Redis SETNX with a short expiry so only one request regenerates the cache while others wait or return stale data."
}
```

#### Output Response (`200 OK`):
```json
{
  "question_id": "q_001",
  "score": 9,
  "strengths": [
    "Correctly identified SETNX distributed lock pattern",
    "Included expiry mechanism to prevent infinite lock hold"
  ],
  "improvements": [
    "Could mention XADD / Redlock for multi-node deployments"
  ],
  "ideal_answer_outline": "1. Explain stampede concept\n2. Mutex locking via SETNX/Redlock\n3. Stale-while-revalidate pattern",
  "security_assessment": {
    "has_security_vulnerabilities": false,
    "identified_risks": [],
    "security_score": 9,
    "mitigation_suggestions": ["Ensure lock keys use unique UUID values to prevent unauthorized unlock"]
  },
  "recommended_action": "Proceed to next system design question"
}
```

---

## 7. Skill Gap Analysis & Explainable Match Endpoints

### 7.1 `POST /api/v1/matches/analyze`
*(Aliases: `POST /api/v1/matches/skill-gap`, `POST /api/v1/matches/evaluate-gap`, `POST /api/v1/matches/explain`)*
* **Summary**: Perform Automated Skill Gap & Explainable Match Analysis
* **Tag**: `Skill Gap Analysis & Explainable Match`

#### Input JSON Payload:
```json
{
  "job_id": "job_9988",
  "candidate_id": "cand_12345",
  "job_requirements": {
    "role_title": "Senior Backend Engineer",
    "required_skills": ["Python", "FastAPI", "PostgreSQL", "Docker"]
  },
  "candidate_profile": {
    "candidate_id": "cand_12345",
    "name": "Jane Doe",
    "skills": ["Python", "FastAPI", "SQL"],
    "work_history": [
      {
        "role": "Backend Engineer",
        "company": "DataCorp",
        "duration": "3 years",
        "description": "Developed Python services with PostgreSQL."
      }
    ]
  }
}
```

#### Output Response (`200 OK`):
```json
{
  "job_id": "job_9988",
  "candidate_id": "cand_12345",
  "overall_match_score": 82.5,
  "qualification_status": "Qualified",
  "full_candidate_summary": "Jane is a strong fit with direct experience in Python and FastAPI. Docker is missing from active evidence.",
  "skill_breakdown": [
    {
      "skill_name": "Python",
      "required_proficiency": "Advanced",
      "candidate_proficiency": "Advanced",
      "match_score": 100.0,
      "is_matched": true,
      "skill_feedback": "Strong Python experience demonstrated in 3 years of work history.",
      "evidence_found": "Developed Python services at DataCorp"
    },
    {
      "skill_name": "Docker",
      "required_proficiency": "Intermediate",
      "candidate_proficiency": "Missing",
      "match_score": 0.0,
      "is_matched": false,
      "skill_feedback": "No direct containerization or Docker experience found.",
      "evidence_found": "None"
    }
  ],
  "missing_critical_skills": ["Docker"],
  "weak_skills": [],
  "blockers": [],
  "nice_to_have_gaps": [],
  "priority": "low",
  "rationale": "High overall score above 80 threshold despite missing Docker.",
  "recommended_upskilling_path": [
    "Complete Docker & Containerization fundamentals course",
    "Deploy sample FastAPI app with Docker Compose"
  ]
}
```

---

### 7.2 `GET /api/v1/matches/{job_id}/candidate/{candidate_id}`
* **Summary**: Retrieve Persisted Match Explanation
* **Tag**: `Skill Gap Analysis & Explainable Match`

#### Output Response (`200 OK`):
```json
{
  "id": "match_rec_1001",
  "job_id": "job_9988",
  "candidate_id": "cand_12345",
  "overall_match_score": 82.5,
  "qualification_status": "Qualified",
  "created_at": "2026-09-13T10:00:00Z"
}
```

---

### 7.3 `GET /api/v1/matches/candidate/{candidate_id}`
* **Summary**: List Match Explanations for Candidate
* **Tag**: `Skill Gap Analysis & Explainable Match`
* **Query Parameters**: `skip` (default 0), `limit` (default 50)

#### Output Response (`200 OK`):
```json
[
  {
    "id": "match_rec_1001",
    "job_id": "job_9988",
    "candidate_id": "cand_12345",
    "overall_match_score": 82.5,
    "qualification_status": "Qualified",
    "created_at": "2026-09-13T10:00:00Z"
  }
]
```

---

## 8. Personalized Job Recommendation Endpoints

### 8.1 `GET /api/v1/recommendations/feed`
* **Summary**: Get the deterministic personalized recommendation feed for a candidate.
* **Tag**: `Personalized Job Recommendations`
* **Query Parameters**:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `candidate_id` | string | No | Candidate identifier; defaults to `cand_001` |
| `page` | integer | No | 1-indexed page number; minimum 1 |
| `limit` | integer | No | Results per page; 1 to 50 |
| `work_mode` | string | No | Optional `remote`, `hybrid`, or `onsite` filter |
| `location` | string | No | Optional location substring filter |
| `min_score` | number | No | Final score cutoff from 0 to 100 |

#### Response (`200 OK`):
```json
{
  "candidate_id": "cand_001",
  "total_results": 0,
  "page": 1,
  "limit": 20,
  "has_more": false,
  "generated_at": "2026-09-17T10:00:00Z",
  "recommendations": []
}
```

Only jobs that pass deterministic qualification eligibility are returned. The ranking formula is `0.60 match + 0.15 role + 0.10 preference + 0.10 freshness + 0.05 behavior`; `min_score` is applied after eligibility.

---

## 9. Shared Review Queue Endpoints

### 9.1 `GET /api/v1/review-queue/`
* **Summary**: List Review Queue Items
* **Tag**: `Shared Review Queue`
* **Query Parameters**:
  * `status`: Filter by status (`pending`, `in_review`, `approved`, `rejected`, `escalated`)
  * `item_type`: Filter by item type (`match_analysis`, `interview_evaluation`)
  * `priority`: Filter by priority (`low`, `medium`, `high`, `urgent`)
  * `skip` (int, default 0), `limit` (int, default 50)

#### Output Response (`200 OK`):
```json
{
  "items": [
    {
      "id": "rev_item_001",
      "item_type": "match_analysis",
      "target_id": "job_9988",
      "status": "pending",
      "priority": "medium",
      "flagged_reasons": ["Confidence score below 0.70 threshold"],
      "payload": {
        "candidate_id": "cand_12345",
        "job_id": "job_9988",
        "score": 68.0
      },
      "reviewer_id": null,
      "reviewer_notes": null,
      "resolution": null,
      "created_at": "2026-09-13T09:30:00Z"
    }
  ],
  "total": 1
}
```

---

### 9.2 `GET /api/v1/review-queue/{item_id}`
* **Summary**: Get Single Review Queue Item
* **Tag**: `Shared Review Queue`

#### Output Response (`200 OK`):
```json
{
  "id": "rev_item_001",
  "item_type": "match_analysis",
  "target_id": "job_9988",
  "status": "pending",
  "priority": "medium",
  "flagged_reasons": ["Confidence score below 0.70 threshold"],
  "payload": {
    "candidate_id": "cand_12345",
    "job_id": "job_9988",
    "score": 68.0
  },
  "reviewer_id": null,
  "reviewer_notes": null,
  "resolution": null,
  "created_at": "2026-09-13T09:30:00Z"
}
```

---

### 9.3 `POST /api/v1/review-queue/{item_id}/claim`
* **Summary**: Claim Item for Review
* **Tag**: `Shared Review Queue`

#### Input JSON Payload:
```json
{
  "reviewer_id": "rev_agent_07"
}
```

#### Output Response (`200 OK`):
```json
{
  "id": "rev_item_001",
  "item_type": "match_analysis",
  "target_id": "job_9988",
  "status": "in_review",
  "priority": "medium",
  "reviewer_id": "rev_agent_07",
  "updated_at": "2026-09-13T10:05:00Z"
}
```

---

### 9.4 `POST /api/v1/review-queue/{item_id}/resolve`
* **Summary**: Resolve Review Item
* **Tag**: `Shared Review Queue`

#### Input JSON Payload:
```json
{
  "status": "approved",
  "reviewer_id": "rev_agent_07",
  "reviewer_notes": "Verified candidate Github repository; Docker skills confirmed.",
  "adjusted_score": 85.0,
  "adjusted_qualification_status": "Qualified",
  "resolution_metadata": {
    "synced_to_laravel": true
  }
}
```

#### Output Response (`200 OK`):
```json
{
  "id": "rev_item_001",
  "item_type": "match_analysis",
  "target_id": "job_9988",
  "status": "approved",
  "priority": "medium",
  "reviewer_id": "rev_agent_07",
  "reviewer_notes": "Verified candidate Github repository; Docker skills confirmed.",
  "resolution": {
    "status": "approved",
    "adjusted_score": 85.0,
    "adjusted_qualification_status": "Qualified"
  },
  "reviewed_at": "2026-09-13T10:10:00Z"
}
```

---

## 10. Dynamic Career Roadmap Endpoints

### 10.1 `POST /api/v1/roadmap/generate`
* **Summary**: Generate Dynamic Career Roadmap
* **Tag**: `Dynamic Career Roadmap`
* **Description**: Converts candidate skill gaps and target role metadata into a sequenced, multi-phase learning roadmap with milestones, weekly tasks, and cited gap grounding.

#### Input JSON Payload:
```json
{
  "candidate_id": "cand_12345",
  "target_role": "Senior Backend Engineer",
  "role_family": "Engineering",
  "skill_gaps": ["Docker", "Kubernetes", "Redis"]
}
```

#### Output Response (`200 OK`):
```json
{
  "roadmap_id": "rm_a1b2c3d4e5f6",
  "candidate_id": "cand_12345",
  "target_role": "Senior Backend Engineer",
  "role_family": "Engineering",
  "total_weeks": 6,
  "phases": [
    {
      "phase_id": "phase_1",
      "title": "Phase 1: Docker Skill Acquisition",
      "order": 1,
      "cited_gap": "Docker",
      "rationale": "Sequential priority phase focused on closing critical Docker gap.",
      "milestones": [
        {
          "milestone_id": "m_1_1",
          "title": "Master Fundamentals of Docker",
          "target_week": 1,
          "status": "not_started",
          "tasks": [
            {
              "task_id": "task_1_1_1",
              "title": "Study core documentation for Docker",
              "description": "Understand container isolation and Dockerfile syntax.",
              "estimated_hours": 3.0,
              "status": "not_started",
              "cited_gap": "Docker",
              "resource_links": ["https://docs.docker.com"]
            }
          ]
        }
      ]
    }
  ],
  "created_at": "2026-09-13T12:00:00Z",
  "updated_at": "2026-09-13T12:00:00Z"
}
```

---

### 10.2 `GET /api/v1/roadmap/{candidate_id}`
* **Summary**: Get Active Candidate Roadmap
* **Tag**: `Dynamic Career Roadmap`

#### Output Response (`200 OK`):
```json
{
  "roadmap_id": "rm_a1b2c3d4e5f6",
  "candidate_id": "cand_12345",
  "target_role": "Senior Backend Engineer",
  "role_family": "Engineering",
  "total_weeks": 6,
  "phases": []
}
```

---

### 9.3 `POST /api/v1/roadmap/tasks/{task_id}/complete`
* **Summary**: Update Roadmap Task Progress
* **Tag**: `Dynamic Career Roadmap`

#### Input JSON Payload:
```json
{
  "candidate_id": "cand_12345",
  "task_id": "task_1_1_1",
  "status": "completed"
}
```

#### Output Response (`200 OK`):
```json
{
  "roadmap_id": "rm_a1b2c3d4e5f6",
  "candidate_id": "cand_12345",
  "phases": [
    {
      "phase_id": "phase_1",
      "milestones": [
        {
          "milestone_id": "m_1_1",
          "status": "completed",
          "tasks": [
            {
              "task_id": "task_1_1_1",
              "status": "completed"
            }
          ]
        }
      ]
    }
  ]
}
```

---

### 9.4 `POST /api/v1/roadmap/refresh`
* **Summary**: Refresh Dynamic Roadmap Priorities
* **Tag**: `Dynamic Career Roadmap`

#### Input JSON Payload:
```json
{
  "candidate_id": "cand_12345",
  "new_skill_gaps": ["Kubernetes Security"]
}
```

#### Output Response (`200 OK`):
```json
{
  "roadmap_id": "rm_a1b2c3d4e5f6",
  "candidate_id": "cand_12345",
  "target_role": "Senior Backend Engineer",
  "phases": [
    {
      "phase_id": "phase_1",
      "cited_gap": "Kubernetes Security"
    }
  ]
}
```

