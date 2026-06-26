"""Smoke tests for Phase A endpoints.

Boots the FastAPI app via httpx ASGI transport (no real network).
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_returns_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_analyze_ticket_returns_stub(client):
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
    assert data["ticket_id"] == "TKT-001"
    assert data["case_type"] == "other"
    assert data["evidence_verdict"] == "insufficient_data"
    assert data["severity"] == "low"
    assert data["department"] == "customer_support"
    assert data["human_review_required"] is True


@pytest.mark.asyncio
async def test_malformed_json_returns_400(client):
    r = await client.post(
        "/analyze-ticket", content="{not json", headers={"content-type": "application/json"}
    )
    assert r.status_code == 400
    assert r.json()["error"] == "malformed_json"


@pytest.mark.asyncio
async def test_missing_required_field_returns_422(client):
    r = await client.post("/analyze-ticket", json={"ticket_id": "TKT-1"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_invalid_enum_returns_422(client):
    r = await client.post(
        "/analyze-ticket",
        json={"ticket_id": "TKT-1", "complaint": "x", "case_type": "Wrong_Transfer"},
    )
    assert r.status_code == 422
