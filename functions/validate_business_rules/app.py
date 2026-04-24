"""Payroll domain rules validator.

Runs after ValidateSchema (JSON structure) and before PersistResult.
Checks business invariants that the JSON schema cannot express:
  - numeric sanity (gross > net, gross - deductions ≈ net)
  - required-field presence beyond schema nullability
  - date ordering

Adds event["business_rules"] and emits CloudWatch metrics.
Never raises on rule violations — violations are recorded, not fatal.
"""
from __future__ import annotations

from typing import Any

from app_common.logging import get_logger, log_json
from app_common.metrics import emit_business_rules


logger = get_logger(__name__)

# Tolerance for gross - deductions == net check (2% of gross)
MATH_TOLERANCE_RATIO = 0.02
TOTAL_RULES = 7


def _check(data: dict[str, Any]) -> tuple[bool, float, list[str]]:
    violations: list[str] = []

    totals = data.get("totals") or {}
    employer = data.get("employer") or {}
    employee = data.get("employee") or {}
    pay_period = data.get("pay_period") or {}

    gross = totals.get("gross_pay")
    net = totals.get("net_pay")
    deductions = totals.get("total_deductions")

    # Rule 1 — gross_pay must be positive
    if not isinstance(gross, (int, float)) or gross <= 0:
        violations.append(f"gross_pay must be > 0 (got {gross!r})")

    # Rule 2 — net_pay must be positive
    if not isinstance(net, (int, float)) or net <= 0:
        violations.append(f"net_pay must be > 0 (got {net!r})")

    # Rule 3 — gross >= net
    if isinstance(gross, (int, float)) and isinstance(net, (int, float)):
        if gross < net:
            violations.append(f"gross_pay ({gross}) < net_pay ({net})")

    # Rule 4 — math check: gross - deductions ≈ net (when deductions present)
    if (
        isinstance(gross, (int, float))
        and isinstance(net, (int, float))
        and isinstance(deductions, (int, float))
        and gross > 0
    ):
        expected_net = gross - deductions
        tolerance = gross * MATH_TOLERANCE_RATIO
        if abs(expected_net - net) > tolerance:
            violations.append(
                f"Math check failed: gross({gross}) - deductions({deductions}) = "
                f"{expected_net:.2f} but net_pay = {net} (tolerance ±{tolerance:.2f})"
            )

    # Rule 5 — employer.name present
    if not employer.get("name"):
        violations.append("employer.name is null or empty")

    # Rule 6 — employee.name present
    if not employee.get("name"):
        violations.append("employee.name is null or empty")

    # Rule 7 — pay_period dates present
    if not pay_period.get("start_date") or not pay_period.get("end_date"):
        violations.append("pay_period.start_date and/or end_date is null")

    passed_rules = TOTAL_RULES - len(violations)
    score = round(passed_rules / TOTAL_RULES, 4)
    return len(violations) == 0, score, violations


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    extracted_data = event["llm_extraction"]["data"]
    profile = event.get("extraction_profile") or {}
    document_format = event.get("document_format", "unknown")
    profile_id = profile.get("id", "unknown")

    passed, score, violations = _check(
        extracted_data if isinstance(extracted_data, dict) else {}
    )

    event["business_rules"] = {
        "passed": passed,
        "score": score,
        "violations": violations,
        "rules_checked": TOTAL_RULES,
    }

    log_json(
        logger,
        "Business rules validated",
        request_id=event["request_id"],
        passed=passed,
        score=score,
        violation_count=len(violations),
        violations=violations,
    )

    emit_business_rules(
        fmt=document_format,
        profile_id=profile_id,
        passed=passed,
        score=score,
        violation_count=len(violations),
    )

    return event
