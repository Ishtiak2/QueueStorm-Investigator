# QueueStorm Investigator

> **bKash presents SUST CSE Carnival 2026 — Codex Community Hackathon (Preliminary)**
> **Team:** Code Warriors · Shahjalal University of Science & Technology

A stateless FastAPI service that investigates a bKash customer complaint against
their transaction history and returns a structured, safety-checked investigation
response. Built for the SUST Codex Community Hackathon Preliminary round.

| | |
|---|---|
| **Live API** | https://queuestorm-investigator-7d8z.onrender.com |
| **GitHub** | https://github.com/Ishtiak2/QueueStorm-Investigator |
| **Swagger UI** | https://queuestorm-investigator-7d8z.onrender.com/docs |
| **OpenAPI** | https://queuestorm-investigator-7d8z.onrender.com/openapi.json |

---

## 1. What it is

A single-file reasoning engine wrapped in a FastAPI HTTP layer. Given a complaint
in English, Bangla, or Banglish, plus the customer's transaction history, the API
returns the **12 fields** required by Section 6 of the problem statement:

1. `ticket_id`
2. `relevant_transaction_id`
3. `evidence_verdict` (`consistent` | `inconsistent` | `insufficient_data`)
4. `case_type` (`wrong_transfer`, `payment_failed`, `refund_request`,
   `phishing_or_social_engineering`, `agent_cash_in_issue`, `duplicate_payment`,
   `merchant_settlement_delay`, `other`)
5. `severity` (`low` | `medium` | `high` | `critical`)
6. `department`
7. `agent_summary`
8. `recommended_next_action`
9. `customer_reply`
10. `human_review_required`
11. `confidence` (0.0 – 1.0)
12. `reason_codes`

### 1.1 Enum reference (exact match required)

All enum values must match **exactly**. Per problem statement §7, variants (case
differences, plural forms, alternate spellings) are scored as schema violations.

| Field | Allowed values |
|---|---|
| `evidence_verdict` | `consistent` · `inconsistent` · `insufficient_data` |
| `case_type` | `wrong_transfer` · `payment_failed` · `refund_request` · `duplicate_payment` · `merchant_settlement_delay` · `agent_cash_in_issue` · `phishing_or_social_engineering` · `other` |
| `severity` | `low` · `medium` · `high` · `critical` |
| `department` | `customer_support` · `dispute_resolution` · `payments_ops` · `merchant_operations` · `agent_operations` · `fraud_risk` |
| `transaction.type` | `transfer` · `payment` · `cash_in` · `cash_out` · `settlement` · `refund` |
| `transaction.status` | `completed` · `failed` · `pending` · `reversed` |
| `language` (request) | `en` · `bn` · `mixed` |
| `channel` (request) | `in_app_chat` · `call_center` · `email` · `merchant_portal` · `field_agent` |
| `user_type` (request) | `customer` · `merchant` · `agent` · `unknown` |

> ⚠️ **No variants, no plurals.** `Wrong_transfer`, `WrongTransfer`, or
> `wrong-transfers` will all be rejected as schema violations by the judge
> harness.

---

## 2. Setup

Requires Python 3.11+.

```bash
git clone https://github.com/Ishtiak2/QueueStorm-Investigator.git
cd QueueStorm-Investigator
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

No external API keys are required — the pipeline is fully rule-based. (An
`.env.example` is provided for the optional Phase E LLM hookup; see [§7 Models](#7-models).)

---

## 3. Run

### Local development

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://127.0.0.1:8000/docs for the interactive Swagger UI.

### Production (single process)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

`/health` should respond `{"status":"ok"}` within 60 s of startup.

### Run the tests

```bash
.venv/bin/pytest -q                           # 185 unit + endpoint tests
.venv/bin/python scripts/check_sample_cases.py # 10/10 public rubric match
.venv/bin/python scripts/check_safety.py      # 0 safety-violations invariant
```

---

## 4. Endpoints

All endpoints accept and return `application/json`.

### HTTP response codes (per problem statement §4.1)

| Code | Meaning |
|---|---|
| `200` | Successful analysis. Response body conforms to the output schema. |
| `400` | Malformed input (invalid JSON, missing required fields). Body carries a non-sensitive error message. |
| `422` | Schema is valid but input is semantically invalid (e.g. empty `complaint`). |
| `500` | Internal error. Body carries a non-sensitive error message. No stack traces, tokens, or secrets. |

The service **must not crash** on malformed input — a 400 or 500 is acceptable;
a process that exits or hangs is not.

### `GET /health` — liveness probe

```bash
curl https://queuestorm-investigator-7d8z.onrender.com/health
# {"status":"ok"}
```

### `POST /analyze-ticket` — structured investigation

Minimal body (only `ticket_id` and `complaint` are required):

```bash
curl -X POST https://queuestorm-investigator-7d8z.onrender.com/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "TKT-001",
    "complaint": "I sent 5000 taka to a wrong number around 2pm today. Please help me get my money back."
  }'
