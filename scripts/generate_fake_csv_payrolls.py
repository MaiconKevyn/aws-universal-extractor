"""Generate synthetic US payroll CSV files for testing the extraction pipeline.

Dev-only dependencies:
    pip install faker

Usage:
    python scripts/generate_fake_csv_payrolls.py --out tests/fixtures/payroll/csv --count 5

Each CSV is paired with a <stem>.expected.json ground-truth file using the same
schema as the PDF and XLSX fixtures.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

from faker import Faker

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paystub_data import Paystub, build_paystub, paystub_to_ground_truth  # noqa: E402


def _fmt(value: float | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render_csv(p: Paystub, out_path: Path) -> None:
    rows = [
        [
            "section",
            "field",
            "value",
            "code",
            "description",
            "kind",
            "hours",
            "rate",
            "current_amount",
            "ytd_amount",
        ],
        ["employer", "name", p.employer_name, "", "", "", "", "", "", ""],
        ["employer", "ein", p.employer_ein, "", "", "", "", "", "", ""],
        ["employer", "address", p.employer_address, "", "", "", "", "", "", ""],
        ["employee", "name", p.employee_name, "", "", "", "", "", "", ""],
        ["employee", "employee_id", p.employee_id, "", "", "", "", "", "", ""],
        ["employee", "ssn_last4", p.ssn_last4, "", "", "", "", "", "", ""],
        ["employee", "job_title", p.job_title, "", "", "", "", "", "", ""],
        ["employee", "hire_date", p.hire_date, "", "", "", "", "", "", ""],
        ["employee", "pay_rate", _fmt(p.pay_rate), "", "", "", "", "", "", ""],
        ["employee", "pay_frequency", p.pay_frequency, "", "", "", "", "", "", ""],
        ["pay_period", "start_date", p.period_start, "", "", "", "", "", "", ""],
        ["pay_period", "end_date", p.period_end, "", "", "", "", "", "", ""],
        ["pay_period", "pay_date", p.pay_date, "", "", "", "", "", "", ""],
        ["summary", "currency", p.currency, "", "", "", "", "", "", ""],
        ["summary", "gross_pay", _fmt(p.gross_pay), "", "", "", "", "", "", ""],
        ["summary", "total_taxes", _fmt(p.total_taxes), "", "", "", "", "", "", ""],
        ["summary", "total_deductions", _fmt(p.total_deductions), "", "", "", "", "", "", ""],
        ["summary", "net_pay", _fmt(p.net_pay), "", "", "", "", "", "", ""],
        ["summary", "ytd_gross_pay", _fmt(p.ytd_gross_pay), "", "", "", "", "", "", ""],
        ["summary", "ytd_net_pay", _fmt(p.ytd_net_pay), "", "", "", "", "", "", ""],
    ]

    for item in p.line_items:
        rows.append([
            "line_item",
            "",
            "",
            item.code or "",
            item.description,
            item.kind,
            _fmt(item.hours),
            _fmt(item.rate),
            _fmt(item.amount),
            _fmt(item.ytd_amount),
        ])

    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--locale", default="en_US")
    ap.add_argument(
        "--variant",
        choices=("canonical", "with_overtime", "with_bonus", "mixed"),
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
        csv_path = args.out / f"{stem}.csv"
        gt_path = args.out / f"{stem}.expected.json"

        render_csv(p, csv_path)
        gt_path.write_text(
            json.dumps(paystub_to_ground_truth(p), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
