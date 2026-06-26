"""Unit tests for `app.matcher`."""
from __future__ import annotations

from datetime import time

from app.matcher import (
    extract_amount,
    extract_counterparty,
    extract_time,
    find_duplicate,
    match_transaction,
)


# --- extract_amount --------------------------------------------------------

def test_extract_amount_ascii():
    assert extract_amount("I sent 5000 taka") == 5000


def test_extract_amount_bengali_digits():
    # Bengali numerals for 5000 = ৫০০০
    assert extract_amount("আমি ৫০০০ টাকা পাঠিয়েছি") == 5000


def test_extract_amount_returns_first_mention():
    assert extract_amount("tried 500, paid 5000 to wrong person") == 500


def test_extract_amount_none_when_missing():
    assert extract_amount("money didn't arrive, no amount given") is None


def test_extract_amount_rejects_tiny_numbers():
    # 1 digit should not count - min 2 digits per spec
    assert extract_amount("I have 5 bkash accounts") is None


# --- extract_time ----------------------------------------------------------

def test_extract_time_2pm():
    assert extract_time("I sent at 2pm") == time(14, 0)


def test_extract_time_4am():
    assert extract_time("around 4am") == time(4, 0)


def test_extract_time_24h_with_minutes():
    assert extract_time("txn at 14:30 was debited") == time(14, 30)


def test_extract_time_english_evening():
    assert extract_time("I sent in the evening") == time(18, 0)


def test_extract_time_bangla_dupur():
    assert extract_time("আজ দুপুরে পাঠিয়েছি") == time(14, 0)


def test_extract_time_none_when_missing():
    assert extract_time("I sent money yesterday") is None


# --- extract_counterparty --------------------------------------------------

def test_extract_counterparty_phone_e164():
    assert extract_counterparty("sent to +8801719876543") == "+8801719876543"


def test_extract_counterparty_merchant_id():
    assert (
        extract_counterparty("bill payment to BILLER-DESCO-12345 failed")
        == "BILLER-DESCO-12345"
    )


def test_extract_counterparty_lowercase_id_not_picked():
    # The ID extractor only catches uppercase tokens; lowercase merchant names
    # are intentionally not treated as a strong counterparty signal.
    assert extract_counterparty("paid at merchant-x") is None


def test_extract_counterparty_none():
    assert extract_counterparty("my payment didn't go through") is None


# --- match_transaction -----------------------------------------------------

def _txn(tid, amount, ts, cp="merchant-x", status="completed", type_="payment"):
    return {
        "transaction_id": tid,
        "timestamp": ts,
        "type": type_,
        "amount": amount,
        "counterparty": cp,
        "status": status,
    }


def test_match_picks_strong_match():
    # Complaint names a phone with +88 prefix and amount + time, so the
    # matcher picks the right txn with full score (amount+time+cp).
    history = [
        _txn("TXN-1", 100, "2025-01-15T10:00:00Z"),
        _txn("TXN-2", 5000, "2025-01-15T14:00:00Z", cp="+8801719876543"),
    ]
    result = match_transaction(
        "I sent 5000 to +8801719876543 at 2pm", history
    )
    assert result.transaction_id == "TXN-2"
    assert result.score == 8  # amount(3) + time(2) + cp(3)
    assert result.ambiguous is False


def test_match_amount_plus_time_only():
    # No counterparty signal - score is 5 (amount + time).
    history = [
        _txn("TXN-1", 100, "2025-01-15T10:00:00Z"),
        _txn("TXN-2", 5000, "2025-01-15T14:00:00Z"),
    ]
    result = match_transaction("I sent 5000 at 2pm", history)
    assert result.transaction_id == "TXN-2"
    assert result.score == 5
    assert result.ambiguous is False


def test_match_returns_none_below_threshold():
    history = [_txn("TXN-1", 100, "2025-01-15T10:00:00Z")]
    result = match_transaction("I sent money yesterday", history)
    assert result.transaction_id is None
    assert result.ambiguous is False


