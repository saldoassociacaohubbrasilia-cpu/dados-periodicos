import io
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Turma, Student, StudentProgress
from app.ingestion.transform import calcular_alerta_aluno, TRILHAS
from app.institutions import get_school_display_name, get_institution, is_excluded_group, normalize_institution
from app.auth import get_current_user

router = APIRouter(prefix="/api/v1/turma", tags=["relatorio-turma"], dependencies=[Depends(get_current_user)])

NAVY = "#002364"
GREEN = "#10B981"

# Mesmo default usado em app/routers/dashboard.py — precisa bater com a
# mesma chave em app/ingestion/transform.py:TRILHAS.
TRILHA_PADRAO = "41"

STATUS_LABEL = {"concluido": "Concluído", "engajado": "Engajado", "inscrito": "Inscrito"}

# --- Ranking de Estudantes por performance ---
# Mesma fórmula do script de diagnóstico pré-semestre:
#   score = PESO_PROGRESSAO * progresso_pct
#         + PESO_PONTOS     * pontos_normalizados
#         + PESO_MOEDAS     * moedas_normalizados
# pontos/moedas são normalizados min-max pra escala 0-100 DENTRO DA
# TURMA antes de entrar na conta — sem isso, comparar pontos (que pode
# ir a milhares) direto com progresso (0-100%) não faz sentido.
PESO_PROGRESSAO = 0.60
PESO_PONTOS = 0.25
PESO_MOEDAS = 0.15


def _slug(texto: str) -> str:
    """Vira um nome de arquivo seguro (sem espaço/acento/caractere especial)."""
    limpo = re.sub(r"[^A-Za-z0-9]+", "_", texto).strip("_")
    return limpo or "turma"


def _normalizar_0_100(valores: list[float]) -> list[float]:
    """Normalização min-max pra escala 0-100. Turma inteira com o mesmo
    valor (ou lista vazia) -> todo mundo fica em 0 (sem variação pra medir)."""
    if not valores:
        return []
    minimo, maximo = min(valores), max(valores)
    if maximo == minimo:
        return [0.0] * len(valores)
    return [(v - minimo) / (maximo - minimo) * 100 for v in valores]


