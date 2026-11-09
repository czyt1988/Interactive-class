"""course provenance: course_imports

Revision ID: 0002_course_imports
Revises: 0001_initial
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_course_imports"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Provenance only: course content stays in ``courses/<slug>/`` and the site
    # catalog keeps reading ``dist/``. One row per imported course.
    op.create_table(
        "course_imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("screens", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_course_imports_slug"), "course_imports", ["slug"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_course_imports_slug"), table_name="course_imports")
    op.drop_table("course_imports")