def test_match_returns_ambiguous_on_tie():
    history = [
        _txn("TXN-A", 5000, "2025-01-15T14:00:00Z"),
        _txn("TXN-B", 5000, "2025-01-15T14:00:00Z"),
    ]
    result = match_transaction("I sent 5000 at 2pm", history)
    assert result.transaction_id is None
    assert result.ambiguous is True
    assert result.score == 5  # amount(3) + time(2)


def test_match_amount_only_passes_threshold():
    history = [_txn("TXN-1", 5000, "2025-01-15T10:00:00Z")]
    result = match_transaction("I sent 5000", history)
    assert result.transaction_id == "TXN-1"
    assert result.score == 3  # amount only


def test_match_empty_history():
    result = match_transaction("sent 5000", [])
    assert result.transaction_id is None
    assert result.ambiguous is False


def test_match_time_within_4h_wraps_midnight():
    # complaint says 11pm, txn at 00:30 should still be within 4h window
    history = [_txn("TXN-1", 5000, "2025-01-15T00:30:00Z")]
    result = match_transaction("sent 5000 at 11pm", history)
    assert result.score >= 5  # amount + time


def test_match_counterparty_substring_complaint_in_txn():
    # Realistic case: txn counterparty is "BILLER-DESC-12345", customer
    # mentions the tail "DESC-12345" - substring containment matches.
    history = [
        _txn("TXN-1", 5000, "2025-01-15T14:00:00Z", cp="BILLER-DESC-12345")
    ]
    result = match_transaction("bill of 5000 to DESC-12345 at 2pm", history)
    assert result.transaction_id == "TXN-1"
    assert result.score == 8  # amount + time + cp


def test_match_counterparty_no_overlap_fails_match():
    # Different ID prefixes - AGENT-318 is not a substring of
    # MERCHANT-MOBILE-OP-318 in either direction.
    history = [
        _txn("TXN-1", 5000, "2025-01-15T14:00:00Z", cp="MERCHANT-MOBILE-OP-318")
    ]
    result = match_transaction("sent 5000 to AGENT-318 at 2pm", history)
    assert result.score == 5  # amount + time only, no cp match
    assert result.transaction_id == "TXN-1"


def test_match_time_too_far_apart():
    history = [_txn("TXN-1", 5000, "2025-01-15T22:00:00Z")]
    # complaint says 2pm, txn at 10pm - 8h apart
    result = match_transaction("sent 5000 at 2pm", history)
    assert result.score == 3  # amount only


# --- find_duplicate --------------------------------------------------------

def test_find_duplicate_two_same_within_window():
    history = [
        _txn("TXN-A", 5000, "2025-01-15T10:00:00Z"),
        _txn("TXN-B", 5000, "2025-01-15T10:05:00Z"),
    ]
    # Second charge is the duplicate
    assert find_duplicate(history, 5000) == "TXN-B"


def test_find_duplicate_no_pair():
    history = [_txn("TXN-A", 5000, "2025-01-15T10:00:00Z")]
    assert find_duplicate(history, 5000) is None


def test_find_duplicate_far_apart_not_duplicate():
    # Same amount/cp but 1h apart - probably two separate legitimate charges
    history = [
        _txn("TXN-A", 5000, "2025-01-15T10:00:00Z"),
        _txn("TXN-B", 5000, "2025-01-15T11:00:00Z"),
    ]
    assert find_duplicate(history, 5000) is None


def test_find_duplicate_different_counterparty_not_duplicate():
    history = [
        _txn("TXN-A", 5000, "2025-01-15T10:00:00Z", cp="merchant-A"),
        _txn("TXN-B", 5000, "2025-01-15T10:05:00Z", cp="merchant-B"),
    ]
    assert find_duplicate(history, 5000) is None


def test_find_duplicate_no_amount_returns_none():
    history = [
        _txn("TXN-A", 5000, "2025-01-15T10:00:00Z"),
        _txn("TXN-B", 5000, "2025-01-15T10:05:00Z"),
    ]
    assert find_duplicate(history, None) is None