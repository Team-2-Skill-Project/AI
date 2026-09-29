# SkillMatch AI-Serv API Documentation

Complete API Reference for the unified **SkillMatch** backend service.

- **Base URL:** `http://localhost:8001` (or production host)
- **API Prefix:** `/api/v1`
- **Interactive Swagger UI:** `http://localhost:8001/docs`
- **ReDoc UI:** `http://localhost:8001/redoc`
- **OpenAPI JSON:** `http://localhost:8001/openapi.json`

---

## 1. Authentication & Global Headers

All endpoints under `/api/v1/*` require API key verification (unless disabled in development configuration).

### Request Headers
| Header Name | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `X-API-Key` | String | Yes (when enabled) | API Key configured in server settings (`settings.API_KEY`). |
| `Authorization` | String | Alternative | Bearer token alternative: `Bearer <API_KEY>` |
| `Content-Type` | String | Yes | `application/json` (or `multipart/form-data` for file uploads) |

---

## Table of Endpoints

| Category | Method | Endpoint | Description |
| :--- | :--- | :--- | :--- |
| **System** | `GET` | `/health` | Service health and Redis status |
| **CV Extraction** | `POST` | `/api/v1/cv/extract-file` | Extract profile directly from PDF/DOCX/TXT file |
| | `POST` | `/api/v1/cv/extract-file-async` | Queue CV file extraction as background job |
| | `GET` | `/api/v1/cv/jobs/{job_id}` | Poll background extraction job status |
| | `POST` | `/api/v1/cv/extract-text` | Extract profile directly from raw CV text |
| **Job Understanding** | `POST` | `/api/v1/jobs/analyze` | Parse job description into structured requirements |
| **Matching & Gap Analysis** | `POST` | `/api/v1/matches/analyze` | Run automated skill gap analysis |
| | `POST` | `/api/v1/matches/skill-gap` | Dedicated skill gap analysis |
| | `POST` | `/api/v1/matches/explain` | Generate explainable match report with evidence |
| | `GET` | `/api/v1/matches/{job_id}/candidate/{candidate_id}` | Get stored match record |
| | `GET` | `/api/v1/matches/candidate/{candidate_id}` | List candidate match history |
| **Job Recommendations** | `GET` | `/api/v1/recommendations/feed` | Personalized scored job recommendations feed |
| **Interview Preparation** | `POST` | `/api/v1/interview/generate` | Generate mock interview questions |
| | `POST` | `/api/v1/interview/evaluate` | Evaluate candidate single answer |
| | `POST` | `/api/v1/interview/prep/generate` | Generate track-based MCQ & essay practice set |
| | `POST` | `/api/v1/interview/prep/submit` | Grade practice answers and return structured scores |
| | `GET` | `/api/v1/interview/prep/sessions/{session_id}` | Get past practice session & score details |
| **Career Roadmap** | `POST` | `/api/v1/roadmap/generate` | Generate multi-phase learning roadmap |
| | `GET` | `/api/v1/roadmap/{candidate_id}` | Retrieve candidate active roadmap |
| | `POST` | `/api/v1/roadmap/tasks/{task_id}/complete` | Update task progress & recalculate completion |
| | `POST` | `/api/v1/roadmap/refresh` | Refresh roadmap priorities for new skill gaps |
| **Review Queue** | `GET` | `/api/v1/review-queue/` | List flagged items awaiting human review |
| | `GET` | `/api/v1/review-queue/{item_id}` | Get single review queue item |
| | `POST` | `/api/v1/review-queue/{item_id}/claim` | Claim item by reviewer |
| | `POST` | `/api/v1/review-queue/{item_id}/resolve` | Resolve / approve / reject / escalate item |
| **Application Strategy** | `POST` | `/api/v1/strategy/evaluate` | Readiness assessment: Apply now vs improve |
| | `POST` | `/api/v1/strategy/jobs/{job_id}` | Evaluate strategy for job ID in path |
| **AI Mentor** | `POST` | `/api/v1/mentor/chat/stream` | Multi-agent streaming mentor chat (SSE) |

