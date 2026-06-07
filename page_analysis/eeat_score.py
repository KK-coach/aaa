"""AAA-170 Sub-step 1 — client E-E-A-T scorer (production callable).

ONE gemini-3.5-flash call per audit scoring the CLIENT page on the four Google
December-2025 E-E-A-T dimensions (Experience / Expertise / Authoritativeness /
Trustworthiness), each integer 0-10, plus total_0_40, per-dimension justification
and a 1-sentence verdict. Validated in AAA-170 Sub-step 0 (run-to-run stable, no
dim drift >2; client cost ~$0.006-0.024 depending on excerpt size).

GROUNDING (preventive, AAA-124 pattern): the prompt embeds a deterministic
ground-truth block built from already-measured signals — AAA-56 eeat_signals,
KG/entity people, AAA-123 phase2_html_measurements, AAA-124 aspect_evaluations —
plus module-derived on-page facts (security-cert keyword presence, placeholder /
unfinished-content detection, customer-count claim, schema-type sophistication).
The model scores ONLY the on-page E-E-A-T signals; it must not contradict the
ground-truth.

HARD GUARD (Krisztián decision, carried from Sub-step 0): justifications and the
verdict are DESCRIPTIVE / DIAGNOSTIC / RELATIVE (what is present vs missing, what
to improve). It is FORBIDDEN to claim or imply that the score predicts Google
ranking / SERP position / AI-citation likelihood, or to reference any SERP
correlation. This is an on-page diagnostic only.

CLIENT-ONLY: competitor E-E-A-T scoring is deferred (RG4) — competitor page prose
is not persisted (only the 16-field summary), so this module scores the client
exclusively. The persisted object carries competitors=[] for forward-compat.

Cost is tracked SEPARATELY (audit_eeat_score_cost_usd, AAA-53 separation) — never
folded into audit_cost_usd.

Skip-finding: ANY failure (Gemini error, parse fail, schema/range validation) →
the result dict carries _meta._error and the audit continues. Never raises.
"""
from __future__ import annotations

import json
import logging
import re
import time

from pydantic import BaseModel, Field, ValidationError

from site_profile.gemini_analyzer import compute_call_cost_usd

logger = logging.getLogger(__name__)

MODEL = "gemini-3.5-flash"
LOCATION = "global"
RUBRIC_VERSION = "eeat_v1"
TEMPERATURE = 0.2
THINKING_LEVEL = "LOW"

DIMS = ("experience", "expertise", "authoritativeness", "trustworthiness")

_CERT_RE = re.compile(
    r"\b(SOC ?2|ISO ?27001|ISO ?9001|GDPR|HIPAA|PCI[- ]?DSS|"
    r"certified|certification)\b", re.I)
_PLACEHOLDER_RE = re.compile(r"lorem ipsum|dolor sit amet", re.I)
_CUSTOMER_RE = re.compile(
    r"\b\d[\d,\.]*\+?\s*(companies|customers|businesses|clients|users)\b", re.I)


# ---------------------------------------------------------------------------
# Pydantic contract (enforces integer 0-10 per dim → off-range = ValidationError)
# ---------------------------------------------------------------------------
class _Justifications(BaseModel):
    experience: str
    expertise: str
    authoritativeness: str
    trustworthiness: str


class EEATScore(BaseModel):
    experience: int = Field(ge=0, le=10)
    expertise: int = Field(ge=0, le=10)
    authoritativeness: int = Field(ge=0, le=10)
    trustworthiness: int = Field(ge=0, le=10)
    justifications: _Justifications
    verdict: str


def _gemini_schema() -> dict:
    s = {"type": "STRING"}
    return {
        "type": "OBJECT",
        "properties": {
            "experience": {"type": "INTEGER"},
            "expertise": {"type": "INTEGER"},
            "authoritativeness": {"type": "INTEGER"},
            "trustworthiness": {"type": "INTEGER"},
            "justifications": {
                "type": "OBJECT",
                "properties": {d: s for d in DIMS},
                "required": list(DIMS),
            },
            "verdict": {"type": "STRING"},
        },
        "required": ["experience", "expertise", "authoritativeness",
                     "trustworthiness", "justifications", "verdict"],
    }


