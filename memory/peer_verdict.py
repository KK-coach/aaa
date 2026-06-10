"""AAA-202 Gate 3 — success-peer comparison verdict (ONE Gemini call) + §9 source.

Input: the client's curated fact-base + the Gate-2 success_peers reference list.
Fetches each peer's audit doc by doc_id and builds its curated fact-base
(decide-pass subset via report.fact_base.build_fact_base — never raw
audit_output / rendered_crawl; ~6-8k tokens each per Gate 0).

Locked prompt structure (Krisztián): Senior SEO/GEO auditor system role,
[TARGET HIDDEN DATA] + [SUCCESSFUL COMPETITORS' HIDDEN DATA FROM MEMORY],
3-step instruction (compare technical+semantic → critical gaps → business
language, no internal term names). Visual axis OMITTED (Phase 2 — no
screenshot data; the prompt must not invite layout comparison).

Advisory-drift constraints (AAA-152) baked into the prompt AND post-checked:
no ranking promises; business-model-conditional framing; every claim grounded
in the provided fact-bases; §9 = "what successful peers do differently"
(complement, not duplicate, of §7's per-audit gap recommendations).

Degrade contract: the Gemini call runs ONLY with a full top-3 peer set.
<3 peers → {"note": ...} (render shows an honest short note); 0 peers or
retrieval error → {} (render omits §9 entirely). Never invents peers.

EN-canonical first (Principle #3); HU via the existing translate_summary pass.
Cost: returned separately for audit_peer_verdict_cost_usd (AAA-53).
"""

from __future__ import annotations

import json
import logging
import re
import time

logger = logging.getLogger(__name__)

# A/B (Gate 3 S1, 2 canaries): 3-flash-preview $0.023-0.025/14s vs 3.5-flash
# $0.076-0.077/15s — comparable grounded quality, 0 drift flags both → the
# 3.3x-cheaper 3-flash-preview wins. Trade-off: preview model id (3.5-flash is
# the stable fallback via the model_id param if preview is retired).
MODEL_DEFAULT = "gemini-3-flash-preview"
THINKING_LEVEL = "LOW"              # judgment task — never thinking_budget=0
LOCATION = "global"
_MAX_FB_CHARS = 40_000              # per fact-base JSON, defense-in-depth

_SYSTEM = (
    "You are a Senior SEO and GEO auditor. Based on the hidden data, write "
    "clear, actionable improvement recommendations for the target URL."
)

_INSTRUCTION = """INSTRUCTION:
1. Compare the target's technical and semantic (entity) characteristics against the successful competitors' hidden data. Do NOT compare visual design or layout — no visual data is provided.
2. Identify the critical gaps — what the successful pages do differently from the target.
3. In the output, do NOT mention internal technical terms (e.g. 'heading_stacking_candidate', 'div_table_suspicious' or any snake_case field name). Translate every finding into direct, business-level, executable tasks for the user.

HARD CONSTRAINTS:
- NO ranking promises. Never claim or imply "do X and you will rank higher / reach #1". Frame findings as what the successful pages do differently — not guaranteed outcomes.
- Be business-model-conditional where relevant ("if your audience is X, consider Y") rather than issuing universal mandates.
- Ground EVERY claim in the provided hidden data. If the data does not support a claim, do not make it. No general best-practice filler.
- Do not restate the target's own per-audit gap list; focus on the DIFFERENCES versus the successful peers.
- Write 250-400 words of flowing, customer-readable English: a 1-2 sentence overview, then 3-5 concrete difference-based recommendations.
"""

# Post-checks (AAA-152): snake_case internal-term leak + ranking-promise phrasing.
_SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_RANK_RE = re.compile(
    r"(guarantee[ds]?\b|will rank\b|rank\s*#?\s*1\b|#1 ranking|first position\b"
    r"|top (position|spot)\b|biztosan.*helyez|garantál)", re.I)


def _drift_flags(text: str) -> list[str]:
    flags = []
    snakes = sorted(set(_SNAKE_RE.findall(text or "")))
    if snakes:
        flags.append("internal_terms: %s" % ", ".join(snakes[:8]))
    if _RANK_RE.search(text or ""):
        flags.append("ranking_promise_phrasing")
    return flags


