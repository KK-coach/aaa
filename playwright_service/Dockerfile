# AAA-19 / AAA-31 — Playwright rendering microservice image.
#
# This is the ONLY image in the system that bundles a browser (Chromium). The
# dispatcher and the audit worker images stay lean and reach this service over
# HTTP (PLAYWRIGHT_URL). The service is fully self-contained (renderer.py +
# app.py only need playwright + selectolax + fastapi), so the build context is
# this directory, deployed with:
#   gcloud run deploy playwright-render --source playwright_service \
#     --region europe-west3 --service-account aaa-playwright@PROJECT... \
#     --no-allow-unauthenticated --concurrency 1 --memory 2Gi --timeout 60s \
#     --min-instances 0
#
# Cloud Run config (AAA-31 S3a):
#   --memory 2Gi            # Chromium is memory-heavy (AAA-19 ticket hint)
#   --concurrency 1         # conservative; each render holds a browser context
#   --region europe-west3   # match the worker / Cloud Tasks queue / Firestore
#   --timeout 60s           # a single render is bounded by TIMEOUT_MS (30s)

# The official Playwright image ships Chromium + all OS deps at a pinned version.
# Keep this tag in sync with the installed `playwright` Python package version.
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

# Minimal runtime deps for just the service (NOT the full audit requirements):
# FastAPI + uvicorn + the renderer's HTML/Playwright stack.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Chromium is already bundled in the base image. Belt-and-suspenders: ensure the
# browser matching the pip-installed playwright is present.
RUN python -m playwright install chromium

# Build context is playwright_service/; place it as the importable package.
COPY . /app/playwright_service

ENV PORT=8081
EXPOSE 8081

# Cloud Run sets $PORT; bind to it. Single worker (request concurrency is capped
# by Cloud Run container concurrency, kept at 1 because of Chromium memory).
CMD ["sh", "-c", "uvicorn playwright_service.app:app --host 0.0.0.0 --port ${PORT}"]