---

## 2. System Endpoints

### 2.1 Health Check
- **Method:** `GET`
- **Path:** `/health`
- **Auth:** None

#### Response (200 OK)
```json
{
  "status": "healthy",
  "service": "SkillMatch AI Services",
  "version": "1.0.0",
  "environment": "development",
  "redis_connected": true
}
```

---

## 3. CV Profile Extraction (`/api/v1/cv`)

### 3.1 Extract Profile from CV File (Synchronous)
- **Method:** `POST`
- **Path:** `/api/v1/cv/extract-file`
- **Content-Type:** `multipart/form-data`

#### Form Parameters
- `file` (*binary, required*): CV document in `.pdf`, `.docx`, or `.txt` format (Max 10MB).
- `candidate_id` (*string, optional*): Custom ID to assign (e.g. `cand_001`).

#### Response (200 OK)
```json
{
  "candidate_id": "cand_9f82ab12",
  "user": {
    "name": "Sarah Connor",
    "email": "sarah.connor@example.com"
  },
  "candidate_profile": {
    "headline": "Senior Full-Stack Engineer",
    "bio": "Experienced engineer specializing in Python, FastAPI, React, and cloud architectures.",
    "phone": "+1-555-0199",
    "location": "San Francisco, CA",
    "linkedin_url": "https://linkedin.com/in/sarahconnor",
    "github_url": "https://github.com/sarahconnor",
    "portfolio_url": "https://sarahconnor.dev"
  },
  "candidate_skills": [
    {
      "skill_id": "skill_python",
      "name": "Python",
      "proficiency": "advanced",
      "confidence": 0.95,
      "evidence": [
        {
          "section": "Experience",
          "verbatim_snippet": "Architected distributed microservices in Python and FastAPI",
          "confidence_score": 0.95
        }
      ]
    },
    {
      "skill_id": "skill_postgresql",
      "name": "PostgreSQL",
      "proficiency": "intermediate",
      "confidence": 0.90,
      "evidence": [
        {
          "section": "Experience",
          "verbatim_snippet": "Optimized complex SQL queries and PostgreSQL indexes",
          "confidence_score": 0.90
        }
      ]
    }
  ],
  "educations": [
    {
      "institution": "University of California, Berkeley",
      "degree": "B.S. in Computer Science",
      "start_year": 2016,
      "end_year": 2020
    }
  ],
  "experiences": [
    {
      "company": "TechCorp Solutions",
      "role": "Senior Software Engineer",
      "start_date": "2021-03",
      "end_date": "Present",
      "description": "Led backend services for high-throughput messaging engine.",
      "technologies": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"]
    }
  ],
  "projects": [
    {
      "name": "Distributed Task Scheduler",
      "description": "Open source asynchronous job scheduler built with Redis and FastAPI.",
      "technologies": ["Python", "Redis", "Docker"],
      "url": "https://github.com/sarahconnor/task-scheduler"
    }
  ],
  "certificates": [
    {
      "name": "AWS Certified Solutions Architect",
      "issuer": "Amazon Web Services",
      "issue_year": 2022
    }
  ],
  "languages": [
    {
      "language": "English",
      "proficiency": "native"
    }
  ],
  "target_roles": ["Senior Backend Engineer", "Lead Python Developer"],
  "preferences": {
    "preferred_work_mode": "remote",
    "preferred_locations": ["San Francisco, CA", "Remote"],
    "employment_types": ["full_time"]
  }
}
```

---

### 3.2 Extract Profile from CV File (Asynchronous Job)
- **Method:** `POST`
- **Path:** `/api/v1/cv/extract-file-async`
- **Content-Type:** `multipart/form-data`

#### Form Parameters
- `file` (*binary, required*): CV document (`.pdf`, `.docx`, `.txt`).
- `candidate_id` (*string, optional*): Custom ID.

