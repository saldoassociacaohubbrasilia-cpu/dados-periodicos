"""add modulo_atual to student_progress

Revision ID: 0b5f558574f1
Revises: dc20df54227d
Create Date: 2026-09-04 17:16:04.157329

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0b5f558574f1'
down_revision: Union[str, Sequence[str], None] = 'dc20df54227d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("student_progress", sa.Column("modulo_atual", sa.String(length=200), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("student_progress", "modulo_atual")
