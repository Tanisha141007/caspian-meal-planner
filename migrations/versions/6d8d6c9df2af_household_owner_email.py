"""household owner email

Revision ID: 6d8d6c9df2af
Revises: 71c78775f522
Create Date: 2026-08-16 20:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6d8d6c9df2af"
down_revision: Union[str, Sequence[str], None] = "71c78775f522"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("households", sa.Column("owner_email", sa.String(), nullable=True))
    op.create_index(op.f("ix_households_owner_email"), "households", ["owner_email"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_households_owner_email"), table_name="households")
    op.drop_column("households", "owner_email")
