"""add status column to policy_documents

Revision ID: c0a8f902d1e2
Revises: <previous_revision_id>
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c0a8f902d1e2'
down_revision = None  # Will automatically attach to current head revision
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Uses server_default='ACTIVE' to safely populate existing rows without NULL errors
    op.add_column(
        'policy_documents',
        sa.Column(
            'status', 
            sa.String(), 
            server_default='ACTIVE', 
            nullable=False
        )
    )

def downgrade() -> None:
    op.drop_column('policy_documents', 'status')