def _buscar_relatorio_turma(db: Session, nome: str, trilha: str = TRILHA_PADRAO) -> dict:
    turma = db.execute(select(Turma).where(Turma.name == nome)).scalar_one_or_none()
    if turma is None:
        raise HTTPException(status_code=404, detail=f"Turma '{nome}' não encontrada.")

    alunos = db.execute(select(Student).where(Student.turma_id == turma.id)).scalars().all()

    # Uma única query pra todos os alunos da turma, em vez de um SELECT de
    # StudentProgress por aluno dentro do loop (N+1 queries). Antes era
    # fixo em trail_external_id == "41" (Trilha Saldo+) — o relatório da
    # turma sempre mostrava o progresso da Saldo+ mesmo quando a Trilha
    # Pocket estava selecionada no dashboard. Agora respeita o mesmo
    # parâmetro `trilha` que /api/v1/dashboard já usa.
    progresso_por_aluno: dict[int, StudentProgress] = {}
    if alunos:
        progress_rows = db.execute(
            select(StudentProgress).where(
                StudentProgress.student_id.in_([a.id for a in alunos]),
                StudentProgress.trail_external_id == trilha,
            )
        ).scalars().all()
        progresso_por_aluno = {p.student_id: p for p in progress_rows}

    linhas = []
    for aluno in alunos:
        progresso = progresso_por_aluno.get(aluno.id)
        status = progresso.status if progresso else "inscrito"
        dias_sem_acesso, alerta, motivo_alerta = calcular_alerta_aluno(aluno.last_access)
        linhas.append({
            "nome": aluno.name or aluno.login,
            "login": aluno.login,
            "progresso_pct": round(progresso.progress_pct, 1) if progresso else 0.0,
            "pontos": aluno.pontos if aluno.pontos is not None else 0,
            "moedas": aluno.moedas if aluno.moedas is not None else 0,
            # Módulo real (via /report/play/course, ver
            # transform.py:_build_module_by_student) — None quando ainda
            # não sincronizamos nenhuma jogada dele nessa trilha.
            "modulo": (progresso.modulo_atual if progresso and progresso.modulo_atual else "—"),
            "status": STATUS_LABEL.get(status, status),
            "dias_sem_acesso": dias_sem_acesso,
            "alerta_inatividade": alerta,
            "motivo_alerta": motivo_alerta,
            "concluido_em": (
                progresso.completed_at.strftime("%d/%m/%Y")
                if progresso and progresso.completed_at else "—"
            ),
        })

    pontos_norm = _normalizar_0_100([l["pontos"] for l in linhas])
    moedas_norm = _normalizar_0_100([l["moedas"] for l in linhas])
    for linha, p_norm, m_norm in zip(linhas, pontos_norm, moedas_norm):
        linha["score_engajamento"] = round(
            PESO_PROGRESSAO * linha["progresso_pct"] + PESO_PONTOS * p_norm + PESO_MOEDAS * m_norm, 2
        )

    linhas.sort(key=lambda l: l["score_engajamento"], reverse=True)
    for posicao, linha in enumerate(linhas, start=1):
        linha["posicao_na_turma"] = posicao

    return {
        "turma": turma.name,
        "escola": get_school_display_name(turma.name),
        "trilha": TRILHAS.get(trilha, trilha),
        "total_alunos": len(linhas),
        "engajados": sum(1 for l in linhas if l["progresso_pct"] > 0),
        "concluintes": sum(1 for l in linhas if l["progresso_pct"] >= 100),
        "em_alerta": sum(1 for l in linhas if l["alerta_inatividade"]),
        "alunos": linhas,
    }


