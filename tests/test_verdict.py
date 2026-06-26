"""Unit tests for `app.verdict`."""
from __future__ import annotations

from app.matcher import MatchResult
from app.schemas import CaseType, EvidenceVerdict, TxnStatus
from app.verdict import (
    confidence_for,
    decide_verdict,
    reason_codes_for,
)


def _txn(tid, ts, status="completed", type_="transfer", cp="merchant-x", amount=5000):
    return {
        "transaction_id": tid,
        "timestamp": ts,
        "type": type_,
        "amount": amount,
        "counterparty": cp,
        "status": status,
    }


# --- decide_verdict: no-match rule ----------------------------------------

def test_no_match_returns_insufficient_data():
    m = MatchResult(transaction_id=None, score=0, ambiguous=False)
    assert decide_verdict(CaseType.WRONG_TRANSFER, m, "complaint", []) == (
        EvidenceVerdict.INSUFFICIENT_DATA
    )


def test_ambiguous_match_treated_as_no_match():
    m = MatchResult(transaction_id=None, score=5, ambiguous=True)
    assert decide_verdict(CaseType.PAYMENT_FAILED, m, "complaint", []) == (
        EvidenceVerdict.INSUFFICIENT_DATA
    )


# --- phishing short-circuit (SAMPLE-05) ------------------------------------

def test_phishing_no_match_insufficient():
    m = MatchResult(transaction_id=None, score=0, ambiguous=False)
    assert decide_verdict(
        CaseType.PHISHING_OR_SOCIAL_ENGINEERING, m, "got OTP request", []
    ) == EvidenceVerdict.INSUFFICIENT_DATA


def test_phishing_with_match_still_insufficient():
    # Even if there is a matching txn, phishing reports are about a social
    # engineering attempt, not the txn itself.
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    hist = [_txn("TXN-1", "2025-01-15T10:00:00Z")]
    assert decide_verdict(
        CaseType.PHISHING_OR_SOCIAL_ENGINEERING, m, "OTP scam", hist
    ) == EvidenceVerdict.INSUFFICIENT_DATA


# --- payment_failed (SAMPLE-03) -------------------------------------------

def test_payment_failed_status_failed_consistent():
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    hist = [_txn("TXN-1", "2025-01-15T10:00:00Z", status=TxnStatus.FAILED.value)]
    assert decide_verdict(CaseType.PAYMENT_FAILED, m, "deducted but failed", hist) == (
        EvidenceVerdict.CONSISTENT
    )


def test_payment_failed_status_completed_inconsistent():
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    hist = [_txn("TXN-1", "2025-01-15T10:00:00Z", status=TxnStatus.COMPLETED.value)]
    assert decide_verdict(CaseType.PAYMENT_FAILED, m, "complaint", hist) == (
        EvidenceVerdict.INCONSISTENT
    )


def test_payment_failed_status_pending_insufficient():
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    hist = [_txn("TXN-1", "2025-01-15T10:00:00Z", status=TxnStatus.PENDING.value)]
    assert decide_verdict(CaseType.PAYMENT_FAILED, m, "complaint", hist) == (
        EvidenceVerdict.INSUFFICIENT_DATA
    )


# --- agent_cash_in_issue (SAMPLE-07) --------------------------------------

def test_agent_cash_in_pending_consistent():
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    hist = [_txn("TXN-1", "2025-01-15T10:00:00Z", status=TxnStatus.PENDING.value)]
    assert decide_verdict(
        CaseType.AGENT_CASH_IN_ISSUE, m, "not received", hist
    ) == EvidenceVerdict.CONSISTENT


def test_agent_cash_in_completed_inconsistent():
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    hist = [_txn("TXN-1", "2025-01-15T10:00:00Z", status=TxnStatus.COMPLETED.value)]
    assert decide_verdict(
        CaseType.AGENT_CASH_IN_ISSUE, m, "not received", hist
    ) == EvidenceVerdict.INCONSISTENT


# --- merchant_settlement_delay (SAMPLE-09) -------------------------------

def test_merchant_settlement_pending_consistent():
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    hist = [_txn("TXN-1", "2025-01-15T10:00:00Z", status=TxnStatus.PENDING.value)]
    assert decide_verdict(
        CaseType.MERCHANT_SETTLEMENT_DELAY, m, "merchant not credited", hist
    ) == EvidenceVerdict.CONSISTENT


def test_merchant_settlement_completed_inconsistent():
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    hist = [_txn("TXN-1", "2025-01-15T10:00:00Z", status=TxnStatus.COMPLETED.value)]
    assert decide_verdict(
        CaseType.MERCHANT_SETTLEMENT_DELAY, m, "merchant not credited", hist
    ) == EvidenceVerdict.INCONSISTENT


# --- duplicate_payment (SAMPLE-10) ----------------------------------------

def test_duplicate_payment_completed_consistent():
    m = MatchResult(transaction_id="TXN-B", score=5, ambiguous=False)
    hist = [_txn("TXN-B", "2025-01-15T10:05:00Z", status=TxnStatus.COMPLETED.value)]
    assert decide_verdict(
        CaseType.DUPLICATE_PAYMENT, m, "charged twice", hist
    ) == EvidenceVerdict.CONSISTENT


def test_duplicate_payment_failed_inconsistent():
    m = MatchResult(transaction_id="TXN-B", score=5, ambiguous=False)
    hist = [_txn("TXN-B", "2025-01-15T10:05:00Z", status=TxnStatus.FAILED.value)]
    assert decide_verdict(
        CaseType.DUPLICATE_PAYMENT, m, "charged twice", hist
    ) == EvidenceVerdict.INCONSISTENT


