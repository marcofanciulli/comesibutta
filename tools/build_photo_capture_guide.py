from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


ROOT = Path(__file__).parents[1]
OUTPUT = ROOT / "output" / "pdf" / "prontuario-fotografico-imballaggi.pdf"


def footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#5A6469"))
    canvas.drawString(14 * mm, 8 * mm, "ComeSiButta - prontuario fotografico v0.1.0")
    canvas.drawRightString(A5[0] - 14 * mm, 8 * mm, str(document.page))
    canvas.restoreState()


def build() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="GuideTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=22, leading=25, textColor=colors.HexColor("#17342D"),
        alignment=TA_CENTER, spaceAfter=8 * mm,
    ))
    styles.add(ParagraphStyle(
        name="GuideHeading", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=13, leading=16, textColor=colors.HexColor("#17342D"),
        spaceBefore=3 * mm, spaceAfter=2 * mm,
    ))
    styles.add(ParagraphStyle(
        name="GuideBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9.5, leading=13, textColor=colors.HexColor("#20272A"),
        spaceAfter=2.5 * mm,
    ))
    styles.add(ParagraphStyle(
        name="GuideSmall", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8.2, leading=10.5, textColor=colors.HexColor("#20272A"),
    ))
    story = [
        Spacer(1, 8 * mm),
        Paragraph("Prontuario fotografico", styles["GuideTitle"]),
        Paragraph(
            "Una convenzione semplice per raccogliere fotografie di marcature "
            "ambientali sugli imballaggi.", styles["GuideBody"],
        ),
        Spacer(1, 4 * mm),
        Paragraph("1. Dai un ID all'imballaggio", styles["GuideHeading"]),
        Paragraph("<b>PKG-AAAAMMGG-NNN</b>", styles["GuideTitle"]),
        Paragraph(
            "Esempio: <b>PKG-20260807-001</b>. Mantieni lo stesso ID per tutte "
            "le foto dello stesso oggetto e dei suoi componenti.", styles["GuideBody"],
        ),
        Paragraph("2. Nomina ogni foto", styles["GuideHeading"]),
        Paragraph(
            "<b>ID__CATEGORIA__NUMERO.jpg</b><br/>"
            "PKG-20260807-001__MI__01.jpg", styles["GuideBody"],
        ),
        Paragraph("3. Evita dati personali", styles["GuideHeading"]),
        Paragraph(
            "Usa un fondo neutro. Non includere persone, targhe, indirizzi, "
            "ricevute o documenti.", styles["GuideBody"],
        ),
        PageBreak(),
        Paragraph("Categorie rapide", styles["GuideTitle"]),
    ]
    rows = [
        ("MI", "Materiale", "PET 1, PAP 22, GL 70, C/PAP 84", "#D9EFE6"),
        ("RI", "Raccolta", "Raccolta plastica; verifica il Comune", "#DCEAF7"),
        ("PR", "Regolamentato", "Bidone barrato RAEE o batterie", "#F8E8C7"),
        ("DA", "Dichiarazione", "Mobius, riciclabile, riciclato", "#F4DDDA"),
        ("CS", "Certificazione", "FSC, PEFC, compostabilita, consorzi", "#DDEDEE"),
        ("NEG", "Negativa", "Nessun segno utile o simbolo estraneo", "#E7E7E7"),
    ]
    table_data = [["Sigla", "Categoria", "Cosa comprende"]]
    for code, category, description, _ in rows:
        table_data.append([
            Paragraph(f"<b>{code}</b>", styles["GuideSmall"]),
            Paragraph(category, styles["GuideSmall"]),
            Paragraph(description, styles["GuideSmall"]),
        ])
    table = Table(table_data, colWidths=[18 * mm, 31 * mm, 74 * mm], repeatRows=1)
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17342D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#AAB3B0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for index, row in enumerate(rows, start=1):
        commands.append(("BACKGROUND", (0, index), (-1, index), colors.HexColor(row[3])))
    table.setStyle(TableStyle(commands))
    story.extend([
        table,
        Spacer(1, 5 * mm),
        Paragraph(
            "Se compaiono piu categorie, usa nel nome quella al centro dello "
            "scatto. Se sei incerto, usa NEG e scrivi nelle note cio che vedi.",
            styles["GuideBody"],
        ),
        PageBreak(),
        Paragraph("Sequenza minima", styles["GuideTitle"]),
    ])
    steps = [
        "Vista generale del fronte o lato principale.",
        "Vista generale del retro.",
        "Primo piano frontale e nitido di ogni marcatura.",
        "Primo piano leggermente obliquo.",
        "Foto distinta di tappo, etichetta, vaschetta o altro componente separabile.",
        "Una condizione difficile reale: curva, riflesso, piega, usura o luce scarsa.",
    ]
    for index, step in enumerate(steps, start=1):
        story.append(Paragraph(f"<b>{index}.</b> {step}", styles["GuideBody"]))
    story.extend([
        Spacer(1, 3 * mm),
        Paragraph("Registra senza indovinare", styles["GuideHeading"]),
        Paragraph(
            "Scrivi soltanto il testo realmente leggibile. Collega un codice "
            "normativo solo quando sigla e numero sono certi.", styles["GuideBody"],
        ),
        Paragraph("Prima di chiudere", styles["GuideHeading"]),
        Paragraph(
            "ID coerente; categoria nel nome; vista generale; primo piano "
            "nitido; componenti separabili; nessun dato personale.", styles["GuideBody"],
        ),
    ])
    document = SimpleDocTemplate(
        OUTPUT.as_posix(), pagesize=A5, rightMargin=14 * mm, leftMargin=14 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm, title="Prontuario fotografico imballaggi",
        author="Marco Fanciulli - ComeSiButta",
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build()
