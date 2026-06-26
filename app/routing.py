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

    Spec rules (PLAN.md §4 / Section 8 of the problem statement):
    - phishing reports: always
    - evidence_verdict != consistent: always (we never auto-confirm a dispute)
    - amount >= 50,000 BDT: always
    - wrong_transfer, agent_cash_in_issue, payment_failed (high amount): always
    - insufficient_data: only when case_type is high-stakes
    """
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return True
    if verdict != EvidenceVerdict.CONSISTENT and case_type in {
        CaseType.DUPLICATE_PAYMENT,
        CaseType.AGENT_CASH_IN_ISSUE,
    }:
        return True
    if amount is not None and amount >= 50_000:
        return True
    if case_type in {
        CaseType.AGENT_CASH_IN_ISSUE,
        CaseType.DUPLICATE_PAYMENT,
    }:
        return True
    if case_type == CaseType.PAYMENT_FAILED and (amount is None or amount >= 10_000):
        return True
    if case_type == CaseType.WRONG_TRANSFER and verdict == EvidenceVerdict.CONSISTENT:
        return True
    if case_type == CaseType.WRONG_TRANSFER and verdict == EvidenceVerdict.INCONSISTENT:
        return True
    # wrong_transfer + insufficient_data (ambiguous) -> do NOT escalate yet
    # (SAMPLE-08: we need disambiguation before opening dispute work).
    return False