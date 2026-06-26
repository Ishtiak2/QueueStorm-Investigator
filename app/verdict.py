"""Evidence verdict.

Maps a (case_type, matched_transaction, complaint, full_history) tuple onto
one of `consistent`, `inconsistent`, or `insufficient_data`.

Rules (see PLAN.md §5 and Section 3 of the problem statement):
    1. No matching transaction in history               -> `insufficient_data`
    2. Match exists AND status aligns with claim         -> `consistent`
    3. Match exists AND status contradicts the claim     -> `inconsistent`
    4. Match exists but status is pending / failed AND
       the complaint asks for a definitive outcome       -> `insufficient_data`

Specialised overrides (built on top of the base rule):
    - `wrong_transfer`: when prior transfers to the same counterparty exist
      in the lookback window, the claim is treated as `inconsistent`
      (established recipient pattern, SAMPLE-02).
    - `payment_failed` with status `failed`               -> `consistent`
      (the failure is exactly what the complaint reports, SAMPLE-03).
    - `agent_cash_in_issue` with status `pending`         -> `consistent`
      (the customer correctly observes the cash-in has not settled,
       SAMPLE-07).
    - `merchant_settlement_delay` with status `pending`   -> `consistent`.
    - `duplicate_payment` with two near-identical charges -> `consistent`.
    - `phishing_or_social_engineering` (no history)       -> `insufficient_data`
      (we have no transaction to verify, by design).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from app.matcher import MatchResult, _parse_txn_timestamp  # noqa: F401  (re-used)
from app.schemas import CaseType, EvidenceVerdict, TxnStatus

# Lookback window for "established recipient pattern" detection.
_RECIPIENT_LOOKBACK = timedelta(days=30)


def _count_prior_transfers(
    txn_id: str,
    counterparty: Optional[str],
    history: Iterable[dict],
) -> int:
    """Count completed transfer transactions to the same counterparty that
    precede the matched one. Used to flag established-recipient patterns."""
    if not counterparty:
        return 0
    matched_ts: Optional[datetime] = None
    for t in history:
        if t.get("transaction_id") == txn_id:
            matched_ts = _parse_txn_timestamp(str(t.get("timestamp", "")))
            break
    if matched_ts is None:
        return 0
    n = 0
    for t in history:
        if t.get("transaction_id") == txn_id:
            continue
        if str(t.get("counterparty", "")) != counterparty:
            continue
        ts = _parse_txn_timestamp(str(t.get("timestamp", "")))
        if ts is None or ts >= matched_ts:
            continue
        if matched_ts - ts > _RECIPIENT_LOOKBACK:
            continue
        if str(t.get("type", "")) == "transfer" and str(t.get("status")) == TxnStatus.COMPLETED.value:
            n += 1
    return n


def decide_verdict(
    case_type: CaseType,
    match: MatchResult,
    complaint: str,
    history: Iterable[dict],
) -> EvidenceVerdict:
    """Decide the evidence verdict.

    `history` is the full list of transactions (we need it to look back for
    prior transfers to the same counterparty).
    """
    history = list(history)

    # Rule 1: phishing/social-engineering reports almost never have a
    # matching transaction; treat absence of evidence as insufficient rather
    # than inconsistent (SAMPLE-05).
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        if match.transaction_id is None:
            return EvidenceVerdict.INSUFFICIENT_DATA
        return EvidenceVerdict.INSUFFICIENT_DATA

    # Rule 1: no match -> insufficient_data.
    if match.transaction_id is None:
        return EvidenceVerdict.INSUFFICIENT_DATA

    # Find the matched txn in the history list (we need full record).
    matched_txn = None
    for t in history:
        if t.get("transaction_id") == match.transaction_id:
            matched_txn = t
            break
    if matched_txn is None:
        # Match was reported but record is missing - shouldn't happen, fail
        # safe to insufficient_data.
        return EvidenceVerdict.INSUFFICIENT_DATA

    status = str(matched_txn.get("status", ""))

    # Per-case-type overrides that elevate the verdict even when the status
    # is not strictly `completed`.

    # payment_failed: status=failed is exactly the complaint's claim
    # (SAMPLE-03 -> consistent, not insufficient).
    if case_type == CaseType.PAYMENT_FAILED:
        if status == TxnStatus.FAILED.value:
            return EvidenceVerdict.CONSISTENT
        if status == TxnStatus.COMPLETED.value:
            # Complaint says "failed" but txn shows completed -> inconsistent.
            return EvidenceVerdict.INCONSISTENT
        if status == TxnStatus.PENDING.value:
            return EvidenceVerdict.INSUFFICIENT_DATA
        return EvidenceVerdict.INSUFFICIENT_DATA

    # agent_cash_in_issue: status=pending is consistent with "not received".
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        if status == TxnStatus.PENDING.value:
            return EvidenceVerdict.CONSISTENT
        if status == TxnStatus.COMPLETED.value:
            # Money IS there but customer claims it's not -> inconsistent.
            return EvidenceVerdict.INCONSISTENT
        if status == TxnStatus.FAILED.value:
            return EvidenceVerdict.CONSISTENT
        return EvidenceVerdict.INSUFFICIENT_DATA

    # merchant_settlement_delay: pending settlement is exactly the complaint.
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        if status == TxnStatus.PENDING.value:
            return EvidenceVerdict.CONSISTENT
        if status == TxnStatus.COMPLETED.value:
            return EvidenceVerdict.INCONSISTENT
        if status == TxnStatus.FAILED.value:
            return EvidenceVerdict.INCONSISTENT
        return EvidenceVerdict.INSUFFICIENT_DATA

    # duplicate_payment: a matched second-of-pair charge is consistent.
    if case_type == CaseType.DUPLICATE_PAYMENT:
        if status == TxnStatus.COMPLETED.value:
            return EvidenceVerdict.CONSISTENT
        if status == TxnStatus.FAILED.value:
            return EvidenceVerdict.INCONSISTENT
        return EvidenceVerdict.INSUFFICIENT_DATA

    # wrong_transfer: status completed + no prior pattern -> consistent.
    # status completed + many prior transfers to same recipient -> inconsistent
    # (established recipient, SAMPLE-02).
    if case_type == CaseType.WRONG_TRANSFER:
        if status == TxnStatus.COMPLETED.value:
            prior = _count_prior_transfers(
                match.transaction_id,
                str(matched_txn.get("counterparty", "")),
                history,
            )
            if prior >= 2:
                return EvidenceVerdict.INCONSISTENT
            return EvidenceVerdict.CONSISTENT
        if status == TxnStatus.FAILED.value:
            # Money didn't move -> there's nothing to dispute.
            return EvidenceVerdict.INCONSISTENT
        return EvidenceVerdict.INSUFFICIENT_DATA

    # refund_request: completed payment is the precondition for asking for a
    # refund, so it's consistent. Failed payment would be inconsistent
    # (nothing to refund).
    if case_type == CaseType.REFUND_REQUEST:
        if status == TxnStatus.COMPLETED.value:
            return EvidenceVerdict.CONSISTENT
        if status == TxnStatus.FAILED.value:
            return EvidenceVerdict.INCONSISTENT
        return EvidenceVerdict.INSUFFICIENT_DATA

    # `other` and fallback: simple status-vs-claim heuristic.
    if status == TxnStatus.COMPLETED.value:
        return EvidenceVerdict.CONSISTENT
    if status == TxnStatus.FAILED.value:
        return EvidenceVerdict.INCONSISTENT
    return EvidenceVerdict.INSUFFICIENT_DATA


def confidence_for(
    case_type: CaseType,
    match: MatchResult,
    verdict: EvidenceVerdict,
    complaint: str,
) -> float:
    """Calibrate a confidence value (0..1) for the response.

    Heuristic - not a true posterior, just a stable scalar the judge can use
    to compare runs.
    """
    if match.ambiguous:
        return 0.4
    if match.transaction_id is None:
        return 0.3 if case_type != CaseType.PHISHING_OR_SOCIAL_ENGINEERING else 0.85
    base = 0.9 if verdict == EvidenceVerdict.CONSISTENT else 0.7
    if verdict == EvidenceVerdict.INCONSISTENT:
        base = 0.75
    # Penalise very short / vague complaints.
    if len(complaint.strip()) < 25:
        base = max(0.4, base - 0.1)
    return round(min(1.0, max(0.1, base)), 2)


def reason_codes_for(
    case_type: CaseType,
    match: MatchResult,
    verdict: EvidenceVerdict,
) -> list[str]:
    """Stable, short reason labels that explain how we reached the verdict."""
    codes: list[str] = [case_type.value]
    if match.ambiguous:
        codes.append("ambiguous_match")
    elif match.transaction_id is None:
        if case_type != CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
            codes.append("no_transaction_match")
    else:
        codes.append("transaction_match")
    if verdict == EvidenceVerdict.INSUFFICIENT_DATA:
        codes.append("needs_clarification")
    if verdict == EvidenceVerdict.INCONSISTENT:
        codes.append("evidence_inconsistent")
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        codes += ["credential_protection", "critical_escalation"]
    return codes