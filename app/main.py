"""FastAPI entry point for QueueStorm Investigator.

Endpoints
---------
GET  /health           - readiness probe, returns {"status":"ok"} within 60s
POST /analyze-ticket   - structured investigation (response in <30s)

HTTP contract (Section 4.1 of the problem statement)
----------------------------------------------------
200 OK             Successful analysis; body conforms to output schema.
400 Bad Request    Malformed input (invalid JSON, missing required fields).
                   Body: {"error": "malformed_json", "detail": [...]} or
                         {"error": "bad_request",  "detail": "..."}.
422 Unprocessable  Schema-valid JSON but semantically invalid (e.g.
                   empty complaint). Body: {"error": "invalid_request",
                   "detail": [...]}.
500 Server Error   Internal failure; never leaks stack traces, tokens,
                   or sensitive payload values.

Phase C scope
-------------
Adds the full evidence-reasoning pipeline (matcher -> verdict -> classifier
-> routing -> templates). The `/analyze-ticket` handler now returns a
substantive response derived from the complaint and transaction history,
while keeping the Phase B safety nets (echoed ticket_id, scrubbed error
bodies, 400/422/500 semantics).

Key invariants:
- All Section 6 response fields are typed and required.
- `ticket_id` is echoed verbatim in the response (Section 6.1).
- Error bodies are non-sensitive (no raw complaint text, no tokens).
- The reasoning engine must complete well under the 30s request budget.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.classifier import classify_case_type
from app.matcher import (
    extract_amount,
    find_duplicate,
    match_transaction,
)
from app.routing import (
    pick_department,
    pick_severity,
    requires_human_review,
)
from app.templates import (
    agent_summary,
    customer_reply,
    recommended_next_action,
)
from app.verdict import (
    confidence_for,
    decide_verdict,
    reason_codes_for,
)
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
    version="0.3.0",
    description="AI/API SupportOps copilot for digital finance complaints.",
)

# Track service start time for the 60s readiness window.
_STARTED_AT = time.monotonic()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    """Readiness probe. Must return {"status":"ok"} within 60s of start."""
    return HealthResponse(status="ok")


# ---------------------------------------------------------------------------
# Error handlers (Section 4.1)
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Map Pydantic/FastAPI body validation errors to spec-mandated HTTP codes.

    - `json_invalid` -> 400 Bad Request (malformed JSON).
    - Everything else (missing field, wrong type, bad enum, empty string,
      whitespace-only complaint) -> 422 Unprocessable Entity.
    """
    errors = exc.errors()
    is_json_error = any(err.get("type") == "json_invalid" for err in errors)

    if is_json_error:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "malformed_json", "detail": _scrub_errors(errors)},
        )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "invalid_request", "detail": _scrub_errors(errors)},
    )


@app.exception_handler(ValidationError)
async def _pydantic_exception_handler(
    _request: Request, exc: ValidationError
) -> JSONResponse:
    """Belt-and-braces handler for any ValidationError that escapes Pydantic
    outside the request body (e.g. inside helpers). Maps to 422."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "invalid_request", "detail": _scrub_errors(exc.errors())},
    )


@app.exception_handler(HTTPException)
async def _http_exception_handler(
    _request: Request, exc: HTTPException
) -> JSONResponse:
    """Surface HTTPExceptions raised inside handlers with a safe body."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": _label_for_status(exc.status_code),
            "detail": exc.detail if isinstance(exc.detail, str) else "request rejected",
        },
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    """Last-resort handler. Never leak stack traces, tokens, or secrets
    (Section 9.2 of the problem statement)."""
    logger.exception("unhandled error in handler: %s", type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "internal_error", "detail": "an unexpected error occurred"},
    )


def _label_for_status(code: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        408: "request_timeout",
        413: "payload_too_large",
        415: "unsupported_media_type",
        422: "invalid_request",
        429: "rate_limited",
    }.get(code, "error")


def _scrub_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip raw `input` / `ctx` payloads from validation errors so we never
    echo back sensitive complaint text or other user data in 4xx bodies."""
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
# Analyze ticket (Phase A: schema-locked stub; Phase C will replace)
# ---------------------------------------------------------------------------

def _run_reasoning_pipeline(req: AnalyzeTicketRequest) -> AnalyzeTicketResponse:
    """Phase C: end-to-end evidence reasoning pipeline.

    Order:
      1. Extract amount from complaint (Bengali digit normalisation included).
      2. Run the matcher to pick the best transaction (or None / ambiguous).
      3. If the classifier flags duplicate_payment, prefer the second-of-pair
         charge from `find_duplicate` (Section 3, SAMPLE-10).
      4. Decide verdict, severity, department, human_review_required.
      5. Render agent_summary, recommended_next_action, customer_reply from
         the template layer (templates.py handles the Section 8 safety rules).
    """
    history = [t.model_dump(mode="json") for t in (req.transaction_history or [])]
    complaint = req.complaint
    language = (req.language or "en").value if req.language else "en"

    # 1. amount
    amount = extract_amount(complaint)

    # 2. case_type first (phishing must short-circuit matcher relevance)
    case_type = classify_case_type(
        complaint,
        user_type=req.user_type.value if req.user_type else None,
        history=history,
        amount=amount,
    )

    # 3. match the transaction
    match = match_transaction(complaint, history)
    relevant_txn = match.transaction_id

    # 4. duplicate_payment override (SAMPLE-10): if a same-amount, same-cp
    # pair exists within 10 minutes, point at the second one.
    if case_type == CaseType.DUPLICATE_PAYMENT and amount is not None:
        dup = find_duplicate(history, amount)
        if dup:
            relevant_txn = dup
            match = match.__class__(
                transaction_id=dup, score=match.score + 1, ambiguous=False
            )

    # 5. verdict
    verdict = decide_verdict(case_type, match, complaint, history)

    # 6. routing
    department = pick_department(
        case_type,
        req.user_type.value if req.user_type else None,
    )
    severity = pick_severity(case_type, amount, verdict)
    needs_human = requires_human_review(
        case_type, amount, verdict, department,
    )

    # 7. text (templates)
    summary = agent_summary(
        case_type, relevant_txn, verdict, complaint, amount,
        req.user_type.value if req.user_type else None,
    )
    next_action = recommended_next_action(
        case_type, relevant_txn, verdict, complaint,
        req.user_type.value if req.user_type else None,
    )
    reply = customer_reply(case_type, relevant_txn, verdict, complaint, language)

    confidence = confidence_for(case_type, match, verdict, complaint)
    reasons = reason_codes_for(case_type, match, verdict)

    return AnalyzeTicketResponse(
        ticket_id=req.ticket_id,
        relevant_transaction_id=relevant_txn,
        evidence_verdict=verdict,
        case_type=case_type,
        severity=severity,
        department=department,
        agent_summary=summary,
        recommended_next_action=next_action,
        customer_reply=reply,
        human_review_required=needs_human,
        confidence=confidence,
        reason_codes=reasons,
    )


# Whitelist of request Content-Type values we accept.
_ALLOWED_CONTENT_TYPES = {"application/json"}


@app.post(
    "/analyze-ticket",
    response_model=AnalyzeTicketResponse,
    tags=["investigate"],
)
async def analyze_ticket(
    request: Request, payload: AnalyzeTicketRequest
) -> AnalyzeTicketResponse:
    """Accept one ticket per Section 5; return a structured response.

    Notes:
    - Content-Type must be application/json; anything else is 415.
    - Body must be valid JSON (Pydantic returns 400 on bad JSON).
    - `ticket_id` is echoed verbatim.
    - Any semantically empty field is rejected with 422 before reaching
      the reasoning engine.
    """
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        # FastAPI would normally 422 on a wrong content-type for a JSON model;
        # we surface it as 415 to be explicit.
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"expected application/json, got {content_type or 'missing'}",
        )

    # Extra defensive check (Pydantic already covers these, but a clearer
    # 422 helps the harness spot the right cause).
    if not payload.ticket_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ticket_id must contain non-whitespace characters",
        )
    if not payload.complaint.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="complaint must contain non-whitespace characters",
        )

    return _run_reasoning_pipeline(payload)
