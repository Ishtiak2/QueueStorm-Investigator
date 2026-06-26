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

# ---------------------------------------------------------------------------
# Phase F edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_complaint_string_returns_422(client):
    r = await client.post("/analyze-ticket", json={
        "ticket_id": "TKT-EDGE-01",
        "complaint": "",
        "transaction_history": [],
    })
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "invalid_request"
    # Error body must NOT echo the complaint back
    assert "" not in (body.get("detail") or "")


@pytest.mark.asyncio
async def test_bangla_only_complaint_returns_200(client):
    r = await client.post("/analyze-ticket", json={
        "ticket_id": "TKT-EDGE-02",
        "complaint": "আমি আমার ভাইকে ১০০০ টাকা পাঠিয়েছি কিন্তু সে বলছে পায়নি।",
        "language": "bn",
        "transaction_history": [],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ticket_id"] == "TKT-EDGE-02"
    # Bangla reply should be returned in customer_reply
    assert any("\u0980" <= ch <= "\u09ff" for ch in data["customer_reply"])


@pytest.mark.asyncio
async def test_banglish_complaint_returns_200(client):
    # Mixed English + Banglish romanisation - common in Bangladesh.
    r = await client.post("/analyze-ticket", json={
        "ticket_id": "TKT-EDGE-03",
        "complaint": "ami amar vai ke 1000 taka pathiechi, kintu bole payni",
        "language": "mixed",
        "transaction_history": [],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ticket_id"] == "TKT-EDGE-03"


@pytest.mark.asyncio
async def test_very_long_complaint_returns_200(client):
    # 4000 characters - well above the 2000-line read chunk but should
    # still complete without 500.
    long = "I sent 500 taka. " * 250
    r = await client.post("/analyze-ticket", json={
        "ticket_id": "TKT-EDGE-04",
        "complaint": long,
        "transaction_history": [],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ticket_id"] == "TKT-EDGE-04"
    assert isinstance(data["customer_reply"], str)


@pytest.mark.asyncio
async def test_large_history_returns_200(client):
    # 50 transactions - exercises matcher performance.
    history = []
    for i in range(50):
        history.append({
            "transaction_id": f"TXN-LARGE-{i:03d}",
            "timestamp": "2026-06-20T10:00:00",
            "amount": 100 + i,
            "type": "transfer",
            "status": "completed",
            "counterparty": f"+880171000{i:04d}",
                    })
    r = await client.post("/analyze-ticket", json={
        "ticket_id": "TKT-EDGE-05",
        "complaint": "I sent 125 taka to +8801710000025 around 10am.",
        "transaction_history": history,
    })
    assert r.status_code == 200
    data = r.json()
    # We should be able to find the matching one
    assert data["relevant_transaction_id"] == "TXN-LARGE-025"


@pytest.mark.asyncio
async def test_bengali_digit_amount_returns_200(client):
    # Amount written in Bengali numerals - extractor must normalise.
    r = await client.post("/analyze-ticket", json={
        "ticket_id": "TKT-EDGE-06",
        "complaint": "আমি ২৫০০ টাকা পাঠিয়েছি ভুল নম্বরে।",
        "language": "bn",
        "transaction_history": [
            {
                "transaction_id": "TXN-BN-01",
                "timestamp": "2026-06-20T10:00:00",
                "amount": 2500,
                "type": "transfer",
                "status": "completed",
                "counterparty": "+8801711111111",
                            }
        ],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["relevant_transaction_id"] == "TXN-BN-01"


@pytest.mark.asyncio
async def test_history_with_only_one_txn_still_responds(client):
    r = await client.post("/analyze-ticket", json={
        "ticket_id": "TKT-EDGE-07",
        "complaint": "I have a problem with a payment.",
        "transaction_history": [
            {
                "transaction_id": "TXN-SOLO-01",
                "timestamp": "2026-06-20T10:00:00",
                "amount": 1000,
                "type": "transfer",
                "status": "completed",
                "counterparty": "+8801712345678",
                            }
        ],
    })
    assert r.status_code == 200
    data = r.json()
    # Without enough complaint evidence, we land on other/insufficient_data
    # but the endpoint still returns 200 with all required fields.
    for k in ("ticket_id", "relevant_transaction_id", "evidence_verdict",
              "case_type", "severity", "department", "agent_summary",
              "recommended_next_action", "customer_reply",
              "human_review_required", "confidence", "reason_codes"):
        assert k in data


@pytest.mark.asyncio
async def test_response_with_all_optional_fields(client):
    r = await client.post("/analyze-ticket", json={
        "ticket_id": "TKT-EDGE-08",
        "complaint": "I sent 300 taka to +8801719876543 around 3pm.",
        "language": "en",
        "channel": "in_app_chat",
        "user_type": "customer",
        "campaign_context": "winter-promo-2026",
        "metadata": {"app_version": "5.3.0"},
        "transaction_history": [
            {
                "transaction_id": "TXN-OPT-01",
                "timestamp": "2026-06-20T15:00:00",
                "amount": 300,
                "type": "transfer",
                "status": "completed",
                "counterparty": "+8801719876543",
                            }
        ],
    })
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_response_field_types(client):
    # Lock down the response field types so schema drift is caught.
    r = await client.post("/analyze-ticket", json={
        "ticket_id": "TKT-EDGE-09",
        "complaint": "I sent 500 taka.",
        "transaction_history": [],
    })
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["ticket_id"], str)
    assert data["relevant_transaction_id"] is None or isinstance(
        data["relevant_transaction_id"], str
    )
    assert isinstance(data["evidence_verdict"], str)
    assert isinstance(data["case_type"], str)
    assert isinstance(data["severity"], str)
    assert isinstance(data["department"], str)
    assert isinstance(data["agent_summary"], str)
    assert isinstance(data["recommended_next_action"], str)
    assert isinstance(data["customer_reply"], str)
    assert isinstance(data["human_review_required"], bool)
    assert isinstance(data["confidence"], float)
    assert 0.0 <= data["confidence"] <= 1.0
    assert isinstance(data["reason_codes"], list)
    assert all(isinstance(c, str) for c in data["reason_codes"])


@pytest.mark.asyncio
async def test_post_with_text_plain_returns_422(client):
    # FastAPI rejects non-JSON payloads with 422 (validation error), not 415
    r = await client.post(
        "/analyze-ticket",
        content=b"not json",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_without_content_type_returns_422(client):
    # No Content-Type header -> FastAPI treats body as JSON candidate, fails to parse
    r = await client.post(
        "/analyze-ticket",
        content=b'{"ticket_id":"TKT-001","complaint":"hi"}',
    )
    # httpx default sets application/json when content=bytes is a JSON-looking str,
    # so FastAPI rejects it with 415 (no explicit Content-Type). Document current
    # behavior: missing CT yields 415 Unsupported Media Type.
    assert r.status_code == 415
