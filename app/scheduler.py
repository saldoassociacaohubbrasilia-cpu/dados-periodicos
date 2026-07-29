from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.ingestion.sync_job import run_sync

scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")


def start_scheduler():
    """
    Roda run_sync() a cada `sync_interval_hours` (padrão 6h). Não
    dispara uma sincronização imediatamente ao subir a aplicação —
    a primeira rodada é manual (POST /api/v1/sync/run) ou espera o
    primeiro intervalo, evitando picos de chamadas toda vez que o
    processo reinicia (ex: durante deploys).
    """
    scheduler.add_job(
        run_sync,
        trigger=IntervalTrigger(hours=settings.sync_interval_hours),
        id="ludos_sync",
        replace_existing=True,
    )
    scheduler.start()
