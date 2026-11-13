"""course watermarks: per-course config that never enters git

Revision ID: 0003_course_watermarks
Revises: 0002_course_imports
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_course_watermarks"
down_revision: str | None = "0002_course_imports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deployment configuration, not course content: the admin page writes these
    # rows and the build reads them before baking the layer into the bundle. The
    # table is the only place the watermark text lives, so it never reaches
    # ``courses/<slug>/course.json`` or git history.
    op.create_table(
        "course_watermarks",
        sa.Column("course_slug", sa.String(length=80), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("course_slug"),
    )


def downgrade() -> None:
    op.drop_table("course_watermarks")
