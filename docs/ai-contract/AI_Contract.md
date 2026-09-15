تمام. خلينا نثبت **DAY 1 Contract** كامل بحيث أنتي والـ AI Engineer التانية تشتغلوا عليه من غير ما كل واحدة تبني شكل مختلف.

أنا هديكي هنا **النسخة التي أقترح تعتمدوا عليها كـ baseline للمشروع**. مش لازم تكون نهائية 100%، لكن لازم تتثبت قبل ما كل واحدة تبدأ implementation.

---

# DAY 1 — SkillMatch AI Shared Contract

## 1. Core Entities

عندنا 6 entities أساسية:

```text
Candidate
CandidateSkill
Job
JobSkill
MatchResult
Roadmap
```

والـ AI Mentor والـ Interview والـ CV Assistant كلهم يستهلكوا البيانات دي.

---

# 2. Candidate Schema

ده الشكل الأساسي للمستخدم بعد الـ CV extraction.

```json
{
  "candidate_id": "cand_001",
  "profile": {
    "name": "Ahmed Hassan",
    "email": "ahmed@example.com",
    "location": "Mansoura, Egypt",
    "education": [
      {
        "degree": "BSc Computer Science",
        "field": "Computer Science",
        "institution": "Mansoura University",
        "start_year": 2022,
        "end_year": 2026,
        "status": "current"
      }
    ],
    "target_roles": [
      "Data Analyst",
      "Junior Data Scientist"
    ],
    "preferences": {
      "employment_type": ["internship", "full_time"],
      "work_mode": ["remote", "hybrid"],
      "locations": ["Egypt"],
      "industries": ["Technology", "FinTech"]
    }
  },

  "skills": [
    {
      "skill_id": "skill_python",
      "name": "Python",
      "level": "intermediate",
      "evidence": [
        {
          "type": "project",
          "text": "Built a customer churn prediction model using Python",
          "source": "cv"
        }
      ],
      "confidence": 0.96
    }
  ],

  "experience": [],
  "projects": [],
  "certifications": [],

  "metadata": {
    "cv_file_id": "cv_001",
    "profile_version": 1,
    "last_updated": "2026-09-06"
  }
}
```

---

# 3. Skill Taxonomy

دي **أهم حاجة عندكم**.

لازم كل الـ AI features تستخدم نفس الـ skill IDs.

## Skill object

```json
{
  "skill_id": "skill_python",
  "canonical_name": "Python",
  "category": "Programming Language",
  "aliases": [
    "Python programming",
    "Python 3"
  ],
  "parent_skill_id": null
}
```

مثال:

```json
{
  "skill_id": "skill_sklearn",
  "canonical_name": "Scikit-learn",
  "category": "Machine Learning Library",
  "aliases": [
    "sklearn",
    "scikit learn"
  ]
}
```

---

## Categories المقترحة

ابدؤوا بالـ categories دي:

```text
Programming Languages
Frameworks
Libraries
Databases
Cloud
DevOps
Data Science
Machine Learning
Deep Learning
Data Visualization
Business Intelligence
Web Development
Mobile Development
Testing
Security
Project Management
Soft Skills
Tools
```

---

# 4. Skill Levels

ممنوع كل Feature تستخدم levels مختلفة.

استخدموا:

```text
beginner
intermediate
advanced
expert
```

وفي حالة الـ CV مش موضح المستوى:

```text
unknown
```

---

# 5. Job Schema

أي Job في المنصة لازم يتحول للشكل ده:

```json
{
  "job_id": "job_001",

  "title": "Junior Data Scientist",

  "company": {
    "company_id": "company_001",
    "name": "ABC Technology"
  },

  "role": {
    "canonical_role": "Data Scientist",
    "seniority": "junior"
  },

  "description": {
    "summary": "Work with data and machine learning models...",
    "responsibilities": [
      "Analyze datasets",
      "Build machine learning models",
      "Prepare reports"
    ]
  },

  "requirements": {
    "required_skills": [
      {
        "skill_id": "skill_python",
        "importance": "critical"
      },
      {
        "skill_id": "skill_sql",
        "importance": "critical"
      },
      {
        "skill_id": "skill_ml",
        "importance": "important"
      }
    ],

    "preferred_skills": [
      {
        "skill_id": "skill_powerbi",
        "importance": "nice_to_have"
      }
    ],

    "experience": {
      "min_years": 0,
      "max_years": 2
    },

    "education": [
      "Computer Science",
      "Computer Engineering",
      "Statistics"
    ]
  },

  "location": {
    "country": "Egypt",
    "city": "Cairo",
    "work_mode": "hybrid"
  },

  "employment_type": "full_time",

  "source": {
    "source_id": "source_001",
    "url": "https://example.com/job/001"
  },

  "metadata": {
    "posted_at": "2026-09-01",
    "expires_at": "2026-09-30",
    "status": "active"
  }
}
```

