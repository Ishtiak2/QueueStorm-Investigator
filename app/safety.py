"""Safety guardrails for QueueStorm Investigator.

Implements the four safety rules from PLAN.md §5 (Section 8 of the problem
statement). The module is the **last line of defence**: every text field
that ends up in the response MUST pass through `sanitize_text()` before the
pipeline returns. It is deliberately conservative.

Rules
-----
1. Credential requests
   A `customer_reply` (or any text we expose) MUST NOT ask the customer
   for PIN, OTP, password, CVV, or a full card number. If such a request
   is detected, the offending span is redacted with `[REDACTED]` and
   `human_review_required` is forced on (via the `SafetyReport` returned
   to the pipeline).

2. Refund / reversal / unblock promises
   Phrases like "we will refund", "we will reverse", "we will unblock" are
   rewritten to a safe alternative ("any eligible amount will be
   processed through official channels after review"). This is the
   standard supported by SAMPLE-02 / SAMPLE-09 reply wording.

3. Unverified contact channels
   Any phone number other than the official `16247` short-code is
   rewritten to `16247`. Any URL other than `https://www.bkash.com` is
   stripped. Customers must never be directed to a third party or an
   external number from a generated reply.

4. Prompt-injection detection
   If the customer complaint contains instructions that look like they are
   aimed at the model (e.g. "ignore previous instructions", "system:"),
   `detect_prompt_injection()` returns True. The pipeline records the
   detection but does NOT follow the injected instruction - the text is
   still used as evidence only.

Usage
-----
The pipeline calls, in order:

    pipeline_reply, report = sanitize_text(pipeline_reply)
    if report.modified or detect_prompt_injection(req.complaint):
        needs_human = True
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Allow-list of official contact channels
# ---------------------------------------------------------------------------

OFFICIAL_NUMBERS: set[str] = {"16247"}
OFFICIAL_URLS: set[str] = {"https://www.bkash.com"}

# Replacement strings
_OFFICIAL_NUMBER_REPLACEMENT = "16247"
_OFFICIAL_CONTACT_PHRASE = "official support channels"
_REFUND_SAFE_REPLACEMENT = (
    "any eligible amount will be processed through official "
    "channels after review"
)
_REDACTION_PLACEHOLDER = "[REDACTED]"


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Rule 1a: a genuine credential request.
# "please share your OTP" / "send your PIN" / "enter your password"
_REQUEST_RE = re.compile(
    r"\b(?:please\s+)?(?:share|send|provide|give|tell|enter|type|verify)\s+"
    r"(?:your\s+)?"
    r"(?:pin|otp|password|cvv|full\s*card(?:\s+number)?)\b",
    re.IGNORECASE,
)

# Rule 1b: negation that turns a request into a safety warning.
# "do not share your PIN" / "never share your OTP"
_NEGATION_RE = re.compile(
    r"\b(?:do\s+not|don'?t|never|please\s+do\s+not|please\s+never)\s+"
    r"(?:share|send|provide|give|tell|enter|type|verify)\b",
    re.IGNORECASE,
)

# Rule 2: refund / reverse / unblock / release / return promises.
# "We will refund / have refunded / shall reverse / we'll unblock"
_REFUND_PROMISE_RE = re.compile(
    r"\b(?:we\s+will|we\s+have|we(?:'ll)?|shall|we\s+can)\s+"
    r"(?:refund|reverse|unblock|release|return)\b[^.]*",
    re.IGNORECASE,
)

# Rule 3a: any phone-shaped number. We keep digits-only comparison so
# +8801719876543 and 01719876543 both resolve to 8801719876543.
_PHONE_RE = re.compile(r"\+?(?:88)?0?\d{10,13}")

# Rule 3b: any URL.
_URL_RE = re.compile(r"https?://[^\s)>\]\"'`]+", re.IGNORECASE)

# Rule 4: prompt-injection signatures. These are patterns that look like
# instructions TO the assistant rather than a real customer complaint.
_INJECTION_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?\b",
               re.IGNORECASE),
    re.compile(r"\bdisregard\s+(?:all\s+)?(?:previous|prior|above|everything|the)\b",
               re.IGNORECASE),
    re.compile(r"\bsystem\s*:\s*", re.IGNORECASE),
    re.compile(r"\b(?:you\s+are\s+now|act\s+as)\b\s+(?:a|an|the)?\s*"
               r"(?:chatbot|assistant|model|ai)\b", re.IGNORECASE),
    re.compile(r"\bforget\s+(?:everything|all)\b", re.IGNORECASE),
    re.compile(r"\boverride\s+(?:safety|policy|rules?)\b", re.IGNORECASE),
    re.compile(r"\breveal\s+(?:the\s+)?(?:system|hidden)\s+prompt\b",
               re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class SafetyReport:
    """Tally of safety actions taken on a piece of text."""

    modified: bool = False
    credential_request: bool = False
    refund_promise: bool = False
    bad_contact: bool = False
    redactions: List[str] = field(default_factory=list)

    def escalate(self) -> bool:
        """True if any rule fired and the pipeline should force human review."""
        return any([
            self.credential_request,
            self.refund_promise,
            self.bad_contact,
        ])


# ---------------------------------------------------------------------------
# Rule 4: prompt-injection detection
# ---------------------------------------------------------------------------

def detect_prompt_injection(text: str) -> bool:
    """Return True if `text` looks like an attempt to steer the model.

    The detection is pattern-based and intentionally tight. False positives
    on legitimate complaints are acceptable (the cost is one human review);
    false negatives could let an attacker rewrite our response.
    """
    if not text:
        return False
    return any(p.search(text) for p in _INJECTION_PATTERNS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s)


def _is_official_number(raw: str) -> bool:
    return _digits_only(raw) in OFFICIAL_NUMBERS


def _is_official_url(raw: str) -> bool:
    cleaned = raw.rstrip(".,;:!?)\"'`")
    return cleaned.lower() in {u.lower() for u in OFFICIAL_URLS}


# ---------------------------------------------------------------------------
# Rule 1 + 2 + 3: text sanitiser
# ---------------------------------------------------------------------------

def sanitize_text(text: str) -> Tuple[str, SafetyReport]:
    """Apply safety rules 1, 2, 3 to `text` and return (new_text, report).

    The function never raises; on any anomaly it redacts or rewrites the
    offending span and records it in the returned `SafetyReport`. The
    caller (the pipeline) inspects the report and forces
    `human_review_required` if `escalate()` is True.
    """
    if not text:
        return text, SafetyReport()

    report = SafetyReport()
    out = text

    # --- Rule 2: refund / reversal / unblock promises -------------------
    def _replace_refund(match: re.Match[str]) -> str:
        report.modified = True
        report.refund_promise = True
        report.redactions.append(
            f"refund_promise@{match.start()}: {match.group(0)[:40]!r}"
        )
        return _REFUND_SAFE_REPLACEMENT

    out = _REFUND_PROMISE_RE.sub(_replace_refund, out)

    # --- Rule 1: credential requests (only if not negated) ---------------
    # We re-scan on the current `out` because rule 2 may have rewritten
    # surrounding text.
    if _REQUEST_RE.search(out) and not _NEGATION_RE.search(out):
        report.modified = True
        report.credential_request = True
        report.redactions.append("credential_request")
        out = _REQUEST_RE.sub(_REDACTION_PLACEHOLDER, out)

    # --- Rule 3a: phone numbers ------------------------------------------
    def _replace_phone(match: re.Match[str]) -> str:
        raw = match.group(0)
        if _is_official_number(raw):
            return raw
        report.modified = True
        report.bad_contact = True
        report.redactions.append(
            f"unverified_phone:{_digits_only(raw)}"
        )
        return _OFFICIAL_NUMBER_REPLACEMENT

    out = _PHONE_RE.sub(_replace_phone, out)

    # --- Rule 3b: URLs ---------------------------------------------------
    def _replace_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        cleaned = raw.rstrip(".,;:!?)\"'`")
        if _is_official_url(cleaned):
            return raw
        report.modified = True
        report.bad_contact = True
        report.redactions.append(f"unverified_url:{cleaned[:60]}")
        return _OFFICIAL_CONTACT_PHRASE

    out = _URL_RE.sub(_replace_url, out)

    return out, report


__all__ = [
    "OFFICIAL_NUMBERS",
    "OFFICIAL_URLS",
    "SafetyReport",
    "detect_prompt_injection",
    "sanitize_text",
]