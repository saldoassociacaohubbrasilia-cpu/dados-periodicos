"""add turma_manager association table

Revision ID: ff28918269ef
Revises: c297e9635eee
Create Date: 2026-09-04 13:16:40.198265

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff28918269ef'
down_revision: Union[str, Sequence[str], None] = 'c297e9635eee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "turma_manager",
        sa.Column("turma_id", sa.Integer(), sa.ForeignKey("turma.id"), primary_key=True),
        sa.Column("manager_id", sa.Integer(), sa.ForeignKey("student.id"), primary_key=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("turma_manager")