#### Response (202 Accepted)
```json
{
  "job_id": "job_cv_48df2a819c44",
  "status": "queued",
  "result": null,
  "error": null,
  "error_code": null
}
```

---

### 3.3 Poll Background CV Extraction Job
- **Method:** `GET`
- **Path:** `/api/v1/cv/jobs/{job_id}`

#### Response (200 OK)
```json
{
  "job_id": "job_cv_48df2a819c44",
  "status": "completed",
  "result": {
    "candidate_id": "cand_9f82ab12",
    "user": { "name": "Sarah Connor", "email": "sarah.connor@example.com" },
    "candidate_skills": [ ... ],
    "experiences": [ ... ]
  },
  "error": null,
  "error_code": null
}
```

---

### 3.4 Extract Profile from Raw CV Text
- **Method:** `POST`
- **Path:** `/api/v1/cv/extract-text`

#### Request Body
```json
{
  "text": "Sarah Connor\nEmail: sarah.connor@example.com\nSenior Backend Engineer with 6 years of experience in Python, FastAPI, Docker, and PostgreSQL.",
  "candidate_id": "cand_001"
}
```

#### Response (200 OK)
Returns the normalized `Candidate` object (same schema as `/api/v1/cv/extract-file`).

---

## 4. Job Description Understanding (`/api/v1/jobs`)

### 4.1 Analyze Job Description
- **Method:** `POST`
- **Path:** `/api/v1/jobs/analyze`

#### Request Body
```json
{
  "job_description": "We are seeking a Senior Backend Engineer to join our core team. Requirements: 5+ years of experience in Python and FastAPI. Proficient in PostgreSQL, Redis, and Docker. Experience with AWS and Kubernetes is preferred. You will design scalable microservices and optimize database queries.",
  "job_id": "job_9981"
}
```

#### Response (200 OK)
```json
{
  "job_id": "job_9981",
  "persisted": true,
  "profile": {
    "role_family": "Engineering",
    "seniority": "Senior",
    "role_title": "Senior Backend Engineer",
    "canonical_role": "Backend Engineer",
    "required_skills": [
      {
        "skill_id": "skill_python",
        "name": "Python",
        "is_critical": true,
        "expected_proficiency": "advanced",
        "min_years_experience": 5.0
      },
      {
        "skill_id": "skill_fastapi",
        "name": "FastAPI",
        "is_critical": true,
        "expected_proficiency": "intermediate",
        "min_years_experience": 3.0
      },
      {
        "skill_id": "skill_postgresql",
        "name": "PostgreSQL",
        "is_critical": true,
        "expected_proficiency": "intermediate"
      }
    ],
    "preferred_skills": [
      {
        "skill_id": "skill_aws",
        "name": "AWS",
        "is_critical": false,
        "expected_proficiency": "intermediate"
      },
      {
        "skill_id": "skill_kubernetes",
        "name": "Kubernetes",
        "is_critical": false,
        "expected_proficiency": "basic"
      }
    ],
    "responsibilities": [
      "Design scalable microservices",
      "Optimize database queries and data layer architecture"
    ],
    "experience_years_min": 5.0,
    "work_mode": "remote",
    "employment_type": "full_time"
  }
}
```

---

## 5. Skill Gap Analysis & Explainable Match (`/api/v1/matches`)

### 5.1 Skill Gap Analysis
- **Method:** `POST`
- **Path:** `/api/v1/matches/analyze` (or `/api/v1/matches/skill-gap`)

