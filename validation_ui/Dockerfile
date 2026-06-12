# AAA-204 S3 — admin dashboard image (Cloud Run service: aaa-admin).
#
# Build context = repo ROOT (the app imports memory.firestore_archive, which
# transitively pulls discovery_agent / page_analysis / site_profile). This file
# deliberately lives in validation_ui/ so it can NEVER be picked up by the
# other services' builds: aaa-worker deploys --source . (root Dockerfile),
# aaa-web deploys --source web_service (web_service/Dockerfile). Build this
# one explicitly via validation_ui/cloudbuild.yaml:
#   gcloud builds submit . --config validation_ui/cloudbuild.yaml
#   gcloud run deploy aaa-admin --image <the built image> ...
#
# Secrets hygiene: .gcloudignore (source upload) + .dockerignore (docker
# context) both exclude .env / credentials / .git — the image is clean even
# though the repo is public.

FROM python:3.11-slim

WORKDIR /app

# Deps first for layer caching: the worker's pinned full-stack set (the
# transitive imports need it) + the dashboard's own UI deps.
COPY deploy_agent/requirements.txt /app/deploy_agent/requirements.txt
# pandas 2.x: the 1.5.x wheels are binary-incompatible with the numpy 2.x
# that the rest of the dependency set resolves to (numpy.dtype size error).
RUN pip install --no-cache-dir -r /app/deploy_agent/requirements.txt \
    streamlit==1.57.0 pandas==2.2.3

# App source (repo root; ignore files keep secrets/junk out).
COPY . /app

ENV PORT=8080
EXPOSE 8080

# Cloud Run injects $PORT. headless + address 0.0.0.0 for container serving;
# CORS/XSRF stay default-on (IAP fronts the service; same-origin anyway).
CMD ["sh", "-c", "python -m streamlit run validation_ui/app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true"]
