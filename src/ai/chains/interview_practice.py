from __future__ import annotations
import asyncio
import logging
import uuid
from typing import Optional, List, Dict, Any, Union, cast

from langchain_core.prompts import PromptTemplate
from langchain_core.language_models import BaseChatModel


from src.core.llm import get_llm, truncate_to_token_limit
from src.schemas.interview import (
    MCQOption,
    MCQQuestion,
    EssayQuestion,
    PracticeQuestionSetGenerationResult,
    EssayGradingSchema,
    EssayEvaluationItem,
    MCQEvaluationItem,
    SummaryFeedbackSchema,
)

logger = logging.getLogger(__name__)

PRACTICE_QUESTION_GEN_PROMPT = """
You are an expert technical interviewer and author.
Career Track: {track}
Skill Gaps / Target Competencies: {skill_gaps}
Target Job ID: {job_id}
Total Questions requested: {total_questions}
Include Essay questions: {include_essay}

Generate high-quality practice interview questions:
1. Distribute questions across the provided skill gaps (1-2 questions per gap). If skill_gaps is empty, create track-appropriate questions.
2. Set `skill_tag` to match the relevant skill gap.
3. For MCQ questions:
   - Provide 3-5 options (ids: 'a', 'b', 'c', 'd'), exactly 1 `correct_option_id`, and a short `explanation`.
   - Set difficulty ('easy', 'medium', or 'hard').
4. For Essay questions (if include_essay is True):
   - Provide a technical/architectural scenario prompt.
   - Provide a complete, ideal `reference_answer`.
   - Provide 2-4 distinct `grading_criteria` items (rubric).
   - Set difficulty ('easy', 'medium', or 'hard').
"""

ESSAY_GRADING_PROMPT = """
You are an objective Technical Interview Evaluator.
Evaluate the candidate's essay response strictly against the provided reference answer and grading criteria.
Do not grade on general writing style or length. Focus solely on conceptual accuracy and criteria coverage.

Question Prompt:
{prompt}

Target Skill: {skill_tag}

Reference Answer (Ideal):
{reference_answer}

Grading Criteria (Rubric):
{grading_criteria}

Candidate's Submitted Answer:
{submitted_answer}

Evaluate and return:
- score: Integer between 0 and 100
- criteria_met: List of grading criteria satisfied by candidate
- criteria_missed: List of grading criteria missed or incorrect
- feedback: Constructive, role-relevant feedback based on reference answer and rubric
"""

SUMMARY_FEEDBACK_PROMPT = """
You are an AI Interview Preparation Coach.
Career Track: {track}
Overall Score: {percentage}% ({raw_points}/{max_points} points)
Per-Question Performance Summary:
{performance_summary}

Write a concise 1-paragraph summary (2-4 sentences) highlighting the candidate's demonstrated strengths and the top 1-2 actionable areas to improve.
"""


