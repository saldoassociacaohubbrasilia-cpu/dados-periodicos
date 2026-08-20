"""baseline schema

Espelha exatamente o schema atual em app/models.py, que até aqui era
criado via Base.metadata.create_all() (só cria tabela que não existe —
nunca altera uma existente, o que já causou dor de cabeça quando novas
colunas foram adicionadas em Student, ver README).

Ambiente NOVO (banco vazio): rode `alembic upgrade head` normalmente —
cria todas as tabelas do zero.

Ambiente EXISTENTE (banco já criado via create_all, ex: produção):
NÃO rode `alembic upgrade head` direto — isso tentaria recriar tabelas
que já existem e falharia. Rode `alembic stamp head` uma única vez,
que só marca o banco como já estando nesta revisão, sem executar
nenhum CREATE TABLE. A partir daí, toda mudança de schema nova entra
como uma migration incremental de verdade.

Revision ID: c297e9635eee
Revises:
Create Date: 2026-08-20 18:57:11.485472

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'c297e9635eee'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "raw_ludos_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("endpoint", sa.String(length=120), nullable=False),
        sa.Column("params", JSONB(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_raw_ludos_snapshot_endpoint", "raw_ludos_snapshot", ["endpoint"])
    op.create_index("ix_raw_ludos_snapshot_fetched_at", "raw_ludos_snapshot", ["fetched_at"])

    op.create_table(
        "sync_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("endpoint", sa.String(length=120), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("records_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
    )

    op.create_table(
        "school",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("regional", sa.String(length=120), nullable=True),
    )
    op.create_index("ix_school_external_id", "school", ["external_id"], unique=True)

    op.create_table(
        "turma",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("school.id"), nullable=False),
    )
    op.create_index("ix_turma_external_id", "turma", ["external_id"], unique=True)

    op.create_table(
        "student",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=60), nullable=False),
        sa.Column("login", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("school.id"), nullable=True),
        sa.Column("turma_id", sa.Integer(), sa.ForeignKey("turma.id"), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("account_status", sa.String(length=20), nullable=True),
        sa.Column("pontos", sa.Float(), nullable=True),
        sa.Column("moedas", sa.Float(), nullable=True),
        sa.Column("last_access", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_staff", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_student_external_id", "student", ["external_id"], unique=True)

    op.create_table(
        "student_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("student.id"), nullable=False),
        sa.Column("trail_external_id", sa.String(length=60), nullable=False),
        sa.Column("trail_name", sa.String(length=200), nullable=False),
        sa.Column("progress_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_student_progress_student_id", "student_progress", ["student_id"])
    op.create_index("ix_student_progress_trail_external_id", "student_progress", ["trail_external_id"])

    op.create_table(
        "metric_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=60), nullable=False),
        sa.Column("scope_label", sa.String(length=200), nullable=False),
        sa.Column("institution", sa.String(length=20), nullable=False, server_default="todas"),
        sa.Column("trilha_id", sa.String(length=20), nullable=False, server_default="41"),
        sa.Column("inscritos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engajados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("concluintes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("taxa_ativacao", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("taxa_conclusao", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("taxa_retencao", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("pontuacao_media", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.create_index("ix_metric_snapshot_snapshot_date", "metric_snapshot", ["snapshot_date"])
    op.create_index("ix_metric_snapshot_scope_type", "metric_snapshot", ["scope_type"])
    op.create_index("ix_metric_snapshot_scope_id", "metric_snapshot", ["scope_id"])
    op.create_index("ix_metric_snapshot_institution", "metric_snapshot", ["institution"])
    op.create_index("ix_metric_snapshot_trilha_id", "metric_snapshot", ["trilha_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("metric_snapshot")
    op.drop_table("student_progress")
    op.drop_table("student")
    op.drop_table("turma")
    op.drop_table("school")
    op.drop_table("sync_log")
    op.drop_table("raw_ludos_snapshot")
