from typing import Optional, List
from pydantic import BaseModel, Field

class QuestionGenerationRequest(BaseModel):
    job_id: str
    target_role: str
    candidate_id: str
    focus_skills: List[str] = Field(
        default=[],
        description="List of skill_ids to target (e.g. ['skill_sql', 'skill_statistics'])"
    )
    job_summary: Optional[str] = Field(
        default=None,
        description="Optional detailed job requirements summary."
    )
    include_essay: bool = Field(
        default=True,
        description="Whether to include architectural/open-ended essay questions."
    )

class AnswerSubmission(BaseModel):
    question_id: str
    question_text: str
    question_type: Optional[str] = Field(
        default="technical",
        description="Type of question: technical, behavioral, system_design, or essay"
    )
    skill_id: Optional[str] = None
    user_answer: str

    # --- Output Schemas ---

class InterviewQuestion(BaseModel):
    question_id:str
    skill_id: Optional[str]= None
    type:str = Field(description="'technical', 'behavioral', or 'system_design'")
    question:str
    context_or_scenario: Optional[str] = None
    key_points_to_cover: List[str] = Field(description="Internal rubric for evaluation")
    security_focus_areas: List[str] = Field(
        default=[],
        description="Specific security concerns (e.g. SQLi, RBAC, Data Encryption) to address."
    )

class QuestionSetResponse(BaseModel):
    job_id: str
    target_role: str
    questions: List[InterviewQuestion]

# Security-specific evaluation breakdown
class SecurityAssessment(BaseModel):
    has_security_vulnerabilities: bool = Field(
        description="True if candidate's answer introduces or overlooks critical security risks."
    )
    identified_risks: List[str] = Field(
        default=[],
        description="List of security risks present in the user's response."
    )
    security_score: int = Field(
        description="Score from 1 to 10 evaluating security posture and awareness."
    )
    mitigation_suggestions: List[str] = Field(
        default=[],
        description="Actions to patch identified vulnerabilities or enhance security."
    )

class AnswerEvaluationResponse(BaseModel):
    question_id:str
    score: int = Field(description="score from 1 to 10")
    strengths : List[str]
    improvements:List[str]
    ideal_answer_outline: str
    security_assessment: Optional[SecurityAssessment] = Field(
        default=None,
        description="Detailed security review for essay, coding, or system design answers."
    )
    recommended_action: Optional[str] = None
