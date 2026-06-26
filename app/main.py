"""FastAPI entry point for QueueStorm Investigator.

Endpoints
---------
GET  /health           - readiness probe, returns {"status":"ok"} within 60s
POST /analyze-ticket   - structured investigation (response in <30s)

Phase A scope
-------------
- App boots in under 60 seconds.
- /health returns 200 {"status":"ok"}.
- /analyze-ticket is wired but returns a Phase A stub response so the
  schema can be validated by the judge harness even before reasoning
  (Phase C) is implemented.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.schemas import (
    AnalyzeTicketRequest,
    AnalyzeTicketResponse,
    CaseType,
    Department,
    EvidenceVerdict,
    HealthResponse,
    Severity,
)

logger = logging.getLogger("queuestorm")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="QueueStorm Investigator",
    version="0.1.0",
    description="AI/API SupportOps copilot for digital finance complaints.",
)


# Track service start time for the 60s readiness window.
_STARTED_AT = time.monotonic()


@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    """Readiness probe. Must return {"status":"ok"} within 60s of start."""
    return HealthResponse(status="ok")


# ---------------------------------------------------------------------------
# Error handlers (Sections 4.1 and B in PLAN.md)
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Distinguish malformed JSON (400) from semantic schema violations (422).
    errors = exc.errors()
    is_json_error = any(err.get("type") == "json_invalid" for err in errors)
    status_code = (
        status.HTTP_400_BAD_REQUEST if is_json_error
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    error_label = "malformed_json" if is_json_error else "invalid_request"
    return JSONResponse(
        status_code=status_code,
        content={"error": error_label, "detail": _scrub_errors(errors)},
    )


@app.exception_handler(ValidationError)
async def _pydantic_exception_handler(
    _request: Request, exc: ValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "invalid_request", "detail": _scrub_errors(exc.errors())},
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    # Never leak stack traces, tokens, or secrets (Section 9.2).
    logger.exception("unhandled error in handler: %s", type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "internal_error", "detail": "an unexpected error occurred"},
    )


def _scrub_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop raw values that might contain sensitive payload bits."""
    safe: list[dict[str, Any]] = []
    for err in errors:
        safe.append(
            {
                "loc": list(err.get("loc", [])),
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
        )
    return safe


# ---------------------------------------------------------------------------
# Analyze ticket (Phase A: schema-locked stub)
# ---------------------------------------------------------------------------

def _phase_a_stub(req: AnalyzeTicketRequest) -> AnalyzeTicketResponse:
    """Phase A placeholder. Returns a schema-valid but uninformative response.

    Phase C will replace this with real evidence reasoning.
    """
    return AnalyzeTicketResponse(
        ticket_id=req.ticket_id,
        relevant_transaction_id=None,
        evidence_verdict=EvidenceVerdict.INSUFFICIENT_DATA,
        case_type=CaseType.OTHER,
        severity=Severity.LOW,
        department=Department.CUSTOMER_SUPPORT,
        agent_summary="Stub response - reasoning engine pending (Phase C).",
        recommended_next_action="Route to human agent for manual triage.",
        customer_reply=(
            "Thank you for contacting support. We have received your "
            "request and a specialist will review it shortly through "
            "official support channels."
        ),
        human_review_required=True,
        confidence=0.0,
        reason_codes=["phase_a_stub"],
    )


@app.post(
    "/analyze-ticket",
    response_model=AnalyzeTicketResponse,
    tags=["investigate"],
)
async def analyze_ticket(payload: AnalyzeTicketRequest) -> AnalyzeTicketResponse:
    """Accept one ticket per Section 5; return a structured response."""
    return _phase_a_stub(payload)