#### Request Body
```json
{
  "job_id": "job_9981",
  "candidate_id": "cand_001",
  "job_title": "Senior Backend Engineer",
  "job_requirements": [
    {
      "skill_id": "skill_python",
      "skill_name": "Python",
      "proficiency": "Advanced",
      "is_critical": true
    },
    {
      "skill_id": "skill_fastapi",
      "skill_name": "FastAPI",
      "proficiency": "Intermediate",
      "is_critical": true
    },
    {
      "skill_id": "skill_kubernetes",
      "skill_name": "Kubernetes",
      "proficiency": "Intermediate",
      "is_critical": false
    }
  ],
  "candidate_profile": {
    "candidate_id": "cand_001",
    "name": "Sarah Connor",
    "skills": [
      { "skill_name": "Python", "proficiency": "Advanced", "years_of_experience": 5.0 },
      { "skill_name": "FastAPI", "proficiency": "Intermediate", "years_of_experience": 3.0 }
    ],
    "work_history": [
      {
        "role": "Backend Developer",
        "company": "Tech Corp",
        "description": "Developed backend APIs in Python and FastAPI"
      }
    ]
  }
}
```

#### Response (200 OK)
```json
{
  "match_id": "match_e71b29a1",
  "job_id": "job_9981",
  "candidate_id": "cand_001",
  "overall_score": 85.5,
  "qualification_status": "Qualified",
  "summary_reasoning": "Candidate demonstrates strong proficiency in core critical requirements (Python, FastAPI). Minor gap in non-critical Kubernetes infrastructure.",
  "matched_skills": [
    {
      "skill_id": "skill_python",
      "skill_name": "Python",
      "candidate_proficiency": "Advanced",
      "required_proficiency": "Advanced",
      "score": 100.0,
      "evidence_snippet": "5 years of experience; Developed backend APIs in Python"
    },
    {
      "skill_id": "skill_fastapi",
      "skill_name": "FastAPI",
      "candidate_proficiency": "Intermediate",
      "required_proficiency": "Intermediate",
      "score": 100.0,
      "evidence_snippet": "Developed backend APIs in FastAPI"
    }
  ],
  "missing_skills": [
    {
      "skill_id": "skill_kubernetes",
      "skill_name": "Kubernetes",
      "is_critical": false,
      "priority": "Medium",
      "recommended_action": "Complete container orchestration tutorial and practical deployment project."
    }
  ],
  "score_breakdown": {
    "critical_skills_score": 100.0,
    "optional_skills_score": 50.0,
    "experience_alignment_score": 90.0,
    "role_fit_score": 95.0
  }
}
```

---

### 5.2 Explainable Job Match
- **Method:** `POST`
- **Path:** `/api/v1/matches/explain`
- Generates and stores the match report with natural language evidence and reasoning.

---

### 5.3 Retrieve Stored Match
- **Method:** `GET`
- **Path:** `/api/v1/matches/{job_id}/candidate/{candidate_id}`

#### Response (200 OK)
```json
{
  "id": "match_e71b29a1",
  "job_id": "job_9981",
  "candidate_id": "cand_001",
  "overall_score": 85.5,
  "qualification_status": "Qualified",
  "reasoning": "Candidate demonstrates strong proficiency...",
  "matched_skills": [ ... ],
  "missing_skills": [ ... ],
  "created_at": "2026-09-29T10:00:00Z"
}
```

---

## 6. Personalized Job Recommendations (`/api/v1/recommendations`)

### 6.1 Get Personalized Recommendation Feed
- **Method:** `GET`
- **Path:** `/api/v1/recommendations/feed`

#### Query Parameters
- `candidate_id` (*string, default: "cand_001"*): Target candidate ID.
- `page` (*int, default: 1*): Page number (1-indexed).
- `limit` (*int, default: 20, max: 50*): Results per page.
- `work_mode` (*string, optional*): Filter by `remote`, `hybrid`, or `onsite`.
- `location` (*string, optional*): Location search string (e.g. `San Francisco`).
- `min_score` (*float, default: 0.0*): Score cutoff threshold (0 to 100).