---

# 6. Required vs Preferred

لازم يكون عندكم 3 levels:

```text
critical
important
nice_to_have
```

مثلاً:

```text
Python      → critical
SQL         → critical
Statistics  → important
Power BI    → nice_to_have
```

ودي هتدخل بعد كده في الـ match وskill gap.

---

# 7. Candidate Skill Evidence

دي نقطة مهمة جدًا للـ Explainability.

كل Skill لازم نعرف **ليه النظام اعتبر المستخدم عنده المهارة دي**.

مثلاً:

```json
{
  "skill_id": "skill_python",
  "level": "intermediate",
  "confidence": 0.94,
  "evidence": [
    {
      "source": "cv",
      "section": "projects",
      "text": "Developed a customer churn prediction model using Python and Scikit-learn."
    }
  ]
}
```

يعني لو المستخدم سأل:

> "ليه قلت إني بعرف Python؟"

نقدر نجاوب.

---

# 8. Job Skill Evidence

ونفس المبدأ للوظيفة.

```json
{
  "skill_id": "skill_powerbi",
  "requirement_type": "required",
  "confidence": 0.91,
  "evidence": {
    "text": "Experience with Power BI is required."
  }
}
```

---

# 9. Match Result Schema

ده أهم Contract بين Engineer 1 وEngineer 2.

Engineer 1 تنتج الـ object ده.

```json
{
  "match_id": "match_001",
  "candidate_id": "cand_001",
  "job_id": "job_001",

  "score": 84,

  "matched_skills": [
    {
      "skill_id": "skill_python",
      "candidate_level": "intermediate",
      "required_level": "intermediate",
      "evidence_strength": 0.92
    }
  ],

  "missing_skills": [
    {
      "skill_id": "skill_powerbi",
      "importance": "nice_to_have"
    }
  ],

  "weak_skills": [
    {
      "skill_id": "skill_statistics",
      "reason": "Job requires stronger statistical knowledge"
    }
  ],

  "constraints": [],

  "strengths": [
    "Strong Python background",
    "Relevant machine learning project experience"
  ],

  "gaps": [
    "Power BI",
    "Advanced statistics"
  ],

  "reasons": [
    {
      "type": "strength",
      "text": "You match the role well on Python, SQL and machine learning."
    },
    {
      "type": "gap",
      "text": "Power BI is missing from your profile."
    }
  ],

  "confidence": 0.89
}
```

---

# 10. Match Score

خلوا score من:

```text
0 → 100
```

لكن لازم **score calculation يكون deterministic**.

مثال كبداية:

```text
Required Skills     50%
Preferred Skills    10%
Experience          15%
Responsibilities    15%
Education           5%
Preferences         5%
```

وبعدين تختبروا وتعدلوا الأوزان.

### مهم

الـ LLM **مش هو اللي يقرر إن الشخص 84%**.

الـ scoring engine يحسب:

```text
84
```

وبعدها الـ LLM يشرح النتيجة.

---

# 11. Skill Gap Schema

```json
{
  "candidate_id": "cand_001",
  "job_id": "job_001",

  "skill_gaps": [
    {
      "skill_id": "skill_powerbi",
      "skill_name": "Power BI",
      "status": "missing",
      "priority": "high",
      "impact": 0.87,
      "reason": "Required by multiple target jobs"
    },
    {
      "skill_id": "skill_statistics",
      "skill_name": "Statistics",
      "status": "weak",
      "priority": "medium",
      "impact": 0.61,
      "reason": "Needed for the target role"
    }
  ]
}
```

---

# 12. Recommendation Schema

```json
{
  "candidate_id": "cand_001",

  "recommendations": [
    {
      "job_id": "job_001",
      "rank": 1,
      "score": 94,
      "reasons": [
        "High skill match",
        "Matches preferred location",
        "Matches target role"
      ]
    },
    {
      "job_id": "job_005",
      "rank": 2,
      "score": 89,
      "reasons": [
        "Strong Python and SQL match"
      ]
    }
  ]
}
```

---

# 13. Roadmap Schema

Engineer 2 هتستخدم الـ Skill Gap اللي Engineer 1 بتطلعه.

