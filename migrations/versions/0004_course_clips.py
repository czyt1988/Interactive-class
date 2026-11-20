"""course clips: per-course intro/outro selection that never enters git

Revision ID: 0004_course_clips
Revises: 0003_course_watermarks
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_course_clips"
down_revision: str | None = "0003_course_watermarks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deployment configuration, not course content: the intro/outro library is
    # shared by every course, so which clip a course uses belongs to the site
    # database. The build reads the row and injects the rendered scene into the
    # built composition; ``courses/<slug>/course.json`` is never touched.
    op.create_table(
        "course_clips",
        sa.Column("course_slug", sa.String(length=80), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("course_slug"),
    )


def downgrade() -> None:
    op.drop_table("course_clips")
