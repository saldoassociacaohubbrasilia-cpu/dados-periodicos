"""add ga4_metrica_diaria

Revision ID: b7e3d91a4c52
Revises: 0a11c832d4c1
Create Date: 2026-10-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e3d91a4c52"
down_revision: Union[str, Sequence[str], None] = "0a11c832d4c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ga4_metrica_diaria",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("recorte", sa.String(length=30), nullable=False),
        sa.Column("dimensao", sa.String(length=200), nullable=False),
        sa.Column("usuarios_ativos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sessoes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("visualizacoes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tempo_engajamento_seg", sa.Float(), nullable=False, server_default="0"),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("data", "recorte", "dimensao", name="uq_ga4_metrica_diaria"),
    )
    op.create_index("ix_ga4_metrica_diaria_data", "ga4_metrica_diaria", ["data"])
    op.create_index("ix_ga4_metrica_diaria_recorte", "ga4_metrica_diaria", ["recorte"])


def downgrade() -> None:
    op.drop_index("ix_ga4_metrica_diaria_recorte", table_name="ga4_metrica_diaria")
    op.drop_index("ix_ga4_metrica_diaria_data", table_name="ga4_metrica_diaria")
    op.drop_table("ga4_metrica_diaria")
