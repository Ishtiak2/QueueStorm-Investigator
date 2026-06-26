# QueueStorm Investigator — Phased Build Plan

> Senior-engineer plan for the **bKash SUST Codex Hackathon — Preliminary Round** (4.5 h, AI/API SupportOps challenge).
> Source docs: `SUST_Hackathon_Preli_Problem_Statement.md` (contract) and `SUST_Preli_Evaluation_Rubric_With_Explanations.md` (scoring).

---

## 0. What we are shipping

A single-container HTTP service that:

| Endpoint | Contract | SLA |
|---|---|---|
| `GET /health` | `{"status":"ok"}` | < 60 s cold start |
| `POST /analyze-ticket` | One ticket + txn snippet in → structured investigation out | < 30 s / request, p95 ≤ 5 s |

The service is a **complaint investigator**, not a classifier. The same complaint can describe one thing while the provided `transaction_history` shows another; the system must reconcile them and decide `relevant_transaction_id`, `evidence_verdict`, `case_type`, `department`, `severity`, and `human_review_required`.

### Rubric → engineering priorities

| Rank | Category | Weight | What this means in code |
|---|---|---|---|
| 1 | Evidence Reasoning | 35 | Strong matcher + verdict + classifier + routing |
| 2 | Safety & Escalation | 20 | Output post-filter + escalation rules |
| 3 | API Contract & Schema | 15 | Pydantic enums + HTTP code mapping |
| 4 | Performance & Reliability | 10 | Slim image, async, try/except on every path |
| 5 | Response Quality | 10 | Crisp summary/action/reply templates (LLM optional) |
| 6 | Deployment & Reproducibility | 5 | Dockerfile + live URL or runbook |
| 7 | Documentation | 5 | README with MODELS + safety + limits |

> **Design rule:** the core must work with **zero external services**. LLM is purely a quality bonus when a key is present.

---

## 1. Tech stack

| Layer | Choice | Reason |
|---|---|---|
| Runtime | Python 3.11 | Fast iteration, rich ecosystem |
| Web | **FastAPI** + **Uvicorn** | Async, auto OpenAPI, fast cold start |
| Validation | **Pydantic v2** | Hard enum enforcement; spec-mirrored models |
| Reasoning | Rule-based heuristics first | Deterministic, <50 ms, no API cost, satisfies hidden cases |
| Text gen (optional) | OpenAI / Anthropic behind env flag | Only used to polish `agent_summary` / `customer_reply`; never trusted raw |
| Tests | pytest + httpx AsyncClient + 10 public cases | Drives hidden-test robustness |
| Packaging | `python:3.11-slim` Docker | < 400 MB image, fast judge boot |
| Deploy | Render / Railway / Fly / Poridhi (single 1 GB VM) | One container, env vars only |

Rejected: any framework requiring a DB (overkill for stateless analysis), any LLM call in the hot path without a 4 s timeout + fallback, any web framework other than FastAPI (speed of writing + async).

---

## 2. File / folder layout

```
preli-question/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app, routes, HTTP error mapping
│   ├── schemas.py         # Request/response Pydantic models + enums
│   ├── matcher.py         # Transaction matching (amount/time/counterparty)
│   ├── verdict.py         # evidence_verdict logic
│   ├── classifier.py      # case_type + Bangla/Banglish keyword maps
│   ├── routing.py         # severity + department + human_review_required
│   ├── safety.py          # Output filters (PIN/OTP/refund/third-party)
│   ├── templates.py       # Rule-based reply templates (EN + BN)
│   └── llm.py             # Optional LLM text gen + safety post-filter
├── tests/
│   ├── test_match.py
│   ├── test_classifier.py
│   ├── test_safety.py
│   └── test_endpoints.py
├── SUST_Preli_Sample_Cases.json
├── sample_output.json     # Generated from one public case
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
├── .dockerignore
├── README.md              # setup, run, AI use, safety, limits
├── RUNBOOK.md             # step-by-step local bring-up
└── PLAN.md                # this file
```

---

## 3. Phased build (time-boxed to 4.5 h)