#### Response (200 OK)
```json
{
  "candidate_id": "cand_001",
  "total_results": 42,
  "page": 1,
  "limit": 20,
  "has_more": true,
  "generated_at": "2026-09-29T10:30:00Z",
  "recommendations": [
    {
      "job_id": "job_9981",
      "rank": 1,
      "score": 92.4,
      "reasons": [
        "Strong match in core skills: Python, FastAPI, PostgreSQL",
        "Aligned with target role: Senior Backend Engineer",
        "Matches remote work preference"
      ],
      "title": "Senior Backend Engineer",
      "company": "Stripe",
      "location": "San Francisco, CA",
      "work_mode": "remote",
      "employment_type": "full_time",
      "experience_level": "Senior",
      "posted_at": "2026-09-28T08:00:00Z",
      "qualification_status": "Qualified",
      "score_breakdown": {
        "match_score": 94.0,
        "role_relevance_score": 96.0,
        "preference_fit_score": 100.0,
        "freshness_score": 90.0,
        "behavior_boost": 50.0
      },
      "explanation": {
        "headline": "Exceptional fit for your Python backend skillset and remote preference.",
        "reasons": [
          {
            "code": "SKILL_MATCH_HIGH",
            "category": "skills",
            "text": "You match 100% of the required core technologies.",
            "weight": "primary"
          },
          {
            "code": "WORK_MODE_MATCH",
            "category": "preference",
            "text": "Matches your remote preference.",
            "weight": "secondary"
          }
        ],
        "matched_skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
        "missing_skills": ["Kubernetes"]
      },
      "is_saved": false,
      "is_applied": false
    }
  ]
}
```

---

## 7. Interview Preparation Coach (`/api/v1/interview`)

### 7.1 Generate Mock Interview Questions
- **Method:** `POST`
- **Path:** `/api/v1/interview/generate`

#### Request Body
```json
{
  "job_id": "job_9981",
  "target_role": "Senior Backend Engineer",
  "candidate_id": "cand_001",
  "focus_skills": ["skill_python", "skill_postgresql", "skill_fastapi"],
  "job_summary": "High-throughput API design and database optimization.",
  "include_essay": true
}
```

#### Response (200 OK)
```json
{
  "job_id": "job_9981",
  "target_role": "Senior Backend Engineer",
  "questions": [
    {
      "question_id": "q_7a8b9c",
      "skill_id": "skill_python",
      "type": "technical",
      "question": "How does the Global Interpreter Lock (GIL) in CPython affect multi-threading vs multi-processing for CPU-bound tasks?",
      "context_or_scenario": "Designing a data processing microservice",
      "key_points_to_cover": [
        "GIL prevents true parallel bytecode execution in threads",
        "Multi-processing bypasses GIL by running separate processes",
        "Asyncio/threads are suitable for I/O-bound tasks"
      ],
      "security_focus_areas": ["Process isolation and memory safety"]
    }
  ]
}
```

---

### 7.2 Evaluate Candidate Answer
- **Method:** `POST`
- **Path:** `/api/v1/interview/evaluate`

#### Request Body
```json
{
  "question_id": "q_7a8b9c",
  "question_text": "How does the Global Interpreter Lock (GIL) in CPython affect multi-threading vs multi-processing?",
  "question_type": "technical",
  "skill_id": "skill_python",
  "user_answer": "The GIL ensures only one thread executes Python bytecode at a time. For CPU-bound tasks, multiprocessing is preferred to utilize multiple cores, while threading is useful for IO-bound work."
}
```

#### Response (200 OK)
```json
{
  "question_id": "q_7a8b9c",
  "score": 9.0,
  "verdict": "strong",
  "feedback": "Clear explanation accurately contrasting CPU-bound vs IO-bound implications with multiprocessing and threading.",
  "covered_points": [
    "Identified single-thread bytecode constraint",
    "Correctly recommended multiprocessing for CPU workloads"
  ],
  "missed_points": [
    "Could mention shared memory vs IPC communication overhead"
  ],
  "security_assessment": {
    "has_security_vulnerabilities": false,
    "identified_risks": [],
    "security_score": 10
  }
}
```

---