```json
{
  "roadmap_id": "roadmap_001",
  "candidate_id": "cand_001",
  "target_role": "Data Scientist",

  "phases": [
    {
      "phase_id": "phase_1",
      "title": "Strengthen Statistics",

      "skills": [
        "skill_statistics"
      ],

      "milestones": [
        {
          "milestone_id": "m1",
          "title": "Complete statistics fundamentals",
          "status": "not_started"
        }
      ],

      "tasks": [
        {
          "task_id": "task_1",
          "title": "Study descriptive statistics",
          "type": "learning",
          "status": "not_started"
        },
        {
          "task_id": "task_2",
          "title": "Solve 20 statistics exercises",
          "type": "practice",
          "status": "not_started"
        }
      ]
    }
  ],

  "progress": {
    "percentage": 0
  }
}
```

---

# 14. AI Output Standard

أي AI feature عندكم لازم يرجع:

```text
Result
+
Reason
+
Evidence
+
Confidence
+
Recommended Action
```

مثلاً:

```json
{
  "result": "Power BI is a high-priority skill gap",

  "reason": "The target job lists Power BI as required",

  "evidence": {
    "job": "Power BI is required",
    "candidate": "No Power BI evidence found"
  },

  "confidence": 0.94,

  "recommended_action": "Add Power BI learning and dashboard practice to the roadmap"
}
```

ده يخلي كل AI feature explainable.

---

# 15. Confidence Standard

اتفقوا إن الـ AI يستخدم:

```text
0.00 - 0.49 → Low
0.50 - 0.74 → Medium
0.75 - 0.89 → High
0.90 - 1.00 → Very High
```

ولو confidence قليل في information مهمة:

```text
AI → Flag for review
```

مش يخمن.

---

# 16. AI Mentor Input Contract

الـ Mentor ما ياخدش database كلها.

يأخذ Context structured:

```json
{
  "candidate": {
    "skills": [],
    "target_roles": [],
    "experience": []
  },

  "career_context": {
    "target_role": "Data Scientist",
    "skill_gaps": [],
    "roadmap": {}
  },

  "job_context": {
    "selected_job": {}
  },

  "application_context": {
    "recent_applications": []
  },

  "conversation": {
    "history": []
  }
}
```

وبناءً عليه يرد.

---

# 17. AI Mentor Output

خلي رد الـ Mentor structured قدر الإمكان:

```json
{
  "message": "You should apply now because...",
  "reasoning": [
    "You meet all critical skill requirements",
    "The remaining gap is a preferred skill"
  ],
  "actions": [
    {
      "type": "apply",
      "job_id": "job_001"
    },
    {
      "type": "roadmap_task",
      "task_id": "task_12"
    }
  ]
}
```

كده الـ AI Mentor مش مجرد chat، لكنه يقدر يرتبط بالـ UI actions.

---

# 18. CV Assistant Output

```json
{
  "job_id": "job_001",

  "suggestions": [
    {
      "type": "missing_evidence",
      "section": "projects",
      "message": "Your ML project is relevant but does not mention model evaluation."
    },
    {
      "type": "rewrite",
      "section": "experience",
      "original": "Worked on data analysis.",
      "suggested": "Performed data analysis using Python and Pandas."
    }
  ],

  "warnings": [
    "Do not add Power BI experience without supporting evidence."
  ]
}
```

---

# 19. Interview Coach Output

```json
{
  "job_id": "job_001",

  "questions": [
    {
      "question_id": "q1",
      "type": "technical",
      "skill_id": "skill_sql",
      "question": "Explain how you would find duplicate records in SQL."
    },
    {
      "question_id": "q2",
      "type": "behavioral",
      "question": "Tell me about a data project you worked on."
    }
  ]
}
```

والـ evaluation:

```json
{
  "question_id": "q1",

  "score": 7,

  "strengths": [
    "Correct SQL concept"
  ],

  "improvements": [
    "Explain the use of GROUP BY more clearly"
  ]
}
```

---

# 20. Application Strategy Output

```json
{
  "job_id": "job_001",

  "recommendation": "APPLY_NOW",

  "confidence": 0.91,

  "reasons": [
    "All critical skills are matched",
    "No major experience blocker"
  ],

  "actions": [
    "Apply to the job",
    "Review SQL interview questions"
  ]
}
```

والـ values تكون:

```text
APPLY_NOW
IMPROVE_FIRST
ALTERNATIVE_ROLE
DO_NOT_RECOMMEND
```

---

# 21. Progress Review Output

```json
{
  "candidate_id": "cand_001",

  "roadmap_id": "roadmap_001",

  "progress": {
    "completed_tasks": 8,
    "new_skills": [
      "Power BI"
    ]
  },

  "changes": {
    "resolved_gaps": [
      "Power BI"
    ],
    "new_priorities": [
      "Advanced Statistics"
    ]
  },

  "next_best_action": {
    "type": "learning",
    "target": "Statistics"
  }
}
```