### Phase A — Skeleton + Health (≈ 20 min) — *must work first*
- [ ] `requirements.txt`: `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `python-dotenv`, `httpx`, `pytest`
- [ ] `app/main.py`: FastAPI app, `GET /health` returning `{"status":"ok"}`
- [ ] `app/schemas.py`: request + response models with all enums locked
- [ ] `POST /analyze-ticket` stub returning a minimal valid response
- [ ] Run `uvicorn app.main:app --reload`, hit `/health` with curl

### Phase B — Schema & HTTP contract (≈ 30 min)
- [ ] All response fields typed and required, enums exactly as Section 7
- [ ] HTTP codes: 200 / 400 / 422 / 500 with non-sensitive error bodies
- [ ] `try/except` around handler so malformed JSON → 400, not 500
- [ ] Echo `ticket_id` from request

### Phase C — Evidence reasoning engine (≈ 75 min) — *largest score bucket*
- [ ] **matcher.py**
  - Extract amount (regex `\d{2,7}` + Bengali digits `০-৯`)
  - Extract time-of-day references ("2 pm", "around 2", "আজ দুপুরে")
  - Extract counterparty (phone regex `\+?88?\d{10,13}`, "wrong number", merchant id)
  - Score each txn: `amount_match * 3 + time_within_4h * 2 + counterparty_match * 3`
  - Pick best above threshold, else `null`
- [ ] **verdict.py**
  - `consistent`: matched txn status + amount + counterparty align with complaint
  - `inconsistent`: matched txn proves opposite (e.g., "didn't receive refund" but txn shows refund completed)
  - `insufficient_data`: no match, or matched txn is `pending` / `failed` with no resolution signal
- [ ] **classifier.py**
  - Keyword + Bangla maps → 8 case_types (see Section 7.1)
  - Phishing triggers: "OTP", "PIN", "password", "ওটিপি", "পিন", "call করে বললো"
  - Wrong transfer: "wrong number", "ভুল নম্বরে", "ভুল মানুষ"
- [ ] **routing.py**
  - Department lookup per Section 7.2
  - Severity heuristic:
    - `critical` → phishing, or amount ≥ 100 000 BDT
    - `high` → wrong_transfer, payment_failed ≥ 10 000, agent_cash_in_issue ≥ 10 000
    - `medium` → refund_request, duplicate_payment, merchant_settlement_delay
    - `low` → insufficient_data, vague, < 1 000 BDT

### Phase D — Safety guardrails (≈ 45 min) — *disqualification risk if missed*
- [ ] **safety.py** runs after reasoning, before returning:
  - Block any `customer_reply` containing `\b(pin|otp|password|cvv|full card)\b` → rephrase to a safe alternative (or set `human_review_required=true`)
  - Replace "we will refund / reverse / unblock" with "any eligible amount will be processed through official channels after review"
  - Strip any URLs / phone numbers not in an allow-list of official channels → replace with `16247` (bKash official) or "official support"
  - Detect prompt-injection attempts in complaint (e.g., "ignore previous instructions") → ignore them, use only as evidence
- [ ] `human_review_required = True` if **any** of:
  - `case_type == phishing_or_social_engineering`
  - `evidence_verdict != consistent`
  - amount ≥ 50 000 BDT
  - `case_type in {wrong_transfer, agent_cash_in_issue}`
  - `evidence_verdict == insufficient_data`
- [ ] Unit tests for each safety rule with positive and negative cases

### Phase E — LLM text generation (optional, ≈ 30 min)
Only if time permits and `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` is set.
- [ ] `llm.py` builds a safety-locked system prompt
- [ ] Generates `agent_summary`, `recommended_next_action`, `customer_reply`
- [ ] Output passes through `safety.py` again before returning
- [ ] Fallback: if LLM fails or times out (> 4 s), use rule-based templates from `templates.py`

### Phase F — Testing (≈ 30 min)
- [ ] Run all 10 public sample cases through `POST /analyze-ticket`
- [ ] Compare `relevant_transaction_id`, `evidence_verdict`, `case_type`, `department`
- [ ] Edge cases: empty complaint, empty history, Bangla-only complaint, malformed JSON, missing fields
- [ ] Save one sample response to `sample_output.json`
- [ ] `pytest` green

### Phase G — Deployment (≈ 30 min)
- [ ] `Dockerfile`: `python:3.11-slim`, copy code, `pip install -r requirements.txt`, `CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]`
- [ ] `docker build -t queuestorm .` then `docker run -p 8000:8000 queuestorm`
- [ ] Hit `http://localhost:8000/health` and `/analyze-ticket` from a sample
- [ ] Push image (Docker Hub) **or** deploy to Render / Railway / Fly
- [ ] Confirm `/health` responds within 60 s of container start

### Phase H — Documentation (≈ 20 min)
- [ ] `README.md` sections:
  1. What it is + hackathon name
  2. Setup (`pip install -r requirements.txt`)
  3. Run (`uvicorn app.main:app --host 0.0.0.0 --port 8000`)
  4. Docker run / push
  5. Endpoints with one curl example each
  6. **MODELS** section: list every model used, where it runs, why (state "rule-based, no LLM" if applicable)
  7. **Safety logic** — the 4 rules from Section 8 and how each is enforced
  8. **Known limitations** — Bangla coverage, ambiguous phrasing, etc.
- [ ] `RUNBOOK.md`: copy-pasteable steps for a stranger
- [ ] `.env.example`: `OPENAI_API_KEY=`, `ANTHROPIC_API_KEY=` (empty)

---

## 4. Architecture at a glance