### 7.3 Generate MCQ & Essay Practice Set
- **Method:** `POST`
- **Path:** `/api/v1/interview/prep/generate`

#### Request Body
```json
{
  "track": "Backend Engineering",
  "user_id": "cand_001",
  "job_id": "job_9981",
  "skill_gaps": ["Kubernetes", "Redis Caching"],
  "total_questions": 4,
  "include_essay": true
}
```

#### Response (200 OK)
*(Answers and rubrics are masked from the client payload during generation)*
```json
{
  "session_id": "sess_81fc2019",
  "track": "Backend Engineering",
  "questions": [
    {
      "id": "mcq_1",
      "type": "mcq",
      "question": "What is the primary difference between a Kubernetes Deployment and a StatefulSet?",
      "options": [
        { "id": "A", "text": "Deployments manage stateless pods with interchangeable identities." },
        { "id": "B", "text": "StatefulSets cannot use persistent volumes." },
        { "id": "C", "text": "Deployments maintain ordered, unique network identifiers." },
        { "id": "D", "text": "There is no difference." }
      ],
      "difficulty": "medium",
      "skill_tag": "Kubernetes"
    },
    {
      "id": "essay_1",
      "type": "essay",
      "prompt": "Explain how you would design a multi-layer caching strategy using Redis to prevent cache stampede.",
      "difficulty": "hard",
      "skill_tag": "Redis Caching"
    }
  ]
}
```

---

### 7.4 Submit Practice Set & Receive Scoring
- **Method:** `POST`
- **Path:** `/api/v1/interview/prep/submit`

#### Request Body
```json
{
  "session_id": "sess_81fc2019",
  "user_id": "cand_001",
  "answers": [
    {
      "question_id": "mcq_1",
      "type": "mcq",
      "submitted_option_id": "A"
    },
    {
      "question_id": "essay_1",
      "type": "essay",
      "submitted_answer": "To prevent cache stampede, I would use probabilistic early expiration (XFetch algorithm) along with mutex locks (singleflight pattern) when regenerating expired cache keys."
    }
  ]
}
```

#### Response (200 OK)
```json
{
  "session_id": "sess_81fc2019",
  "per_question": [
    {
      "question_id": "mcq_1",
      "is_correct": true,
      "correct_option_id": "A",
      "submitted_option_id": "A",
      "points_earned": 2.0,
      "points_possible": 2.0,
      "feedback": "Correct. Deployments manage interchangeable stateless pods."
    },
    {
      "question_id": "essay_1",
      "score": 3.0,
      "points_possible": 3.0,
      "feedback": "Excellent answer covering both probabilistic expiration and distributed locking.",
      "grading_breakdown": [
        { "criterion": "Cache Stampede Solution", "passed": true, "notes": "Mentioned mutex/locking" },
        { "criterion": "Algorithm Selection", "passed": true, "notes": "Cited XFetch / early expiration" }
      ]
    }
  ],
  "overall_score": {
    "raw_points": 5.0,
    "max_points": 5.0,
    "percentage": 100.0
  },
  "summary_feedback": "Outstanding performance demonstrating deep backend system design and architecture expertise."
}
```

---

### 7.5 Get Stored Practice Session
- **Method:** `GET`
- **Path:** `/api/v1/interview/prep/sessions/{session_id}`

---

## 8. Dynamic Career Roadmap (`/api/v1/roadmap`)

### 8.1 Generate Learning Roadmap
- **Method:** `POST`
- **Path:** `/api/v1/roadmap/generate`

#### Request Body
```json
{
  "candidate_id": "cand_001",
  "target_role": "Senior Cloud Architect",
  "role_family": "Engineering",
  "skill_gaps": ["Kubernetes Orchestration", "Terraform Infrastructure as Code"]
}
```

