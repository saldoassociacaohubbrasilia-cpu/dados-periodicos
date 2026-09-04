import datetime as dt
import logging
from collections import Counter, defaultdict

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.config import settings
from app.models import RawLudosSnapshot, Student, School, Turma, StudentProgress, MetricSnapshot
from app.institutions import get_institution, is_excluded_group, get_school_display_name

logger = logging.getLogger("transform")

# Trilhas acompanhadas pelo dashboard. Chave = CourseId na Ludos,
# valor = nome de exibição. Pra adicionar uma trilha nova no futuro,
# basta incluir aqui — rebuild_metrics já processa todas sozinho.
TRILHAS: dict[str, str] = {
    "41": "Trilha Saldo+",
    "43": "Trilha Pocket",
}

# Sistema de Alertas: aluno entra em alerta se nunca fez login
# (last_access nulo) OU se já passaram mais de DIAS_LIMITE_INATIVIDADE
# dias desde o último acesso (Student.last_access, vindo do log de login).
DIAS_LIMITE_INATIVIDADE = 10


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


def _build_module_thresholds(courses_payload: list) -> dict[str, list[tuple[int, str]]]:
    """A partir de /report/courses, monta pra cada courseId a lista de
    módulos na mesma ordem que a Ludos devolve, cada um com o total
    ACUMULADO de atividades até ali (limite, nome). Usado por
    _estimar_modulo_atual pra achar em qual módulo um aluno está a partir
    do activitiesPlayed dele — /report/performance não manda progresso
    por módulo, só o total de atividades jogadas no curso inteiro."""
    thresholds: dict[str, list[tuple[int, str]]] = {}
    for course in courses_payload or []:
        course_id = str(_field(course, "courseId", default=""))
        if not course_id:
            continue
        cumulative = 0
        modulos = []
        for modulo in course.get("modules") or []:
            n_atividades = len(modulo.get("activities") or []) or 1
            cumulative += n_atividades
            nome = modulo.get("moduleName") or f"Módulo {modulo.get('moduleId')}"
            modulos.append((cumulative, nome))
        thresholds[course_id] = modulos
    return thresholds


def _estimar_modulo_atual(activities_played: int, thresholds: list[tuple[int, str]]) -> str:
    """Estimativa: assume que os alunos fazem os módulos na mesma ordem
    que a Ludos lista em /report/courses, e acha o primeiro módulo cujo
    total acumulado de atividades ainda não foi ultrapassado pelo
    activitiesPlayed do aluno. Sem estrutura de módulos pra esse curso
    (ex: /report/courses ainda não sincronizado), cai no fallback antigo."""
    if not thresholds:
        return "Módulo Geral"
    for limite, nome in thresholds:
        if activities_played <= limite:
            return nome
    return thresholds[-1][1]


