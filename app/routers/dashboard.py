from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MetricSnapshot, Student, School, Turma, StudentProgress
from app.schemas import OverviewOut, TrailShareOut
from app.institutions import (
    normalize_institution, get_institution, SCHOOL_COORDINATES,
    get_school_display_name, is_excluded_group,
)
from app.ingestion.transform import calcular_alerta_aluno

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

# Trilhas disponíveis pro parâmetro `trilha` dos endpoints abaixo. Ver
# app/ingestion/transform.py:TRILHAS — precisa bater com as mesmas chaves.
TRILHA_PADRAO = "41"

EMPTY_DASHBOARD = {
    "kpis": {
        "escolas": 0, "inscritos": 0, "engajados": 0,
        "taxa_engajamento": 0.0, "taxa_retencao": 0.0, "pontuacao_media": 0.0,
    },
    "escolas": [], "modulos": [], "turmas": [], "destaque": {},
}


def _latest_date_for_trilha(db: Session, trilha_id: str):
    """Data do snapshot mais recente PARA ESSA TRILHA especificamente —
    nunca usar max(snapshot_date) sem filtrar por trilha_id, senão uma
    trilha processada por último (ex: Pocket depois de Saldo+ na mesma
    rodada de sync) "esconde" os dados da outra por ter timestamp maior."""
    return db.execute(
        select(func.max(MetricSnapshot.snapshot_date))
        .where(MetricSnapshot.trilha_id == trilha_id)
    ).scalar()