# ---------------------------------------------------------------------------
# Deterministic grounding signals (module-derived from audit_output; no fetch)
# ---------------------------------------------------------------------------
def _main_text(ao: dict) -> str:
    cr = ao.get("crawl") or {}
    mc = (cr.get("main_content") or {}).get("text") or ""
    return mc or ((cr.get("content") or {}).get("visible_text") or "")


def _derive_signals(ao: dict) -> dict:
    cr = ao.get("crawl") or {}
    ee = ao.get("eeat_signals") or {}
    ent = ao.get("entities") or {}
    text = _main_text(ao)
    schema_types = (cr.get("schema_markup") or {}).get("schema_types_detected") or []
    schema_l = {str(t).lower() for t in schema_types}
    cust = _CUSTOMER_RE.search(text or "")
    return {
        "named_people": ee.get("named_people") or [],
        "entity_people": ent.get("people") or [],
        "entity_organizations": ent.get("organizations") or [],
        "social_proof_links": ee.get("social_proof_links") or [],
        "schema_types": schema_types,
        "has_softwareapplication": "softwareapplication" in schema_l,
        "has_offer": "offer" in schema_l,
        "has_person_schema": "person" in schema_l,
        "cert_keyword_present": bool(_CERT_RE.search(text or "")),
        "placeholder_count": len(_PLACEHOLDER_RE.findall(text or "")),
        "customer_count_claim": cust.group(0).strip() if cust else None,
        "main_content_words": (cr.get("main_content") or {}).get("words"),
    }


def _ground_truth_block(ao: dict, sig: dict) -> str:
    p2 = (ao.get("phase2_html_measurements") or {}).get("semantic_structure") or {}
    spm = p2.get("schema_pagetype_match") or {}
    ae = ao.get("aaa124_aspect_evaluations") or {}
    schema_find = str((ae.get("schema_entity") or {}).get("structured_finding") or "")[:280]
    named_author = bool(sig["named_people"] or sig["entity_people"])
    return "\n".join([
        "GROUND-TRUTH (deterministic measurements — AUTHORITATIVE; never contradict, never invent a signal not listed):",
        f"  Named author/people on page: {'YES ' + str((sig['named_people'] or sig['entity_people'])[:5]) if named_author else 'NONE (no named author; none KG-recognized)'}.",
        f"  Security/compliance certification keyword on page: {'PRESENT' if sig['cert_keyword_present'] else 'NONE detected (no SOC2/ISO/GDPR/PCI/HIPAA)'}.",
        f"  Customer-proof claim: {sig['customer_count_claim'] or 'none detected'}; named organisations on page: {sig['entity_organizations'][:8] or 'none'}.",
        f"  Structured data: {len(sig['schema_types'])} schema types {sig['schema_types']}; SoftwareApplication={sig['has_softwareapplication']}, Offer={sig['has_offer']}, Person/author-schema={sig['has_person_schema']}.",
        f"  Schema-vs-page-type match (AAA-123): match={spm.get('match')}, matched_types={spm.get('matched_types')}.",
        f"  CONTENT-QUALITY FLAG: {sig['placeholder_count']}x placeholder/unfinished ('lorem ipsum') string(s) detected in the page content (machine-readable; may be CSS-hidden). >0 is an unfinished-content / trust-quality negative.",
        f"  main_content length: {sig['main_content_words']} words; social-proof links present: {len(sig['social_proof_links'])}.",
        f"  AAA-124 schema/entity finding: \"{schema_find}\"",
    ])


