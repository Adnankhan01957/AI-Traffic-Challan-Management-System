"""Printable challan (notice of violation) as PDF."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core import config


def build_pdf(c: dict, out_path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Title"], fontSize=18, spaceAfter=4)
    small = ParagraphStyle("s", parent=styles["Normal"], fontSize=8,
                           textColor=colors.grey)

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=18 * mm,
                            rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm,
                            title=f"Challan {c['challan_no']}")
    story = [
        Paragraph(f"TRAFFIC CHALLAN - {config.STATION_NAME}", title),
        Paragraph("Notice of traffic violation", styles["Normal"]),
        Spacer(1, 6 * mm),
    ]

    # Rs. is used instead of the rupee sign because the built-in PDF fonts
    # do not contain that glyph.
    rows = [
        ["Challan No", c["challan_no"]],
        ["Issued on", c["created_at"]],
        ["Offence date/time", c["offence_time"]],
        ["Location", c["location"] or "-"],
        ["Vehicle number", c["plate_display"]],
        ["Owner", c.get("owner_name") or "Not on record"],
        ["Violation", c["violation"]],
    ]
    if c.get("speed_recorded"):
        rows.append(["Recorded speed",
                     f"{c['speed_recorded']} km/h (limit {c['speed_limit']} km/h)"])
    rows += [
        ["Fine amount", f"Rs. {c['fine']}"],
        ["Issuing officer",
         f"{c.get('officer_name', '-')}  (Badge: {c.get('officer_badge') or '-'})"],
        ["Status", c["status"]],
    ]
    table = Table(rows, colWidths=[45 * mm, 120 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [table, Spacer(1, 6 * mm)]

    ev = c.get("evidence_path")
    if ev and Path(ev).exists():
        from PIL import Image as PILImage

        with PILImage.open(ev) as im:
            w, h = im.size
        max_w, max_h = 120 * mm, 80 * mm
        scale = min(max_w / w, max_h / h)
        story += [Paragraph("Evidence photograph", styles["Heading4"]),
                  Image(ev, width=w * scale, height=h * scale), Spacer(1, 3 * mm)]
        if c.get("evidence_sha256"):
            story.append(Paragraph(f"Evidence SHA-256: {c['evidence_sha256']}", small))

    story.append(Spacer(1, 4 * mm))
    pay = (f"Pay only on the official portal: {config.PAYMENT_URL}"
           if config.PAYMENT_URL else
           "Pay only through official traffic police channels.")
    story.append(Paragraph(pay, styles["Normal"]))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "This notice was prepared with software assistance and confirmed by the "
        "issuing officer. To dispute it, contact the issuing station.", small))

    doc.build(story)
    return out_path