#### Response (200 OK)
```json
{
  "roadmap_id": "road_91a0b3e",
  "candidate_id": "cand_001",
  "target_role": "Senior Cloud Architect",
  "role_family": "Engineering",
  "total_weeks": 4,
  "generation_source": "llm",
  "phases": [
    {
      "phase_id": "phase_1",
      "title": "Container Orchestration Mastery",
      "order": 1,
      "cited_gap": "Kubernetes Orchestration",
      "rationale": "Establishes core foundation for container lifecycle management.",
      "milestones": [
        {
          "milestone_id": "m_1",
          "title": "Deploy Multi-Container App on K8s",
          "target_week": 1,
          "status": "not_started",
          "tasks": [
            {
              "task_id": "t_101",
              "title": "Configure Pods, Services, and Ingress",
              "description": "Write declarative YAML manifests and deploy on minikube/kind.",
              "estimated_hours": 3.5,
              "status": "not_started",
              "cited_gap": "Kubernetes Orchestration",
              "resource_links": [
                {
                  "type": "documentation",
                  "title": "Kubernetes Official Docs - Ingress",
                  "url": "https://kubernetes.io/docs/concepts/services-networking/ingress/"
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

---

### 8.2 Get Active Candidate Roadmap
- **Method:** `GET`
- **Path:** `/api/v1/roadmap/{candidate_id}`

---

### 8.3 Update Roadmap Task Progress
- **Method:** `POST`
- **Path:** `/api/v1/roadmap/tasks/{task_id}/complete`

#### Request Body
```json
{
  "candidate_id": "cand_001",
  "task_id": "t_101",
  "status": "completed"
}
```

#### Response (200 OK)
Returns the updated `RoadmapSchema` with progress recalculated.

---

### 8.4 Refresh Roadmap Priorities
- **Method:** `POST`
- **Path:** `/api/v1/roadmap/refresh`

#### Request Body
```json
{
  "candidate_id": "cand_001",
  "target_role": "Staff Platform Engineer",
  "new_skill_gaps": ["eBPF", "Service Mesh"]
}
```

---

## 9. Shared Review Queue (`/api/v1/review-queue`)

### 9.1 List Items in Review Queue
- **Method:** `GET`
- **Path:** `/api/v1/review-queue/`

#### Query Parameters
- `status` (*string, optional*): `pending`, `in_review`, `approved`, `rejected`, `escalated`
- `item_type` (*string, optional*): `match_analysis`, `interview_evaluation`, `youtube_resource`
- `priority` (*string, optional*): `low`, `medium`, `high`, `urgent`
- `skip` (*int, default: 0*)
- `limit` (*int, default: 50, max: 100*)

#### Response (200 OK)
```json
{
  "total": 1,
  "items": [
    {
      "id": "rev_3910ab",
      "item_type": "match_analysis",
      "target_id": "cand_001",
      "status": "pending",
      "priority": "high",
      "flagged_reasons": ["Disputed qualification status threshold (score 69.8)"],
      "payload": {
        "job_id": "job_9981",
        "candidate_id": "cand_001",
        "score": 69.8
      },
      "reviewer_id": null,
      "reviewer_notes": null,
      "resolution": null,
      "created_at": "2026-09-29T10:15:00Z"
    }
  ]
}
```

---

### 9.2 Claim Review Item
- **Method:** `POST`
- **Path:** `/api/v1/review-queue/{item_id}/claim`

#### Request Body
```json
{
  "reviewer_id": "recruiter_john"
}
```

---

### 9.3 Resolve Review Item
- **Method:** `POST`
- **Path:** `/api/v1/review-queue/{item_id}/resolve`

#### Request Body
```json
{
  "status": "approved",
  "reviewer_id": "recruiter_john",
  "reviewer_notes": "Reviewed candidate projects manually; verified relevant experience.",
  "adjusted_score": 75.0,
  "adjusted_qualification_status": "Qualified",
  "resolution_metadata": {
    "sync_laravel": true
  }
}
```

---

## 10. Application Strategy Guidance (`/api/v1/strategy`)

### 10.1 Evaluate Application Strategy
- **Method:** `POST`
- **Path:** `/api/v1/strategy/evaluate`

#### Request Body
```json
{
  "user_id": "cand_001",
  "job_id": "job_9981",
  "target_role": "Senior Backend Engineer",
  "user_notes": "I have 4 years of Python experience and want to apply this week."
}
```

#### Response (200 OK)
```json
{
  "candidate_id": "cand_001",
  "job_id": "job_9981",
  "job_title": "Senior Backend Engineer",
  "decision": "apply_while_improving",
  "match_score": 0.85,
  "summary_reasoning": "You have a solid foundation in core Python and API development. Applying while brushing up on container orchestration is recommended.",
  "strengths": [
    "5+ years Python expertise",
    "Production FastAPI experience"
  ],
  "blocker_gaps": [],
  "manageable_gaps": [
    {
      "skill": "Kubernetes",
      "severity": "moderate",
      "rationale": "Preferred in job posting but not a hard barrier for initial screening."
    }
  ],
  "action_plan": [
    {
      "task": "Highlight asynchronous FastAPI projects in top summary of your CV",
      "category": "cv_update",
      "timeframe": "Day 1",
      "impact": "High"
    }
  ],
  "alternative_roles": [
    {
      "role_title": "Mid-Level Backend Engineer",
      "match_score": 0.95,
      "rationale": "100% skill match with immediate interview probability.",
      "transition_effort": "Low"
    }
  ],
  "disclaimer": "This strategy is professional career advice based on available profile and job requirements data, not a guarantee of hiring outcomes."
}
```

---

## 11. AI Career Mentor Chat (`/api/v1/mentor`)

### 11.1 Stream Multi-Agent Mentor Chat (SSE)
- **Method:** `POST`
- **Path:** `/api/v1/mentor/chat/stream`
- **Response Format:** `text/event-stream` (Server-Sent Events)

#### Request Body
```json
{
  "message": "How can I improve my chances for the Senior Backend Engineer role at Stripe?",
  "conversation_id": "conv_991823",
  "user_id": "cand_001",
  "job_id": "job_9981",
  "target_role": "Senior Backend Engineer",
  "user_notes": ["Focused on database optimization and system scalability"]
}
```

#### Stream Event Chunks (SSE)

**Token Event:**
```
data: {"type": "token", "content": "Based "}

