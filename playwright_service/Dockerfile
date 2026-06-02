# AAA-19 / AAA-31 Sub-step 2b — Playwright rendering microservice image.
#
# This is the ONLY image in the system that bundles a browser (Chromium). The
# dispatcher and the audit worker images stay lean and reach this service over
# HTTP (PLAYWRIGHT_URL). Build context = repo root:
#   docker build -f playwright_service/Dockerfile -t playwright-render .
#
# Deploy is Sub-step 3 — do NOT deploy from here. Recommended Cloud Run config
# (FLAGGED for S3):
#   --memory 2Gi            # Chromium is memory-heavy (AAA-19 ticket hint)
#   --concurrency 1         # conservative; each render holds a browser context
#   --region europe-west1   # match the worker / Cloud Tasks queue / Firestore
#   --cpu 1 --timeout 60s   # a single render is bounded by TIMEOUT_MS (30s)

# The official Playwright image ships Chromium + all OS deps at a pinned version.
# Keep this tag in sync with the installed `playwright` Python package version.
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

# Minimal runtime deps for just the service (NOT the full audit requirements):
# FastAPI + uvicorn + the renderer's HTML/Playwright stack.
COPY playwright_service/requirements.txt /app/playwright_service/requirements.txt
RUN pip install --no-cache-dir -r /app/playwright_service/requirements.txt

# Chromium is already bundled in the base image. Belt-and-suspenders: ensure the
# browser matching the pip-installed playwright is present.
RUN python -m playwright install chromium

COPY playwright_service /app/playwright_service

ENV PORT=8081
EXPOSE 8081

# Cloud Run sets $PORT; bind to it. Single worker (concurrency handled by Cloud
# Run container concurrency, kept low because of Chromium memory).
CMD ["sh", "-c", "uvicorn playwright_service.app:app --host 0.0.0.0 --port ${PORT}"]
