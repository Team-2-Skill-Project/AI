"""Add persisted candidate profiles and recommendation interactions.

Revision ID: 0003_candidate_interactions
Revises: 0002_mentor_tables
Create Date: 2026-10-01 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_candidate_interactions"
down_revision: Union[str, None] = "0002_mentor_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=100), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("headline", sa.String(length=500), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.String(length=500), nullable=True),
        sa.Column("github_url", sa.String(length=500), nullable=True),
        sa.Column("portfolio_url", sa.String(length=500), nullable=True),
        sa.Column("target_roles", sa.JSON(), nullable=True),
        sa.Column("preferences", sa.JSON(), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=True),
        sa.Column("experiences", sa.JSON(), nullable=True),
        sa.Column("educations", sa.JSON(), nullable=True),
        sa.Column("projects", sa.JSON(), nullable=True),
        sa.Column("certificates", sa.JSON(), nullable=True),
        sa.Column("languages", sa.JSON(), nullable=True),
        sa.Column("raw_profile", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_candidates_email", "candidates", ["email"])

    op.create_table(
        "candidate_interactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("candidate_id", sa.String(length=100), nullable=False),
        sa.Column("job_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_candidate_interactions_candidate_id", "candidate_interactions", ["candidate_id"])
    op.create_index("ix_candidate_interactions_job_id", "candidate_interactions", ["job_id"])
    op.create_index("ix_candidate_interactions_event_type", "candidate_interactions", ["event_type"])
    op.create_index("ix_candidate_interactions_created_at", "candidate_interactions", ["created_at"])
    op.create_index(
        "ix_cand_job_interaction",
        "candidate_interactions",
        ["candidate_id", "job_id"],
    )
    op.create_index(
        "ix_cand_event_type",
        "candidate_interactions",
        ["candidate_id", "event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_cand_event_type", table_name="candidate_interactions")
    op.drop_index("ix_cand_job_interaction", table_name="candidate_interactions")
    op.drop_index("ix_candidate_interactions_created_at", table_name="candidate_interactions")
    op.drop_index("ix_candidate_interactions_event_type", table_name="candidate_interactions")
    op.drop_index("ix_candidate_interactions_job_id", table_name="candidate_interactions")
    op.drop_index("ix_candidate_interactions_candidate_id", table_name="candidate_interactions")
    op.drop_table("candidate_interactions")
    op.drop_index("ix_candidates_email", table_name="candidates")
    op.drop_table("candidates")
