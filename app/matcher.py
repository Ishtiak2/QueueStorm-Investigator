"""Transaction matching.

Given a complaint string and a list of `TransactionHistoryEntry` records, this
module extracts the customer's reported amount / time-of-day / counterparty
clues and picks the transaction that best matches, if any.

Public API
----------
- `MatchResult`           - dataclass returned by `match_transaction`.
- `match_transaction(...)` - find the single best-matching transaction.
- `extract_amount(...)`    - amount in BDT (int) or None.
- `extract_time(...)`      - approximate time-of-day (datetime.time) or None.
- `extract_counterparty(...)` - normalized counterparty (str) or None.

Scoring
-------
    amount_match      * 3   (binary)
    time_within_4h    * 2   (binary)
    counterparty_match* 3   (binary; uses substring containment)

Threshold = 3 (i.e. at least one of the strong signals). When the top two
candidates tie on score we return `None` (ambiguous), which the verdict layer
maps to `insufficient_data` (see Section 3 / SAMPLE-08).

Bangla / Banglish support
-------------------------
Bengali digits `০..৯` are normalized to ASCII `0..9` before any numeric
extraction. Keyword heuristics that the classifier uses rely on the same
normalization.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Bengali -> ASCII digit map. Used for amount extraction and any other place
# we need to parse numerals from Bangla text.
_BN_DIGIT_MAP = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# A reasonable range for transaction amounts in BDT. The problem statement
# does not bound the field, but in practice it is always 2-7 digits. We accept
# 2-7 digits to be safe.
_AMOUNT_RE = re.compile(r"\b(\d{2,7})\b")

# Phone numbers, including the +88 prefix and 11-13 digits total. Counterparty
# strings in the spec use E.164-ish forms like `+8801719876543`.
_PHONE_RE = re.compile(r"\+?88?\d{10,13}")

# Merchant / agent / biller IDs: words that look like identifiers.
# We capture tokens such as MERCHANT-MOBILE-OP, AGENT-318, BILLER-DESCO.
_ID_RE = re.compile(r"\b[A-Z][A-Z0-9-]{2,}\b")

# English relative time-of-day references.
_TIME_PHRASES_EN: dict[str, tuple[int, int]] = {
    "morning": (9, 0),
    "afternoon": (14, 0),
    "noon": (12, 0),
    "midday": (12, 0),
    "evening": (18, 0),
    "night": (21, 0),
    "midnight": (0, 0),
}

# Bangla relative time-of-day references.
_TIME_PHRASES_BN: dict[str, tuple[int, int]] = {
    "সকাল": (9, 0),
    "দুপুর": (14, 0),
    "বিকাল": (16, 0),
    "সন্ধ্যা": (18, 0),
    "রাত": (21, 0),
}

# Numeric time-of-day (24h or 12h with am/pm) like "2pm", "14:30", "around 4".
_TIME_NUMERIC_RE = re.compile(
    r"\b(?:around|at|@|approximately|approx\.?|~)?\s*"
    r"(?P<hour>\d{1,2})(?::(?P<min>\d{2}))?\s*"
    r"(?P<ampm>a\.?m\.?|p\.?m\.?)?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MatchResult:
    """Result of matching a complaint to a transaction.

    `transaction_id` is None when no candidate clears the threshold or when
    two or more candidates tie on score (ambiguous).
    `score` is the raw score of the chosen (or top) candidate, useful for
    confidence calibration.
    `ambiguous` is True when the top two scores tie - the caller is expected
    to surface this as `insufficient_data`.
    """
    transaction_id: Optional[str]
    score: int
    ambiguous: bool


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------

def _normalize_digits(text: str) -> str:
    """Map Bengali digits to ASCII so downstream regexes work uniformly."""
    return text.translate(_BN_DIGIT_MAP)


def extract_amount(complaint: str) -> Optional[int]:
    """Return the first amount in BDT mentioned in the complaint, or None.

    We deliberately pick the FIRST amount because customers usually state the
    disputed amount first ("I sent 5000 to..."). For duplicate-payment
    complaints the classifier layer detects that pattern separately.
    """
    norm = _normalize_digits(complaint)
    m = _AMOUNT_RE.search(norm)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def extract_time(complaint: str) -> Optional[time]:
    """Return an approximate time-of-day from the complaint, or None.

    Supports:
    - explicit numeric times: "2pm", "14:30", "around 4"
    - English keywords: morning / afternoon / evening / night / noon / midnight
    - Bangla keywords: সকাল / দুপুর / বিকাল / সন্ধ্যা / রাত
    """
    if not complaint:
        return None

    norm = complaint.lower()

    # 1) Numeric "2pm" / "14:30" / "around 4".
    for m in _TIME_NUMERIC_RE.finditer(norm):
        raw = m.group(0).strip()
        # Filter out junk like bare numbers from non-time context. Require
        # either an explicit am/pm marker or a colon, OR a contextual
        # time-of-day keyword in the immediate vicinity.
        has_ampm = bool(m.group("ampm"))
        has_colon = bool(m.group("min"))
        hour = int(m.group("hour"))
        if hour < 0 or hour > 23:
            continue
        if has_ampm:
            ampm = m.group("ampm").lower().replace(".", "")
            if ampm.startswith("p") and hour < 12:
                hour += 12
            elif ampm.startswith("a") and hour == 12:
                hour = 0
            minute = int(m.group("min") or 0)
            return time(hour % 24, minute)
        if has_colon:
            minute = int(m.group("min"))
            if 0 <= hour < 24 and 0 <= minute < 60:
                return time(hour, minute)

    # 2) Bangla keywords first (so we don't match 'morning' in English text).
    for key, (h, mm) in _TIME_PHRASES_BN.items():
        if key in complaint:
            return time(h, mm)

    # 3) English keywords.
    for key, (h, mm) in _TIME_PHRASES_EN.items():
        if re.search(rf"\b{key}\b", norm):
            return time(h, mm)

    return None


def extract_counterparty(complaint: str) -> Optional[str]:
    """Return the most specific counterparty signal from the complaint.

    Heuristic priority:
      1. Phone-shaped substring (anything matching `_PHONE_RE`).
      2. Uppercase identifier token (MERCHANT-..., AGENT-..., BILLER-...).
    If nothing matches, return None.

    For "wrong number" claims the classifier layer separately signals
    `wrong_transfer`; this function only returns the *value* the customer
    reported, if any.
    """
    if not complaint:
        return None

    # Normalize Bengali digits first so phones in Bangla are still picked up.
    norm = _normalize_digits(complaint)
    m = _PHONE_RE.search(norm)
    if m:
        return m.group(0)

    for token in _ID_RE.findall(complaint):
        # Skip generic words; require a digit or hyphen to count as an id.
        if any(ch.isdigit() for ch in token) or "-" in token:
            return token
    return None


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------

def _parse_txn_timestamp(raw: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp. Accepts trailing 'Z'. Returns None on
    failure (we never want to crash the whole pipeline on a malformed entry).
    """
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw[:-1]).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _dt_distance_hours(a: datetime, b: datetime) -> float:
    """Absolute distance between two datetimes in hours (timezone-aware safe)."""
    if a.tzinfo is None and b.tzinfo is not None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None and a.tzinfo is not None:
        b = b.replace(tzinfo=timezone.utc)
    return abs((a - b).total_seconds()) / 3600.0


