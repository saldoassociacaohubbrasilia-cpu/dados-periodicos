import datetime as dt
import logging
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RawLudosSnapshot, Student, School, Turma, StudentProgress, MetricSnapshot
from app.institutions import get_institution

logger = logging.getLogger("transform")

TRILHA_EXTERNAL_ID = "41"
TRILHA_NOME = "Trilha Saldo+"


def _latest_payload(db: Session, endpoint: str):
    row = db.execute(
        select(RawLudosSnapshot)
        .where(RawLudosSnapshot.endpoint == endpoint)
        .order_by(RawLudosSnapshot.fetched_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row.payload if row else None


def _field(record: dict, *candidates, default=None):
    """Tenta múltiplas chaves possíveis para o mesmo dado."""
    for key in candidates:
        if key in record:
            return record[key]
    return default


def _upsert_students(db: Session, players: list) -> tuple[dict[str, Student], dict[str, dict]]:
    """Cria/atualiza os alunos a partir de /report/players. Devolve dois
    dicionários indexados por external_id (playerId):
    - {external_id: Student} já com .id definido, pra não reconsultar o
      banco aluno a aluno mais adiante;
    - {external_id: {"group_name": str|None, "pontuacao": float|None}} —
      turma e pontuação só existem aqui (a Ludos não manda isso em
      /report/performance), então o loop de performance consulta esse
      dicionário casando pelo mesmo playerId.
    """
    external_ids = []
    extra_by_id: dict[str, dict] = {}
    # Evita criar 2x o mesmo aluno se a Ludos repetir o playerId na mesma
    # busca (páginas sobrepostas) — sem isso, o segundo INSERT do mesmo
    # external_id quebra com "duplicate key" ao comitar.
    seen_this_run: dict[str, Student] = {}
    for p in players:
        external_id = str(_field(p, "playerId", "id", "player_id", default=""))
        if not external_id:
            continue
        login = _field(p, "login", "username", default="")
        student = seen_this_run.get(external_id)
        if student is None:
            student = db.execute(
                select(Student).where(Student.external_id == external_id)
            ).scalar_one_or_none()
        if student is None:
            student = Student(external_id=external_id, login=login)
            db.add(student)
        seen_this_run[external_id] = student
        student.login = login
        student.name = _field(p, "playerName", "name", "nome")
        external_ids.append(external_id)

        grupos = _field(p, "groups", default=[]) or []
        group_name = str(grupos[0]["groupName"]).strip() if grupos and grupos[0].get("groupName") else None
        pontuacao = _field(p, "coins", "score", "points", "Pontuacao", default=None)
        extra_by_id[external_id] = {"group_name": group_name, "pontuacao": pontuacao}
    db.commit()

    if not external_ids:
        return {}, {}
    rows = db.execute(
        select(Student).where(Student.external_id.in_(external_ids))
    ).scalars().all()
    return {s.external_id: s for s in rows}, extra_by_id


def _get_or_create_school_turma(db: Session, cache: dict, group_name: str) -> tuple[School, Turma]:
    """A Ludos usa GroupName pra representar escola e turma ao mesmo tempo —
    então criamos/reaproveitamos uma School e uma Turma com esse nome.
    `cache` evita reconsultar o banco pra cada registro do mesmo GroupName."""
    if group_name in cache:
        return cache[group_name]

    school = db.execute(select(School).where(School.external_id == group_name)).scalar_one_or_none()
    if school is None:
        school = School(external_id=group_name, name=group_name)
        db.add(school)
        db.flush()

    turma = db.execute(select(Turma).where(Turma.external_id == group_name)).scalar_one_or_none()
    if turma is None:
        turma = Turma(external_id=group_name, name=group_name, school_id=school.id)
        db.add(turma)
        db.flush()

    cache[group_name] = (school, turma)
    return school, turma


def _parse_iso(valor) -> "dt.datetime | None":
    """Converte a data ISO da Ludos (ex: '2026-05-07T17:24:01.61+00:00') em
    datetime. Devolve None se vier vazio ou em formato inesperado — nesse
    caso quem chamou usa 'agora' como aproximação."""
    if not valor:
        return None
    try:
        return dt.datetime.fromisoformat(str(valor))
    except ValueError:
        return None


def _upsert_progress(
    db: Session, student_id: int, progress_pct: float, status: str,
    started_at: "dt.datetime | None" = None, completed_at: "dt.datetime | None" = None,
) -> None:
    row = db.execute(
        select(StudentProgress).where(
            StudentProgress.student_id == student_id,
            StudentProgress.trail_external_id == TRILHA_EXTERNAL_ID,
        )
    ).scalar_one_or_none()

    now = dt.datetime.now(dt.timezone.utc)
    if row is None:
        row = StudentProgress(
            student_id=student_id,
            trail_external_id=TRILHA_EXTERNAL_ID,
            trail_name=TRILHA_NOME,
            progress_pct=progress_pct,
            status=status,
            started_at=started_at or now,
        )
        if status == "concluido":
            row.completed_at = completed_at or now
        db.add(row)
    else:
        row.progress_pct = progress_pct
        row.status = status
        if started_at is not None:
            row.started_at = started_at
        if status == "concluido" and row.completed_at is None:
            row.completed_at = completed_at or now


def rebuild_metrics(db: Session) -> None:
    """
    Recalcula os agregados considerando estritamente a TRILHA SALDO+ (CourseId 41):
    extrai dinamicamente escolas/turmas (GroupName), vincula cada aluno à sua
    turma e grava o progresso individual dele — além dos rollups gerais, por
    módulo e por escola/turma (cada um também por instituição) usados no dashboard.
    """
    players = _latest_payload(db, "/report/players") or []
    performance = _latest_payload(db, "/report/performance") or []

    students_by_id, player_extra = _upsert_students(db, players)
    school_turma_cache: dict = {}

    # --- Estruturas por instituição ('todas' sempre agrega tudo) ---
    inscritos_ids: dict[str, set] = defaultdict(set)
    engaged_ids: dict[str, set] = defaultdict(set)
    completed_ids: dict[str, set] = defaultdict(set)
    module_counts: dict[str, Counter] = defaultdict(Counter)

    # --- Estrutura por escola/turma (GroupName) ---
    group_stats: dict[str, dict] = defaultdict(lambda: {
        "inscritos": set(), "engajados": set(), "concluintes": set(),
        "pontuacao_total": 0.0, "pontuacao_n": 0,
    })

    # Garante que 'todas' sempre existe, mesmo que o payload venha vazio ou
    # sem nenhum registro do CourseId 41 — assim o rollup geral sempre grava
    # um snapshot fresco (ainda que zerado) e o /overview nunca mostra um
    # sync antigo como se fosse o mais recente.
    inscritos_ids["todas"]

    for perf in performance:
        course_id = _field(perf, "courseId", "CourseId", "course_id", "id_curso")
        if course_id is not None and str(course_id) != "41":
            continue

        external_id = str(_field(perf, "playerId", "player_id", "id", "PlayerId", default=""))
        if not external_id:
            continue

        # Turma (GroupName) e pontuação não vêm no /report/performance — a
        # Ludos só manda isso no /report/players, casado pelo mesmo playerId.
        extra = player_extra.get(external_id, {})
        group_name = str(extra.get("group_name") or "Sem Turma")
        inst = get_institution(group_name)

        progress = float(_field(perf, "progression", "progress", "progress_pct", "Complete", default=0) or 0)
        module_name = str(_field(perf, "ModuleId", "module_name", "modulo", default="Módulo Geral"))
        pontuacao = extra.get("pontuacao")
        status = "concluido" if progress >= 100 else ("engajado" if progress > 0 else "inscrito")

        # startDate/endDate reais da Ludos, quando existem, são mais confiáveis
        # que "agora" pra marcar quando o aluno começou/terminou.
        started_raw = _field(perf, "startDate", "started_at")
        completed_raw = _field(perf, "endDate", "completed_at")

        for scope in (inst, "todas"):
            inscritos_ids[scope].add(external_id)
            if progress > 0:
                engaged_ids[scope].add(external_id)
                module_counts[scope][module_name] += 1
            if progress >= 100:
                completed_ids[scope].add(external_id)

        gs = group_stats[group_name]
        gs["inscritos"].add(external_id)
        if progress > 0:
            gs["engajados"].add(external_id)
        if progress >= 100:
            gs["concluintes"].add(external_id)
        if pontuacao is not None:
            gs["pontuacao_total"] += float(pontuacao)
            gs["pontuacao_n"] += 1

        # Vincula o aluno à escola/turma e grava o progresso individual dele
        school, turma = _get_or_create_school_turma(db, school_turma_cache, group_name)
        student = students_by_id.get(external_id)
        if student is not None:
            student.school_id = school.id
            student.turma_id = turma.id
            _upsert_progress(
                db, student.id, progress, status,
                started_at=_parse_iso(started_raw), completed_at=_parse_iso(completed_raw),
            )

    now = dt.datetime.now(dt.timezone.utc)

    # --- Rollup geral (por instituição + 'todas') ---
    for scope in inscritos_ids:
        total_inscritos = len(inscritos_ids[scope])
        total_engajados = len(engaged_ids[scope] & inscritos_ids[scope])
        total_concluintes = len(completed_ids[scope] & inscritos_ids[scope])

        db.add(MetricSnapshot(
            snapshot_date=now,
            scope_type="geral",
            scope_id="trilha_saldo_41",
            scope_label=TRILHA_NOME,
            institution=scope,
            inscritos=total_inscritos,
            engajados=total_engajados,
            concluintes=total_concluintes,
            taxa_ativacao=round(100 * total_engajados / total_inscritos, 2) if total_inscritos else 0.0,
            taxa_conclusao=round(100 * total_concluintes / total_inscritos, 2) if total_inscritos else 0.0,
            taxa_retencao=round(100 * total_concluintes / total_engajados, 2) if total_engajados else 0.0,
        ))

    # --- Rollup por módulo (por instituição + 'todas') ---
    for scope, counts in module_counts.items():
        total_com_modulo = sum(counts.values()) or 1
        for mod_name, count in counts.items():
            db.add(MetricSnapshot(
                snapshot_date=now,
                scope_type="trilha",
                scope_id=mod_name,
                scope_label=f"Módulo {mod_name}",
                institution=scope,
                inscritos=len(inscritos_ids[scope]),
                engajados=count,
                concluintes=0,
                taxa_ativacao=round(100 * count / total_com_modulo, 2),
                taxa_conclusao=0.0,
                taxa_retencao=0.0,
            ))

    # --- Rollup por escola/turma (instituição real da turma + 'todas') ---
    for group_name, gs in group_stats.items():
        inst = get_institution(group_name)
        n_inscritos = len(gs["inscritos"])
        n_engajados = len(gs["engajados"])
        n_concluintes = len(gs["concluintes"])
        pontuacao_media = round(gs["pontuacao_total"] / gs["pontuacao_n"], 2) if gs["pontuacao_n"] else 0.0

        for scope in {inst, "todas"}:
            db.add(MetricSnapshot(
                snapshot_date=now,
                scope_type="escola",
                scope_id=group_name,
                scope_label=group_name,
                institution=scope,
                inscritos=n_inscritos,
                engajados=n_engajados,
                concluintes=n_concluintes,
                taxa_ativacao=round(100 * n_engajados / n_inscritos, 2) if n_inscritos else 0.0,
                taxa_conclusao=round(100 * n_concluintes / n_inscritos, 2) if n_inscritos else 0.0,
                taxa_retencao=round(100 * n_concluintes / n_engajados, 2) if n_engajados else 0.0,
                pontuacao_media=pontuacao_media,
            ))

    db.commit()
    logger.info(
        "Métricas da Trilha Saldo+ recalculadas: %s inscritos únicos, %s engajados, %s escolas/turmas",
        len(inscritos_ids.get("todas", set())),
        len(engaged_ids.get("todas", set()) & inscritos_ids.get("todas", set())),
        len(group_stats),
    )