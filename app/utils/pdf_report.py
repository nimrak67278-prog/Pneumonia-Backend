"""
Generates a professional PDF report for a single X-ray prediction,
matching the fields shown on the app's X-Ray Details screen.
"""

from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
    Table, TableStyle, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus.flowables import Flowable
from datetime import datetime

# --- Palette, matching the app's blue-to-teal theme ---
PRIMARY = HexColor("#1976D2")
PRIMARY_DARK = HexColor("#0D47A1")
TEAL_ACCENT = HexColor("#00BFA5")
INK = HexColor("#1A1A1A")
MUTED = HexColor("#6B7280")
LIGHT_BG = HexColor("#F4F6F8")
BORDER = HexColor("#E2E5E9")

RISK_COLORS = {
    "high": (HexColor("#C62828"), HexColor("#FDECEA")),
    "moderate-high": (HexColor("#E65100"), HexColor("#FEF1E6")),
    "moderate": (HexColor("#B7791F"), HexColor("#FEF7E0")),
    "low-moderate": (HexColor("#2E7D32"), HexColor("#EAF6EC")),
    "low": (HexColor("#2E7D32"), HexColor("#EAF6EC")),
}

PREDICTION_COLORS = {
    "PNEUMONIA": HexColor("#C62828"),
    "NORMAL": HexColor("#2E7D32"),
}


class ColorBar(Flowable):
    """A simple solid horizontal color bar used as a header banner background."""
    def __init__(self, width, height, color):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.color = color

    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.rect(0, 0, self.width, self.height, stroke=0, fill=1)


def _section_card(title, body_text, accent_color=PRIMARY):
    """Returns a Table styled to look like a bordered card with a colored left edge."""
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CardTitle", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=10, textColor=MUTED, spaceAfter=4, tracking=0.5,
    )
    body_style = ParagraphStyle(
        "CardBody", parent=styles["Normal"], fontName="Helvetica",
        fontSize=11.5, textColor=INK, leading=16,
    )
    content = [
        Paragraph(title.upper(), title_style),
        Paragraph(body_text, body_style),
    ]
    table = Table([[content]], colWidths=[16.5 * cm])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
        ("LINEBEFORE", (0, 0), (0, -1), 3, accent_color),
        ("BACKGROUND", (0, 0), (-1, -1), white),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    return table