@router.get("/dashboard")
def get_full_dashboard(instituicao: str = "todas", trilha: str = TRILHA_PADRAO, db: Session = Depends(get_db)):
    """
    Painel unificado de uma trilha (default: Saldo+, CourseId 41),
    filtrado pela instituição selecionada ('todas' | 'secretaria' | 'cvp').
    Passe ?trilha=43 para ver a Trilha Pocket.
    """
    inst = normalize_institution(instituicao)

    latest_date = _latest_date_for_trilha(db, trilha)
    if not latest_date:
        return EMPTY_DASHBOARD

    kpi_row = db.execute(
        select(MetricSnapshot).where(
            MetricSnapshot.snapshot_date == latest_date,
            MetricSnapshot.scope_type == "geral",
            MetricSnapshot.institution == inst,
            MetricSnapshot.trilha_id == trilha,
        )
    ).scalar_one_or_none()

    escola_rows = db.execute(
        select(MetricSnapshot)
        .where(
            MetricSnapshot.snapshot_date == latest_date,
            MetricSnapshot.scope_type == "escola",
            MetricSnapshot.institution == inst,
            MetricSnapshot.trilha_id == trilha,
        )
        .order_by(MetricSnapshot.inscritos.desc())
    ).scalars().all()

    modulo_rows = db.execute(
        select(MetricSnapshot)
        .where(
            MetricSnapshot.snapshot_date == latest_date,
            MetricSnapshot.scope_type == "trilha",
            MetricSnapshot.institution == inst,
            MetricSnapshot.trilha_id == trilha,
        )
        .order_by(MetricSnapshot.engajados.desc())
    ).scalars().all()

    turma_rows = db.execute(
        select(MetricSnapshot)
        .where(
            MetricSnapshot.snapshot_date == latest_date,
            MetricSnapshot.scope_type == "turma",
            MetricSnapshot.institution == inst,
            MetricSnapshot.trilha_id == trilha,
        )
        .order_by(MetricSnapshot.inscritos.desc())
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

    turmas = [
        {
            "nome": r.scope_label,
            "escola": get_school_display_name(r.scope_label),
            "total_alunos": r.inscritos,
            "alunos_engajados": r.engajados,
            "progresso_medio": r.taxa_ativacao,
        }
        for r in turma_rows
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
def get_overview(instituicao: str = "todas", trilha: str = TRILHA_PADRAO, db: Session = Depends(get_db)):
    inst = normalize_institution(instituicao)
    latest = db.execute(
        select(MetricSnapshot)
        .where(
            MetricSnapshot.scope_type == "geral",
            MetricSnapshot.institution == inst,
            MetricSnapshot.trilha_id == trilha,
        )
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
def get_trail_shares(instituicao: str = "todas", trilha: str = TRILHA_PADRAO, db: Session = Depends(get_db)):
    inst = normalize_institution(instituicao)
    latest_date = _latest_date_for_trilha(db, trilha)
    if latest_date is None:
        return []

    rows = db.execute(
        select(MetricSnapshot)
        .where(
            MetricSnapshot.snapshot_date == latest_date,
            MetricSnapshot.scope_type == "trilha",
            MetricSnapshot.institution == inst,
            MetricSnapshot.trilha_id == trilha,
        )
    ).scalars().all()

    return [
        TrailShareOut(trilha=r.scope_label or "Trilha Saldo+", total_alunos=r.engajados or 0, percentual=r.taxa_ativacao or 0.0)
        for r in rows
    ]


@router.get("/ranking")
def get_ranking(instituicao: str = "todas", trilha: str = TRILHA_PADRAO, db: Session = Depends(get_db)):
    """
    Ranking de escolas/turmas ordenado por taxa de engajamento (não por
    quantidade de inscritos, como o /dashboard). Pensado pra apresentação
    à Secretaria: mostra quem está engajando bem e quem está patinando.
    Passe ?trilha=43 para ver o ranking da Trilha Pocket.
    """
    inst = normalize_institution(instituicao)
    latest_date = _latest_date_for_trilha(db, trilha)
    if not latest_date:
        return {"ranking": []}

    rows = db.execute(
        select(MetricSnapshot)
        .where(
            MetricSnapshot.snapshot_date == latest_date,
            MetricSnapshot.scope_type == "escola",
            MetricSnapshot.institution == inst,
            MetricSnapshot.trilha_id == trilha,
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


@router.get("/alertas")
def get_alertas(instituicao: str = "todas", db: Session = Depends(get_db)):
    """
    Sistema de Alertas: lista os alunos ATIVOS/INATIVOS (nunca Bloqueados)
    sem acesso há mais de DIAS_LIMITE_INATIVIDADE dias (ou que nunca
    acessaram), de todas as turmas, filtrável por instituição. Depende
    de Student.last_access, preenchido pelo log de login sincronizado
    em /report/logs (ver app/ludos_client.py:LOGIN_LOG_PATH).
    """
    inst_filtro = normalize_institution(instituicao)

    # Join único com Turma em vez de um db.get(Turma, ...) por aluno dentro
    # do loop — evita N+1 queries (uma por aluno) nessa listagem.
    rows = db.execute(
        select(Student, Turma).outerjoin(Turma, Turma.id == Student.turma_id)
    ).all()

    alertas = []
    for aluno, turma in rows:
        # Mesma regra do resto do dashboard: Bloqueado nunca entra,
        # mesmo que ele também esteja sem acesso há muito tempo — ele
        # já não conta como aluno ativo do programa. Conta de professor/
        # gestor (is_staff) também não é aluno — nunca entra no alerta.
        if aluno.account_status == "BLOCKED" or aluno.is_staff:
            continue

        dias_sem_acesso, alerta, motivo = calcular_alerta_aluno(aluno.last_access)
        if not alerta:
            continue

        nome_turma = turma.name if turma else "Sem Turma"
        inst_aluno = get_institution(nome_turma)

        if inst_filtro != "todas" and inst_aluno != inst_filtro:
            continue

        alertas.append({
            "nome": aluno.name or aluno.login,
            "login": aluno.login,
            "turma": nome_turma,
            "instituicao": inst_aluno,
            "dias_sem_acesso": dias_sem_acesso,
            "motivo_alerta": motivo,
        })

    alertas.sort(key=lambda a: (a["dias_sem_acesso"] is None, a["dias_sem_acesso"] or 0), reverse=True)
    return {"total_em_alerta": len(alertas), "alertas": alertas}


@router.get("/usuarios-ativos-semana")
def get_usuarios_ativos_semana(instituicao: str = "todas", db: Session = Depends(get_db)):
    """
    Quantos alunos acessaram a plataforma nos últimos 7 dias, a partir de
    Student.last_access (vem do log de login /report/logs — ver
    app/ludos_client.py:LOGIN_LOG_PATH). Não é por trilha: last_access é
    o último login na Ludos como um todo, não em um curso específico.

    Também devolve os 7 dias anteriores a esses, pra dar uma noção de
    tendência (variação %) sem precisar guardar histórico à parte.
    """
    inst_filtro = normalize_institution(instituicao)
    agora = datetime.now(timezone.utc)
    limite_semana_atual = agora - timedelta(days=7)
    limite_semana_anterior = agora - timedelta(days=14)

    # Mesmo filtro de "aluno de verdade" do resto do dashboard: nunca
    # Bloqueado, nunca staff/gestor — e nunca um grupo de teste/piloto
    # (Trilha Pocket, Equipe Gestão) que ainda não é da Secretaria/CVP.
    rows = db.execute(
        select(Student.last_access, Turma.name)
        .outerjoin(Turma, Turma.id == Student.turma_id)
        .where(Student.account_status != "BLOCKED", Student.is_staff.is_(False))
    ).all()

    ativos_semana_atual = 0
    ativos_semana_anterior = 0
    for last_access, turma_nome in rows:
        if is_excluded_group(turma_nome):
            continue
        if inst_filtro != "todas" and get_institution(turma_nome) != inst_filtro:
            continue
        if last_access is None:
            continue
        if last_access >= limite_semana_atual:
            ativos_semana_atual += 1
        elif last_access >= limite_semana_anterior:
            ativos_semana_anterior += 1

    variacao_pct = None
    if ativos_semana_anterior > 0:
        variacao_pct = round(
            100 * (ativos_semana_atual - ativos_semana_anterior) / ativos_semana_anterior, 1
        )

    return {
        "ativos_ultima_semana": ativos_semana_atual,
        "ativos_semana_anterior": ativos_semana_anterior,
        "variacao_pct": variacao_pct,
    }


@router.post("/sync/run")
def trigger_manual_sync():
    from app.ingestion.sync_job import run_sync
    executou = run_sync()
    if not executou:
        return {"status": "sincronização já em andamento em outro processo — nada foi feito"}
    return {"status": "sincronização executada"}