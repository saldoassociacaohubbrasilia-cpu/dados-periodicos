import datetime as dt
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models import RawLudosSnapshot, SyncLog
from app.ludos_client import LudosClient, LudosAPIError
from app.ingestion.transform import rebuild_metrics, TRILHAS

# Data mais antiga considerada ao buscar /report/play/course (a Ludos exige
# um período, não devolve "tudo" sem filtro de data) — bem anterior ao
# início de qualquer trilha hoje, só pra não deixar nada de fora.
PLAY_COURSE_START_DATE = "2020-01-01"

logger = logging.getLogger("sync_job")

# Chave arbitrária (mas fixa) do advisory lock do Postgres usado para
# garantir que só existe UMA rodada de sync em andamento por vez —
# mesmo que o processo web seja escalado para múltiplas instâncias, já
# que o lock vive no banco, não em memória de um processo só. Sem isso,
# um "rodar agora" manual sobrepondo o job agendado (ou dois manuais em
# paralelo) faz dois LudosClient concorrentes e duas sessões de banco
# mexendo nas mesmas linhas ao mesmo tempo — risco de IntegrityError em
# Student.external_id (unique) e de StudentProgress duplicado (não tem
# unique constraint, só é checado via SELECT antes do INSERT).
_SYNC_LOCK_KEY = 928374651

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
    "/report/courses": lambda c: c.get_courses(),
    "/report/trails": lambda c: c.get_trails(),
    "/report/trails-performance": lambda c: c.get_trails_performance(),
    "/report/logs": lambda c: c.get_login_log(),
    "/report/players": lambda c: c.get_players(),
}


def run_sync() -> bool:
    """
    Executa uma rodada completa: busca cada endpoint (com throttling
    já embutido no LudosClient), grava o retorno cru em JSONB, loga o
    resultado e, ao final, recalcula as métricas agregadas.
    Uma falha em um endpoint não impede os demais de rodar.

    Protegida por um advisory lock do Postgres: se já existe uma rodada
    em andamento (agendada ou disparada manualmente, neste processo ou
    em outro), essa chamada não faz nada e devolve False na hora — em
    vez de rodar em paralelo e arriscar corromper dado.
    """
    lock_conn = engine.connect()
    got_lock = lock_conn.execute(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": _SYNC_LOCK_KEY}
    ).scalar()
    if not got_lock:
        logger.info("Sincronização já em andamento (outro processo/thread) — pulando esta rodada.")
        lock_conn.close()
        return False

    try:
        _run_sync_locked()
        return True
    finally:
        lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _SYNC_LOCK_KEY})
        lock_conn.close()


def _run_sync_locked() -> None:
    db: Session = SessionLocal()
    client = LudosClient()
    try:
        courses_payload: list = []
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
                if endpoint == "/report/courses":
                    courses_payload = payload
            except LudosAPIError as exc:
                logger.error("Erro sincronizando %s: %s", endpoint, exc)
                log.status = "erro"
                log.error_message = str(exc)[:1000]
            finally:
                log.finished_at = dt.datetime.now(dt.timezone.utc)
                db.commit()

        _sync_play_course(db, client, courses_payload)

        rebuild_metrics(db)
    finally:
        client.close()
        db.close()


def _sync_play_course(db: Session, client: LudosClient, courses_payload: list) -> None:
    """Busca /report/play/course pra cada trilha em TRILHAS — dado por
    aluno/módulo/atividade, único jeito de saber em qual módulo cada aluno
    está de verdade (ver transform.py:_modulo_mais_avancado). Endpoint
    parametrizado por curso, então roda fora do laço genérico de ENDPOINTS
    (que não passa parâmetro nenhum) — uma chamada por trilha, usando o
    externalCode que acabou de vir em /report/courses nesta mesma rodada.
    """
    codigo_por_curso = {
        str(c.get("courseId")): c.get("externalCode")
        for c in (courses_payload or [])
    }
    # endDate parece ser um limite EXCLUSIVO (meia-noite) do lado da Ludos —
    # usar a data de hoje cortava fora quem jogou hoje mesmo antes do sync
    # rodar. +1 dia garante que o dia corrente inteiro sempre entra.
    amanha = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).strftime("%Y-%m-%d")

    for trilha_id in TRILHAS:
        code = codigo_por_curso.get(trilha_id)
        endpoint_label = f"/report/play/course/{trilha_id}"
        started = dt.datetime.now(dt.timezone.utc)
        log = SyncLog(endpoint=endpoint_label, started_at=started, status="em_andamento")
        db.add(log)
        db.commit()

        if not code:
            log.status = "erro"
            log.error_message = f"Sem externalCode pra trilha {trilha_id} em /report/courses"
            log.finished_at = dt.datetime.now(dt.timezone.utc)
            db.commit()
            continue

        try:
            payload = client.get_play_course(code, PLAY_COURSE_START_DATE, amanha)
            db.add(RawLudosSnapshot(
                endpoint=endpoint_label,
                params={"code": code, "startDate": PLAY_COURSE_START_DATE, "endDate": amanha},
                payload=payload,
            ))
            log.status = "sucesso"
            log.records_ingested = len(payload) if isinstance(payload, list) else 1
        except LudosAPIError as exc:
            logger.error("Erro sincronizando %s: %s", endpoint_label, exc)
            log.status = "erro"
            log.error_message = str(exc)[:1000]
        finally:
            log.finished_at = dt.datetime.now(dt.timezone.utc)
            db.commit()