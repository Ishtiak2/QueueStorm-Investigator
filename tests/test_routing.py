"""Unit tests for `app.routing`."""
from __future__ import annotations

from app.routing import pick_department, pick_severity, requires_human_review
from app.schemas import (
    CaseType,
    Department,
    EvidenceVerdict,
    Severity,
)


# --- pick_department ------------------------------------------------------

def test_department_phishing_fraud_risk():
    assert pick_department(CaseType.PHISHING_OR_SOCIAL_ENGINEERING) == (
        Department.FRAUD_RISK
    )


def test_department_wrong_transfer_dispute():
    assert pick_department(CaseType.WRONG_TRANSFER) == Department.DISPUTE_RESOLUTION


def test_department_payment_failed_payments_ops():
    assert pick_department(CaseType.PAYMENT_FAILED) == Department.PAYMENTS_OPS


def test_department_duplicate_payments_ops():
    assert pick_department(CaseType.DUPLICATE_PAYMENT) == Department.PAYMENTS_OPS


def test_department_refund_customer_support():
    assert pick_department(CaseType.REFUND_REQUEST) == Department.CUSTOMER_SUPPORT


def test_department_merchant_settlement():
    assert pick_department(CaseType.MERCHANT_SETTLEMENT_DELAY) == (
        Department.MERCHANT_OPERATIONS
    )


def test_department_agent_cash_in():
    assert pick_department(CaseType.AGENT_CASH_IN_ISSUE) == (
        Department.AGENT_OPERATIONS
    )


def test_department_other_customer_support():
    assert pick_department(CaseType.OTHER) == Department.CUSTOMER_SUPPORT


# --- pick_severity --------------------------------------------------------

def test_severity_phishing_always_critical():
    assert pick_severity(
        CaseType.PHISHING_OR_SOCIAL_ENGINEERING, 100, EvidenceVerdict.INSUFFICIENT_DATA
    ) == Severity.CRITICAL


def test_severity_huge_amount_critical_regardless_of_case():
    assert pick_severity(CaseType.OTHER, 200_000, EvidenceVerdict.INSUFFICIENT_DATA) == (
        Severity.CRITICAL
    )


def test_severity_wrong_transfer_consistent_high():
    assert pick_severity(
        CaseType.WRONG_TRANSFER, 5_000, EvidenceVerdict.CONSISTENT
    ) == Severity.HIGH


def test_severity_wrong_transfer_inconsistent_medium():
    assert pick_severity(
        CaseType.WRONG_TRANSFER, 5_000, EvidenceVerdict.INCONSISTENT
    ) == Severity.MEDIUM


def test_severity_wrong_transfer_insufficient_medium():
    # Ambiguous wrong_transfer -> medium (SAMPLE-08).
    assert pick_severity(
        CaseType.WRONG_TRANSFER, 5_000, EvidenceVerdict.INSUFFICIENT_DATA
    ) == Severity.MEDIUM


def test_severity_payment_failed_always_high():
    assert pick_severity(CaseType.PAYMENT_FAILED, 500, EvidenceVerdict.CONSISTENT) == (
        Severity.HIGH
    )


def test_severity_duplicate_high():
    assert pick_severity(
        CaseType.DUPLICATE_PAYMENT, 5_000, EvidenceVerdict.CONSISTENT
    ) == Severity.HIGH


def test_severity_agent_cash_in_high_when_amount_over_1000():
    assert pick_severity(
        CaseType.AGENT_CASH_IN_ISSUE, 5_000, EvidenceVerdict.CONSISTENT
    ) == Severity.HIGH


def test_severity_agent_cash_in_medium_when_tiny_amount():
    assert pick_severity(
        CaseType.AGENT_CASH_IN_ISSUE, 500, EvidenceVerdict.CONSISTENT
    ) == Severity.MEDIUM


def test_severity_merchant_settlement_medium():
    assert pick_severity(
        CaseType.MERCHANT_SETTLEMENT_DELAY, 5_000, EvidenceVerdict.CONSISTENT
    ) == Severity.MEDIUM