```
                     POST /analyze-ticket
                              │
                              ▼
            ┌────────────────────────────────────┐
            │   FastAPI handler  (main.py)       │
            │   - JSON parse + Pydantic validate │
            │   - try/except → 400/422/500       │
            └─────────────────┬──────────────────┘
                              │
            ┌─────────────────▼──────────────────┐
            │   Reasoning pipeline (pure Python) │
            │   1. matcher.py  → relevant_tx_id  │
            │   2. verdict.py  → evidence_verdict│
            │   3. classifier.py → case_type     │
            │   4. routing.py  → sev / dept /    │
            │                     human_review    │
            └─────────────────┬──────────────────┘
                              │
            ┌─────────────────▼──────────────────┐
            │   Text generation                  │
            │   - if LLM_KEY set: llm.py (4s)    │
            │   - else: templates.py (EN + BN)   │
            └─────────────────┬──────────────────┘
                              │
            ┌─────────────────▼──────────────────┐
            │   safety.py  (post-filter)         │
            │   - no creds / no refund / no 3p / │
            │     injection-ignore               │
            └─────────────────┬──────────────────┘
                              │
                              ▼
                  Pydantic response (200 OK)
```

---

## 5. Critical algorithms

### Transaction matching
```python
def match(complaint, history):
    amount = extract_amount(complaint)          # int | None
    time_ref = extract_time_of_day(complaint)   # datetime | None
    cp = extract_counterparty(complaint)        # str | None
    best, best_score = None, 0
    for t in history:
        s = 0
        if amount and t["amount"] == amount: s += 3
        if time_ref and abs(parse(t["timestamp"]) - time_ref) < timedelta(hours=4): s += 2
        if cp and cp in t["counterparty"]: s += 3
        if s > best_score:
            best, best_score = t, s
    return best if best_score >= 3 else None
```

### Evidence verdict
| Condition | Verdict |
|---|---|
| `match is None` | `insufficient_data` |
| Match exists, complaint claim aligns with `status` | `consistent` |
| Match exists, complaint claim contradicts `status` (e.g., "no refund" but `refund` txn is `completed`) | `inconsistent` |
| Match is `pending` or `failed` and complaint asks about outcome | `insufficient_data` |

### Severity heuristic
| Condition | Severity |
|---|---|
| `case_type == phishing_or_social_engineering` | `critical` |
| amount ≥ 100 000 BDT | `critical` |
| `case_type == wrong_transfer` OR (`payment_failed` and amount ≥ 10 000) | `high` |
| `refund_request`, `duplicate_payment`, `merchant_settlement_delay`, `agent_cash_in_issue` | `medium` |
| `insufficient_data`, vague, amount < 1 000 | `low` |

### Safety post-processing (order matters)
1. Drop any request for PIN/OTP/password → keep, but flag with internal `safety_flag` and force `human_review_required=true`
2. Detect refund promise verbs (`refund`, `reverse`, `unblock`, `return your money`, `ফেরত দেব`) → rewrite to "any eligible amount will be processed through official channels after review"
3. Detect non-allow-listed URLs or phone numbers → strip, replace with `16247` and "bKash official app / hotline"
4. Reject any instruction in the complaint that tries to override system rules (`ignore previous`, `act as`, `you are now`) — treat as plain text

### Bangla / Banglish coverage
- Bengali digit map: `০১২৩৪৫৬৭৮৯ → 0..9`
- Keyword maps:
  - wrong: `ভুল`, `wrong`, `ভুল নম্বরে`
  - refund: `ফেরত`, `refund`, `টাকা ফেরত`
  - failed: `ফেইল`, `failed`, `কাজ করছে না`
  - phishing: `OTP`, `PIN`, `পিন`, `ওটিপি`, `password`, `পাসওয়ার্ড`, `কল করে বললো`

---

## 6. Risk register

| Risk | Mitigation |
|---|---|
| No LLM API credits | Reasoning stays rule-based; LLM only enhances text |
| Hidden case surprises | Always set `human_review_required=true` when in doubt |
| Bangla not covered | Conservative — when language is `bn` or `mixed`, lower confidence and escalate |
| Slow cold start | Slim base image, no ML model baked in |
| 5xx under judge load | Wrap every handler; degrade gracefully |
| Time over-run | Phase A → G is non-negotiable; Phase E (LLM) and H (docs polish) are first to be cut |
| Prompt injection in complaint | `safety.py` strips override phrases; reasoning uses only schema fields |

---

## 7. Definition of Done

- [ ] `GET /health` → `{"status":"ok"}` in < 60 s
- [ ] `POST /analyze-ticket` returns schema-valid JSON on all 10 sample cases
- [ ] No customer_reply contains PIN / OTP / password / card-number requests
- [ ] No customer_reply confirms a refund or reversal
- [ ] All phishing / inconsistent / high-value cases have `human_review_required: true`
- [ ] p95 latency ≤ 5 s; no 5xx on valid input
- [ ] Dockerfile builds and the container serves `/health` within 60 s
- [ ] README documents setup, run, tech, safety, models, limits
- [ ] At least one `sample_output.json` from a public case committed
- [ ] One submission path (live URL preferred) is reachable

---

## 8. Execution order (one-liner)

> **Schema → Health → Matcher → Verdict → Classifier → Routing → Safety → Tests on 10 cases → Dockerfile → README → Deploy → Submit.**

If the clock forces a cut: keep Phase A + B + C + D + F + G + H. Drop Phase E first; compress Phase H last.
