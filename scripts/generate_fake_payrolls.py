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
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
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


WATERMARK_TEXT = "SAMPLE - NOT A REAL DOCUMENT"

PAY_FREQUENCIES = {
    "weekly": 52,
    "biweekly": 26,
    "semimonthly": 24,
    "monthly": 12,
}


@dataclass
class LineItem:
    code: str | None
    description: str
    kind: str  # "earning" or "deduction"
    hours: float | None
    rate: float | None
    amount: float
    ytd_amount: float


@dataclass
class Paystub:
    employer_name: str
    employer_ein: str
    employer_address: str
    employee_name: str
    employee_id: str
    ssn_last4: str
    job_title: str
    hire_date: str
    pay_rate: float
    pay_frequency: str
    period_start: str
    period_end: str
    pay_date: str
    currency: str
    line_items: list[LineItem] = field(default_factory=list)

    @property
    def gross_pay(self) -> float:
        return _round2(sum(i.amount for i in self.line_items if i.kind == "earning"))

    @property
    def total_deductions(self) -> float:
        return _round2(sum(i.amount for i in self.line_items if i.kind == "deduction"))

    @property
    def total_taxes(self) -> float:
        tax_desc = {
            "Federal Income Tax",
            "Social Security Tax",
            "Medicare Tax",
            "State Income Tax",
        }
        return _round2(
            sum(i.amount for i in self.line_items if i.description in tax_desc)
        )

    @property
    def net_pay(self) -> float:
        return _round2(self.gross_pay - self.total_deductions)

    @property
    def ytd_gross_pay(self) -> float:
        return _round2(sum(i.ytd_amount for i in self.line_items if i.kind == "earning"))

    @property
    def ytd_net_pay(self) -> float:
        ytd_deductions = sum(i.ytd_amount for i in self.line_items if i.kind == "deduction")
        return _round2(self.ytd_gross_pay - ytd_deductions)


def _round2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _fmt_usd(value: float) -> str:
    return f"{value:,.2f}"


def _fake_ein(fake: Faker) -> str:
    a = fake.random_int(10, 99)
    b = fake.random_int(1000000, 9999999)
    return f"{a:02d}-{b:07d}"


def _fake_ssn_last4(fake: Faker) -> str:
    return f"{fake.random_int(1000, 9999)}"


def _us_address(fake: Faker) -> str:
    return f"{fake.street_address()}, {fake.city()}, {fake.state_abbr()} {fake.zipcode()}"


