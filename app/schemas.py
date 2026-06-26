"""Pydantic models for QueueStorm Investigator.

Spec source: SUST_Hackathon_Preli_Problem_Statement.md, Sections 5, 6, 7.

All enum values match the problem statement exactly. Variants (case
differences, plural forms, alternate spellings) are rejected by Pydantic
so the judge harness can score them as schema violations.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enums (Section 7)
# ---------------------------------------------------------------------------

class CaseType(str, Enum):
    WRONG_TRANSFER = "wrong_transfer"
    PAYMENT_FAILED = "payment_failed"
    REFUND_REQUEST = "refund_request"
    DUPLICATE_PAYMENT = "duplicate_payment"
    MERCHANT_SETTLEMENT_DELAY = "merchant_settlement_delay"
    AGENT_CASH_IN_ISSUE = "agent_cash_in_issue"
    PHISHING_OR_SOCIAL_ENGINEERING = "phishing_or_social_engineering"
    OTHER = "other"


class Department(str, Enum):
    CUSTOMER_SUPPORT = "customer_support"
    DISPUTE_RESOLUTION = "dispute_resolution"
    PAYMENTS_OPS = "payments_ops"
    MERCHANT_OPERATIONS = "merchant_operations"
    AGENT_OPERATIONS = "agent_operations"
    FRAUD_RISK = "fraud_risk"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvidenceVerdict(str, Enum):
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    INSUFFICIENT_DATA = "insufficient_data"


class Language(str, Enum):
    EN = "en"
    BN = "bn"
    MIXED = "mixed"


class Channel(str, Enum):
    IN_APP_CHAT = "in_app_chat"
    CALL_CENTER = "call_center"
    EMAIL = "email"
    MERCHANT_PORTAL = "merchant_portal"
    FIELD_AGENT = "field_agent"


class UserType(str, Enum):
    CUSTOMER = "customer"
    MERCHANT = "merchant"
    AGENT = "agent"
    UNKNOWN = "unknown"


class TxnType(str, Enum):
    TRANSFER = "transfer"
    PAYMENT = "payment"
    CASH_IN = "cash_in"
    CASH_OUT = "cash_out"
    SETTLEMENT = "settlement"
    REFUND = "refund"


class TxnStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING = "pending"
    REVERSED = "reversed"


# ---------------------------------------------------------------------------
# Request models (Section 5)
# ---------------------------------------------------------------------------

class TransactionHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(..., min_length=1)
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    type: TxnType
    amount: float = Field(..., ge=0)
    counterparty: str = Field(..., min_length=1)
    status: TxnStatus

    @field_validator("timestamp")
    @classmethod
    def _validate_iso(cls, v: str) -> str:
        # Accept ISO 8601 with optional trailing Z.
        candidate = v[:-1] + "+00:00" if v.endswith("Z") else v
        try:
            datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError(f"timestamp must be ISO 8601, got {v!r}") from exc
        return v


class AnalyzeTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str = Field(..., min_length=1)
    complaint: str = Field(..., min_length=1)
    language: Optional[Language] = None
    channel: Optional[Channel] = None
    user_type: Optional[UserType] = None
    campaign_context: Optional[str] = None
    transaction_history: list[TransactionHistoryEntry] = Field(default_factory=list)
    metadata: Optional[dict] = None


# ---------------------------------------------------------------------------
# Response models (Section 6)
# ---------------------------------------------------------------------------

class AnalyzeTicketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    relevant_transaction_id: Optional[str]
    evidence_verdict: EvidenceVerdict
    case_type: CaseType
    severity: Severity
    department: Department
    agent_summary: str = Field(..., min_length=1)
    recommended_next_action: str = Field(..., min_length=1)
    customer_reply: str = Field(..., min_length=1)
    human_review_required: bool
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reason_codes: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