data: {"type": "token", "content": "on your strong "}

data: {"type": "token", "content": "Python experience..."}
```

**Suggested Follow-up Prompts Event:**
```
data: {"type": "suggested_prompts", "agent": "mentor", "prompts": ["What system design topics should I study?", "How should I structure my resume for Stripe?", "Can we do a mock interview question on PostgreSQL?"]}
```

**Stream Termination:**
```
data: [DONE]
```

---

## 12. Standard Error Responses

When an error occurs, the API returns a structured JSON payload:

```json
{
  "error": "BAD_REQUEST",
  "error_code": "UNSUPPORTED_FILE_TYPE",
  "detail": "Unsupported file format: '.doc'. Allowed formats are: .docx, .pdf, .txt"
}
```

### Common HTTP Status Codes
| Status Code | Code String | Description |
| :--- | :--- | :--- |
| `400` | `BAD_REQUEST` | Malformed request body, invalid file format, or empty input |
| `401` | `UNAUTHORIZED` | Missing or invalid API key |
| `404` | `NOT_FOUND` | Candidate, Job, Session, or Item not found |
| `413` | `FILE_TOO_LARGE` | Uploaded file exceeds 10MB limit |
| `422` | `VALIDATION_ERROR` | Schema validation error against Pydantic model |
| `429` | `RATE_LIMIT_EXCEEDED` | Request rate limit exceeded |
| `500` | `INTERNAL_SERVER_ERROR` | Unhandled internal server failure |
| `503` | `SERVICE_UNAVAILABLE` | External LLM or processing provider unavailable |
