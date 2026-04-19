"""Generate synthetic US payroll (pay stub) PDFs for testing the extraction pipeline.

Dev-only dependencies (not shipped to Lambda):
    pip install reportlab faker

Usage:
    python scripts/generate_fake_payrolls.py --out tests/fixtures/payrolls --count 5
    python scripts/generate_fake_payrolls.py --variant scanned --out /tmp/payrolls

Each PDF is paired with a <stem>.expected.json ground-truth file so it can double as a
regression fixture against the live extraction output.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from faker import Faker
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paystub_data import Paystub, build_paystub, paystub_to_ground_truth  # noqa: E402


WATERMARK_TEXT = "SAMPLE - NOT A REAL DOCUMENT"


def _fmt_usd(value: float) -> str:
    return f"{value:,.2f}"


def _draw_watermark(canvas, _doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 48)
    canvas.setFillColor(colors.Color(0.85, 0.85, 0.85, alpha=0.4))
    canvas.translate(LETTER[0] / 2, LETTER[1] / 2)
    canvas.rotate(30)
    canvas.drawCentredString(0, 0, WATERMARK_TEXT)
    canvas.restoreState()


def render_pdf(p: Paystub, out_path: Path) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        title=f"Pay Stub {p.employee_name}",
    )
    story = []

    story.append(Paragraph(f"<b>{p.employer_name}</b>", styles["Title"]))
    story.append(Paragraph(p.employer_address, styles["Normal"]))
    story.append(Paragraph(f"EIN: {p.employer_ein}", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(
        f"<b>EARNINGS STATEMENT</b> &nbsp;&nbsp; Pay Date: {p.pay_date}",
        styles["Heading2"],
    ))
    story.append(Spacer(1, 0.15 * inch))

    info_table = Table(
        [
            ["Employee", p.employee_name, "Employee ID", p.employee_id],
            ["Job Title", p.job_title, "SSN", f"XXX-XX-{p.ssn_last4}"],
            ["Hire Date", p.hire_date, "Pay Frequency", p.pay_frequency.title()],
            ["Pay Period", f"{p.period_start} to {p.period_end}",
             "Pay Rate", _fmt_usd(p.pay_rate)],
        ],
        colWidths=[1.1 * inch, 2.6 * inch, 1.2 * inch, 2.0 * inch],
    )
    info_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("BACKGROUND", (2, 0), (2, -1), colors.whitesmoke),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.25 * inch))

    earnings = [i for i in p.line_items if i.kind == "earning"]
    deductions = [i for i in p.line_items if i.kind == "deduction"]

    story.append(Paragraph("<b>Earnings</b>", styles["Heading3"]))
    earn_rows = [["Code", "Description", "Hours", "Rate", "Current", "YTD"]]
    for i in earnings:
        earn_rows.append([
            i.code or "",
            i.description,
            f"{i.hours:.2f}" if i.hours is not None else "",
            _fmt_usd(i.rate) if i.rate is not None else "",
            _fmt_usd(i.amount),
            _fmt_usd(i.ytd_amount),
        ])
    earn_rows.append(["", "Gross Pay", "", "", _fmt_usd(p.gross_pay), _fmt_usd(p.ytd_gross_pay)])
    earn_table = Table(earn_rows, colWidths=[0.6 * inch, 2.4 * inch, 0.7 * inch, 0.8 * inch, 1.0 * inch, 1.0 * inch])
    earn_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.whitesmoke),
    ]))
    story.append(earn_table)
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("<b>Deductions</b>", styles["Heading3"]))
    ded_rows = [["Code", "Description", "Current", "YTD"]]
    for i in deductions:
        ded_rows.append([i.code or "", i.description, _fmt_usd(i.amount), _fmt_usd(i.ytd_amount)])
    ded_rows.append(["", "Total Deductions", _fmt_usd(p.total_deductions),
                     _fmt_usd(p.ytd_gross_pay - p.ytd_net_pay)])
    ded_table = Table(ded_rows, colWidths=[0.6 * inch, 3.9 * inch, 1.0 * inch, 1.0 * inch])
    ded_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.whitesmoke),
    ]))
    story.append(ded_table)
    story.append(Spacer(1, 0.25 * inch))

    summary = Table(
        [
            ["Gross Pay", _fmt_usd(p.gross_pay), "YTD Gross", _fmt_usd(p.ytd_gross_pay)],
            ["Total Taxes", _fmt_usd(p.total_taxes), "Total Deductions", _fmt_usd(p.total_deductions)],
            ["", "", "NET PAY", _fmt_usd(p.net_pay)],
        ],
        colWidths=[1.3 * inch, 1.3 * inch, 1.6 * inch, 1.5 * inch],
    )
    summary.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("FONTNAME", (2, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (2, -1), (-1, -1), colors.lightyellow),
    ]))
    story.append(summary)

    doc.build(story, onFirstPage=_draw_watermark, onLaterPages=_draw_watermark)


def render_scanned_pdf(p: Paystub, out_path: Path) -> None:
    """Render a text-based PDF, rasterize each page, reassemble as images.

    Result is a PDF whose pages are images — PyMuPDF text extraction returns empty,
    exactly the case that should trip DocumentExtractionError.
    """
    try:
        import fitz
    except ImportError as exc:
        raise SystemExit("scanned variant requires PyMuPDF (pip install PyMuPDF)") from exc

    tmp = out_path.with_suffix(".text.pdf")
    render_pdf(p, tmp)
    src = fitz.open(tmp)
    dst = fitz.open()
    for page in src:
        pix = page.get_pixmap(dpi=150)
        new_page = dst.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(page.rect, pixmap=pix)
    dst.save(out_path)
    dst.close()
    src.close()
    tmp.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--locale", default="en_US")
    ap.add_argument(
        "--variant",
        choices=("canonical", "with_overtime", "with_bonus", "scanned", "mixed"),
        default="mixed",
    )
    args = ap.parse_args()

    random.seed(args.seed)
    fake = Faker(args.locale)
    Faker.seed(args.seed)

    args.out.mkdir(parents=True, exist_ok=True)

    variants = (
        ["canonical", "with_overtime", "with_bonus"]
        if args.variant == "mixed"
        else [args.variant]
    )

    for i in range(args.count):
        variant = variants[i % len(variants)]
        p = build_paystub(fake, variant=variant)
        stem = f"paystub_{i + 1:03d}_{variant}"
        pdf_path = args.out / f"{stem}.pdf"
        gt_path = args.out / f"{stem}.expected.json"

        if args.variant == "scanned":
            render_scanned_pdf(p, pdf_path)
        else:
            render_pdf(p, pdf_path)

        gt_path.write_text(
            json.dumps(paystub_to_ground_truth(p), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"wrote {pdf_path}")


if __name__ == "__main__":
    main()
