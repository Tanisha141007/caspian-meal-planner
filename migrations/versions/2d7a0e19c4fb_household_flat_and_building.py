"""household flat and building

Revision ID: 2d7a0e19c4fb
Revises: f6f71d9bc6e2
Create Date: 2026-08-16 22:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2d7a0e19c4fb"
down_revision: Union[str, Sequence[str], None] = "f6f71d9bc6e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("households", sa.Column("flat_no", sa.String(), nullable=True))
    op.add_column("households", sa.Column("building", sa.String(), nullable=True))
    op.execute("UPDATE households SET flat_no = '' WHERE flat_no IS NULL")
    op.execute("UPDATE households SET building = '' WHERE building IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("households", "building")
    op.drop_column("households", "flat_no")
