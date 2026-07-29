import io
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Turma, Student, StudentProgress

router = APIRouter(prefix="/api/v1/turma", tags=["relatorio-turma"])

NAVY = "#002364"
GREEN = "#10B981"

STATUS_LABEL = {"concluido": "Concluído", "engajado": "Engajado", "inscrito": "Inscrito"}


def _slug(texto: str) -> str:
    """Vira um nome de arquivo seguro (sem espaço/acento/caractere especial)."""
    limpo = re.sub(r"[^A-Za-z0-9]+", "_", texto).strip("_")
    return limpo or "turma"


def _buscar_relatorio_turma(db: Session, nome: str) -> dict:
    turma = db.execute(select(Turma).where(Turma.name == nome)).scalar_one_or_none()
    if turma is None:
        raise HTTPException(status_code=404, detail=f"Turma '{nome}' não encontrada.")

    alunos = db.execute(select(Student).where(Student.turma_id == turma.id)).scalars().all()

    linhas = []
    for aluno in alunos:
        progresso = db.execute(
            select(StudentProgress).where(
                StudentProgress.student_id == aluno.id,
                StudentProgress.trail_external_id == "41",
            )
        ).scalar_one_or_none()
        status = progresso.status if progresso else "inscrito"
        linhas.append({
            "nome": aluno.name or aluno.login,
            "login": aluno.login,
            "progresso_pct": round(progresso.progress_pct, 1) if progresso else 0.0,
            "status": STATUS_LABEL.get(status, status),
            "concluido_em": (
                progresso.completed_at.strftime("%d/%m/%Y")
                if progresso and progresso.completed_at else "—"
            ),
        })

    linhas.sort(key=lambda l: l["nome"].lower())

    return {
        "turma": turma.name,
        "escola": turma.school.name if turma.school else turma.name,
        "total_alunos": len(linhas),
        "engajados": sum(1 for l in linhas if l["progresso_pct"] > 0),
        "concluintes": sum(1 for l in linhas if l["progresso_pct"] >= 100),
        "alunos": linhas,
    }


@router.get("/relatorio")
def get_relatorio_turma(nome: str, db: Session = Depends(get_db)):
    """Dados do relatório de uma turma — usado pelo modal 'Ver Alunos' no dashboard."""
    return _buscar_relatorio_turma(db, nome)


@router.get("/relatorio/pdf")
def get_relatorio_turma_pdf(nome: str, db: Session = Depends(get_db)):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    dados = _buscar_relatorio_turma(db, nome)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    titulo_style = ParagraphStyle("TituloSaldo", parent=styles["Title"], textColor=colors.HexColor(NAVY), fontSize=18)
    subtitulo_style = ParagraphStyle("SubtituloSaldo", parent=styles["Normal"], textColor=colors.HexColor("#64748B"), fontSize=9)

    story = [
        Paragraph(f"Saldo+ — Relatório da turma {dados['turma']}", titulo_style),
        Paragraph(f"Gerado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} (UTC)", subtitulo_style),
        Spacer(1, 14),
        Paragraph(
            f"{dados['total_alunos']} alunos · {dados['engajados']} engajados · {dados['concluintes']} concluintes",
            styles["Normal"],
        ),
        Spacer(1, 14),
    ]

    linhas_tabela = [["Aluno", "Login", "Progresso", "Status", "Concluído em"]]
    for a in dados["alunos"]:
        linhas_tabela.append([a["nome"], a["login"], f"{a['progresso_pct']:.1f}%", a["status"], a["concluido_em"]])

    tabela = Table(linhas_tabela, colWidths=[5.5 * cm, 4 * cm, 2.5 * cm, 2.8 * cm, 3 * cm], repeatRows=1)
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

    filename = f"relatorio_{_slug(dados['turma'])}.pdf"
    return StreamingResponse(
        buffer, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/relatorio/excel")
def get_relatorio_turma_excel(nome: str, db: Session = Depends(get_db)):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    dados = _buscar_relatorio_turma(db, nome)

    wb = Workbook()
    ws = wb.active
    ws.title = "Relatório da Turma"

    ws.merge_cells("A1:E1")
    ws["A1"] = f"Saldo+ — Relatório da turma {dados['turma']}"
    ws["A1"].font = Font(name="Arial", size=14, bold=True, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY.lstrip("#"))
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    ws["A2"] = (
        f"Gerado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} (UTC) — "
        f"{dados['total_alunos']} alunos · {dados['engajados']} engajados · {dados['concluintes']} concluintes"
    )
    ws["A2"].font = Font(name="Arial", size=9, italic=True, color="666666")

    header_row = 4
    for col, texto in enumerate(["Aluno", "Login", "Progresso", "Status", "Concluído em"], start=1):
        celula = ws.cell(row=header_row, column=col, value=texto)
        celula.font = Font(name="Arial", bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor=NAVY.lstrip("#"))
        celula.alignment = Alignment(horizontal="center")

    for i, aluno in enumerate(dados["alunos"], start=header_row + 1):
        ws.cell(row=i, column=1, value=aluno["nome"]).font = Font(name="Arial")
        ws.cell(row=i, column=2, value=aluno["login"]).font = Font(name="Arial")
        celula_pct = ws.cell(row=i, column=3, value=aluno["progresso_pct"] / 100)
        celula_pct.number_format = "0.0%"
        celula_pct.font = Font(name="Arial")
        ws.cell(row=i, column=4, value=aluno["status"]).font = Font(name="Arial")
        ws.cell(row=i, column=5, value=aluno["concluido_em"]).font = Font(name="Arial")

    for col, largura in zip("ABCDE", [30, 22, 14, 14, 16]):
        ws.column_dimensions[col].width = largura

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"relatorio_{_slug(dados['turma'])}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
