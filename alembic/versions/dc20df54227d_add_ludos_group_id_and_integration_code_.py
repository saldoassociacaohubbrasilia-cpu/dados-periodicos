"""add ludos_group_id and integration_code to turma

Revision ID: dc20df54227d
Revises: ff28918269ef
Create Date: 2026-09-04 15:25:34.426819

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc20df54227d'
down_revision: Union[str, Sequence[str], None] = 'ff28918269ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("turma", sa.Column("ludos_group_id", sa.Integer(), nullable=True))
    op.add_column("turma", sa.Column("integration_code", sa.String(length=60), nullable=True))
    op.create_index("ix_turma_ludos_group_id", "turma", ["ludos_group_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_turma_ludos_group_id", table_name="turma")
    op.drop_column("turma", "integration_code")
    op.drop_column("turma", "ludos_group_id")
