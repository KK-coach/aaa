# AAA-97 — public serving service image (Cloud Run, internet-facing).
# Lean: only fastapi/uvicorn + firestore + storage (no audit-pipeline deps).
# Self-contained build context = this dir:
#   gcloud run deploy aaa-web --source web_service --region europe-west3 \
#     --service-account aaa-web@PROJECT... --build-service-account .../aaa-build... \
#     --allow-unauthenticated --set-env-vars FIRESTORE_DATABASE=ai-advisor-app

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Build context is web_service/; place it as the importable package.
COPY . /app/web_service

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn web_service.app:app --host 0.0.0.0 --port ${PORT}"]
