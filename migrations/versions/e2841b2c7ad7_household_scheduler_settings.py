"""household scheduler settings

Revision ID: e2841b2c7ad7
Revises: b0e3a8f41d2c
Create Date: 2026-08-16 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2841b2c7ad7"
down_revision: Union[str, Sequence[str], None] = "b0e3a8f41d2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("households", sa.Column("notify_me", sa.Boolean(), nullable=True, server_default=sa.false()))
    op.add_column("households", sa.Column("notify_meals", sa.JSON(), nullable=True))
    op.execute("UPDATE households SET notify_meals = '[\"breakfast\", \"lunch\", \"snack\", \"dinner\"]' WHERE notify_meals IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("households", "notify_meals")
    op.drop_column("households", "notify_me")
