from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Ga4MetricaDiaria

router = APIRouter(prefix="/api/v1", tags=["uso-plataforma"], dependencies=[Depends(get_current_user)])

DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
PERIODO_PADRAO_DIAS = 30


@router.get("/uso-plataforma")
def get_uso_plataforma(inicio: date | None = None, fim: date | None = None, db: Session = Depends(get_db)):
    """
    Uso da plataforma (Google Analytics 4, sincronizado a cada sync — ver
    app/ingestion/ga4_sync.py), no período [inicio, fim] (padrão: últimos
    30 dias). Só cobre o site saldo.ludos.pro: acesso pelo app de celular
    não passa pela tag do GA4.

    "usuarios" aqui é soma de usuários por dia (usuários-dia): quem acessou
    em 3 dias diferentes conta 3 vezes. Sessões, visualizações e tempo
    podem ser somados normalmente.
    """
    fim = fim or date.today()
    inicio = inicio or fim - timedelta(days=PERIODO_PADRAO_DIAS - 1)
    if inicio > fim:
        raise HTTPException(status_code=400, detail="inicio precisa ser antes de fim.")

    linhas = db.execute(
        select(Ga4MetricaDiaria).where(Ga4MetricaDiaria.data >= inicio, Ga4MetricaDiaria.data <= fim)
    ).scalars().all()
    por_recorte: dict[str, list[Ga4MetricaDiaria]] = {}
    for linha in linhas:
        por_recorte.setdefault(linha.recorte, []).append(linha)

    # --- Horários de pico: grade dia da semana x hora (sessões) ---
    grade = {(dia, hora): {"sessoes": 0, "usuarios": 0} for dia in range(7) for hora in range(24)}
    for l in por_recorte.get("dia_hora", []):
        celula = grade[(l.data.weekday(), int(l.dimensao))]
        celula["sessoes"] += l.sessoes
        celula["usuarios"] += l.usuarios_ativos
    horarios_pico = [
        {"dia_semana": DIAS_SEMANA[dia], "dia_semana_idx": dia, "hora": hora, **valores}
        for (dia, hora), valores in grade.items()
    ]

    # --- Computador x celular ---
    dispositivos: dict[str, dict] = {}
    for l in por_recorte.get("dispositivo", []):
        d = dispositivos.setdefault(l.dimensao, {"sessoes": 0, "usuarios": 0, "tempo_engajamento_seg": 0.0})
        d["sessoes"] += l.sessoes
        d["usuarios"] += l.usuarios_ativos
        d["tempo_engajamento_seg"] += l.tempo_engajamento_seg
    total_sessoes = sum(d["sessoes"] for d in dispositivos.values())
    dispositivos_out = sorted(
        (
            {
                "dispositivo": nome,
                "sessoes": d["sessoes"],
                "usuarios": d["usuarios"],
                "percentual_sessoes": round(100 * d["sessoes"] / total_sessoes, 1) if total_sessoes else 0.0,
                # Tempo com a tela aberta e em primeiro plano — menor que a
                # "duração da sessão" do painel do GA4, que conta o tempo parado.
                "tempo_engajado_medio_sessao_min": round(d["tempo_engajamento_seg"] / d["sessoes"] / 60, 1) if d["sessoes"] else 0.0,
            }
            for nome, d in dispositivos.items()
        ),
        key=lambda d: d["sessoes"], reverse=True,
    )

    # --- Telas mais usadas e tempo em cada uma ---
    telas: dict[str, dict] = {}
    for l in por_recorte.get("tela", []):
        t = telas.setdefault(l.dimensao, {"visualizacoes": 0, "usuarios": 0, "tempo_engajamento_seg": 0.0})
        t["visualizacoes"] += l.visualizacoes
        t["usuarios"] += l.usuarios_ativos
        t["tempo_engajamento_seg"] += l.tempo_engajamento_seg
    telas_out = sorted(
        (
            {
                "tela": nome,
                "visualizacoes": t["visualizacoes"],
                "usuarios": t["usuarios"],
                "tempo_total_min": round(t["tempo_engajamento_seg"] / 60, 1),
                "tempo_medio_por_visualizacao_seg": round(t["tempo_engajamento_seg"] / t["visualizacoes"], 1) if t["visualizacoes"] else 0.0,
            }
            for nome, t in telas.items()
        ),
        key=lambda t: t["visualizacoes"], reverse=True,
    )

    # --- Novos x recorrentes por semana (segunda a domingo) ---
    semanas: dict[date, dict] = {}
    for l in por_recorte.get("novos_recorrentes", []):
        segunda = l.data - timedelta(days=l.data.weekday())
        s = semanas.setdefault(segunda, {"novos": 0, "recorrentes": 0})
        if l.dimensao == "new":
            s["novos"] += l.usuarios_ativos
        elif l.dimensao == "returning":
            s["recorrentes"] += l.usuarios_ativos
    novos_recorrentes_out = [
        {"semana_inicio": segunda.isoformat(), **valores} for segunda, valores in sorted(semanas.items())
    ]

    return {
        "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat()},
        "atualizado_em": max((l.atualizado_em for l in linhas), default=None),
        "horarios_pico": horarios_pico,
        "dispositivos": dispositivos_out,
        "telas": telas_out,
        "novos_recorrentes_semana": novos_recorrentes_out,
    }