def build_paystub(fake: Faker, *, variant: str = "canonical") -> Paystub:
    pay_frequency = random.choice(list(PAY_FREQUENCIES.keys()))
    periods_per_year = PAY_FREQUENCIES[pay_frequency]

    is_hourly = random.random() < 0.5
    if is_hourly:
        hourly_rate = round(random.uniform(18.0, 75.0), 2)
        regular_hours = {"weekly": 40, "biweekly": 80, "semimonthly": 86.67, "monthly": 173.33}[pay_frequency]
        regular_pay = _round2(hourly_rate * regular_hours)
        pay_rate_shown = hourly_rate
    else:
        annual_salary = round(random.uniform(55000, 185000), 2)
        regular_pay = _round2(annual_salary / periods_per_year)
        regular_hours = None
        hourly_rate = None
        pay_rate_shown = annual_salary

    employer = fake.company()
    employee = fake.name()
    job_title = random.choice([
        "Software Engineer",
        "Senior Software Engineer",
        "Systems Analyst",
        "Financial Analyst",
        "Project Manager",
        "Marketing Coordinator",
        "Customer Success Manager",
        "Sales Representative",
        "Operations Supervisor",
        "Data Analyst",
    ])

    hire_date = fake.date_between(start_date="-10y", end_date="-6m")
    period_end = fake.date_between(start_date="-1y", end_date="today")
    period_length = {"weekly": 7, "biweekly": 14, "semimonthly": 15, "monthly": 30}[pay_frequency]
    period_start = period_end - timedelta(days=period_length - 1)
    pay_date = period_end + timedelta(days=random.randint(3, 7))

    periods_ytd = random.randint(3, periods_per_year)

    items: list[LineItem] = []

    items.append(LineItem(
        code="REG",
        description="Regular Pay",
        kind="earning",
        hours=regular_hours,
        rate=hourly_rate,
        amount=regular_pay,
        ytd_amount=_round2(regular_pay * periods_ytd),
    ))

    if variant == "with_overtime" or random.random() < 0.35:
        ot_hours = round(random.uniform(2.0, 15.0), 2)
        ot_rate = _round2((hourly_rate or (pay_rate_shown / 2080)) * 1.5)
        ot_amount = _round2(ot_hours * ot_rate)
        items.append(LineItem(
            code="OT",
            description="Overtime",
            kind="earning",
            hours=ot_hours,
            rate=ot_rate,
            amount=ot_amount,
            ytd_amount=_round2(ot_amount * random.uniform(3, periods_ytd)),
        ))

    if variant == "with_bonus" or random.random() < 0.2:
        bonus = _round2(regular_pay * random.uniform(0.10, 0.30))
        items.append(LineItem(
            code="BON",
            description="Bonus",
            kind="earning",
            hours=None,
            rate=None,
            amount=bonus,
            ytd_amount=bonus,
        ))

    if random.random() < 0.25:
        pto_hours = round(random.uniform(4.0, 16.0), 2)
        pto_rate = hourly_rate or _round2(pay_rate_shown / 2080)
        pto_amount = _round2(pto_hours * pto_rate)
        items.append(LineItem(
            code="PTO",
            description="Paid Time Off",
            kind="earning",
            hours=pto_hours,
            rate=pto_rate,
            amount=pto_amount,
            ytd_amount=_round2(pto_amount * random.uniform(1, 4)),
        ))

    gross_current = _round2(sum(i.amount for i in items))

    federal_tax = _round2(gross_current * random.uniform(0.10, 0.18))
    social_security = _round2(gross_current * 0.062)
    medicare = _round2(gross_current * 0.0145)
    state_tax = _round2(gross_current * random.uniform(0.03, 0.08))

    items.extend([
        LineItem("FIT", "Federal Income Tax", "deduction", None, None,
                 federal_tax, _round2(federal_tax * periods_ytd)),
        LineItem("SS", "Social Security Tax", "deduction", None, None,
                 social_security, _round2(social_security * periods_ytd)),
        LineItem("MED", "Medicare Tax", "deduction", None, None,
                 medicare, _round2(medicare * periods_ytd)),
        LineItem("SIT", "State Income Tax", "deduction", None, None,
                 state_tax, _round2(state_tax * periods_ytd)),
    ])

    if random.random() < 0.6:
        k401 = _round2(gross_current * random.choice([0.03, 0.05, 0.06, 0.08, 0.10]))
        items.append(LineItem(
            "401K", "401(k) Contribution", "deduction", None, None,
            k401, _round2(k401 * periods_ytd),
        ))

    if random.random() < 0.7:
        health = _round2(random.uniform(45.0, 220.0))
        items.append(LineItem(
            "HLTH", "Health Insurance", "deduction", None, None,
            health, _round2(health * periods_ytd),
        ))

    if random.random() < 0.4:
        dental = _round2(random.uniform(8.0, 35.0))
        items.append(LineItem(
            "DENT", "Dental Insurance", "deduction", None, None,
            dental, _round2(dental * periods_ytd),
        ))

    return Paystub(
        employer_name=employer,
        employer_ein=_fake_ein(fake),
        employer_address=_us_address(fake),
        employee_name=employee,
        employee_id=f"{random.randint(10000, 999999):06d}",
        ssn_last4=_fake_ssn_last4(fake),
        job_title=job_title,
        hire_date=hire_date.isoformat(),
        pay_rate=pay_rate_shown,
        pay_frequency=pay_frequency,
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        pay_date=pay_date.isoformat(),
        currency="USD",
        line_items=items,
    )


def paystub_to_ground_truth(p: Paystub) -> dict:
    return {
        "employer": {
            "name": p.employer_name,
            "ein": p.employer_ein,
            "address": p.employer_address,
        },
        "employee": {
            "name": p.employee_name,
            "employee_id": p.employee_id,
            "ssn_last4": p.ssn_last4,
            "job_title": p.job_title,
            "hire_date": p.hire_date,
            "pay_rate": p.pay_rate,
            "pay_frequency": p.pay_frequency,
        },
        "pay_period": {
            "start_date": p.period_start,
            "end_date": p.period_end,
            "pay_date": p.pay_date,
        },
        "currency": p.currency,
        "totals": {
            "gross_pay": p.gross_pay,
            "total_taxes": p.total_taxes,
            "total_deductions": p.total_deductions,
            "net_pay": p.net_pay,
            "ytd_gross_pay": p.ytd_gross_pay,
            "ytd_net_pay": p.ytd_net_pay,
        },
        "line_items": [asdict(i) for i in p.line_items],
    }


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