def match_transaction(
    complaint: str,
    history: Iterable[dict],
) -> MatchResult:
    """Find the single best-matching transaction for `complaint`.

    Each candidate is scored:
      amount == reported     -> +3
      time-of-day within 4h  -> +2
      counterparty match     -> +3

    Ties on the top score are treated as ambiguous (returns `transaction_id=None`
    and `ambiguous=True`). A score of 0 always returns None with ambiguous=False.
    """
    history = list(history)
    if not history:
        return MatchResult(transaction_id=None, score=0, ambiguous=False)

    amount = extract_amount(complaint)
    t_time = extract_time(complaint)
    cp = extract_counterparty(complaint)

    scored: list[tuple[int, dict]] = []
    for txn in history:
        score = 0

        # --- amount match (exact equality on the numeric field) ---
        if amount is not None:
            try:
                if int(txn.get("amount", -1)) == amount:
                    score += 3
            except (TypeError, ValueError):
                pass

        # --- time-of-day within 4 hours of txn timestamp ---
        if t_time is not None:
            ts = _parse_txn_timestamp(str(txn.get("timestamp", "")))
            if ts is not None:
                txn_time = ts.time()
                # Compare the time-of-day component. We treat the delta as
                # `min(|a-b|, 24h-|a-b|)` so it wraps around midnight.
                a_min = t_time.hour * 60 + t_time.minute
                b_min = txn_time.hour * 60 + txn_time.minute
                delta_min = abs(a_min - b_min)
                delta_min = min(delta_min, 24 * 60 - delta_min)
                if delta_min <= 4 * 60:
                    score += 2

        # --- counterparty match (substring containment, both ways) ---
        if cp:
            txn_cp = str(txn.get("counterparty", ""))
            if cp and (cp in txn_cp or txn_cp in cp):
                score += 3

        scored.append((score, txn))

    if not scored:
        return MatchResult(transaction_id=None, score=0, ambiguous=False)

    # Pick the highest score; tie = ambiguous.
    scored.sort(key=lambda x: (-x[0], x[1].get("transaction_id", "")))
    top_score, top_txn = scored[0]
    if top_score < 3:
        return MatchResult(transaction_id=None, score=top_score, ambiguous=False)

    if len(scored) > 1 and scored[1][0] == top_score:
        return MatchResult(transaction_id=None, score=top_score, ambiguous=True)

    return MatchResult(
        transaction_id=top_txn.get("transaction_id"),
        score=top_score,
        ambiguous=False,
    )


def find_duplicate(history: Iterable[dict], amount: Optional[int]) -> Optional[str]:
    """Return the id of the second of two near-identical transactions when
    the customer is reporting a duplicate charge.

    Heuristic: among transactions with the matching amount AND same
    counterparty, return the one with the later timestamp (we assume the
    system processed the first then accidentally re-charged).

    Returns None if no clear pair is found.
    """
    if amount is None:
        return None
    candidates = []
    for txn in history:
        try:
            if int(txn.get("amount", -1)) != amount:
                continue
        except (TypeError, ValueError):
            continue
        ts = _parse_txn_timestamp(str(txn.get("timestamp", "")))
        if ts is None:
            continue
        candidates.append((ts, txn))
    if len(candidates) < 2:
        return None
    candidates.sort(key=lambda x: x[0])
    cp = candidates[0][1].get("counterparty")
    same_cp = [c for c in candidates if c[1].get("counterparty") == cp]
    if len(same_cp) < 2:
        return None
    # Return the latest of a same-counterparty, same-amount pair if they are
    # within 10 minutes of each other (otherwise they look like two separate
    # legitimate payments).
    same_cp.sort(key=lambda x: x[0])
    if (same_cp[-1][0] - same_cp[0][0]) <= timedelta(minutes=10):
        return same_cp[-1][1].get("transaction_id")
    return None