def _curated_fb(ao: dict) -> str:
    """Curated fact-base JSON for the prompt: the persisted decide-pass
    fact_base if present, else built fresh ($0, pure)."""
    fb = ao.get("fact_base")
    if not isinstance(fb, dict) or not fb:
        from report.fact_base import build_fact_base
        fb = build_fact_base(ao)
    return json.dumps(fb, ensure_ascii=False, default=str)[:_MAX_FB_CHARS]


def _build_prompt(client_fb_json: str, peer_blocks: list[tuple[str, str]]) -> str:
    peers_txt = "\n\n".join(
        "--- SUCCESSFUL COMPETITOR %d (%s) ---\n%s" % (i + 1, url, fbj)
        for i, (url, fbj) in enumerate(peer_blocks))
    return ("[TARGET HIDDEN DATA]\n%s\n\n"
            "[SUCCESSFUL COMPETITORS' HIDDEN DATA FROM MEMORY]\n%s\n\n%s"
            % (client_fb_json, peers_txt, _INSTRUCTION))


async def build_peer_verdict(client_ao: dict, success_peers: list[dict],
                             db, model_id: str = MODEL_DEFAULT) -> dict:
    """Returns {text_en, text_hu, model_id, cost_usd, latency_s, peers_used,
    drift_flags, note, _error}. Never raises. Empty dict semantics:
    text_en None + note None + _error None → caller omits §9."""
    out = {"text_en": None, "text_hu": None, "model_id": model_id,
           "cost_usd": 0.0, "latency_s": None, "peers_used": [],
           "drift_flags": [], "note": None, "_error": None}
    peers = [p for p in (success_peers or []) if isinstance(p, dict) and p.get("doc_id")]
    if len(peers) == 0:
        return out  # omit §9 (no peers / retrieval error upstream)
    if len(peers) < 3:
        out["note"] = "insufficient_peers:%d" % len(peers)
        return out  # honest short note, no fabricated comparison
    try:
        import asyncio

        from google.genai import types

        from site_profile.gemini_analyzer import (
            compute_usage_cost_usd, make_genai_client)

        peer_blocks = []
        for p in peers[:3]:
            snap = await asyncio.to_thread(
                lambda pid=p["doc_id"]: db.collection("audits").document(pid).get())
            pao = (snap.to_dict() or {}).get("audit_output") or {}
            peer_blocks.append((p.get("url") or "?", _curated_fb(pao)))
        prompt = _build_prompt(_curated_fb(client_ao), peer_blocks)

        client = make_genai_client(location=LOCATION)
        t0 = time.time()

        def _call(extra: str = ""):
            return client.models.generate_content(
                model=model_id,
                contents=prompt + extra,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    temperature=0.2,
                    thinking_config=types.ThinkingConfig(
                        thinking_level=THINKING_LEVEL),
                ),
            )

        resp = await asyncio.to_thread(_call)
        text = (resp.text or "").strip()
        cost = compute_usage_cost_usd(resp.usage_metadata, model=model_id)
        flags = _drift_flags(text)
        if flags:  # one corrective retry, then flag honestly
            resp = await asyncio.to_thread(
                _call, "\n\nREMINDER: no snake_case internal field names and no "
                       "ranking promises in the output. Rewrite accordingly.")
            text2 = (resp.text or "").strip()
            cost += compute_usage_cost_usd(resp.usage_metadata, model=model_id)
            if text2:
                text = text2
            flags = _drift_flags(text)
        out["latency_s"] = round(time.time() - t0, 2)
        if not text:
            out["_error"] = "empty model response"
            out["cost_usd"] = round(cost, 6)
            return out
        out["text_en"] = text
        out["drift_flags"] = flags
        out["peers_used"] = [p.get("url") for p in peers[:3]]
        # HU via the established translation pass (Principle #3 two-pass).
        try:
            from page_analysis.translate_summary import translate_summary
            hu, _mv, tcost = await translate_summary(text, "en", "hu",
                                                     thinking_level="LOW")
            cost += tcost or 0.0
            if hu:
                out["text_hu"] = hu
        except Exception as e:  # noqa: BLE001 — HU is best-effort, EN canonical
            logger.warning("peer_verdict HU translate failed: %s", e)
        out["cost_usd"] = round(cost, 6)
        return out
    except Exception as e:  # noqa: BLE001 — never kill the pipeline
        out["_error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        return out