def _build_prompt(ao: dict, sig: dict, anchor_keyword: str) -> str:
    sp = ao.get("site_profile") or {}
    brand = sp.get("brand_name") or sp.get("brand") or "(unknown)"
    text = _main_text(ao)
    excerpt = text[:2800]
    gt = _ground_truth_block(ao, sig)
    anchor = anchor_keyword or "(no target query supplied)"
    return f"""\
You are a Google E-E-A-T diagnostic evaluator (December-2025 framework; E-E-A-T
applies to competitive commercial queries). Score ONE webpage on the four E-E-A-T
dimensions, each an INTEGER 0-10, **relative to the TARGET SEARCH QUERY below** —
i.e. how strong is this page's E-E-A-T FOR THIS QUERY'S TOPIC — grounded ONLY in
the GROUND-TRUTH block and the content excerpt. The ground-truth measurements are
AUTHORITATIVE — never contradict them, and never invent a signal not listed.

TARGET SEARCH QUERY (the relevance anchor — judge every dimension against THIS
query's topic, NOT the page's generic credibility):
  "{anchor}"

PAGE CONTEXT:
  url: {ao.get('url')}
  brand: {brand}
  page_type: {ao.get('page_type')}   business_model: {ao.get('business_model')}
  audience: {ao.get('audience_relationship_primary')}   topic_domain: {ao.get('topic_domain')}

{gt}

MAIN CONTENT EXCERPT (first 2800 chars):
{excerpt}

DIMENSIONS (score each 0-10, judged FOR THE TARGET QUERY'S TOPIC above):
  - experience: first-hand/operational proof RELEVANT TO the query topic — named customers, case studies, usage scale, product depth on that topic.
  - expertise: subject-matter / topical depth & specificity ON the query topic; presence of a named, accountable author with relevant credentials.
  - authoritativeness: named entities / ecosystem breadth and structured-data sophistication relevant to the query topic (e.g. SoftwareApplication/Offer); brand/market signals on the page.
  - trustworthiness: security/compliance certifications, transparency, NO placeholder/unfinished content, no overclaiming.

If the page's content is largely OFF-TOPIC for the target query, the topic-relevant
dimensions (experience/expertise/authoritativeness) should score LOWER even if the
page is otherwise polished — this is a query-relative judgment, not generic page quality.

For each dimension write a 1-2 sentence justification, and one overall 1-sentence
verdict. Name the SPECIFIC signal each score rests on (e.g. "no SOC2/ISO cert
detected", "no named author", "{sig['placeholder_count']}x placeholder string present",
"SoftwareApplication schema {'present' if sig['has_softwareapplication'] else 'absent'}").

HARD RULES (mandatory):
  - Score is "E-E-A-T strength for the target query's topic", NOT a generic page
    score and NOT a ranking prediction.
  - Justifications and the verdict must be DESCRIPTIVE / DIAGNOSTIC / RELATIVE:
    what is present vs missing on THIS page for THIS query, and what to improve.
  - ABSOLUTELY FORBIDDEN: any claim or hint that this score predicts Google
    ranking, SERP position, or AI-citation likelihood; any reference to search
    position or to a correlation with rankings. No ranking-prediction language.

Return ONLY structured JSON matching the required schema.
"""


_client = None


def _get_client():
    global _client
    if _client is None:
        from site_profile.gemini_analyzer import make_genai_client
        _client = make_genai_client(location=LOCATION)
    return _client