class PracticeInterviewChains:
    def __init__(self, llm: Optional[BaseChatModel] = None):
        self._custom_llm = llm

    def get_active_llm(self) -> BaseChatModel:
        if self._custom_llm is not None:
            return self._custom_llm
        return get_llm()

    async def generate_practice_questions(
        self,
        track: str,
        skill_gaps: List[str],
        job_id: str,
        total_questions: int = 4,
        include_essay: bool = True,
        timeout_seconds: float = 20.0,
    ) -> List[Union[MCQQuestion, EssayQuestion]]:
        """Generates a balanced set of MCQ and Essay practice questions with structured output and fallback."""
        try:
            return await asyncio.wait_for(
                self._generate_questions_llm(
                    track=track,
                    skill_gaps=skill_gaps,
                    job_id=job_id,
                    total_questions=total_questions,
                    include_essay=include_essay,
                ),
                timeout=timeout_seconds,
            )
        except Exception as exc:
            logger.warning("Practice question generation LLM call failed or timed out: %s. Using curated fallback.", exc)
            return self._generate_fallback_questions(
                track=track,
                skill_gaps=skill_gaps,
                job_id=job_id,
                total_questions=total_questions,
                include_essay=include_essay,
            )

    async def _generate_questions_llm(
        self,
        track: str,
        skill_gaps: List[str],
        job_id: str,
        total_questions: int,
        include_essay: bool,
    ) -> List[Union[MCQQuestion, EssayQuestion]]:
        active_llm = self.get_active_llm()
        prompt = PromptTemplate(
            template=PRACTICE_QUESTION_GEN_PROMPT,
            input_variables=["track", "skill_gaps", "job_id", "total_questions", "include_essay"],
        )
        formatted = prompt.format(
            track=track,
            skill_gaps=", ".join(skill_gaps) if skill_gaps else f"Core {track} competencies",
            job_id=job_id,
            total_questions=str(total_questions),
            include_essay=str(include_essay),
        )

        structured_llm = active_llm.with_structured_output(PracticeQuestionSetGenerationResult)
        raw_result = await structured_llm.ainvoke(formatted)
        if isinstance(raw_result, dict):
            result: PracticeQuestionSetGenerationResult = PracticeQuestionSetGenerationResult.model_validate(raw_result)
        else:
            result = cast(PracticeQuestionSetGenerationResult, raw_result)


        questions: List[Union[MCQQuestion, EssayQuestion]] = []
        for q in result.mcq_questions:
            if not q.id:
                q.id = f"q_{uuid.uuid4().hex[:6]}"
            q.related_job_id = job_id
            questions.append(q)

        for q in result.essay_questions:
            if not q.id:
                q.id = f"q_{uuid.uuid4().hex[:6]}"
            q.related_job_id = job_id
            questions.append(q)

        if not questions:
            return self._generate_fallback_questions(
                track=track,
                skill_gaps=skill_gaps,
                job_id=job_id,
                total_questions=total_questions,
                include_essay=include_essay,
            )

        return questions[:total_questions]

    def _generate_fallback_questions(
        self,
        track: str,
        skill_gaps: List[str],
        job_id: str,
        total_questions: int,
        include_essay: bool,
    ) -> List[Union[MCQQuestion, EssayQuestion]]:
        """Provides deterministic fallback questions covering the requested track and skill gaps."""
        targets = skill_gaps if skill_gaps else [f"{track} Core Principles", f"{track} Problem Solving"]
        questions: List[Union[MCQQuestion, EssayQuestion]] = []

        for idx, skill in enumerate(targets):
            # MCQ fallback for skill
            mcq_id = f"q_fb_mcq_{idx + 1}"
            questions.append(
                MCQQuestion(
                    id=mcq_id,
                    type="mcq",
                    prompt=f"In the context of {track}, which of the following best represents standard best practice for {skill}?",
                    skill_tag=skill,
                    difficulty="medium",
                    related_job_id=job_id,
                    options=[
                        MCQOption(id="a", text=f"Apply modular design and validate inputs for {skill}."),
                        MCQOption(id="b", text=f"Bypass error handling to maximize throughput in {skill}."),
                        MCQOption(id="c", text=f"Hardcode configuration parameters directly in {skill} modules."),
                        MCQOption(id="d", text=f"Disable logging and telemetry during {skill} execution."),
                    ],
                    correct_option_id="a",
                    explanation=f"Applying modular design and validating inputs ensures reliability, security, and maintainability for {skill}.",
                )
            )

            # Essay fallback if requested and space permits
            if include_essay and len(questions) < total_questions:
                essay_id = f"q_fb_ess_{idx + 1}"
                questions.append(
                    EssayQuestion(
                        id=essay_id,
                        type="essay",
                        prompt=f"Explain how you would design and implement a scalable solution for {skill} in a production {track} environment. Discuss key trade-offs.",
                        skill_tag=skill,
                        difficulty="medium",
                        related_job_id=job_id,
                        reference_answer=f"A scalable solution for {skill} involves clear abstraction layers, proper validation, efficient resource utilization, and robust error handling. Key trade-offs include consistency versus latency and operational complexity.",
                        grading_criteria=[
                            f"Identifies architectural principles for {skill}",
                            "Discusses scalability and fault-tolerance trade-offs",
                            "Provides concrete examples of implementation",
                        ],
                    )
                )

            if len(questions) >= total_questions:
                break

        return questions[:total_questions]

    async def grade_essay(
        self,
        question_id: str,
        prompt: str,
        skill_tag: str,
        reference_answer: str,
        grading_criteria: List[str],
        submitted_answer: str,
        timeout_seconds: float = 10.0,
    ) -> EssayEvaluationItem:
        """Grades an open-ended essay answer using structured LLM output with timeout and fallback."""
        # Pre-check: empty, whitespace, or trivial answer
        clean_sub = (submitted_answer or "").strip()
        if len(clean_sub) < 5:
            return EssayEvaluationItem(
                question_id=question_id,
                type="essay",
                score=0,
                points_possible=100,
                criteria_met=[],
                criteria_missed=grading_criteria or [],
                feedback="No substantive answer was submitted for this question.",
            )

        try:
            return await asyncio.wait_for(
                self._grade_essay_llm(
                    question_id=question_id,
                    prompt=prompt,
                    skill_tag=skill_tag,
                    reference_answer=reference_answer,
                    grading_criteria=grading_criteria,
                    submitted_answer=clean_sub,
                ),
                timeout=timeout_seconds,
            )
        except Exception as exc:
            logger.warning("Essay grading failed or timed out for question %s: %s. Using neutral fallback.", question_id, exc)
            return EssayEvaluationItem(
                question_id=question_id,
                type="essay",
                score=None,
                points_possible=100,
                criteria_met=[],
                criteria_missed=[],
                feedback="Grading unavailable due to a service timeout, please retry.",
            )

    async def _grade_essay_llm(
        self,
        question_id: str,
        prompt: str,
        skill_tag: str,
        reference_answer: str,
        grading_criteria: List[str],
        submitted_answer: str,
    ) -> EssayEvaluationItem:
        safe_prompt = truncate_to_token_limit(prompt, max_tokens=1000)
        safe_ref = truncate_to_token_limit(reference_answer or "Accurate, comprehensive explanation covering key criteria.", max_tokens=1500)
        safe_sub = truncate_to_token_limit(submitted_answer, max_tokens=2000)
        criteria_str = "\n".join(f"- {c}" for c in grading_criteria) if grading_criteria else "- Accurate conceptual understanding and explanation"

        eval_prompt = PromptTemplate(
            template=ESSAY_GRADING_PROMPT,
            input_variables=["prompt", "skill_tag", "reference_answer", "grading_criteria", "submitted_answer"],
        )
        formatted = eval_prompt.format(
            prompt=safe_prompt,
            skill_tag=skill_tag or "General",
            reference_answer=safe_ref,
            grading_criteria=criteria_str,
            submitted_answer=safe_sub,
        )

        active_llm = self.get_active_llm()
        grader = active_llm.with_structured_output(EssayGradingSchema)
        raw_grading = await grader.ainvoke(formatted)
        if isinstance(raw_grading, dict):
            grading_res: EssayGradingSchema = EssayGradingSchema.model_validate(raw_grading)
        else:
            grading_res = cast(EssayGradingSchema, raw_grading)


        return EssayEvaluationItem(
            question_id=question_id,
            type="essay",
            score=max(0, min(100, grading_res.score)),
            points_possible=100,
            criteria_met=grading_res.criteria_met,
            criteria_missed=grading_res.criteria_missed,
            feedback=grading_res.feedback,
        )

    async def generate_summary_feedback(
        self,
        track: str,
        percentage: float,
        raw_points: float,
        max_points: float,
        per_question_results: List[Union[MCQEvaluationItem, EssayEvaluationItem]],
        timeout_seconds: float = 6.0,
    ) -> str:
        """Generates summary paragraph feedback across all scored items with fallback."""
        try:
            return await asyncio.wait_for(
                self._generate_summary_feedback_llm(
                    track=track,
                    percentage=percentage,
                    raw_points=raw_points,
                    max_points=max_points,
                    per_question_results=per_question_results,
                ),
                timeout=timeout_seconds,
            )
        except Exception as exc:
            logger.debug("Summary feedback LLM failed or timed out: %s. Using heuristic summary.", exc)
            return self._fallback_summary_feedback(percentage)

    async def _generate_summary_feedback_llm(
        self,
        track: str,
        percentage: float,
        raw_points: float,
        max_points: float,
        per_question_results: List[Union[MCQEvaluationItem, EssayEvaluationItem]],
    ) -> str:
        lines: List[str] = []
        for item in per_question_results:
            if isinstance(item, MCQEvaluationItem):
                lines.append(f"- MCQ {item.question_id}: {'Correct' if item.is_correct else 'Incorrect'} ({item.points_earned}/{item.points_possible} pts). Feedback: {item.feedback}")
            elif isinstance(item, EssayEvaluationItem):
                score_str = f"{item.score}/100" if item.score is not None else "Pending"
                lines.append(f"- Essay {item.question_id}: Score {score_str}. Met: {len(item.criteria_met)}, Missed: {len(item.criteria_missed)}. Feedback: {item.feedback}")

        perf_summary = "\n".join(lines)
        prompt = PromptTemplate(
            template=SUMMARY_FEEDBACK_PROMPT,
            input_variables=["track", "percentage", "raw_points", "max_points", "performance_summary"],
        )
        formatted = prompt.format(
            track=track or "General Role",
            percentage=f"{percentage:.1f}",
            raw_points=f"{raw_points:.1f}",
            max_points=f"{max_points:.1f}",
            performance_summary=perf_summary,
        )

        active_llm = self.get_active_llm()
        summarizer = active_llm.with_structured_output(SummaryFeedbackSchema)
        raw_summary = await summarizer.ainvoke(formatted)
        if isinstance(raw_summary, dict):
            res: SummaryFeedbackSchema = SummaryFeedbackSchema.model_validate(raw_summary)
        else:
            res = cast(SummaryFeedbackSchema, raw_summary)
        return res.summary_feedback


    def _fallback_summary_feedback(self, percentage: float) -> str:
        if percentage >= 80.0:
            return "Excellent performance across the evaluated topics. Continue refining practical applications, system architecture nuances, and edge case discussions."
        elif percentage >= 50.0:
            return "Solid foundational understanding demonstrated. Focus on deepening conceptual clarity in missed areas and practicing structured essay responses."
        else:
            return "Review foundational concepts in the target skill gaps, practice relevant multiple-choice questions, and prepare structured explanations for essay questions."
