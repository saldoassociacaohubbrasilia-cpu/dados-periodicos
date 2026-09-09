from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.ingestion.sync_job import run_sync
from app.models import SyncLog

scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")


def _horas_desde_ultima_sincronizacao() -> float | None:
    """None quando nunca sincronizou nada ainda."""
    db = SessionLocal()
    try:
        ultimo = db.execute(
            select(SyncLog.started_at)
            .where(SyncLog.endpoint == "/report/performance", SyncLog.status == "sucesso")
            .order_by(SyncLog.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    finally:
        db.close()
    if ultimo is None:
        return None
    if ultimo.tzinfo is None:
        ultimo = ultimo.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ultimo).total_seconds() / 3600


def start_scheduler():
    """
    Roda run_sync() a cada `sync_interval_hours` (padrão 6h). O
    agendamento em si nunca dispara na hora que o processo sobe — só no
    primeiro intervalo completo — pra não sobrecarregar a Ludos toda vez
    que o Render reinicia (ex: durante um deploy).

    Só que isso tem um efeito colateral sério em semana de
    desenvolvimento ativo, com vários deploys por dia: cada reinício
    reseta esse temporizador do zero, e se os deploys forem mais
    frequentes que `sync_interval_hours`, a sincronização agendada NUNCA
    chega a disparar de verdade — foi exatamente o que aconteceu (5 dias
    sem sincronizar, mesmo com o intervalo configurado em 6h). Por isso,
    ao subir, se já faz mais tempo que `sync_interval_hours` desde a
    última sincronização bem-sucedida (consultando o SyncLog), dispara
    uma rodada extra logo (com um atraso curto, só pra deixar a
    aplicação terminar de subir primeiro) em vez de esperar o próximo
    intervalo completo.
    """
    horas_desde_ultima = _horas_desde_ultima_sincronizacao()
    if horas_desde_ultima is None or horas_desde_ultima >= settings.sync_interval_hours:
        scheduler.add_job(
            run_sync,
            trigger="date",
            run_date=datetime.now() + timedelta(seconds=60),
            id="ludos_sync_atrasada",
            replace_existing=True,
        )

    scheduler.add_job(
        run_sync,
        trigger=IntervalTrigger(hours=settings.sync_interval_hours),
        id="ludos_sync",
        replace_existing=True,
    )
    scheduler.start()