def score_eeat(audit_output: dict, anchor_keyword: str | None = None) -> tuple[dict | None, float]:
    """Score the CLIENT page on the 4 E-E-A-T dimensions. Returns
    (eeat_score_dict, cost_usd). Skip-finding: any failure → a dict carrying
    _meta._error and cost 0.0; never raises.

    Shape:
      {rubric_version, client:{experience,expertise,authoritativeness,
        trustworthiness,total_0_40,justifications,verdict,grounding_confidence},
       competitors:[], _meta:{model_id,temperature,thinking_level,input_tokens,
        output_tokens,latency_s,cost_usd,error}}
    """
    from google.genai import types

    t0 = time.perf_counter()
    try:
        sig = _derive_signals(audit_output)
        # AAA-172 (+fix): query-anchored. The anchor is the SERP INPUT keyword =
        # the DESCRIPTIVE CATEGORY query the audit/SERP ran on (target_keywords.
        # category_keyword), NOT the drift-prone derived primary_keyword. An
        # explicit anchor_keyword (threaded from the client for competitors)
        # overrides; the client path falls back to its OWN category_keyword.
        # NEVER falls back to primary_keyword (per AAA-172 fix). Missing ->
        # anchor unavailable (no primary fallback), flagged in _meta.
        tk = audit_output.get("target_keywords") or {}
        if anchor_keyword:
            anchor, anchor_source = anchor_keyword.strip(), "explicit_category_keyword"
        elif (tk.get("category_keyword") or "").strip():
            anchor, anchor_source = tk["category_keyword"].strip(), "category_keyword"
        else:
            anchor, anchor_source = "", "unavailable"
        prompt = _build_prompt(audit_output, sig, anchor)
        resp = _get_client().models.generate_content(
            model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=TEMPERATURE,
                response_mime_type="application/json",
                response_schema=_gemini_schema(),
                thinking_config=types.ThinkingConfig(thinking_level=THINKING_LEVEL),
            ),
        )
        latency = round(time.perf_counter() - t0, 3)
        um = resp.usage_metadata
        in_tok = getattr(um, "prompt_token_count", 0) or 0
        out_tok = ((getattr(um, "candidates_token_count", 0) or 0)
                   + (getattr(um, "thoughts_token_count", 0) or 0))
        cost = round(compute_call_cost_usd(MODEL, in_tok, out_tok), 8)

        parsed = json.loads(resp.text)
        validated = EEATScore(**parsed)  # enforces int 0-10 per dim
        v = validated.model_dump()
        total = (v["experience"] + v["expertise"]
                 + v["authoritativeness"] + v["trustworthiness"])  # deterministic
        client = {
            "experience": v["experience"], "expertise": v["expertise"],
            "authoritativeness": v["authoritativeness"],
            "trustworthiness": v["trustworthiness"],
            "total_0_40": total,
            "justifications": v["justifications"],
            "verdict": v["verdict"],
            "grounding_confidence": "full_content",
        }
        logger.info("score_eeat: total %d/40, $%.6f, %.1fs", total, cost, latency)
        return {
            "rubric_version": RUBRIC_VERSION,
            "client": client,
            "competitors": [],  # forward-compat (RG4 deferred)
            "_meta": {"model_id": MODEL, "temperature": TEMPERATURE,
                      "thinking_level": THINKING_LEVEL, "anchor_keyword": anchor, "anchor_source": anchor_source, "input_tokens": in_tok,
                      "output_tokens": out_tok, "latency_s": latency,
                      "cost_usd": cost, "error": None},
        }, cost
    except (ValidationError, json.JSONDecodeError) as e:
        logger.warning("score_eeat: schema/parse fail: %s: %s", type(e).__name__, e)
        return _skip(t0, f"{type(e).__name__}: {e}"), 0.0
    except Exception as e:  # noqa: BLE001 — never fail the audit
        logger.warning("score_eeat: call failed: %s: %s", type(e).__name__, e)
        return _skip(t0, f"{type(e).__name__}: {e}"), 0.0


def _skip(t0: float, err: str) -> dict:
    return {
        "rubric_version": RUBRIC_VERSION,
        "client": None,
        "competitors": [],
        "_meta": {"model_id": MODEL, "latency_s": round(time.perf_counter() - t0, 3),
                  "cost_usd": 0.0, "error": err},
    }