---

# 22. Data Quality Output

بالنسبة للـ Admin:

```json
{
  "issue_id": "issue_001",

  "entity_type": "job",
  "entity_id": "job_123",

  "issue_type": "possible_duplicate",

  "confidence": 0.93,

  "evidence": [
    "Same company",
    "Similar title",
    "87% description similarity"
  ],

  "recommended_action": "REVIEW"
}
```

والـ Admin هو صاحب القرار النهائي.

---

# 23. API Contracts بينكم

ودي أهم حاجة عشان تشتغلوا Parallel.

## Engineer 1 → Engineer 2

لازم توفر:

```text
GET /candidates/{id}/profile
```

يرجع:

```text
Candidate Profile
```

---

```text
GET /jobs/{id}/requirements
```

يرجع:

```text
Job Profile
```

---

```text
GET /matches/{candidate_id}/{job_id}
```

يرجع:

```text
MatchResult
```

---

```text
GET /candidates/{id}/skill-gaps/{job_id}
```

يرجع:

```text
SkillGapResult
```

---

```text
GET /candidates/{id}/recommendations
```

يرجع:

```text
RecommendationResult
```

---

# 24. Engineer 2 → User/Application Layer

```text
POST /roadmaps
```

```text
GET /roadmaps/{candidate_id}
```

```text
POST /mentor/chat
```

```text
POST /cv/review
```

```text
POST /interview/generate
```

```text
POST /interview/evaluate
```

```text
POST /application/advice
```

```text
POST /roadmap/review
```

---

# 25. الـ Shared Skill IDs

ابدؤوا بالـ skills دي كـ seed data عشان تقدروا تعملوا testing من أول يوم:

```text
skill_python
skill_java
skill_cpp
skill_javascript
skill_typescript

skill_sql
skill_postgresql
skill_mysql
skill_mongodb

skill_pandas
skill_numpy
skill_sklearn

skill_machine_learning
skill_deep_learning
skill_statistics

skill_tensorflow
skill_pytorch

skill_powerbi
skill_tableau
skill_excel

skill_git
skill_docker
skill_linux

skill_aws
skill_azure
skill_gcp

skill_fastapi
skill_django
skill_flask
skill_react

skill_html
skill_css

skill_communication
skill_problem_solving
skill_teamwork
```

دي **Seed taxonomy** مش القائمة النهائية. بعد كده تزودوا عليها بناءً على الوظائف الحقيقية اللي المنصة بتجمعها.

---

# 26. مثال كامل تمشوا عليه في Testing

استخدموا candidate تجريبي:

### Candidate

```text
Ahmed Hassan
Computer Science Student

Skills:
Python
SQL
Pandas
Scikit-learn
Machine Learning
Git

Project:
Customer Churn Prediction
```

### Target Role

```text
Junior Data Scientist
```

### Job

```text
Required:
Python
SQL
Machine Learning
Statistics

Preferred:
Power BI
Docker
```

### Expected Match

```text
~80–85%
```

### Expected Gaps

```text
Statistics → High
Power BI → Medium/Low
Docker → Low
```

### Expected Roadmap

```text
Phase 1
Statistics

Phase 2
Power BI

Phase 3
Portfolio Project

Phase 4
Interview Preparation
```

### Mentor

لو المستخدم قال:

> هل أقدم على الوظيفة؟

المفروض الـ AI يقول حاجة منطقية مثل:

> نعم، أنصح بالتقديم لأنك تستوفي معظم المتطلبات الأساسية، بينما Statistics هو أهم gap يجب تطويره بالتوازي.

---

# أهم اتفاق بينكم كـ 2 AI Engineers

احفظوا القاعدة دي:

```text
Engineer 1
───────────
UNDERSTAND + MATCH

Engineer 2
───────────
PLAN + GUIDE + ACT
```

وبالتالي:

```text
CV
 ↓
Candidate Profile
          \
           \
            → Matching → Skill Gaps
           /
Job ------/
               ↓
        Engineer 2 starts
               ↓
          Roadmap
               ↓
        Mentor / CV / Interview
               ↓
         User Actions
               ↓
        Progress Review
               ↓
          Updated Profile
               ↓
          Re-Matching
```

**ده هو الـ shared contract اللي أنصحكم تثبتوه في Git من Day 1** في ملف مثل:

```text
/docs/ai-contract/
    candidate-schema.json
    job-schema.json
    skill-taxonomy.json
    match-schema.json
    skill-gap-schema.json
    roadmap-schema.json
    mentor-schema.json
```
