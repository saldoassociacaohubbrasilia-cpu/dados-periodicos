import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import RawLudosSnapshot, SyncLog
from app.ludos_client import LudosClient, LudosAPIError
from app.ingestion.transform import rebuild_metrics

logger = logging.getLogger("sync_job")

# Endpoints buscados a cada rodada. Adicione novos aqui conforme o
# dashboard precisar de mais dados (ex: /report/certificates).
#
# ORDEM IMPORTA: /report/performance é o que alimenta os KPIs do
# dashboard (inscritos/engajados/concluintes), e é bem menor que
# /report/players (500+ páginas). Por isso os relatórios pequenos e
# essenciais pros indicadores vêm primeiro — assim, se a cota da Ludos
# acabar no meio do caminho, ela corta o /report/players (que só dá
# nome/escola/turma) em vez de zerar os KPIs principais.
ENDPOINTS = {
    "/report/performance": lambda c: c.get_performance(),
    "/report/trails": lambda c: c.get_trails(),
    "/report/trails-performance": lambda c: c.get_trails_performance(),
    "/report/players": lambda c: c.get_players(),
}


def run_sync():
    """
    Executa uma rodada completa: busca cada endpoint (com throttling
    já embutido no LudosClient), grava o retorno cru em JSONB, loga o
    resultado e, ao final, recalcula as métricas agregadas.
    Uma falha em um endpoint não impede os demais de rodar.
    """
    db: Session = SessionLocal()
    client = LudosClient()
    try:
        for endpoint, fetch_fn in ENDPOINTS.items():
            started = dt.datetime.now(dt.timezone.utc)
            log = SyncLog(endpoint=endpoint, started_at=started, status="em_andamento")
            db.add(log)
            db.commit()

            try:
                payload = fetch_fn(client)
                db.add(RawLudosSnapshot(endpoint=endpoint, params={}, payload=payload))
                log.status = "sucesso"
                log.records_ingested = len(payload) if isinstance(payload, list) else 1
            except LudosAPIError as exc:
                logger.error("Erro sincronizando %s: %s", endpoint, exc)
                log.status = "erro"
                log.error_message = str(exc)[:1000]
            finally:
                log.finished_at = dt.datetime.now(dt.timezone.utc)
                db.commit()

        rebuild_metrics(db)
    finally:
        client.close()
        db.close()