# ===========================================================================
# AAA-172 S1 — COMPARATIVE (query-anchored, common-keyword-basis) scorer
# ===========================================================================
# ONE gemini call scores the client + N competitors against EACH OTHER on the
# client's category_keyword (the SERP query the competitor set was built on).
# Validated on the rollout-gate (tax + vercel): produces an ordering-STABLE
# relative ranking (zero slot-swaps across shuffled order) where the per-page-
# independent scorer's ordering was unstable. The absolute /40 floats run-to-run
# (correlated global scale shift) — render relative/banded, not the bare number.
#
# Prompt is byte-faithful to the gate-validated corrected comparative probe:
# NO "(December-2025 framework)" persona tag; PAGE_n headers keyed to the
# archived URL (not brand); same GROUND-TRUTH block, rubric, HARD GUARD, and
# dimension definitions as the per-page scorer; vertical-neutral wording.
RUBRIC_VERSION_COMPARATIVE = "eeat_v2_query_anchored"
_CONTENT_WORD_MIN = 150  # full_content gate (word-count, NOT grounding_confidence)


def _content_words(ao: dict) -> int:
    """Deterministic full_content gate signal — main_content word count.
    Reliable where grounding_confidence is NOT (a 403-blocked page can carry
    grounding_confidence='full_content' with an empty body, AAA-172 gate)."""
    cr = ao.get("crawl") or {}
    mc = cr.get("main_content") or {}
    w = mc.get("words")
    if isinstance(w, int) and w > 0:
        return w
    # fallback: estimate from text length if words not populated
    txt = mc.get("text") or (cr.get("content") or {}).get("visible_text") or ""
    return len((txt or "").split())


def _comparative_schema() -> dict:
    return {"type": "OBJECT", "properties": {"evaluations": {"type": "ARRAY", "items": {
        "type": "OBJECT", "properties": {
            "page_id": {"type": "STRING"},
            "experience": {"type": "INTEGER"}, "expertise": {"type": "INTEGER"},
            "authoritativeness": {"type": "INTEGER"}, "trustworthiness": {"type": "INTEGER"},
            "justification": {"type": "STRING"}},
        "required": ["page_id", "experience", "expertise", "authoritativeness",
                     "trustworthiness", "justification"]}}},
        "required": ["evaluations"]}


def _comparative_page_block(url: str, ao: dict, pid: str) -> str:
    sig = _derive_signals(ao)
    txt = _main_text(ao)[:1800]
    gt = _ground_truth_block(ao, sig)
    return (f"===== {pid} (url: {url}) =====\n"
            f"GROUND-TRUTH (deterministic; authoritative, never contradict):\n"
            f"{gt}\n"
            f"PAGE CONTENT EXCERPT:\n"
            f"{txt}\n")


def _build_comparative_prompt(pages: list, anchor: str) -> str:
    """pages = list of (url, audit_output) in display order (client first)."""
    blocks = [_comparative_page_block(u, ao, f"PAGE_{i}")
              for i, (u, ao) in enumerate(pages, 1)]
    body = "\n".join(blocks)
    n = len(pages)
    return f"""You are a Google E-E-A-T COMPARATIVE diagnostic evaluator.
TARGET SEARCH QUERY (relevance anchor for ALL pages): "{anchor}"

You are given {n} pages below (PAGE_1..PAGE_{n}). Score EACH page on the four
E-E-A-T dimensions (experience, expertise, authoritativeness, trustworthiness),
each an INTEGER 0-10, JUDGED FOR THE TARGET QUERY'S TOPIC. Evaluate the pages
COMPARATIVELY and RELATIVELY against one another on the same query. If a page is
largely off-topic for the query, its topic-relevant dimensions score lower.

HARD GUARD: justifications must be DESCRIPTIVE / DIAGNOSTIC / RELATIVE (what is
present vs missing). It is FORBIDDEN to predict or imply Google ranking, SERP
position, or AI-citation likelihood, or to reference SERP correlation. Never
invent a signal not in the ground-truth. Score ONLY on-page signals.

Return JSON: {{"evaluations":[{{"page_id","experience","expertise",
"authoritativeness","trustworthiness","justification"}}]}} — one object per page,
page_id EXACTLY as labelled (PAGE_1..).

{body}
"""


