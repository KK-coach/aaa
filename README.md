# AAA — AI-powered SEO / GEO / AEO audit tool

AAA reverse-engineers how a website performs in classic search (SEO),
generative engines (GEO — AI Overviews, ChatGPT, Perplexity) and answer
engines (AEO), benchmarks it against the competitors that actually rank for
its queries, and produces a customer-facing audit report. It combines a
deterministic crawl/measurement pipeline with LLM agents (Vertex AI Gemini)
and a Firestore-backed memory "flywheel" of prior audits.

## Architecture (high level)

- **Discovery agent** — full single-site audit: crawl (with optional
  Playwright JS-render escalation), site profiling, entities/keywords, schema
  and content-depth analysis, Core Web Vitals / CrUX, AI-Overview & ChatGPT
  citation checks, and per-aspect findings. Archives each audit (source of
  truth) to Firestore and embeds it into the memory corpus.
- **Reverse-Engineering (RE) agent** — runs Discovery on the client, resolves
  the competitive SERP landscape (DataForSEO), audits the top competitors at
  "corpus-subset" quality, and produces the comparison + findings.
- **Coordinator + report layer** — assembles the bilingual (HU/EN)
  customer summary and the static→progressive HTML report.

### Async deployment (Agent Runtime + Cloud Run)

- **Dispatcher** (`deploy_agent/`) — a conversational front-door ADK agent
  wrapped as a Vertex AI Agent Engine `AdkApp`. It creates a job in the
  Firestore `audit_jobs` collection and enqueues a **Cloud Tasks** task.
- **Worker** (`deploy_agent/worker.py`) — a Cloud Run FastAPI service
  (container concurrency = 1) that receives the Cloud Tasks payload and runs
  the heavy (~20 min) audit to completion, transitioning the job
  `queued → running → done|error`.
- **Cloud Tasks** queue `audit-jobs` decouples the fast front-door from the
  long-running worker (OIDC-authenticated HTTP POST).

## Setup

Requires Python 3.10+, Google Cloud credentials (`gcloud auth
application-default login`) for Vertex AI / Firestore, and Node.js (for the
DataForSEO MCP server, launched via `npx`).

```bash
pip install -r requirements.txt
```

### Environment variables

Credentials are read from the process environment first (on Cloud Run they are
injected from Secret Manager); a local `.env` is used as a dev fallback. Set
the following (names only — never commit values):

| Variable | Purpose |
| --- | --- |
| `GOOGLE_CLOUD_PROJECT` | GCP project id |
| `GOOGLE_GENAI_USE_VERTEXAI` | `True` (use Vertex AI for Gemini) |
| `GOOGLE_CLOUD_LOCATION` | Vertex location (e.g. `global`) |
| `FIRESTORE_DATABASE` | Firestore database id |
| `DATAFORSEO_LOGIN` | DataForSEO account login |
| `DATAFORSEO_PASSWORD` | DataForSEO API password |
| `OPENAI_API_KEY` | OpenAI key (ChatGPT citation check) |
| `WORKER_URL` | Cloud Run worker URL (Cloud Tasks target) |
| `WORKER_INVOKER_SA` | Service account for OIDC task auth |
| `CLOUD_TASKS_LOCATION` | Cloud Tasks region (e.g. `europe-west1`) |

> A polished README, architecture diagram and full deployment guide are part
> of a later submission-packaging task; this is the minimal scaffold.

## License

[Apache-2.0](./LICENSE)
