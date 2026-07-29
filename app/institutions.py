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

# Preencha aqui: "GroupName exatamente como vem da Ludos" -> "cvp"
GROUPNAME_TO_INSTITUTION: dict[str, str] = {
    # "CVP - Turma Exemplo": "cvp",
}

# Preencha aqui as coordenadas de cada escola/turma (GroupName -> (lat, lng))
# para elas aparecerem no mapa. Quem não estiver aqui simplesmente não
# aparece no mapa — mas continua aparecendo nos gráficos e na tabela.
SCHOOL_COORDINATES: dict[str, tuple[float, float]] = {
    # "CED Jardins": (-15.793, -47.882),
}

VALID_INSTITUTIONS = {"todas", "secretaria", "cvp"}

_NORMALIZED_MAP = {k.strip().lower(): v for k, v in GROUPNAME_TO_INSTITUTION.items()}


def get_institution(group_name: str | None) -> str:
    """Retorna 'cvp' ou 'secretaria' para um GroupName. Nunca retorna 'todas'
    aqui — 'todas' é só um agregado calculado em cima dessas duas."""
    if not group_name:
        return "secretaria"
    return _NORMALIZED_MAP.get(str(group_name).strip().lower(), "secretaria")


def normalize_institution(instituicao: str | None) -> str:
    """Normaliza o parâmetro `instituicao` vindo da query string da API."""
    inst = (instituicao or "todas").strip().lower()
    return inst if inst in VALID_INSTITUTIONS else "todas"