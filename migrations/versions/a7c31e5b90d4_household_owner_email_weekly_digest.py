"""household owner_email + weekly digest fields

Revision ID: a7c31e5b90d4
Revises: 8adb3bc68dc9
Create Date: 2026-08-16 12:10:44.118203

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c31e5b90d4'
down_revision: Union[str, Sequence[str], None] = '8adb3bc68dc9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('households', sa.Column('owner_email', sa.String(), nullable=True))
    op.add_column('households', sa.Column('weekly_email_enabled', sa.Boolean(), nullable=True))
    op.add_column('households', sa.Column('owner_conversation_id', sa.String(), nullable=True))
    # Existing rows predate the column, so they'd read back NULL and be
    # skipped by weekly_owner_email_job()'s `is_(True)` filter - opt them in
    # explicitly to match the model default rather than silently excluding
    # every household created before this migration.
    # TRUE, not 1: Postgres rejects an integer literal for a boolean column,
    # and SQLite has understood TRUE since 3.23 - so this one statement works
    # against both DATABASE_URL targets.
    op.execute('UPDATE households SET weekly_email_enabled = TRUE WHERE weekly_email_enabled IS NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('households', 'owner_conversation_id')
    op.drop_column('households', 'weekly_email_enabled')
    op.drop_column('households', 'owner_email')