```

Full body with transaction history (matches the rubric fixture; includes every
optional field from problem statement §5.1):

```bash
curl -X POST https://queuestorm-investigator-7d8z.onrender.com/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "TKT-001",
    "complaint": "I sent 5000 taka to a wrong number around 2pm today. The number was supposed to be 01712345678 but I think I typed it wrong.",
    "language": "en",
    "channel": "in_app_chat",
    "user_type": "customer",
    "campaign_context": "boishakh_bonanza_day_1",
    "transaction_history": [
      {"transaction_id": "TXN-9101", "timestamp": "2026-04-14T14:08:22Z",
       "type": "transfer", "amount": 5000,
       "counterparty": "+8801719876543", "status": "completed"}
    ],
    "metadata": {"agent_id": "AGENT-042", "session_id": "S-9911"}
  }'
```

A successful response (`200 OK`) carries all 12 Section 6 fields plus a
`reason_codes` array explaining the classification.

### `GET /docs` — Swagger UI

```bash
open https://queuestorm-investigator-7d8z.onrender.com/docs
```

### `GET /openapi.json` — machine-readable schema

```bash
curl https://queuestorm-investigator-7d8z.onrender.com/openapi.json | jq .
```

---

## 5. Deployed on Render

**Live URL:** https://queuestorm-investigator-7d8z.onrender.com

---

## 6. Models

**This service runs no machine-learning models and makes no external API calls in
the hot path.** Every classification, matching, and text-generation decision is
made by a deterministic rule-based pipeline. Concretely:

| Component | Implementation | Where it runs |
|---|---|---|
| Transaction matching (`matcher.py`) | Pure-Python: numeric + phone + counterparty + timestamp heuristics | In-process |
| Duplicate-payment detector | O(n²) exact-match on amount + counterparty + type + 60 s window | In-process |
| Evidence verdict (`verdict.py`) | Branch on `matcher` output + complaint signals | In-process |
| Case-type classifier (`classifier.py`) | EN + BN + Banglish keyword maps; tie-breaks in favour of `wrong_transfer` | In-process |
| Severity + department routing (`routing.py`) | Enum tables; case-type is the primary key | In-process |
| Human-review routing | Rule: phishing OR inconsistent OR (consistent AND case_type ∈ escalation set) | In-process |
| Text generation (`templates.py`) | String templates per case_type / language, filled from schema fields | In-process |
| Safety post-processor (`safety.py`) | Regex redaction + prompt-injection detection | In-process |
| Optional LLM polish (`app/llm.py`, **disabled by default**) | OpenAI / Anthropic behind `USE_LLM=1` env flag with 4 s timeout + fallback to template | External, only if enabled |

The optional LLM hook is **off by default**, so:

- No API keys are required to run the service.
- No data leaves the process unless the operator explicitly sets `USE_LLM=1`.
- The pipeline is reproducible and offline-friendly.

If LLM polish is enabled, the LLM output is **never trusted raw** — it always
passes through `safety.sanitize_text()` before being returned to the customer.

---

## 7. Safety logic

`app/safety.py` is the **last line of defence** — every free-text field
(`agent_summary`, `recommended_next_action`, `customer_reply`) is passed through
`sanitize_text()` before the response leaves the service. Four rules, each
backed by a regex test in `tests/test_safety.py`:

### Rule 1 — Never ask for credentials

Any of `pin`, `otp`, `password`, `card number`, `cvv` is replaced with
`[REDACTED]`. A short negation guard (`don't / never / do not`) is recognised
so that "We will **never** ask for your PIN" is left untouched.

```text
Input:  "Please share your OTP with us."
Output: "Please share your [REDACTED] with us."

Input:  "bKash will never ask for your PIN."
Output: "bKash will never ask for your PIN."   # unchanged
```

### Rule 2 — Never promise a refund / reversal

Phrases like "we will refund", "we'll reverse", "your money will be returned"
are replaced with the safe sentence
`any eligible amount will be processed through official channels after review`.

```text
Input:  "We will refund 500 taka within 24 hours."
Output: "any eligible amount will be processed through official channels after review 500 taka within 24 hours."
```

### Rule 3 — Allow-list contact channels

Any phone number or URL in the output is normalised and only retained if it
matches the official allow-list:

- Phone: `16247` (digits-only normalisation; `+880 16247` collapses to `16247`).
- URL: `https://www.bkash.com` (case-insensitive).

Any other phone or URL is stripped. Customers cannot be told to call an
attacker-controlled number or visit a lookalike domain.

### Rule 4 — Prompt-injection detection

The complaint text is scanned for phrases like
`ignore previous instructions`, `disregard everything`, `act as a system`,
`you are now`, `reveal your prompt`, etc. If detected:

- `human_review_required` is forced to `true`.
- `reason_codes` includes `prompt_injection_detected`.
- The reasoning engine is **not** allowed to follow the injected instruction
  (it only sees the complaint as a string, never as instructions).

The same `sanitize_text()` function is idempotent — calling it twice yields
the same string — which is asserted in `tests/test_safety.py`.

---

## 8. Known limitations

| Limitation | Impact | Mitigation |
|---|---|---|
| **Bangla coverage is keyword-based**, not embedding-based. Long Bangla sentences that paraphrase the issue without using a mapped keyword may fall through to `case_type=other`. | Some Bangla cases may be mis-classified. | Conservative verdict — when language is `bn` or `mixed`, confidence is lowered and `human_review_required` is biased towards `true`. |
| **No OCR / image understanding.** Complaints that reference a screenshot in free text cannot be linked to a transaction by content. | Customers must paste the transaction id or describe it. | The matcher accepts transaction-id references in the complaint text. |
| **Phone-number matching is heuristic.** `017...`, `+88017...`, `88017...` collapse to the same digits; full international variants are not enumerated. | Numbers in unusual formats may not link. | Matcher falls back to amount + timestamp + counterparty when phone normalisation fails. |
| **No persistent memory.** Each request is independent; an analyst cannot pick up where a previous conversation left off. | Multi-turn tickets require the caller to repeat context. | The response includes `ticket_id` and `reason_codes` so a downstream CRM can stitch turns. |
| **Single-process uvicorn.** The render.yaml uses one worker. | Burst capacity is bounded. | `Dockerfile` is multi-process-ready — bump `--workers` on a larger Render plan. |
| **Free-tier sleep.** Render free services sleep after 15 min of idleness. | First request after sleep is ~30 s. | Documented; `autoDeploy` keeps the latest commit live. |
| **Optional LLM is unbounded.** If `USE_LLM=1` is set, an upstream provider outage will fall back to templates — but the timeout is 4 s. | Latency spike possible. | Default off; operators must opt in via env var. |

---

## 9. Project layout

```
.
├── app/
│   ├── main.py             # FastAPI entry point + error handlers
│   ├── schemas.py          # Pydantic request/response models + enums
│   ├── matcher.py          # Transaction-matching + duplicate detection
│   ├── classifier.py       # Case-type classification + verdict
│   ├── routing.py          # Severity, department, human-review routing
│   ├── templates.py        # Template-based text generation (EN + BN)
│   ├── safety.py           # Phase D guardrails (4 rules, see §8)
│   └── llm.py              # Optional LLM polish (disabled by default)
├── tests/
│   ├── test_endpoints.py   # HTTP contract + edge cases (30 tests)
│   ├── test_matcher.py
│   ├── test_classifier.py
│   ├── test_routing.py
│   ├── test_templates.py
│   └── test_safety.py      # Phase D guardrail tests (37 tests)
├── scripts/
│   ├── check_sample_cases.py   # 10/10 rubric verifier
│   └── check_safety.py         # safety invariant verifier
├── requirements.txt
├── render.yaml             # Render Blueprint (primary deploy)
├── Procfile                # Render/Heroku start command
├── Dockerfile              # Docker fallback
├── .dockerignore
├── pytest.ini
└── README.md
```

---

## 10. Team

**Team Code Warriors** — Shahjalal University of Science & Technology

| Name | Role | Email |
|---|---|---|
| Ishtiak Rahman | Leader | ishtiakrahman13579@gmail.com |
| OMOR SULTAN | Member | omorsultansust@gmail.com |
| Md. Shahmat Hossain Mahin | Member | shahmatmahin@gmail.com |

---

## 11. Submission paths

Per the problem statement, live URL is the preferred submission path.

1. **Live URL:** https://queuestorm-investigator-7d8z.onrender.com
2. **Repo:** https://github.com/Ishtiak2/QueueStorm-Investigator
3. **Fallback:** `docker run -p 8000:8000 queuestorm-investigator` from this repo.

The endpoint contract, safety guarantees, and 12-field response shape are
documented at `/docs` and `/openapi.json` on the live deployment.