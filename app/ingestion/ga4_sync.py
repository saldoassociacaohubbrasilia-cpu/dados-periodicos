"""Sync do Google Analytics 4 -> Ga4MetricaDiaria.

Roda no fim de cada rodada do sync da Ludos (ver sync_job.py). Fonte
opcional: sem credencial configurada, ou com o GA4 fora do ar, só
registra no SyncLog e segue — nunca derruba o sync da Ludos.
"""
import datetime as dt
import logging

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.ga4_client import RECORTES, Ga4Client, Ga4NaoConfigurado
from app.models import Ga4MetricaDiaria, SyncLog

logger = logging.getLogger("ga4_sync")

ENDPOINT_LABEL = "ga4"


def _inicio_da_janela(db: Session, hoje: dt.date) -> dt.date:
    """Primeiro sync: desde ga4_data_inicio. Depois: só os últimos
    ga4_dias_reprocessar dias antes do último dia já gravado."""
    ultimo = db.execute(select(func.max(Ga4MetricaDiaria.data))).scalar()
    inicio_tag = dt.date.fromisoformat(settings.ga4_data_inicio)
    if ultimo is None:
        return inicio_tag
    return max(inicio_tag, min(ultimo, hoje) - dt.timedelta(days=settings.ga4_dias_reprocessar))


def sync_ga4(db: Session) -> None:
    log = SyncLog(endpoint=ENDPOINT_LABEL, started_at=dt.datetime.now(dt.timezone.utc), status="em_andamento")
    db.add(log)
    db.commit()

    try:
        # Datas do GA4 seguem o fuso da propriedade (Brasília), não UTC.
        hoje = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).date()
        inicio = _inicio_da_janela(db, hoje)
        client = Ga4Client()

        linhas_por_recorte = {recorte: client.buscar_recorte(recorte, inicio, hoje) for recorte in RECORTES}

        # Só troca os dados depois que TODOS os recortes vieram — falha no
        # meio não deixa a janela pela metade (apagada e não regravada).
        db.execute(delete(Ga4MetricaDiaria).where(Ga4MetricaDiaria.data >= inicio, Ga4MetricaDiaria.data <= hoje))
        total = 0
        for recorte, linhas in linhas_por_recorte.items():
            for linha in linhas:
                db.add(Ga4MetricaDiaria(recorte=recorte, **linha))
            total += len(linhas)

        log.status = "sucesso"
        log.records_ingested = total
    except Ga4NaoConfigurado as exc:
        db.rollback()
        logger.info("GA4 sem credencial configurada — pulando: %s", exc)
        log.status = "erro"
        log.error_message = f"GA4 sem credencial configurada: {exc}"[:1000]
    except Exception as exc:  # fonte opcional: qualquer falha do Google não pode parar o sync da Ludos
        db.rollback()
        logger.error("Erro sincronizando GA4: %s", exc)
        log.status = "erro"
        log.error_message = str(exc)[:1000]
    finally:
        log.finished_at = dt.datetime.now(dt.timezone.utc)
        db.add(log)
        db.commit()