def _buscar_relatorio_geral(db: Session, trilha: str, instituicao: str) -> dict:
    """Mesmos dados de _buscar_relatorio_turma, só que pra TODAS as turmas
    de uma vez (respeitando o filtro de instituição) — usado pelo
    relatório geral em Excel. Busca tudo em 3 queries (turmas, alunos,
    progresso) em vez de repetir _buscar_relatorio_turma por turma, que
    faria 2 queries a mais por turma sem necessidade."""
    inst_filtro = normalize_institution(instituicao)

    turmas = db.execute(select(Turma)).scalars().all()
    turmas = [t for t in turmas if not is_excluded_group(t.name)]
    if inst_filtro != "todas":
        turmas = [t for t in turmas if get_institution(t.name) == inst_filtro]
    turmas.sort(key=lambda t: (get_school_display_name(t.name), t.name))

    turma_ids = [t.id for t in turmas]
    alunos = (
        db.execute(select(Student).where(Student.turma_id.in_(turma_ids))).scalars().all()
        if turma_ids else []
    )

    progresso_por_aluno: dict[int, StudentProgress] = {}
    if alunos:
        progress_rows = db.execute(
            select(StudentProgress).where(
                StudentProgress.student_id.in_([a.id for a in alunos]),
                StudentProgress.trail_external_id == trilha,
            )
        ).scalars().all()
        progresso_por_aluno = {p.student_id: p for p in progress_rows}

    alunos_por_turma: dict[int, list[Student]] = {}
    for aluno in alunos:
        alunos_por_turma.setdefault(aluno.turma_id, []).append(aluno)

    linhas_geral = []
    resumo_por_escola: dict[str, dict] = {}

    for turma in turmas:
        escola = get_school_display_name(turma.name)

        linhas_turma = []
        for aluno in alunos_por_turma.get(turma.id, []):
            progresso = progresso_por_aluno.get(aluno.id)
            status = progresso.status if progresso else "inscrito"
            dias_sem_acesso, alerta, motivo_alerta = calcular_alerta_aluno(aluno.last_access)
            linhas_turma.append({
                "escola": escola,
                "turma": turma.name,
                "nome": aluno.name or aluno.login,
                "login": aluno.login,
                "progresso_pct": round(progresso.progress_pct, 1) if progresso else 0.0,
                "pontos": aluno.pontos if aluno.pontos is not None else 0,
                "moedas": aluno.moedas if aluno.moedas is not None else 0,
                "modulo": (progresso.modulo_atual if progresso and progresso.modulo_atual else "—"),
                "status": STATUS_LABEL.get(status, status),
                "alerta_inatividade": alerta,
                "motivo_alerta": motivo_alerta,
                "concluido_em": (
                    progresso.completed_at.strftime("%d/%m/%Y")
                    if progresso and progresso.completed_at else "—"
                ),
            })

        pontos_norm = _normalizar_0_100([l["pontos"] for l in linhas_turma])
        moedas_norm = _normalizar_0_100([l["moedas"] for l in linhas_turma])
        for linha, p_norm, m_norm in zip(linhas_turma, pontos_norm, moedas_norm):
            linha["score_engajamento"] = round(
                PESO_PROGRESSAO * linha["progresso_pct"] + PESO_PONTOS * p_norm + PESO_MOEDAS * m_norm, 2
            )
        linhas_turma.sort(key=lambda l: l["score_engajamento"], reverse=True)
        for posicao, linha in enumerate(linhas_turma, start=1):
            linha["posicao_na_turma"] = posicao

        linhas_geral.extend(linhas_turma)

        resumo = resumo_por_escola.setdefault(escola, {
            "total_alunos": 0, "engajados": 0, "concluintes": 0, "em_alerta": 0,
        })
        resumo["total_alunos"] += len(linhas_turma)
        resumo["engajados"] += sum(1 for l in linhas_turma if l["progresso_pct"] > 0)
        resumo["concluintes"] += sum(1 for l in linhas_turma if l["progresso_pct"] >= 100)
        resumo["em_alerta"] += sum(1 for l in linhas_turma if l["alerta_inatividade"])

    resumo_escolas = [
        {
            "escola": nome,
            "total_alunos": r["total_alunos"],
            "engajados": r["engajados"],
            "concluintes": r["concluintes"],
            "em_alerta": r["em_alerta"],
            "taxa_engajamento": round(100 * r["engajados"] / r["total_alunos"], 1) if r["total_alunos"] else 0.0,
        }
        for nome, r in sorted(resumo_por_escola.items())
    ]

    return {
        "instituicao": inst_filtro,
        "trilha": TRILHAS.get(trilha, trilha),
        "total_escolas": len(resumo_escolas),
        "total_turmas": len(turmas),
        "total_alunos": len(linhas_geral),
        "alunos": linhas_geral,
        "resumo_por_escola": resumo_escolas,
    }


@router.get("/relatorio")
def get_relatorio_turma(nome: str, trilha: str = TRILHA_PADRAO, db: Session = Depends(get_db)):
    """Dados do relatório de uma turma — usado pelo modal 'Ver Alunos' no dashboard.
    Passe ?trilha=43 para o progresso na Trilha Pocket (default: 41, Saldo+)."""
    return _buscar_relatorio_turma(db, nome, trilha)


@router.get("/gestores")
def get_gestores_turma(nome: str, db: Session = Depends(get_db)):
    """Professores/coordenadores responsáveis por uma turma (Student com
    is_staff=True, vinculados via a tabela turma_manager). Alimentado pelo
    managerId/managerLogin que a Ludos manda em /report/players."""
    turma = db.execute(select(Turma).where(Turma.name == nome)).scalar_one_or_none()
    if turma is None:
        raise HTTPException(status_code=404, detail=f"Turma '{nome}' não encontrada.")

    return {
        "turma": turma.name,
        "gestores": [
            {"nome": gestor.name or gestor.login, "login": gestor.login}
            for gestor in turma.managers
        ],
    }


