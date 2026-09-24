"""
Mapeamento de instituição e de coordenadas por GroupName (o campo que a
Ludos usa para identificar escola/turma).

A Ludos não manda um campo de "instituição" — então quem sabe se uma
turma é da Secretaria de Educação ou da CVP é você. Preencha
GROUPNAME_TO_INSTITUTION abaixo com os nomes reais de GroupName que
pertencem à CVP; qualquer GroupName que não estiver listado aqui é
tratado como "secretaria" (o padrão, já que é a maioria das escolas).

A comparação ignora maiúsculas/minúsculas e espaços nas pontas, então
"CVP - Turma A" e "cvp - turma a" batem com a mesma entrada.
"""

# Cursos (CourseId da Ludos) que o dashboard acompanha, e a categoria de
# cada um. A categoria vem do CURSO, não do nome do grupo: é o curso que a
# Ludos separa de forma confiável (CVP 46 e ONGs são cursos próprios lá).
#   - usa_escola: SEEDF organiza Escola → Turma; CVP não tem escola — o
#     nível simplesmente não existe (sem KPI de escolas, mapa ou ranking).
# Curso novo do CVP = uma entrada nova aqui, sem mudar mais nada.
CURSOS: dict[str, dict] = {
    "41": {"nome": "Trilha Saldo+", "categoria": "secretaria", "usa_escola": True},
    "43": {"nome": "Trilha Pocket", "categoria": "secretaria", "usa_escola": True},
    "45": {"nome": "CVP 46", "categoria": "cvp", "usa_escola": False},
    "46": {"nome": "ONGs", "categoria": "cvp", "usa_escola": False},
}


def curso_usa_escola(course_id: str) -> bool:
    return CURSOS.get(str(course_id), {}).get("usa_escola", True)


# Contas de teste da equipe (login na Ludos, sem diferenciar maiúsculas) —
# ficam fora de todos os números, em qualquer categoria. "Danielle" é a
# conta usada pra conferir o painel do aluno (está em turma da SEEDF, na
# Equipe Gestão e no CVP - 46 ao mesmo tempo).
CONTAS_TESTE: set[str] = {
    "danielle",
}


def is_conta_teste(login: str | None) -> bool:
    return bool(login) and str(login).strip().lower() in CONTAS_TESTE


# Normalmente não precisa preencher: a categoria de cada grupo é deduzida
# de /report/courses (ver montar_categorias_por_grupo). Use só pra forçar
# um grupo específico: "GroupName exatamente como vem da Ludos" -> "cvp".
GROUPNAME_TO_INSTITUTION: dict[str, str] = {
    "CVP - 46": "cvp",
}

# Coordenadas de cada ESCOLA REAL (a chave é o nome que sai de
# get_school_display_name() em GROUPNAME_TO_SCHOOL abaixo, não o nome da
# turma) — pra aparecerem no mapa. Quem não estiver aqui simplesmente não
# aparece no mapa — mas continua aparecendo nos gráficos e na tabela.
#
# Buscadas por endereço público (CRE/SEEDF, QEdu) em 2026-09; a maioria
# está no endereço exato da escola, mas duas ficaram aproximadas — ajuste
# se tiver a coordenada exata:
#   - "CED 17 CEI": a busca de geocoding devolveu um ponto muito longe de
#     Ceilândia (~40km) — usei o centro conhecido do bairro Setor O.
#   - "CEMI 310": não confirmei 100% que é o mesmo prédio do "CED 310 de
#     Santa Maria" (só nome parecido + mesmo número de quadra "310").
SCHOOL_COORDINATES: dict[str, tuple[float, float]] = {
    "CED 01 Itapoã": (-15.7483, -47.7592),       # DF-250 Km 2,5, Itapoã
    "CEMAB": (-15.8368, -48.0528),                # QSA 03/05, Taguatinga Sul
    "CEDLAN": (-15.7386, -47.8594),               # SHIN CA 02, Lago Norte
    "CEMI 310": (-16.0122, -48.0142),             # Quadra CL 310, Santa Maria (aproximado)
    "CED 17 CEI": (-15.8150, -48.1072),           # EQNO 1/3, Setor O, Ceilândia (aproximado)
    "CED Incra 08": (-15.7404, -48.1704),         # Quadra 4 AE, Incra 8, Brazlândia
}

VALID_INSTITUTIONS = {"todas", "secretaria", "cvp"}

_NORMALIZED_MAP = {k.strip().lower(): v for k, v in GROUPNAME_TO_INSTITUTION.items()}

# Grupos que existem na Ludos mas NÃO são turma real de aluno — times de
# teste/piloto e conta de gestão interna. Já ficam fora dos agregados hoje
# porque essas contas não têm managerId (viram is_staff=True em
# transform.py), mas listar aqui explicitamente documenta a intenção e
# evita que voltem a contar por engano se um dia ganharem um gestor na
# Ludos. Adicione aqui qualquer outro grupo que apareça e não deva contar
# (ex: uma trilha ainda não contratada pela Secretaria).
EXCLUDED_GROUPS: set[str] = {
    "Trilha Pocket",
    "Equipe Gestão",
}

_NORMALIZED_EXCLUDED = {g.strip().lower() for g in EXCLUDED_GROUPS}


def is_excluded_group(group_name: str | None) -> bool:
    """True se esse GroupName não deve contar em nenhum agregado do
    dashboard (ver EXCLUDED_GROUPS acima)."""
    return bool(group_name) and str(group_name).strip().lower() in _NORMALIZED_EXCLUDED


# Preencha aqui: "GroupName da turma, como vem da Ludos" -> "Nome da escola
# real". A Ludos só tem o conceito de turma (GroupName) — não existe uma
# entidade "escola" separada lá, e não dá pra cadastrar escola por lá,
# só turma. Várias turmas pertencem à mesma escola; sem entrada aqui, a
# turma aparece como sua própria "escola" no dashboard (1 turma = 1
# "escola", como era antes desta tabela existir).
#
# Ainda em validação com a Secretaria de Educação — mantido estático,
# edite à mão conforme a lista de escolas for confirmada.
GROUPNAME_TO_SCHOOL: dict[str, str] = {
    "CED 01 ITAPOÃ Turma H": "CED 01 Itapoã",
    "CED 01 ITAPOÃ Turma I": "CED 01 Itapoã",
    "CED 01 ITAPOÃ Turma J": "CED 01 Itapoã",
    "CED 01 ITAPOÃ Turma K": "CED 01 Itapoã",
    "CED 01 ITAPOÃ Turma L": "CED 01 Itapoã",
    "CED 01 ITAPOÃ Turma M": "CED 01 Itapoã",
    "CED 01 ITAPOÃ Turma N": "CED 01 Itapoã",
    "CEMAB Turma J": "CEMAB",
    "CEMAB Turma K": "CEMAB",
    "CEMAB Turma L": "CEMAB",
    "CED 17 CEI Turma G": "CED 17 CEI",
    "CED 17 CEI Turma H": "CED 17 CEI",
    "CEMI 310 Turma C": "CEMI 310",
    "CEMI 310 Turma D": "CEMI 310",
    "CED Incra 08 Turma C": "CED Incra 08",
    "CEDLAN Turma A": "CEDLAN",
    "CEDLAN Turma B": "CEDLAN",
    "CEDLAN Turma C": "CEDLAN",
    "CEDLAN Turma D": "CEDLAN",
    "CEDLAN Turma E": "CEDLAN",
    "CEDLAN Turma F": "CEDLAN",
}

_NORMALIZED_SCHOOL_MAP = {k.strip().lower(): v for k, v in GROUPNAME_TO_SCHOOL.items()}


def get_school_display_name(group_name: str | None) -> str:
    """Nome da escola real que agrupa essa turma pro rollup 'escola' do
    dashboard (KPI 'Total de Escolas', mapa, ranking). Sem entrada em
    GROUPNAME_TO_SCHOOL, devolve o próprio GroupName — a turma continua
    aparecendo, só que como sua própria 'escola'."""
    if not group_name:
        return "Sem Turma"
    nome = str(group_name).strip()
    return _NORMALIZED_SCHOOL_MAP.get(nome.lower(), nome)


def montar_categorias_por_grupo(courses_payload: list | None) -> dict[str, str]:
    """{groupName normalizado: 'secretaria' | 'cvp'} a partir de
    /report/courses. Um grupo vinculado a algum curso da SEEDF é SEEDF;
    vinculado só a cursos do CVP, é CVP — é assim que um grupo novo de ONG
    entra sozinho, sem cadastro manual. A ordem importa: na Ludos as
    turmas da SEEDF também estão vinculadas aos cursos 45/46, e continuam
    sendo SEEDF. GROUPNAME_TO_INSTITUTION tem a palavra final."""
    por_grupo: dict[str, set[str]] = {}
    for course in courses_payload or []:
        categoria = CURSOS.get(str(course.get("courseId")), {}).get("categoria")
        if not categoria:
            continue
        for g in course.get("groups") or []:
            nome = str(g.get("groupName") or "").strip().lower()
            if nome:
                por_grupo.setdefault(nome, set()).add(categoria)
    categorias = {
        nome: "secretaria" if "secretaria" in cats else "cvp"
        for nome, cats in por_grupo.items()
    }
    categorias.update(_NORMALIZED_MAP)
    return categorias


def get_institution(group_name: str | None, categorias: dict[str, str] | None = None) -> str:
    """Retorna 'cvp' ou 'secretaria' para um GroupName. Nunca retorna 'todas'
    aqui — 'todas' é só um agregado calculado em cima dessas duas.
    `categorias`: resultado de montar_categorias_por_grupo; sem ele, só
    vale o GROUPNAME_TO_INSTITUTION manual."""
    if not group_name:
        return "secretaria"
    nome = str(group_name).strip().lower()
    return (categorias or _NORMALIZED_MAP).get(nome, "secretaria")


def normalize_institution(instituicao: str | None) -> str:
    """Normaliza o parâmetro `instituicao` vindo da query string da API."""
    inst = (instituicao or "todas").strip().lower()
    return inst if inst in VALID_INSTITUTIONS else "todas"