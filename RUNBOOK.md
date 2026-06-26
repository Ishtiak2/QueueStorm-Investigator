# RUNBOOK — QueueStorm Investigator

> Copy-pasteable steps for a stranger to bring up the service and verify it.

This runbook assumes a clean macOS / Linux shell with Python 3.11 and Docker
(optionally) installed. Total time: **~3 min** for the local path,
**~5 min** for the Render path.

---

## A. Local — fastest

```bash
# 1. Clone and enter
git clone https://github.com/Ishtiak2/QueueStorm-Investigator.git
cd QueueStorm-Investigator

# 2. Create a venv and install deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Run the API (binds 0.0.0.0:8000)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. In a second terminal, verify /health
curl http://127.0.0.1:8000/health
# -> {"status":"ok"}

# 5. Hit /analyze-ticket with the SAMPLE-01 payload
curl -X POST http://127.0.0.1:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "TKT-001",
    "complaint": "I sent 5000 taka to a wrong number around 2pm today.",
    "transaction_history": [
      {"transaction_id":"TXN-9101","timestamp":"2026-04-14T14:08:22Z",
       "type":"transfer","amount":5000,
       "counterparty":"+8801719876543","status":"completed"}
    ]
  }'

# 6. Open the Swagger UI in a browser
open http://127.0.0.1:8000/docs
```

To stop the server: press **Ctrl+C** in the uvicorn terminal.

---

## B. Local — via Docker

```bash
# 1. Clone
git clone https://github.com/Ishtiak2/QueueStorm-Investigator.git
cd QueueStorm-Investigator

# 2. Build the image
docker build -t queuestorm-investigator .

# 3. Run, mapping host port 8000 -> container port 8000
docker run --rm -p 8000:8000 --name qsi queuestorm-investigator

# 4. In a second terminal, verify
curl http://127.0.0.1:8000/health
# -> {"status":"ok"}
```

To stop: `docker stop qsi`.

To push to Docker Hub (optional):

```bash
docker login
docker tag queuestorm-investigator:latest YOUR_DOCKERHUB_USER/queuestorm-investigator:latest
docker push YOUR_DOCKERHUB_USER/queuestorm-investigator:latest
```

---

## C. Render — Blueprint (recommended)

```bash
# Nothing to run locally; everything happens in the Render dashboard.
```

1. Open https://render.com and sign in with GitHub.
2. Click **New + → Blueprint**.
3. Select repo `Ishtiak2/QueueStorm-Investigator`.
4. Click **Apply**. Render reads `render.yaml` and creates the service.
5. Wait ~2 min for the first build. The URL is shown on the dashboard,
   e.g. `https://queuestorm-investigator-7d8z.onrender.com`.
6. Verify:

```bash
curl https://queuestorm-investigator-7d8z.onrender.com/health
# -> {"status":"ok"}
```

Subsequent pushes to `main` auto-deploy because `autoDeploy: true`.

---

## D. Render — manual setup (no Blueprint)

```bash
# Nothing to run locally.
```

In the Render dashboard:

1. **New + → Web Service** → connect `Ishtiak2/QueueStorm-Investigator`.
2. **Runtime**: Python 3.
3. **Build Command**: `pip install --upgrade pip && pip install -r requirements.txt`.
4. **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
5. **Health Check Path**: `/health`.
6. **Instance Type**: Free.
7. Click **Create Web Service**.

---

## E. Verifying the rubric (judges / reviewers)

```bash
# 1. Activate venv (only needed for the local path)
source .venv/bin/activate

# 2. Run the 185-test unit + endpoint suite
pytest -q
# -> 185 passed

# 3. Verify the 10 public sample cases match the rubric
python scripts/check_sample_cases.py
# -> Matched 10/10 on rubric-automated fields.

# 4. Verify no safety rule is violated across the 10 cases
python scripts/check_safety.py
# -> PASSED: zero safety violations across all sample cases
```

---

## F. Verifying a live Render deployment

```bash
# Replace the host with the actual URL Render gave you.
HOST=https://queuestorm-investigator-7d8z.onrender.com

# Health
curl -sS $HOST/health | jq .

# Analyze a ticket (minimal)
curl -sS -X POST $HOST/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"TKT-PROBE","complaint":"I sent 500 taka to the wrong number."}' | jq .

# OpenAPI schema (for ad-hoc schema validation)
curl -sS $HOST/openapi.json | jq '.paths."/analyze-ticket".post.responses."200".content."application/json".schema'
```

---

## G. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Address already in use` on `uvicorn` | Port 8000 is busy. | Pick another port: `uvicorn app.main:app --port 8001`. |
| `python3: command not found` | Python not on `PATH`. | Install Python 3.11+ from https://python.org or `brew install python@3.11`. |
| `ModuleNotFoundError: fastapi` | venv not activated or `pip install` was skipped. | `source .venv/bin/activate` and re-run `pip install -r requirements.txt`. |
| Render deploy fails at build | `requirements.txt` drift or missing dep. | Compare against `Dockerfile`'s `pip install -r requirements.txt`. |
| Live URL returns `404` after first deploy | Render hasn't finished the build. | Wait for the dashboard event log to show "Deploy live". |
| Live URL returns `502` after free-tier sleep | Service is waking up. | Retry after ~30 s. |
| `429 Too Many Requests` on live URL | Render free-tier rate limits. | Reduce request rate or upgrade to a paid plan. |
| `/analyze-ticket` returns `422` | Missing required field (`ticket_id` or `complaint`). | See `/docs` for the schema. |
| `/analyze-ticket` returns `422` with `extra_forbidden` | Sent an unknown field (e.g. `merchant_id`). | Allowed optional fields are `language`, `channel`, `user_type`, `campaign_context`, `metadata`. |

---

## H. Environment variables (optional)

The default install runs **zero** external services. If you choose to enable the
optional LLM hook, copy `.env.example` to `.env` and fill in one key:

```bash
cp .env.example .env
# edit .env
```

| Variable | Default | Effect |
|---|---|---|
| `USE_LLM` | `0` | Set to `1` to enable the optional OpenAI / Anthropic polish step. |
| `OPENAI_API_KEY` | _empty_ | Required only if `USE_LLM=1` and `LLM_PROVIDER=openai`. |
| `ANTHROPIC_API_KEY` | _empty_ | Required only if `USE_LLM=1` and `LLM_PROVIDER=anthropic`. |
| `LLM_PROVIDER` | `openai` | `openai` or `anthropic`. |
| `LLM_MODEL` | `gpt-4o-mini` | Model name to call. |

LLM output **always** passes through `safety.sanitize_text()` before being
returned, so even a compromised upstream cannot leak credentials, refunds, or
contact-channel pivots into the response.