from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MetricSnapshot
from app.schemas import OverviewOut, TrailShareOut
from app.institutions import normalize_institution, SCHOOL_COORDINATES

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

EMPTY_DASHBOARD = {
    "kpis": {
        "escolas": 0, "inscritos": 0, "engajados": 0,
        "taxa_engajamento": 0.0, "taxa_retencao": 0.0, "pontuacao_media": 0.0,
    },
    "escolas": [], "modulos": [], "turmas": [], "destaque": {},
}


@router.get("/dashboard")
def get_full_dashboard(instituicao: str = "todas", db: Session = Depends(get_db)):
    """
    Painel unificado da Trilha Saldo+ (CourseId 41), filtrado pela
    instituição selecionada ('todas' | 'secretaria' | 'cvp').
    """
    inst = normalize_institution(instituicao)

    latest_date = db.execute(select(func.max(MetricSnapshot.snapshot_date))).scalar()
    if not latest_date:
        return EMPTY_DASHBOARD

    kpi_row = db.execute(
        select(MetricSnapshot).where(
            MetricSnapshot.snapshot_date == latest_date,
            MetricSnapshot.scope_type == "geral",
            MetricSnapshot.institution == inst,
        )
    ).scalar_one_or_none()

    escola_rows = db.execute(
        select(MetricSnapshot)
        .where(
            MetricSnapshot.snapshot_date == latest_date,
            MetricSnapshot.scope_type == "escola",
            MetricSnapshot.institution == inst,
        )
        .order_by(MetricSnapshot.inscritos.desc())
    ).scalars().all()

    modulo_rows = db.execute(
        select(MetricSnapshot)
        .where(
            MetricSnapshot.snapshot_date == latest_date,
            MetricSnapshot.scope_type == "trilha",
            MetricSnapshot.institution == inst,
        )
        .order_by(MetricSnapshot.engajados.desc())
    ).scalars().all()

    kpis = {
        "escolas": len(escola_rows),
        "inscritos": kpi_row.inscritos if kpi_row else 0,
        "engajados": kpi_row.engajados if kpi_row else 0,
        "taxa_engajamento": kpi_row.taxa_ativacao if kpi_row else 0.0,
        "taxa_retencao": kpi_row.taxa_retencao if kpi_row else 0.0,
        "pontuacao_media": kpi_row.pontuacao_media if kpi_row else 0.0,
    }

    escolas = []
    for r in escola_rows:
        item = {
            "nome": r.scope_label,
            "inscritos": r.inscritos,
            "engajados": r.engajados,
            "engajamento_pct": r.taxa_ativacao,
            "pontuacao_media": r.pontuacao_media,
        }
        coords = SCHOOL_COORDINATES.get(r.scope_label)
        if coords:
            item["lat"], item["lng"] = coords
        escolas.append(item)

    modulos = [
        {"nome": r.scope_label.replace("Módulo ", "", 1), "total_alunos": r.engajados}
        for r in modulo_rows
    ]

    # A Ludos não distingue turma de escola no GroupName hoje — então a
    # tabela de turmas reaproveita a mesma base de escola/turma.
    turmas = [
        {
            "nome": r.scope_label,
            "escola": r.scope_label,
            "total_alunos": r.inscritos,
            "alunos_engajados": r.engajados,
            "progresso_medio": r.taxa_ativacao,
        }
        for r in escola_rows
    ]

    destaque = {
        "escola_mais_inscritos": escolas[0]["nome"] if escolas else None,
        "escola_mais_engajados": max(escolas, key=lambda e: e["engajados"])["nome"] if escolas else None,
        "modulo_destaque": modulos[0]["nome"] if modulos else None,
    }

    return {
        "kpis": kpis,
        "escolas": escolas,
        "modulos": modulos,
        "turmas": turmas,
        "destaque": destaque,
    }


@router.get("/overview", response_model=OverviewOut)
def get_overview(instituicao: str = "todas", db: Session = Depends(get_db)):
    inst = normalize_institution(instituicao)
    latest = db.execute(
        select(MetricSnapshot)
        .where(MetricSnapshot.scope_type == "geral", MetricSnapshot.institution == inst)
        .order_by(MetricSnapshot.snapshot_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    if latest is None:
        return OverviewOut(
            inscritos=0, engajados=0, concluintes=0,
            taxa_ativacao=0, taxa_conclusao=0, taxa_retencao=0,
            atualizado_em=datetime.now(timezone.utc).isoformat(),
        )

    return OverviewOut(
        inscritos=latest.inscritos,
        engajados=latest.engajados,
        concluintes=latest.concluintes,
        taxa_ativacao=latest.taxa_ativacao,
        taxa_conclusao=latest.taxa_conclusao,
        taxa_retencao=latest.taxa_retencao,
        atualizado_em=latest.snapshot_date.isoformat(),
    )


@router.get("/trails", response_model=list[TrailShareOut])
def get_trail_shares(instituicao: str = "todas", db: Session = Depends(get_db)):
    inst = normalize_institution(instituicao)
    latest_date = db.execute(select(func.max(MetricSnapshot.snapshot_date))).scalar()
    if latest_date is None:
        return []

    rows = db.execute(
        select(MetricSnapshot)
        .where(
            MetricSnapshot.snapshot_date == latest_date,
            MetricSnapshot.scope_type == "trilha",
            MetricSnapshot.institution == inst,
        )
    ).scalars().all()

    return [
        TrailShareOut(trilha=r.scope_label or "Trilha Saldo+", total_alunos=r.engajados or 0, percentual=r.taxa_ativacao or 0.0)
        for r in rows
    ]


@router.get("/ranking")
def get_ranking(instituicao: str = "todas", db: Session = Depends(get_db)):
    """
    Ranking de escolas/turmas ordenado por taxa de engajamento (não por
    quantidade de inscritos, como o /dashboard). Pensado pra apresentação
    à Secretaria: mostra quem está engajando bem e quem está patinando.
    """
    inst = normalize_institution(instituicao)
    latest_date = db.execute(select(func.max(MetricSnapshot.snapshot_date))).scalar()
    if not latest_date:
        return {"ranking": []}

    rows = db.execute(
        select(MetricSnapshot)
        .where(
            MetricSnapshot.snapshot_date == latest_date,
            MetricSnapshot.scope_type == "escola",
            MetricSnapshot.institution == inst,
        )
        .order_by(MetricSnapshot.taxa_ativacao.desc())
    ).scalars().all()

    return {
        "ranking": [
            {
                "posicao": i + 1,
                "nome": r.scope_label,
                "inscritos": r.inscritos,
                "engajados": r.engajados,
                "engajamento_pct": r.taxa_ativacao,
                "pontuacao_media": r.pontuacao_media,
            }
            for i, r in enumerate(rows)
        ]
    }


@router.post("/sync/run")
def trigger_manual_sync():
    from app.ingestion.sync_job import run_sync
    run_sync()
    return {"status": "sincronização executada"}