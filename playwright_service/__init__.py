"""AAA-19 / AAA-31 Sub-step 2b — Playwright rendering microservice.

A small FastAPI Cloud Run service that bundles headless Chromium and exposes
``POST /render``. It is the ONLY image in the system that ships a browser; the
dispatcher/worker images stay lean and reach JS-rendered DOM over HTTP via
``playwright_poc.render.render_url`` (which calls this service at
``PLAYWRIGHT_URL``). Build-only here — deploy is Sub-step 3.
"""
