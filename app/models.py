from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ======================================================================
# CAMADA 1 — RAW (aterrissagem): guarda a resposta crua da Ludos em JSONB.
# Nada é descartado aqui; serve de auditoria e permite reprocessar
# métricas sem bater na API de novo caso a regra de negócio mude.
# ======================================================================

class RawLudosSnapshot(Base):
    __tablename__ = "raw_ludos_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(120), index=True)  # ex: "/report/players"
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    payload: Mapped[dict] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class SyncLog(Base):
    """Log operacional de cada rodada de sincronização, por endpoint."""
    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # "sucesso" | "erro" | "em_andamento"
    records_ingested: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)


# ======================================================================
# CAMADA 2 — PROCESSADA: tabelas tipadas, alimentadas a partir do RAW.
# É o que os endpoints REST leem — leitura rápida, sem reprocessar JSON
# a cada requisição do dashboard.
# ======================================================================

class School(Base):
    __tablename__ = "school"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    regional: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    turmas: Mapped[list["Turma"]] = relationship(back_populates="school")


class Turma(Base):
    __tablename__ = "turma"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    school_id: Mapped[int] = mapped_column(ForeignKey("school.id"))

    school: Mapped["School"] = relationship(back_populates="turmas")


class Student(Base):
    __tablename__ = "student"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # player id na Ludos
    login: Mapped[str] = mapped_column(String(150))
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    school_id: Mapped[Optional[int]] = mapped_column(ForeignKey("school.id"), nullable=True)
    turma_id: Mapped[Optional[int]] = mapped_column(ForeignKey("turma.id"), nullable=True)
    enrolled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Status da CONTA do aluno na Ludos: "ACTIVE" | "BLOCKED" | "INACTIVE".
    # Vem de /report/players (campo "status"). Não confundir com o
    # status de progresso em StudentProgress, que é sobre a trilha, não
    # sobre a conta. Quando um semestre termina, a Ludos costuma marcar
    # os alunos antigos como BLOCKED — é esse campo que o dashboard usa
    # pra mostrar só quem está ativo no período corrente.
    account_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    progress_records: Mapped[list["StudentProgress"]] = relationship(back_populates="student")


class StudentProgress(Base):
    """
    Estado atual (não histórico) de um aluno em uma trilha/módulo.
    Sobrescrita a cada sincronização. Para série histórica agregada,
    use MetricSnapshot abaixo.
    """
    __tablename__ = "student_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    trail_external_id: Mapped[str] = mapped_column(String(60), index=True)
    trail_name: Mapped[str] = mapped_column(String(200))
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(40))  # campo cru da Ludos — não usar sozinho como engajamento
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    student: Mapped["Student"] = relationship(back_populates="progress_records")


class MetricSnapshot(Base):
    """
    Rollup agregado, recalculado a cada sincronização — é o que a API
    lê diretamente para responder rápido ao dashboard.

    scope_type: 'geral' | 'escola' | 'turma' | 'trilha'
    scope_id:   external_id do escopo (ou 'geral')
    """
    __tablename__ = "metric_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    scope_type: Mapped[str] = mapped_column(String(20), index=True)
    scope_id: Mapped[str] = mapped_column(String(60), index=True)
    scope_label: Mapped[str] = mapped_column(String(200))

    # 'todas' | 'secretaria' | 'cvp' — ver app/institutions.py para o
    # mapeamento de GroupName -> instituição. Toda linha (geral, escola
    # ou módulo) é gravada tanto para "todas" quanto para a instituição
    # real do registro, permitindo filtrar sem reprocessar o JSON bruto.
    institution: Mapped[str] = mapped_column(String(20), default="todas", index=True)

    # ID da trilha na Ludos (ex: "41" = Trilha Saldo+, "43" = Trilha
    # Pocket) — cada trilha é um curso separado na Ludos, com seus
    # próprios inscritos/engajados. Ver app/ingestion/transform.py:TRILHAS.
    trilha_id: Mapped[str] = mapped_column(String(20), default="41", index=True)

    inscritos: Mapped[int] = mapped_column(Integer, default=0)
    engajados: Mapped[int] = mapped_column(Integer, default=0)
    concluintes: Mapped[int] = mapped_column(Integer, default=0)

    taxa_ativacao: Mapped[float] = mapped_column(Float, default=0.0)
    taxa_conclusao: Mapped[float] = mapped_column(Float, default=0.0)
    taxa_retencao: Mapped[float] = mapped_column(Float, default=0.0)
    pontuacao_media: Mapped[float] = mapped_column(Float, default=0.0)