def _upsert_students(db: Session, players: list, school_turma_cache: dict) -> tuple[dict[str, Student], dict[str, dict]]:
    """Cria/atualiza os alunos a partir de /report/players. Devolve dois
    dicionários indexados por external_id (playerId):
    - {external_id: Student} já com .id definido, pra não reconsultar o
      banco aluno a aluno mais adiante;
    - {external_id: {"group_name": str|None, "pontuacao": float|None}} —
      turma e pontuação só existem aqui (a Ludos não manda isso em
      /report/performance), então o loop de performance consulta esse
      dicionário casando pelo mesmo playerId.

    Já vincula escola/turma aqui mesmo (não só no laço de performance) —
    assim um aluno que nunca jogou nada (por isso aparece em alerta de
    inatividade) ainda fica com a turma certa, em vez de "Sem Turma".
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
        student.account_status = _field(p, "status", default=None)
        student.pontos = _field(p, "score", default=None)
        student.moedas = _field(p, "coins", default=None)
        # Sem managerId nem managerLogin -> não tem professor responsável
        # acima -> é conta de professor/gestor/staff, não aluno de verdade.
        manager_id = _field(p, "managerId", default=None)
        manager_login = _field(p, "managerLogin", default=None)
        student.is_staff = not manager_id and not manager_login
        external_ids.append(external_id)

        grupos = _field(p, "groups", default=[]) or []
        group_name = str(grupos[0]["groupName"]).strip() if grupos and grupos[0].get("groupName") else None
        pontuacao = _field(p, "coins", "score", "points", "Pontuacao", default=None)
        extra_by_id[external_id] = {"group_name": group_name, "pontuacao": pontuacao}

        # Vincula escola/turma já aqui — mesmo que esse aluno nunca
        # apareça no /report/performance (ex: nunca jogou nada), ele
        # ainda fica com a turma certa, não "Sem Turma".
        school, turma = _get_or_create_school_turma(db, school_turma_cache, group_name or "Sem Turma")
        student.school_id = school.id
        student.turma_id = turma.id
        # Se este aluno tem um manager (gestor/professor), garanta que
        # o gestor exista como Student(is_staff=True) e vincule-o à turma
        # via a relação many-to-many `turma.managers`.
        if manager_id:
            mgr_ext = str(manager_id)
            mgr = db.execute(select(Student).where(Student.external_id == mgr_ext)).scalar_one_or_none()
            if mgr is None:
                mgr = Student(external_id=mgr_ext, login=manager_login or "")
                db.add(mgr)
                db.flush()
            mgr.is_staff = True
            # opcionalmente, associe escola do gestor
            mgr.school_id = school.id
            if mgr not in turma.managers:
                turma.managers.append(mgr)
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
    """Converte a data ISO da Ludos em datetime. Aceita tanto o formato
    com offset ('2026-05-07T17:24:01.61+00:00', usado em startDate/endDate)
    quanto com sufixo 'Z' ('2026-09-15T10:30:00Z', usado no log de acesso)
    — 'Z' vira '+00:00' antes de converter, pra funcionar em qualquer
    versão do Python, não só 3.11+. Devolve None se vier vazio ou em
    formato inesperado — nesse caso quem chamou usa 'agora' como aproximação.

    Sempre devolve um datetime com timezone (UTC quando a string não traz
    offset nenhum) — nunca naive. calcular_alerta_aluno() subtrai o valor
    devolvido aqui de um datetime.now(timezone.utc); se algum dia a Ludos
    mandar uma data sem offset, fromisoformat() devolveria naive e essa
    subtração quebraria com TypeError."""
    if not valor:
        return None
    texto = str(valor)
    if texto.endswith("Z"):
        texto = texto[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(texto)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _upsert_progress(
    db: Session, student_id: int, trilha_id: str, trilha_nome: str,
    progress_pct: float, status: str,
    started_at: "dt.datetime | None" = None, completed_at: "dt.datetime | None" = None,
) -> None:
    row = db.execute(
        select(StudentProgress).where(
            StudentProgress.student_id == student_id,
            StudentProgress.trail_external_id == trilha_id,
        )
    ).scalar_one_or_none()

    now = dt.datetime.now(dt.timezone.utc)
    if row is None:
        row = StudentProgress(
            student_id=student_id,
            trail_external_id=trilha_id,
            trail_name=trilha_nome,
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


def _process_trilha(
    db: Session, performance: list, trilha_id: str, trilha_nome: str,
    player_extra: dict, students_by_id: dict, school_turma_cache: dict,
    module_thresholds: list[tuple[int, str]],
) -> None:
    """Processa uma trilha (CourseId) inteira: filtra o /report/performance
    pra esse curso, calcula os rollups (geral, módulo, escola/turma) e
    grava tudo em MetricSnapshot já marcado com esse trilha_id — sem
    misturar números de trilhas diferentes."""
    inscritos_ids: dict[str, set] = defaultdict(set)
    engaged_ids: dict[str, set] = defaultdict(set)
    completed_ids: dict[str, set] = defaultdict(set)
    module_counts: dict[str, Counter] = defaultdict(Counter)
    # turma_stats: por GroupName exato (o que a Ludos manda) — vira a
    # tabela de turmas do dashboard, uma linha por turma.
    # escola_stats: turma_stats agrupado pelo nome real da escola via
    # GROUPNAME_TO_SCHOOL (app/institutions.py) — vira o KPI "Total de
    # Escolas", o mapa e o ranking. Sem entrada na tabela, cada turma
    # continua sendo sua própria "escola" (mesmo valor nos dois dicts).
    def _nova_stat():
        return {"inscritos": set(), "engajados": set(), "concluintes": set(),
                "pontuacao_total": 0.0, "pontuacao_n": 0}
    turma_stats: dict[str, dict] = defaultdict(_nova_stat)
    escola_stats: dict[str, dict] = defaultdict(_nova_stat)
    # Uma escola real pode agregar turmas de instituições diferentes só se
    # o cadastro em GROUPNAME_TO_INSTITUTION estiver inconsistente — rastreia
    # de fato em qual(is) instituição(ões) cada escola apareceu, em vez de
    # tentar recalcular get_institution() em cima do nome já agregado da
    # escola (que não é um GroupName válido pra bater no mapeamento).
    escola_institutions: dict[str, set] = defaultdict(set)
    # Garante que 'todas' sempre existe, mesmo com payload vazio — assim
    # o rollup geral sempre grava um snapshot fresco (ainda que zerado)
    # e o /overview nunca mostra um sync antigo como se fosse o mais recente.
    inscritos_ids["todas"]

    # --- Base de "inscritos": TODO aluno ativo do /report/players conta,
    # mesmo que ainda não tenha tocado na trilha. A Ludos só cria uma linha
    # em /report/performance quando o aluno JÁ iniciou o curso (progression
    # > 0 sempre) — não existe ali um estado "atribuído com 0% de progresso".
    # Sem esta base, "inscritos" ficava, na prática, igual a "engajados"
    # (daí a taxa de engajamento aparecer sempre 100%), e turmas inteiras
    # que ainda não começaram a trilha sumiam do rollup por escola/turma.
    # Como a Ludos não expõe em qual trilha cada aluno está matriculado,
    # aplicamos a mesma base pra todas as trilhas em TRILHAS.
    for external_id, extra in player_extra.items():
        student_account = students_by_id.get(external_id)
        if student_account is not None and (
            student_account.account_status == "BLOCKED" or student_account.is_staff
        ):
            continue
        group_name = str(extra.get("group_name") or "Sem Turma")
        if is_excluded_group(group_name):
            continue
        inst = get_institution(group_name)
        for scope in (inst, "todas"):
            inscritos_ids[scope].add(external_id)
        turma_stats[group_name]["inscritos"].add(external_id)
        escola_nome = get_school_display_name(group_name)
        escola_stats[escola_nome]["inscritos"].add(external_id)
        escola_institutions[escola_nome].add(inst)

    for perf in performance:
        course_id = _field(perf, "courseId", "CourseId", "course_id", "id_curso")
        if course_id is not None and str(course_id) != trilha_id:
            continue

        external_id = str(_field(perf, "playerId", "player_id", "id", "PlayerId", default=""))
        if not external_id:
            continue

        # Só exclui aluno BLOQUEADO na Ludos. INACTIVE (nunca logou, mas
        # ainda não foi bloqueado) continua contando — ele é "cadastrado
        # mas sem primeiro acesso", não um aluno de semestre encerrado.
        # Conta de professor/gestor (is_staff) também nunca conta como
        # aluno, mesmo tendo algum registro de "performance" na trilha.
        student_account = students_by_id.get(external_id)
        if student_account is not None and (
            student_account.account_status == "BLOCKED" or student_account.is_staff
        ):
            continue

        # Turma (GroupName) e pontuação não vêm no /report/performance — a
        # Ludos só manda isso no /report/players, casado pelo mesmo playerId.
        extra = player_extra.get(external_id, {})
        group_name = str(extra.get("group_name") or "Sem Turma")
        if is_excluded_group(group_name):
            continue
        inst = get_institution(group_name)

        progress = float(_field(perf, "progression", "progress", "progress_pct", "Complete", default=0) or 0)
        activities_played = int(_field(perf, "activitiesPlayed", "activities_played", default=0) or 0)
        module_name = _estimar_modulo_atual(activities_played, module_thresholds)
        pontuacao = extra.get("pontuacao")
        status = "concluido" if progress >= 100 else ("engajado" if progress > 0 else "inscrito")

        # startDate/endDate reais da Ludos, quando existem, são mais confiáveis
        # que "agora" pra marcar quando o aluno começou/terminou.
        started_raw = _field(perf, "startDate", "started_at")
        completed_raw = _field(perf, "endDate", "completed_at")

        for scope in (inst, "todas"):
            # Já foi contado como inscrito no laço de player_extra acima —
            # exceto quando este external_id só existe aqui por causa do
            # fallback de "missing_ids" em rebuild_metrics (payload de
            # /report/players cortado pela cota nesta rodada). O .add()
            # é idempotente (é um set), então repetir não tem custo.
            inscritos_ids[scope].add(external_id)
            if progress > 0:
                engaged_ids[scope].add(external_id)
                module_counts[scope][module_name] += 1
            if progress >= 100:
                completed_ids[scope].add(external_id)

        escola_nome = get_school_display_name(group_name)
        escola_institutions[escola_nome].add(inst)
        for gs in (turma_stats[group_name], escola_stats[escola_nome]):
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
                db, student.id, trilha_id, trilha_nome, progress, status,
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
            scope_id=f"trilha_{trilha_id}",
            scope_label=trilha_nome,
            institution=scope,
            trilha_id=trilha_id,
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
                trilha_id=trilha_id,
                inscritos=len(inscritos_ids[scope]),
                engajados=count,
                concluintes=0,
                taxa_ativacao=round(100 * count / total_com_modulo, 2),
                taxa_conclusao=0.0,
                taxa_retencao=0.0,
            ))

    # --- Rollup por turma (instituição real da turma + 'todas') — uma
    # linha por GroupName exato, usada na tabela de turmas do dashboard. ---
    for group_name, gs in turma_stats.items():
        inst = get_institution(group_name)
        n_inscritos = len(gs["inscritos"])
        n_engajados = len(gs["engajados"])
        n_concluintes = len(gs["concluintes"])
        pontuacao_media = round(gs["pontuacao_total"] / gs["pontuacao_n"], 2) if gs["pontuacao_n"] else 0.0

        for scope in {inst, "todas"}:
            db.add(MetricSnapshot(
                snapshot_date=now,
                scope_type="turma",
                scope_id=group_name,
                scope_label=group_name,
                institution=scope,
                trilha_id=trilha_id,
                inscritos=n_inscritos,
                engajados=n_engajados,
                concluintes=n_concluintes,
                taxa_ativacao=round(100 * n_engajados / n_inscritos, 2) if n_inscritos else 0.0,
                taxa_conclusao=round(100 * n_concluintes / n_inscritos, 2) if n_inscritos else 0.0,
                taxa_retencao=round(100 * n_concluintes / n_engajados, 2) if n_engajados else 0.0,
                pontuacao_media=pontuacao_media,
            ))

    # --- Rollup por escola real (turmas agregadas via GROUPNAME_TO_SCHOOL)
    # — usada no KPI "Total de Escolas", mapa e ranking. ---
    for escola_nome, gs in escola_stats.items():
        n_inscritos = len(gs["inscritos"])
        n_engajados = len(gs["engajados"])
        n_concluintes = len(gs["concluintes"])
        pontuacao_media = round(gs["pontuacao_total"] / gs["pontuacao_n"], 2) if gs["pontuacao_n"] else 0.0

        for scope in escola_institutions[escola_nome] | {"todas"}:
            db.add(MetricSnapshot(
                snapshot_date=now,
                scope_type="escola",
                scope_id=escola_nome,
                scope_label=escola_nome,
                institution=scope,
                trilha_id=trilha_id,
                inscritos=n_inscritos,
                engajados=n_engajados,
                concluintes=n_concluintes,
                taxa_ativacao=round(100 * n_engajados / n_inscritos, 2) if n_inscritos else 0.0,
                taxa_conclusao=round(100 * n_concluintes / n_inscritos, 2) if n_inscritos else 0.0,
                taxa_retencao=round(100 * n_concluintes / n_engajados, 2) if n_engajados else 0.0,
                pontuacao_media=pontuacao_media,
            ))

    logger.info(
        "%s recalculada: %s inscritos únicos, %s engajados, %s turmas, %s escolas",
        trilha_nome,
        len(inscritos_ids.get("todas", set())),
        len(engaged_ids.get("todas", set()) & inscritos_ids.get("todas", set())),
        len(turma_stats),
        len(escola_stats),
    )


def calcular_alerta_aluno(last_access: "dt.datetime | None", agora: "dt.datetime | None" = None) -> tuple:
    """
    Calcula o alerta de inatividade de UM aluno a partir do último acesso.
    Devolve (dias_sem_acesso, alerta: bool, motivo: str|None):
      - last_access nulo -> aluno nunca logou -> sempre em alerta
      - dias_sem_acesso > DIAS_LIMITE_INATIVIDADE -> em alerta
      - caso contrário -> sem alerta (motivo None)
    """
    agora = agora or dt.datetime.now(dt.timezone.utc)
    if last_access is None:
        return None, True, "Nunca acessou"
    dias = (agora - last_access).days
    if dias > DIAS_LIMITE_INATIVIDADE:
        return dias, True, f"Sem acesso há {dias} dias"
    return dias, False, None


def _aplicar_ultimo_acesso(db: Session, students_by_id: dict[str, Student], login_log: list) -> None:
    """
    Recebe o log de acesso cru ([{idPlayer, dtLog, txData}, ...]) e grava
    em cada Student o dtLog MAIS RECENTE (um mesmo aluno aparece uma vez
    por login que já fez, então precisa pegar o máximo por idPlayer).
    Assume que o endpoint devolve o histórico completo a cada chamada —
    se um dia a Ludos passar a mandar só os logins novos, essa lógica
    de "pega o maior" deixa de ser suficiente e precisaria acumular
    entre sincronizações em vez de substituir.
    """
    ultimo_por_aluno: dict[str, "dt.datetime"] = {}
    for registro in login_log:
        external_id = str(_field(registro, "idPlayer", "playerId", "player_id", default=""))
        if not external_id:
            continue
        dt_log = _parse_iso(_field(registro, "dtLog", "dt_log", "logDate"))
        if dt_log is None:
            continue
        atual = ultimo_por_aluno.get(external_id)
        if atual is None or dt_log > atual:
            ultimo_por_aluno[external_id] = dt_log

    for external_id, ultimo_acesso in ultimo_por_aluno.items():
        student = students_by_id.get(external_id)
        if student is not None:
            student.last_access = ultimo_acesso


def rebuild_metrics(db: Session) -> None:
    """
    Recalcula os agregados de TODAS as trilhas em TRILHAS (hoje: Saldo+ e
    Pocket): extrai dinamicamente escolas/turmas (GroupName) por trilha,
    vincula cada aluno à sua turma e grava o progresso individual dele —
    além dos rollups gerais, por módulo e por escola/turma (cada um
    também por instituição), usados no dashboard, com trilha_id marcado
    em cada linha pra não misturar números de trilhas diferentes.

    A distribuição por módulo é uma ESTIMATIVA: /report/performance não
    diz em qual módulo o aluno está, só o total de atividades jogadas no
    curso inteiro — _build_module_thresholds usa a estrutura real de
    módulos de /report/courses pra inferir isso (ver _estimar_modulo_atual).
    """
    players = _latest_payload(db, "/report/players") or []
    performance = _latest_payload(db, "/report/performance") or []
    login_log = _latest_payload(db, "/report/logs") or []
    courses = _latest_payload(db, "/report/courses") or []
    module_thresholds_por_trilha = _build_module_thresholds(courses)

    # Um cache só, criado antes e reaproveitado tanto pra vincular turma
    # de cada aluno (mesmo que ele nunca apareça em performance) quanto
    # pro laço de cada trilha depois — evita School/Turma duplicada pro
    # mesmo GroupName.
    school_turma_cache: dict = {}
    students_by_id, player_extra = _upsert_students(db, players, school_turma_cache)

    # Se /report/players veio cortado pela cota da Ludos nesta rodada (ver
    # LudosClient._get_single), students_by_id só cobre quem apareceu no
    # payload parcial. Sem isso, um aluno BLOCKED/staff de uma sincronização
    # anterior que não caiu nesse recorte ficaria de fora do dict e
    # _process_trilha deixaria de filtrá-lo (a checagem lá só exclui quando
    # encontra o Student), voltando a contar como ativo/engajado por engano.
    # Complementamos com quem já existe no banco, usando o último status
    # conhecido, pra manter o filtro "fail closed" em vez de "fail open".
    performance_ids = {
        str(_field(perf, "playerId", "player_id", "id", "PlayerId", default=""))
        for perf in performance
    }
    missing_ids = performance_ids - students_by_id.keys()
    missing_ids.discard("")
    if missing_ids:
        rows_existentes = db.execute(
            select(Student).where(Student.external_id.in_(missing_ids))
        ).scalars().all()
        for s in rows_existentes:
            students_by_id[s.external_id] = s

    _aplicar_ultimo_acesso(db, students_by_id, login_log)

    for trilha_id, trilha_nome in TRILHAS.items():
        _process_trilha(
            db, performance, trilha_id, trilha_nome,
            player_extra, students_by_id, school_turma_cache,
            module_thresholds_por_trilha.get(trilha_id, []),
        )

    _limpar_snapshots_antigos(db)
    db.commit()


def _limpar_snapshots_antigos(db: Session) -> None:
    """Apaga MetricSnapshot mais velho que METRIC_SNAPSHOT_RETENTION_DAYS.
    Só o snapshot_date mais recente por trilha é lido pelo dashboard hoje
    (ver _latest_date_for_trilha em app/routers/dashboard.py) — sem essa
    limpeza, cada sync (geral + módulo + escola/turma, x instituição, x
    trilha) empilha um lote novo de linhas pra sempre. Roda a cada
    rebuild_metrics(), então nunca deixa a tabela crescer além da janela
    de retenção configurada."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=settings.metric_snapshot_retention_days)
    resultado = db.execute(delete(MetricSnapshot).where(MetricSnapshot.snapshot_date < cutoff))
    if resultado.rowcount:
        logger.info("Limpeza de metric_snapshot: %s linhas com mais de %sd removidas.",
                     resultado.rowcount, settings.metric_snapshot_retention_days)