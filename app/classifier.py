"""Case-type classifier.

Maps a free-text complaint (English / Bangla / Banglish) onto one of the 8
case_type values declared in `app.schemas.CaseType`. The classifier is purely
keyword/pattern-based: it must be deterministic, fast (<1 ms), and explainable
(Section 7.1 of the problem statement).

Priority order (highest first):
    1. phishing_or_social_engineering  - explicit credential request
    2. duplicate_payment               - "twice" / "duplicate" / "দুইবার"
    3. wrong_transfer                  - "wrong number" / "ভুল নম্বর"
    4. payment_failed                  - "failed" + balance-deduction context
    5. merchant_settlement_delay       - "settlement" / user_type=merchant
    6. agent_cash_in_issue             - "agent" + "cash in" / "ক্যাশ ইন"
    7. refund_request                  - "refund" / "ফেরত"
    8. other                           - fallback

Phishing is checked first because it has the highest safety priority even if
the complaint also mentions transactions.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from app.schemas import CaseType

# ---------------------------------------------------------------------------
# Keyword maps. Weights are not summed; the first category whose set matches
# wins. Ties are broken by priority (see `classify_case_type`).
# ---------------------------------------------------------------------------

# Phishing: explicit credential request, or unsolicited "we are from bKash"
# contact. The check is intentionally tight so we do not false-positive on
# legitimate complaints that mention security (e.g. "my account is hacked").
_PHISHING_TOKENS = [
    "otp", "o.t.p.", "ওটিপি",
    "pin", "পিন",
    "password", "পাসওয়ার্ড",
    "cvv",
    "full card",
]
_PHISHING_PATTERNS = [
    re.compile(r"\botp\b", re.IGNORECASE),
    re.compile(r"\bpin\b", re.IGNORECASE),
    re.compile(r"\bpassword\b", re.IGNORECASE),
    re.compile(r"\bcvv\b", re.IGNORECASE),
    re.compile(r"ওটিপি"),
    re.compile(r"পিন"),
    re.compile(r"পাসওয়ার্ড"),
]
_PHISHING_SOCIAL_ENGINEERING = [
    re.compile(r"from\s+bkash", re.IGNORECASE),
    re.compile(r"calling\s+from\b", re.IGNORECASE),
    re.compile(r"কল\s*করে\s*বলল[োো]"),
    re.compile(r"বিকাশ\s*থেকে\s*বল[ো]ছ[েে]"),
    re.compile(r"if\s+i\s+don'?t\s+share", re.IGNORECASE),
    re.compile(r"account\s+will\s+be\s+blocked", re.IGNORECASE),
]

# Duplicate payment: explicit "twice"/"duplicate"/"দুইবার".
_DUPLICATE_TOKENS = [
    "twice", "duplicate", "two times", "2 times",
    "দুইবার", "দুই বার", "ডুপ্লিকেট", "একই",
]

# Wrong transfer: explicit wrong-recipient claim.
_WRONG_TRANSFER_TOKENS = [
    "wrong number", "wrong person", "wrong recipient", "wrong account",
    "ভুল নম্বর", "ভুল নাম্বার", "ভুল মানুষ", "ভুল একাউন্ট", "ভুল ব্যক্তি",
]
_WRONG_PATTERNS = [
    re.compile(r"to\s+a?\s*wrong\b", re.IGNORECASE),
    re.compile(r"to\s+the\s+wrong\b", re.IGNORECASE),
    re.compile(r"sent\s+to\s+the\s+wrong\b", re.IGNORECASE),
    # Non-receipt phrasing ("he says he didn't get it") is also wrong_transfer
    # per Section 7.1: "money sent to the wrong recipient" includes "intended
    # recipient reports they did not receive it".
    re.compile(r"didn'?t\s+(?:get|receive)\s+it", re.IGNORECASE),
    re.compile(r"did\s+not\s+(?:get|receive)\s+it", re.IGNORECASE),
    re.compile(r"hasn'?t\s+(?:got|gotten|received)\s+it", re.IGNORECASE),
    re.compile(r"(?:has|have)\s+not\s+(?:got|gotten|received)\s+it", re.IGNORECASE),
    re.compile(r"not\s+(?:got|gotten|received)", re.IGNORECASE),
    re.compile(r"didn'?t\s+receive", re.IGNORECASE),
    re.compile(r"never\s+(?:got|received|gotten)", re.IGNORECASE),
]

# Payment failed: "failed" / "কাজ করছে না" / "didn't go through" +
# optional "balance deducted" / "টাকা কেটে নিয়েছে".
_FAILED_TOKENS = [
    "failed", "didn't work", "did not work", "didnt work",
    "kaje korche na", "কাজ করছে না", "কাজ করে না", "ব্যর্থ",
    "couldn't pay", "could not pay", "payment failed", "recharge failed",
]
_BALANCE_DEDUCTION = [
    "balance deducted", "balance was deducted", "money deducted",
    "টাকা কেটে নিয়েছে", "টাকা কেটে গেছে", "ব্যালেন্স কেটে",
]

# Refund request: explicit refund language.
_REFUND_TOKENS = [
    "refund", "ফেরত", "ফেরত দিন", "টাকা ফেরত", "return my money",
    "change my mind", "i don't want it anymore", "want my money back",
]

# Merchant settlement: "settlement" + user_type=merchant cue.
_SETTLEMENT_TOKENS = [
    "settlement", "settle", "settled",
    "সেটেলমেন্ট", "মিটমাট",
]

# Agent cash-in: "agent" + "cash in" / "ক্যাশ ইন" / "balance e taka asheni".
_AGENT_CASH_IN_TOKENS = [
    "agent", "এজেন্ট",
    "cash in", "cash-in", "ক্যাশ ইন", "ক্যাশইন",
    "balance e taka asheni", "ব্যালেন্সে টাকা আসেনি", "ব্যালেন্সে আসেনি",
]


def _any_token(haystack: str, tokens: Iterable[str]) -> bool:
    h = haystack.lower()
    for t in tokens:
        if t.lower() in h:
            return True
    return False


def _any_pattern(text: str, patterns: Iterable[re.Pattern]) -> bool:
    for p in patterns:
        if p.search(text):
            return True
    return False


def classify_case_type(
    complaint: str,
    user_type: Optional[str] = None,
    history: Optional[Iterable[dict]] = None,
    amount: Optional[int] = None,
    match_transaction_id: Optional[str] = None,
) -> CaseType:
    """Return the best-guess `CaseType` for a complaint.

    `user_type` and `amount` are hints pulled from the request envelope so we
    can resolve ties (e.g. settlement claim from a user_type=merchant customer
    is much more likely to be merchant_settlement_delay than refund_request).
    """
    text = complaint or ""
    lower = text.lower()

    # 1. Phishing: explicit credential request OR social-engineering framing.
    has_credential_token = (
        _any_token(lower, _PHISHING_TOKENS) or _any_pattern(text, _PHISHING_PATTERNS)
    )
    has_se_framing = _any_pattern(text, _PHISHING_SOCIAL_ENGINEERING)
    if has_credential_token or has_se_framing:
        return CaseType.PHISHING_OR_SOCIAL_ENGINEERING

    # 2. Duplicate payment.
    if _any_token(lower, _DUPLICATE_TOKENS):
        return CaseType.DUPLICATE_PAYMENT

    # 3. Wrong transfer.
    if _any_token(lower, _WRONG_TRANSFER_TOKENS) or _any_pattern(lower, _WRONG_PATTERNS):
        return CaseType.WRONG_TRANSFER

    # 4. Payment failed: a "failed" token alone is too broad (people say
    # "my recharge failed" but also "the agent failed to give me cash").
    # Require either a payment-y word nearby, or a balance-deduction cue.
    has_failed = _any_token(lower, _FAILED_TOKENS) or "failed" in lower
    if has_failed:
        payment_words = (
            "pay", "paid", "payment", "recharge", "bill", "টাকা", "পেমেন্ট",
            "রিচার্জ", "বিল",
        )
        if any(w in lower for w in payment_words) or _any_token(lower, _BALANCE_DEDUCTION):
            return CaseType.PAYMENT_FAILED
        # "failed" but no payment context: fall through to refund/other.
        if _any_token(lower, _BALANCE_DEDUCTION):
            return CaseType.PAYMENT_FAILED

    # 5. Merchant settlement: explicit "settlement" word. user_type=merchant
    # reinforces, but is not required.
    if _any_token(lower, _SETTLEMENT_TOKENS):
        return CaseType.MERCHANT_SETTLEMENT_DELAY
    if user_type == "merchant" and ("sale" in lower or "sales" in lower):
        return CaseType.MERCHANT_SETTLEMENT_DELAY

    # 6. Agent cash-in.
    has_agent = _any_token(lower, ["agent", "এজেন্ট"])
    has_cash_in = _any_token(lower, ["cash in", "cash-in", "ক্যাশ ইন", "ক্যাশইন"])
    if has_agent and has_cash_in:
        return CaseType.AGENT_CASH_IN_ISSUE
    if has_agent and _any_token(lower, _BALANCE_DEDUCTION):
        # "agent deducted but balance not updated"-ish case.
        return CaseType.AGENT_CASH_IN_ISSUE

    # 7. Refund request.
    if _any_token(lower, _REFUND_TOKENS):
        return CaseType.REFUND_REQUEST

    # 8. Fallback.
    return CaseType.OTHER


def classify_amount_band(amount: Optional[int]) -> str:
    """Bucket the disputed amount into coarse bands used by the severity
    heuristic. Returns one of: 'tiny', 'small', 'medium', 'large', 'huge'.
    """
    if amount is None:
        return "unknown"
    if amount < 1_000:
        return "tiny"
    if amount < 10_000:
        return "small"
    if amount < 50_000:
        return "medium"
    if amount < 100_000:
        return "large"
    return "huge"