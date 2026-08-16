"""household cook message schedule

Revision ID: f6f71d9bc6e2
Revises: e2841b2c7ad7
Create Date: 2026-08-16 22:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6f71d9bc6e2"
down_revision: Union[str, Sequence[str], None] = "e2841b2c7ad7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("households", sa.Column("cook_message_schedule", sa.JSON(), nullable=True))
    op.execute("UPDATE households SET cook_message_schedule = '{}' WHERE cook_message_schedule IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("households", "cook_message_schedule")
