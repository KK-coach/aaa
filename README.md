# AAA — AI-powered SEO / GEO / AEO reverse-engineering audit

**Paste a URL in. Get back why your site underperforms the competitors that
actually rank for its queries — in classic search *and* AI search — and what to
do about it.**

AAA is a multi-agent system (built on **Google's Agent Development Kit**) that
reverse-engineers a website's visibility across **SEO** (Google organic),
**GEO** (Generative Engine Optimization — AI Overviews, ChatGPT), and **AEO**
(Answer Engine Optimization). It crawls and deterministically measures the
target, discovers and audits the real SERP competitors, scores everything with
**Gemini on Vertex AI**, and produces a customer-facing **8-section fact-first
report** — topped with a memory-flywheel verdict: *"what successful pages do
differently"*, grounded in a corpus of previously-audited winning pages.

The business problem it solves: a site owner can see *that* they rank poorly, but
not *why* versus the specific pages beating them, and has no idea whether they're
even visible to ChatGPT / AI Overviews. AAA answers both, with measured evidence
and an impact-ranked action list — no generic "write more content" advice.

---

## What makes it interesting (judging hooks)

- **ADK multi-agent orchestration** — a Coordinator/Dispatcher agent + a
  Discovery agent + a Reverse-Engineering agent, each a real ADK `Agent` with a
  Gemini model and a tool-belt; the RE agent fans Discovery out across the client
  **and up to 3 SERP competitors in parallel**.
- **Gemini / Vertex AI throughout** — all reasoning (site profiling, entity &
  keyword classification, E-E-A-T scoring, competitive synthesis, peer-verdict)
  runs on Gemini via Vertex AI.
- **Grounding & RAG** — every audit is embedded into a **Vertex AI RAG** corpus;
  a **Vertex AI Vector Search** index over *successful* pages (SERP top-3 or
  AI-cited) powers the flywheel: retrieve real winning peers → ground a Gemini
  comparison verdict in their actual measured fact-bases.
- **MCP** — competitive SERP/keyword data via the **DataForSEO remote MCP**
  server.
- **Deterministic-measurement + LLM split** — the report's §1–§8 are *measured
  facts* (provenance-tagged: measured / estimate / AI-interpretation /
  inference); the LLM composes and judges, it never invents the numbers.

---

## Architecture

```mermaid
flowchart TD
    U[User: URL in via web form] -->|POST /submit| W[aaa-web · Cloud Run<br/>form + report serve]
    W -->|create job| FS[(Firestore<br/>audit_jobs / audits)]
    W -->|enqueue OIDC task| CT[Cloud Tasks<br/>queue: audit-jobs]
    CT -->|POST /run| WK[aaa-worker · Cloud Run<br/>concurrency = 1]

    subgraph ADK[ADK multi-agent run]
      RE[Reverse-Engineering Agent<br/>Gemini · tools]
      DISC[Discovery Agent<br/>Gemini · tools]
      RE -->|client + up to 3 competitors<br/>in parallel| DISC
    end
    WK --> RE

    DISC -->|crawl / measure| DATA[DataForSEO MCP · PageSpeed/CrUX<br/>Knowledge Graph · ChatGPT citation signal]
    DISC -->|archive + embed| RAG[Vertex AI RAG corpus]
    RE -->|success-filtered retrieval| VS[Vertex AI Vector Search<br/>winning-page index]
    VS -->|top-3 peers| PV[Gemini peer-verdict]
    RE -->|fact-first render| REP[8-section report + peer-verdict<br/>EN/HU → Cloud Storage]
    REP --> W
```

*(A polished diagram can live at `docs/architecture.png`; the Mermaid graph above
renders on GitHub and is the source of truth.)*

### The agents (as they exist in code)

| Agent | Module | Role |
| --- | --- | --- |
| **Dispatcher / Coordinator** | `deploy_agent/dispatcher.py` | Conversational front-door ADK `Agent`, wrapped as a Vertex AI Agent Engine `AdkApp`. Creates the Firestore job and enqueues the Cloud Tasks task. |
| **Discovery** | `discovery_agent/` | Full single-site audit: crawl (+ optional Playwright JS-render escalation), site profiling, entity/keyword extraction, schema & content-depth analysis, Core Web Vitals / CrUX, AI-Overview & ChatGPT citation checks, per-aspect findings. Archives each audit to Firestore and embeds it into the memory corpus. |
| **Reverse-Engineering (RE)** | `reverse_engineering_agent/` | Runs Discovery on the client, resolves the competitive SERP (DataForSEO), selects the first-3 comparable competitors in SERP order, deep-audits them in parallel, and produces the comparison, E-E-A-T benchmark, recommendations, and the success-peer verdict. |

### The flywheel value loop (the differentiator)

1. Every audit's EN-canonical summary is **embedded** into a Vertex AI RAG corpus.
2. A **Vector Search index** holds only *successful* pages (SERP position ≤ 3 **or**
   cited by AI search), labelled by a one-pass backfill over the archive.
3. On each new client audit, a deterministic pipeline step retrieves the **top-3
   successful peers** (industry-plausible, self-excluding the client's own domain).
4. One **Gemini** call compares the client's curated fact-base against the 3 peers'
   fact-bases and writes a grounded, business-language verdict — *what the winning
   pages do differently* — rendered as the report's peer-verdict section.

### Report layer

A `$0`, deterministic **fact-first renderer** turns the measured `fact_base` into an
8-section HTML report (EN canonical + HU), each datapoint carrying a provenance
chip. Sections: AI-visibility dashboard · keyword research (demand chart) · AI
visibility · your page (content, semantics, machine-readability, technical) ·
E-E-A-T · competitor benchmark · impact-ranked recommendations · peer-verdict ·
data-quality / provenance.

---

## Tech stack

**Intelligence (all reasoning on Google):**
- **Vertex AI — Gemini** for every decision/judgment: site profiling, keyword &
  entity classification, multi-dimensional page classification, aspect
  evaluation, E-E-A-T scoring, competitive synthesis, and the success-peer verdict.
- **Vertex AI RAG** (audit corpus embeddings) + **Vertex AI Vector Search**
  (winning-page index, 3072-dim `gemini-embedding-001`) for grounding / retrieval.

> **Third-party-intelligence compliance.** A single **OpenAI (`gpt-5.4`)** call is
> used **only as a measured data signal** — "does ChatGPT cite this page for its
> query?" and query fan-out coverage. It is **not** a reasoning or decision
> engine; it produces a fact the report records, exactly like a SERP position or a
> PageSpeed score. **All intelligence and orchestration run on Gemini / Vertex AI.**

**Data sources:** DataForSEO (SERP + keyword volume, via remote **MCP** and REST),
Google **PageSpeed Insights** / CrUX, Google **Knowledge Graph**.

**Orchestration:** Google **Agent Development Kit (ADK)**.

**Infrastructure (Google Cloud):**
- **Cloud Run** — `aaa-web` (launch form + report serving from `web_service/`),
  `aaa-worker` (the long-running audit worker, container concurrency = 1),
  `playwright-render` (JS-render microservice for SPA crawls).
- **Cloud Tasks** — `audit-jobs` queue (OIDC-authenticated) decouples the fast
  front-door from the ~15–25 min worker run.
- **Firestore** — job state (`audit_jobs`) and the audit archive (`audits`,
  source of truth + memory corpus).
- **Vertex AI Agent Engine** — hosts the Dispatcher `AdkApp`.
- **Cloud Storage** — rendered HTML reports.

Python 3.10+, FastAPI, selectolax / Playwright (crawl), Node.js (DataForSEO MCP via `npx`).

---

## Reproducibility / spin-up

```bash
pip install -r requirements.txt
gcloud auth application-default login   # Vertex AI + Firestore credentials
```

**Environment variables — names only; never commit values** (read from the
process environment first; on Cloud Run injected from Secret Manager / env, with a
local `.env` dev fallback — `.env` is gitignored):

| Variable | Purpose |
| --- | --- |
| `GOOGLE_CLOUD_PROJECT` | GCP project id |
| `GOOGLE_GENAI_USE_VERTEXAI` | `True` — use Vertex AI for Gemini |
| `GOOGLE_CLOUD_LOCATION` | Vertex location (`global` for the current Gemini model) |
| `FIRESTORE_DATABASE` | Firestore database id |
| `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` | DataForSEO API credentials |
| `GOOGLE_PAGESPEED_API_KEY` | PageSpeed Insights API key |
| `GOOGLE_KG_API_KEY` | Knowledge Graph API key |
| `OPENAI_API_KEY` | OpenAI key (ChatGPT-citation *data signal* only) |
| `WORKER_URL` / `WORKER_INVOKER_SA` | Cloud Run worker URL + SA for OIDC task auth |
| `CLOUD_TASKS_LOCATION` | Cloud Tasks region |
| `CUSTOMER_REPORTS_BUCKET` | GCS bucket for rendered reports |
| `FORM_AUTH_USER` / `FORM_AUTH_PASS` | *(optional)* Basic-Auth gate on the launch form |

**Deploy:**
```bash
# launch form + report server (ALWAYS from web_service/, never --source .)
gcloud run deploy aaa-web --source web_service --region <REGION>

# audit worker (root Dockerfile)
gcloud run deploy aaa-worker --source . --region <REGION>

# JS-render microservice
gcloud run deploy playwright-render --source playwright_service --region <REGION>
```

---

## Testing instructions (for judges)

**Live demo:** `<LIVE_SUBMIT_URL>` *(filled in at submission — the hosted launch
form; if a Basic-Auth gate is enabled, the shared credentials are provided with
the submission).*

1. Open the URL, paste any website URL (English-language sites fully supported),
   and click **Start my audit**. No signup, no cost, no usage restriction.
2. The audit runs **asynchronously (~15–25 minutes)** — a full client crawl plus
   parallel deep-audits of up to 3 SERP competitors.
3. The result page shows a **bookmarkable report link** (`/report/{id}`). Revisit
   it; the 8-section report + peer-verdict appears automatically when ready
   (report links are public / shareable even when the launch form is gated).

To run a single audit on the developer path, invoke the RE agent's
`run_one(url, audit_id, locale)` entry point in `reverse_engineering_agent/`.

---

## Selected learnings

- **Worker-vs-local divergence is the silent killer.** A credentials reader that
  worked locally (`.env`) returned empty on Cloud Run (env-var only), nulling a
  whole data signal — caught only by verifying on the *worker* path, not local
  runs. Verification now always exercises the deployed UI → worker chain.
- **Provenance discipline beats polish.** Distinguishing *measured-clean*
  (positive finding) from *not-measured* (hedge) from *absent* keeps the report
  from ever asserting "OK" on data it doesn't have — and from inventing problems
  it never measured.
- **Retrieve ≠ use.** A working RAG retrieval that the synthesis ignored taught us
  to make the flywheel a *deterministic pipeline step*, not an advisory agent
  instruction the LLM can skip.

(The full story is in the Devpost write-up.)

## License

[Apache License 2.0](./LICENSE).
