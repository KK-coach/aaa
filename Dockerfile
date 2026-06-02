# AAA-31 S3b — audit worker image (Cloud Run).
#
# Runs the heavy ~20-min run_one to completion, triggered by the dispatcher's
# Cloud Tasks payload (POST /run). Build context = repo ROOT (the worker imports
# the whole audit pipeline). Deploy:
#   gcloud run deploy aaa-worker --source . --region europe-west3 \
#     --service-account aaa-worker@PROJECT... --no-allow-unauthenticated \
#     --concurrency 1 --timeout 3600 --memory 4Gi --cpu 2 --min-instances 0 \
#     --build-service-account .../aaa-build... --set-secrets=... --set-env-vars=...
#
# Chromium is intentionally NOT installed (no `playwright install chromium`):
# the browser lives in the separate playwright-render service and the worker
# renders over PLAYWRIGHT_URL/HTTP. The `playwright` python package is still a
# dep (imported by playwright_service.renderer at module load).

FROM python:3.11-slim

WORKDIR /app

# Install deps first for layer caching.
COPY deploy_agent/requirements.txt /app/deploy_agent/requirements.txt
RUN pip install --no-cache-dir -r /app/deploy_agent/requirements.txt

# App source (repo root; .gcloudignore keeps secrets/junk/node_modules out).
COPY . /app

ENV PORT=8080
EXPOSE 8080

# Cloud Run injects $PORT. Container concurrency = 1 (set at deploy), so the
# module-level cost counters / ADK session in the pipeline are safe as-is.
CMD ["sh", "-c", "uvicorn deploy_agent.worker:app --host 0.0.0.0 --port ${PORT}"]
