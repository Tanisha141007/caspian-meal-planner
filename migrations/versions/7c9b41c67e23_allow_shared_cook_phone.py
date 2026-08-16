"""allow shared cook phone

Revision ID: 7c9b41c67e23
Revises: 2d7a0e19c4fb
Create Date: 2026-08-16 23:15:00.000000

"""
from typing import Sequence, Union

from alembic import context
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "7c9b41c67e23"
down_revision: Union[str, Sequence[str], None] = "2d7a0e19c4fb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if context.get_context().dialect.name == "sqlite":
        naming_convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table("households", naming_convention=naming_convention) as batch_op:
            batch_op.drop_constraint("uq_households_cook_phone", type_="unique")
        return

    op.drop_constraint("households_cook_phone_key", "households", type_="unique")


def downgrade() -> None:
    """Downgrade schema."""
    if context.get_context().dialect.name == "sqlite":
        with op.batch_alter_table("households") as batch_op:
            batch_op.create_unique_constraint("uq_households_cook_phone", ["cook_phone"])
        return

    op.create_unique_constraint("households_cook_phone_key", "households", ["cook_phone"])