@router.get("/relatorio/pdf")
def get_relatorio_turma_pdf(nome: str, trilha: str = TRILHA_PADRAO, db: Session = Depends(get_db)):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    dados = _buscar_relatorio_turma(db, nome, trilha)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    titulo_style = ParagraphStyle("TituloSaldo", parent=styles["Title"], textColor=colors.HexColor(NAVY), fontSize=18)
    subtitulo_style = ParagraphStyle("SubtituloSaldo", parent=styles["Normal"], textColor=colors.HexColor("#64748B"), fontSize=9)

    story = [
        Paragraph(f"{dados['trilha']} — Relatório da turma {dados['turma']}", titulo_style),
        Paragraph(f"Gerado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} (UTC)", subtitulo_style),
        Spacer(1, 14),
        Paragraph(
            f"{dados['total_alunos']} estudantes · {dados['engajados']} engajados · {dados['concluintes']} concluintes",
            styles["Normal"],
        ),
        Spacer(1, 14),
    ]

    # Nome, login, módulo e motivo do alerta viram Paragraph (não string
    # crua) — login da Ludos costuma ser um token longo sem espaço nenhum
    # (ex: "REG6CED01ITAPOAKADRIELLIMA"), e uma célula de Table com string
    # crua não quebra linha nesse caso: o texto simplesmente vazava por
    # cima da coluna vizinha. Paragraph quebra até palavra sem espaço
    # (splitLongWords, ligado por padrão no ParagraphStyle do reportlab).
    corpo_style = ParagraphStyle("CorpoTabela", parent=styles["Normal"], fontSize=8, leading=9.5)
    login_style = ParagraphStyle("LoginTabela", parent=corpo_style, fontSize=7, leading=8)
    # Cabeçalho também vira Paragraph — string crua não quebra linha, e
    # "Concluído em" numa coluna estreita cortava a palavra no meio.
    cabecalho_style = ParagraphStyle(
        "CabecalhoTabela", parent=styles["Normal"], fontSize=8.5, leading=10,
        textColor=colors.white, fontName="Helvetica-Bold",
    )

    # Pontos/moedas saíram da tabela (continuam calculados por baixo dos
    # panos pra ordenar o ranking da turma, só não aparecem mais aqui) —
    # no lugar, o módulo real em que o estudante está (mesmo dado de
    # /report/play/course usado na distribuição por módulo do dashboard).
    cabecalhos = ["#", "Estudante", "Login", "Progresso", "Módulo", "Status", "Alerta", "Concluído em"]
    linhas_tabela = [[Paragraph(h, cabecalho_style) for h in cabecalhos]]
    for a in dados["alunos"]:
        linhas_tabela.append([
            str(a["posicao_na_turma"]),
            Paragraph(a["nome"], corpo_style),
            Paragraph(a["login"], login_style),
            f"{a['progresso_pct']:.1f}%",
            Paragraph(a["modulo"], corpo_style),
            a["status"],
            Paragraph(a["motivo_alerta"] or "—", corpo_style),
            a["concluido_em"],
        ])

    # Soma das larguras precisa caber em 18cm (A4 = 21cm - 1.5cm de
    # margem de cada lado).
    tabela = Table(linhas_tabela, colWidths=[0.7 * cm, 2.9 * cm, 2.5 * cm, 1.6 * cm, 3.5 * cm, 1.6 * cm, 2.3 * cm, 2.3 * cm], repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tabela)

    doc.build(story)
    buffer.seek(0)

    # Slug da trilha no nome do arquivo pra não sobrescrever o PDF de
    # Saldo+ com o de Pocket (ou vice-versa) da mesma turma.
    filename = f"relatorio_{_slug(dados['turma'])}_{_slug(dados['trilha'])}.pdf"
    return StreamingResponse(
        buffer, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/relatorio/excel")
def get_relatorio_turma_excel(nome: str, trilha: str = TRILHA_PADRAO, db: Session = Depends(get_db)):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    dados = _buscar_relatorio_turma(db, nome, trilha)

    wb = Workbook()
    ws = wb.active
    ws.title = "Relatório da Turma"

    ws.merge_cells("A1:E1")
    ws["A1"] = f"{dados['trilha']} — Relatório da turma {dados['turma']}"
    ws["A1"].font = Font(name="Arial", size=14, bold=True, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY.lstrip("#"))
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    ws["A2"] = (
        f"Gerado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} (UTC) — "
        f"{dados['total_alunos']} estudantes · {dados['engajados']} engajados · {dados['concluintes']} concluintes"
    )
    ws["A2"].font = Font(name="Arial", size=9, italic=True, color="666666")

    header_row = 4
    for col, texto in enumerate(["#", "Estudante", "Login", "Progresso", "Módulo", "Status", "Alerta", "Concluído em"], start=1):
        celula = ws.cell(row=header_row, column=col, value=texto)
        celula.font = Font(name="Arial", bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor=NAVY.lstrip("#"))
        celula.alignment = Alignment(horizontal="center")

    for i, aluno in enumerate(dados["alunos"], start=header_row + 1):
        ws.cell(row=i, column=1, value=aluno["posicao_na_turma"]).font = Font(name="Arial")
        ws.cell(row=i, column=2, value=aluno["nome"]).font = Font(name="Arial")
        ws.cell(row=i, column=3, value=aluno["login"]).font = Font(name="Arial")
        celula_pct = ws.cell(row=i, column=4, value=aluno["progresso_pct"] / 100)
        celula_pct.number_format = "0.0%"
        celula_pct.font = Font(name="Arial")
        ws.cell(row=i, column=5, value=aluno["modulo"]).font = Font(name="Arial")
        ws.cell(row=i, column=6, value=aluno["status"]).font = Font(name="Arial")
        celula_alerta = ws.cell(row=i, column=7, value=aluno["motivo_alerta"] or "—")
        celula_alerta.font = Font(name="Arial", color="DC2626" if aluno["alerta_inatividade"] else "000000")
        ws.cell(row=i, column=8, value=aluno["concluido_em"]).font = Font(name="Arial")

    for col, largura in zip("ABCDEFGH", [5, 28, 20, 12, 32, 14, 22, 16]):
        ws.column_dimensions[col].width = largura

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"relatorio_{_slug(dados['turma'])}_{_slug(dados['trilha'])}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/relatorio-geral/excel")
def get_relatorio_geral_excel(instituicao: str = "todas", trilha: str = TRILHA_PADRAO, db: Session = Depends(get_db)):
    """Relatório único com TODOS os alunos de TODAS as escolas/turmas
    (respeitando o filtro de instituição selecionado no dashboard) — uma
    aba de resumo por escola e uma aba com todo mundo, em vez de precisar
    baixar turma por turma."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    dados = _buscar_relatorio_geral(db, trilha, instituicao)
    if not dados["alunos"]:
        raise HTTPException(status_code=404, detail="Nenhum aluno encontrado para esse filtro.")

    wb = Workbook()

    # --- Aba 1: Resumo por Escola ---
    ws_resumo = wb.active
    ws_resumo.title = "Resumo por Escola"

    ws_resumo.merge_cells("A1:F1")
    ws_resumo["A1"] = f"{dados['trilha']} — Relatório Geral ({dados['total_escolas']} escolas)"
    ws_resumo["A1"].font = Font(name="Arial", size=14, bold=True, color="FFFFFF")
    ws_resumo["A1"].fill = PatternFill("solid", fgColor=NAVY.lstrip("#"))
    ws_resumo["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws_resumo.row_dimensions[1].height = 26

    ws_resumo["A2"] = (
        f"Gerado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} (UTC) — "
        f"{dados['total_turmas']} turmas · {dados['total_alunos']} estudantes"
    )
    ws_resumo["A2"].font = Font(name="Arial", size=9, italic=True, color="666666")

    header_row = 4
    for col, texto in enumerate(["Escola", "Total de Alunos", "Engajados", "Concluintes", "Em Alerta", "Engajamento"], start=1):
        celula = ws_resumo.cell(row=header_row, column=col, value=texto)
        celula.font = Font(name="Arial", bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor=NAVY.lstrip("#"))
        celula.alignment = Alignment(horizontal="center")

    for i, escola in enumerate(dados["resumo_por_escola"], start=header_row + 1):
        ws_resumo.cell(row=i, column=1, value=escola["escola"]).font = Font(name="Arial")
        ws_resumo.cell(row=i, column=2, value=escola["total_alunos"]).font = Font(name="Arial")
        ws_resumo.cell(row=i, column=3, value=escola["engajados"]).font = Font(name="Arial")
        ws_resumo.cell(row=i, column=4, value=escola["concluintes"]).font = Font(name="Arial")
        celula_alerta = ws_resumo.cell(row=i, column=5, value=escola["em_alerta"])
        celula_alerta.font = Font(name="Arial", color="DC2626" if escola["em_alerta"] else "000000")
        celula_pct = ws_resumo.cell(row=i, column=6, value=escola["taxa_engajamento"] / 100)
        celula_pct.number_format = "0.0%"
        celula_pct.font = Font(name="Arial")

    for col, largura in zip("ABCDEF", [32, 16, 14, 14, 12, 14]):
        ws_resumo.column_dimensions[col].width = largura

    # --- Aba 2: Todos os Alunos ---
    ws_alunos = wb.create_sheet("Todos os Alunos")
    cabecalhos = ["Escola", "Turma", "#", "Estudante", "Login", "Progresso", "Módulo", "Status", "Alerta", "Concluído em"]
    for col, texto in enumerate(cabecalhos, start=1):
        celula = ws_alunos.cell(row=1, column=col, value=texto)
        celula.font = Font(name="Arial", bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor=NAVY.lstrip("#"))
        celula.alignment = Alignment(horizontal="center")

    for i, a in enumerate(dados["alunos"], start=2):
        ws_alunos.cell(row=i, column=1, value=a["escola"]).font = Font(name="Arial")
        ws_alunos.cell(row=i, column=2, value=a["turma"]).font = Font(name="Arial")
        ws_alunos.cell(row=i, column=3, value=a["posicao_na_turma"]).font = Font(name="Arial")
        ws_alunos.cell(row=i, column=4, value=a["nome"]).font = Font(name="Arial")
        ws_alunos.cell(row=i, column=5, value=a["login"]).font = Font(name="Arial")
        celula_pct = ws_alunos.cell(row=i, column=6, value=a["progresso_pct"] / 100)
        celula_pct.number_format = "0.0%"
        celula_pct.font = Font(name="Arial")
        ws_alunos.cell(row=i, column=7, value=a["modulo"]).font = Font(name="Arial")
        ws_alunos.cell(row=i, column=8, value=a["status"]).font = Font(name="Arial")
        celula_alerta = ws_alunos.cell(row=i, column=9, value=a["motivo_alerta"] or "—")
        celula_alerta.font = Font(name="Arial", color="DC2626" if a["alerta_inatividade"] else "000000")
        ws_alunos.cell(row=i, column=10, value=a["concluido_em"]).font = Font(name="Arial")

    ws_alunos.freeze_panes = "A2"
    for idx, largura in enumerate([28, 22, 5, 28, 20, 12, 32, 14, 22, 16], start=1):
        ws_alunos.column_dimensions[get_column_letter(idx)].width = largura

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"relatorio_geral_{_slug(dados['instituicao'])}_{_slug(dados['trilha'])}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )