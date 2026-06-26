"""HTTP integration tests for the FastAPI app.

Covers the Section 5/9 contract:
- GET  /health               -> 200
- POST /analyze-ticket       -> 200 (success path)
- POST /analyze-ticket       -> 400 (malformed JSON)
- POST /analyze-ticket       -> 422 (validation)
- POST /analyze-ticket       -> 500 (unhandled error - no stacktrace leak)
- Error body never contains the complaint text
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_returns_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# 200 OK - success path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_ticket_returns_200_with_echo(client):
    body = {
        "ticket_id": "TKT-001",
        "complaint": "I sent 5000 taka to a wrong number around 2pm today.",
        "language": "en",
        "channel": "in_app_chat",
        "user_type": "customer",
        "transaction_history": [
            {
                "transaction_id": "TXN-9101",
                "timestamp": "2026-04-14T14:08:22Z",
                "type": "transfer",
                "amount": 5000,
                "counterparty": "+8801719876543",
                "status": "completed",
            }
        ],
    }
    r = await client.post("/analyze-ticket", json=body)
    assert r.status_code == 200
    data = r.json()

    # ticket_id must be echoed verbatim (Section 6.1).
    assert data["ticket_id"] == "TKT-001"

    # All Section 6 fields must be present.
    required = {
        "ticket_id",
        "relevant_transaction_id",
        "evidence_verdict",
        "case_type",
        "severity",
        "department",
        "agent_summary",
        "recommended_next_action",
        "customer_reply",
        "human_review_required",
        "confidence",
        "reason_codes",
    }
    assert required.issubset(data.keys()), f"missing fields: {required - set(data.keys())}"

    # Pipeline correctly classifies this as a wrong_transfer with a
    # matching completed transaction (Phase C behavior).
    assert data["evidence_verdict"] == "consistent"
    assert data["case_type"] == "wrong_transfer"
    assert data["severity"] == "high"
    assert data["department"] == "dispute_resolution"
    assert data["relevant_transaction_id"] == "TXN-9101"
    assert isinstance(data["human_review_required"], bool)


@pytest.mark.asyncio
async def test_ticket_id_is_echoed_verbatim(client):
    body = {"ticket_id": "TKT-中文-αβγ-9999", "complaint": "real complaint"}
    r = await client.post("/analyze-ticket", json=body)
    assert r.status_code == 200
    assert r.json()["ticket_id"] == "TKT-中文-αβγ-9999"


@pytest.mark.asyncio
async def test_empty_transaction_history_is_allowed(client):
    body = {"ticket_id": "TKT-2", "complaint": "Something vague happened."}
    r = await client.post("/analyze-ticket", json=body)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_reason_codes_is_list(client):
    body = {"ticket_id": "TKT-3", "complaint": "money deducted but no recharge"}
    r = await client.post("/analyze-ticket", json=body)
    assert r.status_code == 200
    assert isinstance(r.json()["reason_codes"], list)
    assert len(r.json()["reason_codes"]) > 0


@pytest.mark.asyncio
async def test_customer_reply_non_empty(client):
    body = {"ticket_id": "TKT-4", "complaint": "I sent 5000 to the wrong person."}
    r = await client.post("/analyze-ticket", json=body)
    assert r.status_code == 200
    assert r.json()["customer_reply"].strip() != ""


@pytest.mark.asyncio
async def test_confidence_is_between_0_and_1(client):
    body = {"ticket_id": "TKT-5", "complaint": "I sent 5000 to wrong number at 2pm"}
    r = await client.post("/analyze-ticket", json=body)
    assert r.status_code == 200
    conf = r.json()["confidence"]
    assert 0.0 <= conf <= 1.0


# ---------------------------------------------------------------------------
# 400 - malformed JSON
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_json_returns_400(client):
    r = await client.post(
        "/analyze-ticket",
        content=b"{not valid json",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "malformed_json"


@pytest.mark.asyncio
async def test_empty_body_returns_400_or_422(client):
    r = await client.post("/analyze-ticket", content=b"")
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# 422 - validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_required_fields_returns_422(client):
    r = await client.post("/analyze-ticket", json={})
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_whitespace_only_complaint_returns_422(client):
    r = await client.post(
        "/analyze-ticket",
        json={"ticket_id": "TKT-1", "complaint": "   \t  "},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_extra_fields_rejected(client):
    body = {
        "ticket_id": "TKT-1",
        "complaint": "real",
        "unknown_field": "should be rejected",
    }
    r = await client.post("/analyze-ticket", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_invalid_enum_value_returns_422(client):
    body = {
        "ticket_id": "TKT-1",
        "complaint": "real",
        "language": "Klingon",
    }
    r = await client.post("/analyze-ticket", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_invalid_txn_status_returns_422(client):
    body = {
        "ticket_id": "TKT-1",
        "complaint": "x",
        "transaction_history": [
            {
                "transaction_id": "TXN-1",
                "timestamp": "2026-04-14T14:08:22Z",
                "type": "transfer",
                "amount": 100,
                "counterparty": "+8801719876543",
                "status": "successful",  # not in TxnStatus enum
            }
        ],
    }
    r = await client.post("/analyze-ticket", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bad_iso_timestamp_returns_422(client):
    body = {
        "ticket_id": "TKT-1",
        "complaint": "x",
        "transaction_history": [
            {
                "transaction_id": "TXN-1",
                "timestamp": "yesterday afternoon",
                "type": "transfer",
                "amount": 100,
                "counterparty": "+8801719876543",
                "status": "completed",
            }
        ],
    }
    r = await client.post("/analyze-ticket", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_negative_amount_returns_422(client):
    body = {
        "ticket_id": "TKT-1",
        "complaint": "x",
        "transaction_history": [
            {
                "transaction_id": "TXN-1",
                "timestamp": "2026-04-14T14:08:22Z",
                "type": "transfer",
                "amount": -100,
                "counterparty": "+8801719876543",
                "status": "completed",
            }
        ],
    }
    r = await client.post("/analyze-ticket", json=body)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Error body safety (Section 9.2 - no leak of complaint text)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_error_body_does_not_leak_complaint_text(client):
    secret = "VERY_SECRET_PHRASE_DO_NOT_LEAK"
    r = await client.post(
        "/analyze-ticket",
        json={"ticket_id": "TKT-1", "complaint": secret, "language": "English"},
    )
    assert r.status_code == 422
    raw = r.text
    assert secret not in raw, f"error body leaked complaint text: {raw}"


# ---------------------------------------------------------------------------
# 500 - unhandled exception path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unhandled_exception_returns_500_without_stacktrace(monkeypatch, client):
    from app import main as main_module

    def _boom(req):
        raise RuntimeError("simulated internal fault")

    monkeypatch.setattr(main_module, "_run_reasoning_pipeline", _boom)

    r = await client.post(
        "/analyze-ticket",
        json={"ticket_id": "TKT-1", "complaint": "hello"},
    )
    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "internal_error"
    raw = r.text
    assert "simulated internal fault" not in raw
    assert "Traceback" not in raw


# ---------------------------------------------------------------------------
# Method-not-allowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_on_analyze_ticket_returns_405(client):
    r = await client.get("/analyze-ticket")
    assert r.status_code == 405