def generate_xray_report_pdf(record: dict, xray_image_bytes: bytes | None) -> bytes:
    """
    record: the prediction row (id, prediction, confidence, risk_level,
            explanation, recommendation, created_at, patient_id, etc.)
    xray_image_bytes: raw bytes of the X-ray image, or None if unavailable
    Returns: raw PDF bytes.
    """
    buffer = BytesIO()
    page_width, page_height = A4

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=0, bottomMargin=1.8 * cm,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
    )

    styles = getSampleStyleSheet()

    header_title_style = ParagraphStyle(
        "HeaderTitle", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=22, textColor=white, leading=26,
    )
    header_subtitle_style = ParagraphStyle(
        "HeaderSubtitle", parent=styles["Normal"], fontName="Helvetica",
        fontSize=11, textColor=HexColor("#E3F2FD"), leading=14,
    )
    meta_label_style = ParagraphStyle(
        "MetaLabel", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9, textColor=MUTED,
    )
    meta_value_style = ParagraphStyle(
        "MetaValue", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=10.5, textColor=INK,
    )
    disclaimer_style = ParagraphStyle(
        "Disclaimer", parent=styles["Normal"], fontSize=8,
        textColor=MUTED, alignment=TA_CENTER, leading=11,
    )
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"], fontSize=8,
        textColor=HexColor("#AAAAAA"), alignment=TA_CENTER,
    )

    elements = []

    # ---------- HEADER BANNER (full-bleed colored bar) ----------
    header_inner = Table(
        [[
            Paragraph("PneumoScan AI", header_title_style),
        ], [
            Paragraph("Chest X-Ray Screening Report", header_subtitle_style),
        ]],
        colWidths=[page_width - 4.4 * cm],
    )
    header_inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (0, 0), 26),
        ("BOTTOMPADDING", (0, 0), (0, 0), 2),
        ("BOTTOMPADDING", (0, 1), (0, 1), 24),
    ]))

    banner = Table(
        [[header_inner]],
        colWidths=[page_width],
        rowHeights=[3.6 * cm],
    )
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PRIMARY_DARK),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.2 * cm),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(banner)
    elements.append(Spacer(1, 0.9 * cm))

    # ---------- REPORT META ROW ----------
    created_at = record.get("created_at", "")
    try:
        created_display = datetime.fromisoformat(
            created_at.replace("Z", "+00:00")
        ).strftime("%B %d, %Y  \u2022  %I:%M %p")
    except Exception:
        created_display = created_at

    meta_table = Table(
        [[
            Paragraph("PATIENT NAME", meta_label_style),
            Paragraph("REPORT ID", meta_label_style),
            Paragraph("DATE GENERATED", meta_label_style),
        ], [
            Paragraph(record.get("patient_name", "N/A"), meta_value_style),
            Paragraph(f"#{record.get('id', '')[:8].upper()}", meta_value_style),
            Paragraph(created_display, meta_value_style),
        ]],
        colWidths=[5.5 * cm, 5.5 * cm, 5.5 * cm],
    )
    meta_table.setStyle(TableStyle([
        ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 0.5 * cm))
    elements.append(HRFlowable(width="100%", color=BORDER, thickness=1))
    elements.append(Spacer(1, 0.6 * cm))

    # ---------- X-RAY IMAGE ----------
    if xray_image_bytes:
        try:
            img_buffer = BytesIO(xray_image_bytes)
            img = RLImage(img_buffer, width=9 * cm, height=9 * cm, kind="proportional")
            img_wrapper = Table([[img]], colWidths=[16.5 * cm])
            img_wrapper.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("BOX", (0, 0), (-1, -1), 1, BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            elements.append(img_wrapper)
            elements.append(Spacer(1, 0.7 * cm))
        except Exception:
            pass

    # ---------- RESULT SUMMARY CARD ----------
    prediction = (record.get("prediction") or "N/A").upper()
    prediction_color = PREDICTION_COLORS.get(prediction, INK)
    confidence = record.get("confidence", 0)
    risk_level_raw = record.get("risk_level", "N/A")
    risk_key = (risk_level_raw or "").lower()
    risk_text_color, risk_bg_color = RISK_COLORS.get(risk_key, (MUTED, LIGHT_BG))

    prediction_style = ParagraphStyle(
        "PredictionValue", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=20, textColor=prediction_color,
    )
    confidence_style = ParagraphStyle(
        "ConfidenceValue", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=20, textColor=INK,
    )
    summary_label_style = ParagraphStyle(
        "SummaryLabel", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=8.5, textColor=MUTED,
    )
    risk_badge_style = ParagraphStyle(
        "RiskBadge", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=10, textColor=risk_text_color, alignment=TA_CENTER,
    )

    risk_badge = Table([[Paragraph(risk_level_raw.upper(), risk_badge_style)]], colWidths=[4.5 * cm])
    risk_badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), risk_bg_color),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))

    summary_table = Table(
        [
            [
                Paragraph("PREDICTION", summary_label_style),
                Paragraph("CONFIDENCE", summary_label_style),
                Paragraph("RISK LEVEL", summary_label_style),
            ],
            [
                Paragraph(prediction, prediction_style),
                Paragraph(f"{confidence}%", confidence_style),
                risk_badge,
            ],
        ],
        colWidths=[5.5 * cm, 5.5 * cm, 5.5 * cm],
    )
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("TOPPADDING", (0, 0), (-1, 0), 12),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 14),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.7 * cm))

    # ---------- EXPLANATION & RECOMMENDATION CARDS ----------
    elements.append(_section_card(
        "Explanation", record.get("explanation", "N/A"), accent_color=PRIMARY
    ))
    elements.append(Spacer(1, 0.45 * cm))
    elements.append(_section_card(
        "Recommendation", record.get("recommendation", "N/A"), accent_color=TEAL_ACCENT
    ))
    elements.append(Spacer(1, 1 * cm))

    # ---------- DISCLAIMER ----------
    elements.append(HRFlowable(width="100%", color=BORDER, thickness=1))
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(Paragraph(
        "This is an AI-assisted screening tool and not a substitute for professional "
        "medical diagnosis. Always consult a qualified doctor for confirmation and "
        "treatment decisions.",
        disclaimer_style,
    ))
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(Paragraph("Generated by PneumoScan AI", footer_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer.read()