def test_severity_refund_low_when_tiny():
    assert pick_severity(
        CaseType.REFUND_REQUEST, 500, EvidenceVerdict.CONSISTENT
    ) == Severity.LOW


def test_severity_refund_medium_when_normal():
    assert pick_severity(
        CaseType.REFUND_REQUEST, 5_000, EvidenceVerdict.CONSISTENT
    ) == Severity.MEDIUM


def test_severity_other_low_when_small():
    assert pick_severity(CaseType.OTHER, 500, EvidenceVerdict.INSUFFICIENT_DATA) == (
        Severity.LOW
    )


def test_severity_other_medium_when_50k_plus():
    assert pick_severity(CaseType.OTHER, 50_000, EvidenceVerdict.INSUFFICIENT_DATA) == (
        Severity.MEDIUM
    )


# --- requires_human_review -----------------------------------------------

def test_human_review_phishing_always():
    # SAMPLE-05
    assert requires_human_review(
        CaseType.PHISHING_OR_SOCIAL_ENGINEERING, None, EvidenceVerdict.CONSISTENT,
        Department.FRAUD_RISK,
    ) is True


def test_human_review_inconsistent_always_escalates():
    # SAMPLE-02: inconsistent verdict always escalates.
    assert requires_human_review(
        CaseType.WRONG_TRANSFER, 5_000, EvidenceVerdict.INCONSISTENT,
        Department.DISPUTE_RESOLUTION,
    ) is True


def test_human_review_insufficient_data_alone_does_not_escalate():
    # SAMPLE-06 and SAMPLE-08: insufficient_data verdict on its own is not
    # enough to require human review; the customer reply asks for info.
    assert requires_human_review(
        CaseType.OTHER, 500, EvidenceVerdict.INSUFFICIENT_DATA,
        Department.CUSTOMER_SUPPORT,
    ) is False
    assert requires_human_review(
        CaseType.WRONG_TRANSFER, 1_000, EvidenceVerdict.INSUFFICIENT_DATA,
        Department.DISPUTE_RESOLUTION,
    ) is False


def test_human_review_wrong_transfer_consistent_escalates():
    # SAMPLE-01
    assert requires_human_review(
        CaseType.WRONG_TRANSFER, 1_000, EvidenceVerdict.CONSISTENT,
        Department.DISPUTE_RESOLUTION,
    ) is True


def test_human_review_agent_cash_in_consistent_escalates():
    # SAMPLE-07
    assert requires_human_review(
        CaseType.AGENT_CASH_IN_ISSUE, 2_000, EvidenceVerdict.CONSISTENT,
        Department.AGENT_OPERATIONS,
    ) is True


def test_human_review_duplicate_consistent_escalates():
    # SAMPLE-10
    assert requires_human_review(
        CaseType.DUPLICATE_PAYMENT, 850, EvidenceVerdict.CONSISTENT,
        Department.PAYMENTS_OPS,
    ) is True


def test_human_review_payment_failed_consistent_no_escalation():
    # SAMPLE-03: payment_failed + consistent is not in the OR list.
    assert requires_human_review(
        CaseType.PAYMENT_FAILED, 1_500, EvidenceVerdict.CONSISTENT,
        Department.PAYMENTS_OPS,
    ) is False


def test_human_review_refund_consistent_no_escalation():
    # SAMPLE-04
    assert requires_human_review(
        CaseType.REFUND_REQUEST, 1_200, EvidenceVerdict.CONSISTENT,
        Department.CUSTOMER_SUPPORT,
    ) is False


def test_human_review_merchant_consistent_no_escalation():
    # SAMPLE-09
    assert requires_human_review(
        CaseType.MERCHANT_SETTLEMENT_DELAY, 25_000, EvidenceVerdict.CONSISTENT,
        Department.MERCHANT_OPERATIONS,
    ) is False


def test_human_review_amount_50k_alone_does_not_escalate_for_other():
    # Phase C had a 50k universal cap. The calibrated rule does not;
    # 50k alone does not escalate other / merchant / payment_failed.
    assert requires_human_review(
        CaseType.PAYMENT_FAILED, 60_000, EvidenceVerdict.CONSISTENT,
        Department.PAYMENTS_OPS,
    ) is False
