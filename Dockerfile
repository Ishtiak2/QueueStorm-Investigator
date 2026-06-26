# syntax=docker/dockerfile:1.7
# ----- Stage 1: build wheels -----
FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Build deps for httpx / uvicorn[standard] (uvloop + httptools wheels exist
# for linux/amd64 and linux/arm64, so this stays minimal).
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt


# ----- Stage 2: runtime image -----
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0

# Run as a non-root user for least privilege.
RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

# Copy the prebuilt packages from the builder.
COPY --from=builder /install /usr/local

# Application code + assets. Keep this small; .dockerignore drops the rest.
COPY app ./app
COPY sample_output.json ./sample_output.json
COPY requirements.txt ./requirements.txt

USER app

EXPOSE 8000

# Single-process uvicorn. For production-grade concurrency, swap this for
# `uvicorn.workers.UvicornWorker` under gunicorn or run multiple replicas.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
