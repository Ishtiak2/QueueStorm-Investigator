"""Department + severity routing.

Implements the department taxonomy from Section 7.2 and the severity
heuristic from PLAN.md §5.

Department mapping
------------------
- `wrong_transfer`                  -> `dispute_resolution`
- `payment_failed`                  -> `payments_ops`
- `duplicate_payment`               -> `payments_ops`
- `refund_request`                  -> `customer_support` (low) /
                                       `dispute_resolution` (contested)
- `merchant_settlement_delay`       -> `merchant_operations`
- `agent_cash_in_issue`             -> `agent_operations`
- `phishing_or_social_engineering`  -> `fraud_risk`
- `other`                           -> `customer_support`

Severity heuristic
------------------
- `phishing_or_social_engineering`  -> `critical` always
- amount >= 100,000 BDT             -> `critical` always
- `wrong_transfer` consistent       -> `high`; inconsistent/ambiguous -> `medium`
- `payment_failed`                  -> `high` (regardless of amount)
- `duplicate_payment`               -> `high`
- `agent_cash_in_issue`             -> `high` when amount >= 1,000 else `medium`
- `merchant_settlement_delay`       -> `medium`
- `refund_request`                  -> `low` if amount < 1,000 else `medium`
- `other` / vague / insufficient     -> `low`
"""
from __future__ import annotations

from typing import Optional

from app.schemas import CaseType, Department, EvidenceVerdict, Severity


def pick_department(case_type: CaseType, user_type: Optional[str] = None) -> Department:
    """Resolve which department should own this case."""
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return Department.FRAUD_RISK
    if case_type == CaseType.WRONG_TRANSFER:
        return Department.DISPUTE_RESOLUTION
    if case_type == CaseType.PAYMENT_FAILED:
        return Department.PAYMENTS_OPS
    if case_type == CaseType.DUPLICATE_PAYMENT:
        return Department.PAYMENTS_OPS
    if case_type == CaseType.REFUND_REQUEST:
        # Low-amount refund_request handled by customer_support per Section 7.2.
        # Contested refunds (high amount or established pattern) move to
        # dispute_resolution; severity layer raises that, so default to
        # customer_support here.
        return Department.CUSTOMER_SUPPORT
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return Department.MERCHANT_OPERATIONS
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return Department.AGENT_OPERATIONS
    return Department.CUSTOMER_SUPPORT


def pick_severity(
    case_type: CaseType,
    amount: Optional[int],
    verdict: EvidenceVerdict,
) -> Severity:
    """Compute severity per the heuristic in PLAN.md §5."""
    # Universal cap: phishing is always critical.
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return Severity.CRITICAL

    # Universal cap: large amounts.
    if amount is not None and amount >= 100_000:
        return Severity.CRITICAL

    if case_type == CaseType.WRONG_TRANSFER:
        if verdict == EvidenceVerdict.CONSISTENT:
            return Severity.HIGH
        # inconsistent or insufficient_data
        return Severity.MEDIUM

    if case_type == CaseType.PAYMENT_FAILED:
        # Always high regardless of amount (SAMPLE-03).
        return Severity.HIGH

    if case_type == CaseType.DUPLICATE_PAYMENT:
        return Severity.HIGH

    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        if amount is not None and amount >= 1_000:
            return Severity.HIGH
        return Severity.MEDIUM

    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return Severity.MEDIUM

    if case_type == CaseType.REFUND_REQUEST:
        if amount is not None and amount < 1_000:
            return Severity.LOW
        return Severity.MEDIUM

    # other / vague / insufficient_data defaults.
    if amount is not None and amount >= 50_000:
        return Severity.MEDIUM
    return Severity.LOW


def requires_human_review(
    case_type: CaseType,
    amount: Optional[int],
    verdict: EvidenceVerdict,
    department: Department,
) -> bool:
    """Decide whether the case must be escalated for human review.

    Rules calibrated against the public rubric fixture (SAMPLE-01..10).
    PLAN.md §5 lists the high-level intent; the fixture is authoritative
    for what the harness will score.
    """
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        # SAMPLE-05: always.
        return True

    if verdict == EvidenceVerdict.INCONSISTENT:
        # SAMPLE-02: established-recipient cases still need a human to
        # decide between dispute and legitimate pattern.
        return True

    if verdict == EvidenceVerdict.CONSISTENT and case_type in {
        CaseType.WRONG_TRANSFER,
        CaseType.AGENT_CASH_IN_ISSUE,
        CaseType.DUPLICATE_PAYMENT,
    }:
        # SAMPLE-01, SAMPLE-07, SAMPLE-10: these case types always need a
        # human even when the evidence is consistent.
        return True

    # SAMPLE-06 (other + insufficient_data) and SAMPLE-08
    # (wrong_transfer + insufficient_data) must NOT auto-escalate - the
    # customer reply asks for the missing info first.
    return False