def score_eeat_comparative(client_ao: dict, competitors: list,
                           anchor_keyword: str) -> tuple[dict, float]:
    """AAA-172 S1 — comparative query-anchored E-E-A-T.

    client_ao   : the client's archived audit_output (full content).
    competitors : list of {"url","audit_id","audit_output"} for the audited set.
    anchor_keyword : the client's category_keyword (common-query basis).

    full_content gate (word-count >= _CONTENT_WORD_MIN) is applied to each
    COMPETITOR; sub-threshold competitors are excluded (recorded with reason +
    word_count). If < 2 genuine competitors remain -> returns a 'skip' marker
    (status='skipped_insufficient_full_content') and the caller keeps the
    page-intrinsic client score (no comparative call made; cost 0.0).

    Returns (result_dict, cost_usd). Never raises (skip-finding).

    result_dict on success:
      {rubric_version, anchor_keyword, scoring_mode:"comparative",
       comparative_status:"ok",
       client:{4 dims, total_0_40, justifications, verdict, grounding_confidence},
       competitors:[{url, brand, audit_id, 4 dims, total_0_40, justification,
                     grounding_confidence}],
       ranking:[{url, brand, total_0_40, rank}],
       competitors_excluded:[{url, reason, word_count}],
       _meta:{...}}
    """
    from google.genai import types

    t0 = time.perf_counter()
    try:
        anchor = (anchor_keyword or "").strip()
        # full_content gate on competitors (word-count, NOT grounding_confidence)
        genuine, excluded = [], []
        for c in competitors:
            cao = c.get("audit_output") or {}
            w = _content_words(cao)
            if w >= _CONTENT_WORD_MIN:
                genuine.append(c)
            else:
                excluded.append({"url": c.get("url"), "reason": "below_full_content_threshold",
                                 "word_count": w})

        if len(genuine) < 2:
            # Fallback — no comparative; caller keeps page-intrinsic client score.
            return ({
                "scoring_mode": "page_intrinsic_fallback",
                "comparative_status": "skipped_insufficient_full_content",
                "rubric_version": RUBRIC_VERSION_COMPARATIVE,
                "anchor_keyword": anchor,
                "competitors_excluded": excluded,
                "competitors_genuine_count": len(genuine),
                "_meta": {"model_id": MODEL, "cost_usd": 0.0,
                          "latency_s": round(time.perf_counter() - t0, 3),
                          "error": None},
            }, 0.0)

        # Build pages: client first (PAGE_1), then genuine competitors.
        pages = [(client_ao.get("url") or (client_ao.get("site_profile") or {}).get("url")
                  or "(client)", client_ao)]
        for c in genuine:
            pages.append((c.get("url"), c.get("audit_output") or {}))
        prompt = _build_comparative_prompt(pages, anchor)

        resp = _get_client().models.generate_content(
            model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=TEMPERATURE,
                response_mime_type="application/json",
                response_schema=_comparative_schema(),
                thinking_config=types.ThinkingConfig(thinking_level=THINKING_LEVEL),
            ),
        )
        latency = round(time.perf_counter() - t0, 3)
        um = resp.usage_metadata
        in_tok = getattr(um, "prompt_token_count", 0) or 0
        out_tok = ((getattr(um, "candidates_token_count", 0) or 0)
                   + (getattr(um, "thoughts_token_count", 0) or 0))
        cost = round(compute_call_cost_usd(MODEL, in_tok, out_tok), 8)

        parsed = json.loads(resp.text).get("evaluations") or []
        by_pid = {e.get("page_id"): e for e in parsed}

        def _dims(e: dict) -> dict:
            d = {k: int(e[k]) for k in DIMS}
            for k in DIMS:
                if not (0 <= d[k] <= 10):
                    raise ValueError(f"dim {k} out of range: {d[k]}")
            d["total_0_40"] = sum(d[k] for k in DIMS)
            return d

        # client = PAGE_1
        ce = by_pid.get("PAGE_1")
        if not ce:
            raise ValueError("comparative response missing PAGE_1 (client)")
        cd = _dims(ce)
        client_block = {
            **{k: cd[k] for k in DIMS}, "total_0_40": cd["total_0_40"],
            "justifications": {"comparative": ce.get("justification") or ""},
            "verdict": ce.get("justification") or "",
            "grounding_confidence": "full_content",
        }
        # competitors = PAGE_2..
        comp_out, ranking = [], []
        for i, c in enumerate(genuine, start=2):
            ee = by_pid.get(f"PAGE_{i}")
            cao = c.get("audit_output") or {}
            brand = (cao.get("site_profile") or {}).get("brand") or c.get("brand")
            if not ee:
                continue
            dd = _dims(ee)
            comp_out.append({
                "url": c.get("url"), "brand": brand, "audit_id": c.get("audit_id"),
                **{k: dd[k] for k in DIMS}, "total_0_40": dd["total_0_40"],
                "justification": ee.get("justification") or "",
                "grounding_confidence": "full_content",
            })
        # ranking incl. client, by total desc
        rank_rows = [{"url": pages[0][0],
                      "brand": (client_ao.get("site_profile") or {}).get("brand"),
                      "total_0_40": client_block["total_0_40"], "is_client": True}]
        rank_rows += [{"url": c["url"], "brand": c["brand"],
                       "total_0_40": c["total_0_40"], "is_client": False}
                      for c in comp_out]
        rank_rows.sort(key=lambda r: -r["total_0_40"])
        for n, r in enumerate(rank_rows, 1):
            r["rank"] = n
        ranking = rank_rows

        logger.info("score_eeat_comparative: %d pages, client %d/40, $%.6f, %.1fs",
                    len(pages), client_block["total_0_40"], cost, latency)
        return ({
            "scoring_mode": "comparative",
            "comparative_status": "ok",
            "rubric_version": RUBRIC_VERSION_COMPARATIVE,
            "anchor_keyword": anchor,
            "client": client_block,
            "competitors": comp_out,
            "ranking": ranking,
            "competitors_excluded": excluded,
            "_meta": {"model_id": MODEL, "temperature": TEMPERATURE,
                      "thinking_level": THINKING_LEVEL, "anchor_keyword": anchor,
                      "anchor_source": "category_keyword",
                      "input_tokens": in_tok, "output_tokens": out_tok,
                      "latency_s": latency, "cost_usd": cost, "error": None},
        }, cost)
    except (ValidationError, json.JSONDecodeError, ValueError) as e:
        logger.warning("score_eeat_comparative: parse/schema fail: %s: %s",
                       type(e).__name__, e)
        return ({"scoring_mode": "comparative", "comparative_status": "error",
                 "rubric_version": RUBRIC_VERSION_COMPARATIVE,
                 "anchor_keyword": (anchor_keyword or "").strip(),
                 "_meta": {"model_id": MODEL, "cost_usd": 0.0,
                           "latency_s": round(time.perf_counter() - t0, 3),
                           "error": f"{type(e).__name__}: {e}"}}, 0.0)
    except Exception as e:  # noqa: BLE001 — never fail the audit
        logger.warning("score_eeat_comparative: call failed: %s: %s",
                       type(e).__name__, e)
        return ({"scoring_mode": "comparative", "comparative_status": "error",
                 "rubric_version": RUBRIC_VERSION_COMPARATIVE,
                 "anchor_keyword": (anchor_keyword or "").strip(),
                 "_meta": {"model_id": MODEL, "cost_usd": 0.0,
                           "latency_s": round(time.perf_counter() - t0, 3),
                           "error": f"{type(e).__name__}: {e}"}}, 0.0)
