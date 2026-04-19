"""Shared synthetic US paystub data model, used by every format generator.

Kept separate from any rendering library (reportlab, openpyxl, ...) so it can be
imported by format-specific generators without pulling their deps.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from faker import Faker


PAY_FREQUENCIES: dict[str, int] = {
    "weekly": 52,
    "biweekly": 26,
    "semimonthly": 24,
    "monthly": 12,
}

JOB_TITLES: tuple[str, ...] = (
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
)


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
        return _round2(sum(i.amount for i in self.line_items if i.description in tax_desc))

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
        regular_hours_by_freq = {
            "weekly": 40,
            "biweekly": 80,
            "semimonthly": 86.67,
            "monthly": 173.33,
        }
        regular_hours = regular_hours_by_freq[pay_frequency]
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
    job_title = random.choice(JOB_TITLES)

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
