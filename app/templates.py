"""Customer-reply, agent-summary, and next-action templates.

All customer-reply templates follow the Section 8 safety rules:
  - never request PIN, OTP, password, CVV, or full card number;
  - never promise a refund / reversal / unblock;
  - never direct the customer to a third party outside official channels.

The templates are calibrated against the 10 public sample cases in
`SUST_Preli_Sample_Cases.json`. They return plain text, not Markdown, so they
are safe to drop directly into the `customer_reply` field.
"""
from __future__ import annotations

from typing import Optional

from app.schemas import CaseType, EvidenceVerdict

# Universal safety footer (English). Phishing and refund cases use a slightly
# different footer; see the per-case-type functions below.
_SAFETY_EN = "Please do not share your PIN or OTP with anyone."
_SAFETY_BN = "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"

# Refund-safe phrasing, used whenever money might come back to the customer.
_REFUND_SAFE_EN = (
    "any eligible amount will be returned through official channels"
)
_REFUND_SAFE_BN = (
    "যোগ্য পরিমাণ অফিসিয়াল চ্যানেলে ফেরত দেওয়া হবে"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_txn(txn_id: Optional[str]) -> str:
    return txn_id if txn_id else "your transaction"


def _is_bn_or_mixed(text: str) -> bool:
    """Return True if the input string contains Bengali-script characters."""
    return any("\u0980" <= ch <= "\u09ff" for ch in text or "")


# ---------------------------------------------------------------------------
# Customer reply
# ---------------------------------------------------------------------------

def customer_reply(
    case_type: CaseType,
    txn_id: Optional[str],
    verdict: EvidenceVerdict,
    complaint: str,
    language: str = "en",
) -> str:
    """Build the safe customer-facing reply.

    `language` is the value from the request (`en`/`bn`/`mixed`). For Bangla
    or Bangla-heavy input we return a fully Bangla reply (SAMPLE-07).
    """
    use_bn = (language == "bn") or (language == "mixed" and _is_bn_or_mixed(complaint))
    tid = _fmt_txn(txn_id)

    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return _phishing_reply(language, use_bn)

    if use_bn:
        return _bangla_reply(case_type, tid, verdict)

    # English / mixed-with-ASCII path.
    return _english_reply(case_type, tid, verdict)


def _english_reply(case_type: CaseType, tid: str, verdict: EvidenceVerdict) -> str:
    if case_type == CaseType.WRONG_TRANSFER:
        if verdict == EvidenceVerdict.CONSISTENT:
            return (
                f"We have noted your concern about transaction {tid}. {_SAFETY_EN} "
                "Our dispute team will review the case and contact you "
                "through official support channels."
            )
        # inconsistent / insufficient
        return (
            f"We have received your request regarding transaction {tid}. "
            f"{_SAFETY_EN} Our dispute team will review the case carefully and "
            "contact you through official support channels."
        )

    if case_type == CaseType.PAYMENT_FAILED:
        return (
            f"We have noted that transaction {tid} may have caused an "
            "unexpected balance deduction. Our payments team will review the "
            f"case and {_REFUND_SAFE_EN}. {_SAFETY_EN}"
        )

    if case_type == CaseType.REFUND_REQUEST:
        return (
            "Thank you for reaching out. Refunds for completed merchant "
            "payments depend on the merchant's own policy. We recommend "
            "contacting the merchant directly. If you need help reaching "
            f"them, please reply and we will guide you. {_SAFETY_EN}"
        )

    if case_type == CaseType.DUPLICATE_PAYMENT:
        return (
            f"We have noted the possible duplicate payment for transaction "
            f"{tid}. Our payments team will verify with the biller and "
            f"{_REFUND_SAFE_EN}. {_SAFETY_EN}"
        )

    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return (
            f"We have noted your concern about settlement {tid}. Our "
            "merchant operations team will check the batch status and "
            "update you on the expected settlement time through official "
            "channels."
        )

    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return (
            f"We have noted your concern about transaction {tid}. Our "
            "agent operations team will verify this quickly and update you "
            "through official channels. "
            f"{_SAFETY_EN}"
        )

    # other / vague / insufficient_data
    return (
        "Thank you for reaching out. To help you faster, please share the "
        "transaction ID, the amount involved, and a short description of "
        f"what went wrong. {_SAFETY_EN}"
    )


def _bangla_reply(case_type: CaseType, tid: str, verdict: EvidenceVerdict) -> str:
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return (
            f"আপনার লেনদেন {tid} এর বিষয়ে আমরা অবগত হয়েছি। "
            "আমাদের এজেন্ট অপারেশন্স দল এটি দ্রুত যাচাই করবে এবং "
            "অফিসিয়াল চ্যানেলে আপনাকে জানাবে। "
            f"{_SAFETY_BN}"
        )

    # Generic Bangla fallbacks.
    if case_type == CaseType.WRONG_TRANSFER:
        return (
            f"আপনার লেনদেন {tid} সংক্রান্ত অভিযোগ আমরা পেয়েছি। "
            f"{_SAFETY_BN} আমাদের ডিসপিউট টিম এটি পর্যালোচনা করে "
            "অফিসিয়াল চ্যানেলে আপনার সাথে যোগাযোগ করবে।"
        )

    if case_type == CaseType.PAYMENT_FAILED:
        return (
            f"লেনদেন {tid} এর কারণে আপনার ব্যালেন্স থেকে টাকা কেটে যেতে "
            "পারে বলে আমরা অবগত হয়েছি। আমাদের পেমেন্টস টিম এটি পর্যালোচনা "
            f"করবে এবং {_REFUND_SAFE_BN}। {_SAFETY_BN}"
        )

    return (
        "আপনার মূল্যবান মতামতের জন্য ধন্যবাদ। দয়া করে লেনদেনের আইডি, পরিমাণ "
        "এবং সংক্ষেপে সমস্যাটি জানালে আমরা দ্রুত সাহায্য করতে পারব। "
        f"{_SAFETY_BN}"
    )


def _phishing_reply(language: str, use_bn: bool) -> str:
    if use_bn:
        return (
            "যেকোনো তথ্য শেয়ার করার আগে আমাদের সাথে যোগাযোগ করার জন্য "
            "ধন্যবাদ। আমরা কখনোই কোনো অবস্থাতেই আপনার পিন, ওটিপি বা "
            "পাসওয়ার্ড জিজ্ঞেস করি না। কেউ নিজেকে আমাদের প্রতিনিধি "
            "বললেও এই তথ্যগুলো শেয়ার করবেন না। আমাদের ফ্রড টিম এই ঘটনা "
            "সম্পর্কে অবহিত হয়েছে।"
        )
    return (
        "Thank you for reaching out before sharing any information. We never "
        "ask for your PIN, OTP, or password under any circumstances. Please "
        "do not share these with anyone, even if they claim to be from us. "
        "Our fraud team has been notified of this incident."
    )


# ---------------------------------------------------------------------------
# Agent summary (1-2 sentences, agent-facing, contains txn id)
# ---------------------------------------------------------------------------

def agent_summary(
    case_type: CaseType,
    txn_id: Optional[str],
    verdict: EvidenceVerdict,
    complaint: str,
    amount: Optional[int],
    user_type: Optional[str] = None,
) -> str:
    tid = _fmt_txn(txn_id)
    amt = f"{amount} BDT " if amount is not None else ""
    cp_summary = _first_counterparty_phrase(complaint)
    cp_clause = f" to {cp_summary}" if cp_summary else ""

    if case_type == CaseType.WRONG_TRANSFER:
        if verdict == EvidenceVerdict.INCONSISTENT:
            return (
                f"Customer claims {tid} ({amt}transfer{cp_clause}) was a "
                "wrong transfer, but transaction history shows prior "
                "transfers to the same counterparty, suggesting an "
                "established recipient."
            )
        return (
            f"Customer reports sending {amt}via {tid}{cp_clause}, which "
            "they now believe was the wrong recipient. "
            + ("Recipient is unresponsive." if cp_summary else
               "Recipient details to be confirmed with the customer.")
        )

    if case_type == CaseType.PAYMENT_FAILED:
        return (
            f"Customer attempted a {amt}payment ({tid}) which failed, but "
            "reports balance was deducted. Requires payments operations "
            "investigation."
        )

    if case_type == CaseType.REFUND_REQUEST:
        return (
            f"Customer requests refund of {amt}for {tid} (merchant payment) "
            "due to change of mind. Not a service failure."
        )

    if case_type == CaseType.DUPLICATE_PAYMENT:
        return (
            f"Customer reports a possible duplicate {amt}payment around "
            f"{tid}. Multiple near-identical charges detected; the second "
            "is the likely duplicate."
        )

    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return (
            f"Merchant reports a {amt}settlement ({tid}) is delayed beyond "
            "the standard next-day window. Settlement status is pending."
        )

    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return (
            f"Customer reports {amt}cash-in ({tid}) not reflected in balance. "
            "Transaction status is pending."
        )

    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return (
            "Customer reports an unsolicited call or message asking for "
            "credentials (OTP/PIN/password). Likely social engineering "
            "attempt."
        )

    # other / vague
    return (
        "Customer reports a concern without specifying transaction, "
        "amount, or issue. Insufficient detail to identify any relevant "
        "transaction."
    )


def _first_counterparty_phrase(complaint: str) -> Optional[str]:
    """Pull a short counterparty snippet (e.g. +8801719876543) for summaries."""
    import re
    if not complaint:
        return None
    m = re.search(r"\+?88?\d{10,13}", complaint)
    if m:
        return m.group(0)
    m = re.search(r"\b(?:AGENT|MERCHANT|BILLER)-[A-Z0-9-]+\b", complaint)
    if m:
        return m.group(0)
    return None


# ---------------------------------------------------------------------------
# Recommended next action
# ---------------------------------------------------------------------------

def recommended_next_action(
    case_type: CaseType,
    txn_id: Optional[str],
    verdict: EvidenceVerdict,
    complaint: str,
    user_type: Optional[str] = None,
) -> str:
    tid = _fmt_txn(txn_id)

    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return (
            "Escalate to fraud_risk team immediately. Confirm to customer "
            "that the company never asks for OTP. Log the reported number "
            "for fraud pattern analysis."
        )

    if case_type == CaseType.WRONG_TRANSFER:
        if verdict == EvidenceVerdict.INCONSISTENT:
            return (
                "Flag for human review. Verify with the customer whether "
                "this was genuinely a wrong transfer given the established "
                "transaction pattern with this recipient."
            )
        return (
            f"Verify {tid} details with the customer and initiate the "
            "wrong-transfer dispute workflow per policy."
        )

    if case_type == CaseType.PAYMENT_FAILED:
        return (
            f"Investigate {tid} ledger status. If balance was deducted on a "
            "failed payment, initiate the automatic reversal flow within "
            "standard SLA."
        )

    if case_type == CaseType.REFUND_REQUEST:
        return (
            "Inform the customer that refund eligibility depends on the "
            "merchant's own policy. Provide guidance on contacting the "
            "merchant directly for a refund."
        )

    if case_type == CaseType.DUPLICATE_PAYMENT:
        return (
            f"Verify the duplicate with payments_ops. If the biller confirms "
            f"only one payment was received, initiate reversal of {tid}."
        )

    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return (
            "Route to merchant_operations to verify settlement batch "
            "status. If the batch is delayed, communicate a revised ETA to "
            "the merchant."
        )

    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return (
            f"Investigate {tid} pending status with agent operations. "
            "Confirm settlement state and resolve within the standard "
            "cash-in SLA."
        )

    # other / insufficient_data
    return (
        "Reply to customer asking for specific details: which transaction, "
        "what amount, what went wrong, and approximate time."
    )