# --- wrong_transfer (SAMPLE-01, SAMPLE-02, SAMPLE-08) --------------------

def test_wrong_transfer_completed_no_prior_consistent():
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    hist = [_txn("TXN-1", "2025-01-15T10:00:00Z", status=TxnStatus.COMPLETED.value)]
    assert decide_verdict(
        CaseType.WRONG_TRANSFER, m, "wrong number", hist
    ) == EvidenceVerdict.CONSISTENT


def test_wrong_transfer_established_recipient_inconsistent():
    # Two prior completed transfers to same counterparty -> established
    # recipient pattern (SAMPLE-02).
    m = MatchResult(transaction_id="TXN-3", score=5, ambiguous=False)
    hist = [
        _txn("TXN-1", "2025-01-05T10:00:00Z", status=TxnStatus.COMPLETED.value),
        _txn("TXN-2", "2025-01-10T10:00:00Z", status=TxnStatus.COMPLETED.value),
        _txn("TXN-3", "2025-01-15T10:00:00Z", status=TxnStatus.COMPLETED.value),
    ]
    assert decide_verdict(
        CaseType.WRONG_TRANSFER, m, "wrong number", hist
    ) == EvidenceVerdict.INCONSISTENT


def test_wrong_transfer_failed_inconsistent():
    # If the txn didn't move, there's no money to dispute.
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    hist = [_txn("TXN-1", "2025-01-15T10:00:00Z", status=TxnStatus.FAILED.value)]
    assert decide_verdict(
        CaseType.WRONG_TRANSFER, m, "wrong number", hist
    ) == EvidenceVerdict.INCONSISTENT


# --- refund_request (SAMPLE-04) ------------------------------------------

def test_refund_request_completed_consistent():
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    hist = [_txn("TXN-1", "2025-01-15T10:00:00Z", status=TxnStatus.COMPLETED.value)]
    assert decide_verdict(
        CaseType.REFUND_REQUEST, m, "refund please", hist
    ) == EvidenceVerdict.CONSISTENT


def test_refund_request_failed_inconsistent():
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    hist = [_txn("TXN-1", "2025-01-15T10:00:00Z", status=TxnStatus.FAILED.value)]
    assert decide_verdict(
        CaseType.REFUND_REQUEST, m, "refund please", hist
    ) == EvidenceVerdict.INCONSISTENT


# --- confidence_for --------------------------------------------------------

def test_confidence_no_match_low():
    m = MatchResult(transaction_id=None, score=0, ambiguous=False)
    c = confidence_for(CaseType.WRONG_TRANSFER, m, EvidenceVerdict.INSUFFICIENT_DATA, "")
    assert c < 0.5


def test_confidence_ambiguous_match():
    m = MatchResult(transaction_id=None, score=5, ambiguous=True)
    c = confidence_for(CaseType.WRONG_TRANSFER, m, EvidenceVerdict.INSUFFICIENT_DATA, "")
    assert c == 0.4


def test_confidence_strong_consistent():
    m = MatchResult(transaction_id="TXN-1", score=8, ambiguous=False)
    c = confidence_for(
        CaseType.WRONG_TRANSFER, m, EvidenceVerdict.CONSISTENT,
        "I sent 5000 taka to the wrong number at 2pm yesterday please help",
    )
    assert c >= 0.9


def test_confidence_phishing_no_match_is_high():
    # Phishing reports have a stable high confidence even without a match,
    # because the classification itself is the strong signal.
    m = MatchResult(transaction_id=None, score=0, ambiguous=False)
    c = confidence_for(
        CaseType.PHISHING_OR_SOCIAL_ENGINEERING,
        m,
        EvidenceVerdict.INSUFFICIENT_DATA,
        "they asked for my OTP over the phone",
    )
    assert c == 0.85


# --- reason_codes_for ------------------------------------------------------

def test_reason_codes_phishing():
    m = MatchResult(transaction_id=None, score=0, ambiguous=False)
    codes = reason_codes_for(
        CaseType.PHISHING_OR_SOCIAL_ENGINEERING,
        m,
        EvidenceVerdict.INSUFFICIENT_DATA,
    )
    assert "phishing_or_social_engineering" in codes
    assert "credential_protection" in codes
    assert "critical_escalation" in codes
    assert "needs_clarification" in codes


def test_reason_codes_no_match():
    m = MatchResult(transaction_id=None, score=0, ambiguous=False)
    codes = reason_codes_for(
        CaseType.PAYMENT_FAILED, m, EvidenceVerdict.INSUFFICIENT_DATA
    )
    assert "payment_failed" in codes
    assert "no_transaction_match" in codes


def test_reason_codes_ambiguous():
    m = MatchResult(transaction_id=None, score=5, ambiguous=True)
    codes = reason_codes_for(
        CaseType.WRONG_TRANSFER, m, EvidenceVerdict.INSUFFICIENT_DATA
    )
    assert "ambiguous_match" in codes


def test_reason_codes_consistent_match():
    m = MatchResult(transaction_id="TXN-1", score=5, ambiguous=False)
    codes = reason_codes_for(
        CaseType.PAYMENT_FAILED, m, EvidenceVerdict.CONSISTENT
    )
    assert "transaction_match" in codes
    assert "no_transaction_match" not in codes