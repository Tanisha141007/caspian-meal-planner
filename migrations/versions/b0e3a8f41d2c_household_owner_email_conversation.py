"""household owner email conversation

Revision ID: b0e3a8f41d2c
Revises: 6d8d6c9df2af
Create Date: 2026-08-16 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b0e3a8f41d2c"
down_revision: Union[str, Sequence[str], None] = "6d8d6c9df2af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("households", sa.Column("owner_caspian_conversation_id", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("households", "owner_caspian_conversation_id")
