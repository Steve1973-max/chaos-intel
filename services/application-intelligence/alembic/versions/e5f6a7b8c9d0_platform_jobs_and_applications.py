"""Platform applications and background jobs migration

Revision ID: e5f6a7b8c9d0
Revises: cd4d74de49fe
Create Date: 2026-11-05 22:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'cd4d74de49fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create applications and background_jobs platform tables."""
    # 1. Platform applications table
    op.create_table(
        'applications',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('source_type', sa.String(length=64), nullable=False),
        sa.Column('source_location', sa.Text(), nullable=False),
        sa.Column('file_hash', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('metadata_payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('registered', 'analyzing', 'analyzed', 'failed')", name='check_valid_app_status'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_app_name', 'applications', ['name'], unique=False)

    # 2. Platform background_jobs table
    op.create_table(
        'background_jobs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('task_name', sa.String(length=128), nullable=False),
        sa.Column('correlation_id', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error', sa.JSON(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='300'),
        sa.Column('worker_id', sa.String(length=128), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'dead_letter')",
            name='check_valid_job_status'
        ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_background_jobs_task_name', 'background_jobs', ['task_name'], unique=False)
    op.create_index('ix_background_jobs_correlation_id', 'background_jobs', ['correlation_id'], unique=False)
    op.create_index('idx_job_status_priority', 'background_jobs', ['status', 'priority'], unique=False)


def downgrade() -> None:
    """Drop platform tables."""
    op.drop_index('idx_job_status_priority', table_name='background_jobs')
    op.drop_index('ix_background_jobs_correlation_id', table_name='background_jobs')
    op.drop_index('ix_background_jobs_task_name', table_name='background_jobs')
    op.drop_table('background_jobs')
    op.drop_index('idx_app_name', table_name='applications')
    op.drop_table('applications')

