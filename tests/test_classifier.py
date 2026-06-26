"""Unit tests for `app.classifier`."""
from __future__ import annotations

from app.classifier import classify_amount_band, classify_case_type
from app.schemas import CaseType


# --- phishing (highest priority, even when other tokens present) ----------

def test_classify_phishing_otp_english():
    assert classify_case_type("someone called and asked for my OTP") == (
        CaseType.PHISHING_OR_SOCIAL_ENGINEERING
    )


def test_classify_phishing_pin_english():
    assert classify_case_type("they wanted my PIN over the phone") == (
        CaseType.PHISHING_OR_SOCIAL_ENGINEERING
    )


def test_classify_phishing_otp_bangla():
    assert classify_case_type("ওটিপি দিতে বললো") == (
        CaseType.PHISHING_OR_SOCIAL_ENGINEERING
    )


def test_classify_phishing_bkash_caller():
    assert classify_case_type("a person calling from bkash asked me") == (
        CaseType.PHISHING_OR_SOCIAL_ENGINEERING
    )


def test_classify_phishing_takes_priority_over_wrong_transfer():
    # Even though complaint mentions wrong number, phishing wins.
    assert classify_case_type(
        "OTP scam: I sent 5000 to a wrong number after they asked for my OTP"
    ) == CaseType.PHISHING_OR_SOCIAL_ENGINEERING


# --- duplicate_payment ----------------------------------------------------

def test_classify_duplicate_twice():
    assert classify_case_type("I was charged twice for the same bill") == (
        CaseType.DUPLICATE_PAYMENT
    )


def test_classify_duplicate_bangla():
    assert classify_case_type("একই বিল দুইবার কেটে নিয়েছে") == (
        CaseType.DUPLICATE_PAYMENT
    )


def test_classify_duplicate_word():
    assert classify_case_type("duplicate payment of 500") == (
        CaseType.DUPLICATE_PAYMENT
    )


# --- wrong_transfer ------------------------------------------------------

def test_classify_wrong_number():
    assert classify_case_type("sent money to wrong number") == (
        CaseType.WRONG_TRANSFER
    )


def test_classify_wrong_bangla():
    assert classify_case_type("ভুল নাম্বারে টাকা পাঠিয়েছি") == (
        CaseType.WRONG_TRANSFER
    )


def test_classify_didnt_receive_intended():
    # SAMPLE-08: "he says he didn't get it" - non-receipt is also wrong_transfer.
    assert classify_case_type(
        "I sent 5000 but the recipient says he didn't get it"
    ) == CaseType.WRONG_TRANSFER


def test_classify_never_received():
    assert classify_case_type("he never received the money") == (
        CaseType.WRONG_TRANSFER
    )


# --- payment_failed -------------------------------------------------------

def test_classify_payment_failed_with_deduction():
    assert classify_case_type("payment failed but balance was deducted") == (
        CaseType.PAYMENT_FAILED
    )


def test_classify_payment_failed_bangla():
    assert classify_case_type("পেমেন্ট ব্যর্থ হয়েছে, টাকা কেটে নিয়েছে") == (
        CaseType.PAYMENT_FAILED
    )


def test_classify_recharge_failed():
    assert classify_case_type("my recharge failed and money was deducted") == (
        CaseType.PAYMENT_FAILED
    )


def test_classify_failed_alone_not_payment_failed():
    # "the agent failed" without payment context should NOT be payment_failed.
    result = classify_case_type("the agent failed to give me cash")
    assert result != CaseType.PAYMENT_FAILED


# --- merchant_settlement_delay -------------------------------------------

def test_classify_merchant_settlement_english():
    assert classify_case_type("my settlement has been pending for days") == (
        CaseType.MERCHANT_SETTLEMENT_DELAY
    )


def test_classify_merchant_user_type_sale():
    # user_type=merchant + sale = merchant_settlement_delay.
    assert classify_case_type(
        "I made a sale but no settlement yet", user_type="merchant"
    ) == CaseType.MERCHANT_SETTLEMENT_DELAY


# --- agent_cash_in_issue --------------------------------------------------

def test_classify_agent_cash_in_bangla():
    # Use Bangla phrasing so we don't accidentally hit the wrong_transfer
    # non-receipt pattern, which fires before agent_cash_in.
    assert classify_case_type("এজেন্টের মাধ্যমে ক্যাশ ইন করেছি, ব্যালেন্সে আসেনি") == (
        CaseType.AGENT_CASH_IN_ISSUE
    )


def test_classify_agent_cash_in_balance_not_updated():
    # "balance e taka asheni" is the agent-cash-in signal.
    assert classify_case_type(
        "I went to an agent for cash in but balance e taka asheni"
    ) == CaseType.AGENT_CASH_IN_ISSUE


# --- refund_request ------------------------------------------------------

def test_classify_refund_request():
    assert classify_case_type("I want a refund please") == (
        CaseType.REFUND_REQUEST
    )


def test_classify_refund_bangla():
    assert classify_case_type("টাকা ফেরত দিন") == (
        CaseType.REFUND_REQUEST
    )


# --- fallback ------------------------------------------------------------

def test_classify_other_fallback():
    assert classify_case_type("my account is not working properly") == (
        CaseType.OTHER
    )


def test_classify_empty():
    assert classify_case_type("") == CaseType.OTHER


# --- amount bands --------------------------------------------------------

def test_amount_band_unknown():
    assert classify_amount_band(None) == "unknown"


def test_amount_band_tiny():
    assert classify_amount_band(500) == "tiny"


def test_amount_band_small():
    assert classify_amount_band(5_000) == "small"


def test_amount_band_medium():
    assert classify_amount_band(20_000) == "medium"


def test_amount_band_large():
    assert classify_amount_band(75_000) == "large"


def test_amount_band_huge():
    assert classify_amount_band(500_000) == "huge"