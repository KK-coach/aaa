"""AAA-61 Sub-step 1 — Firestore archive layer (source of truth).

The archive stores the FULL AuditOutput per audit so the memory layer is
forward-compatible: the Vertex RAG embedding index (AAA-60/AAA-3b) is
regenerable from this archive, so the embedding strategy can change without
rebuilding the source of truth (user's "store everything" principle).

Identity / region (verified by live probe, AAA-61 Gate-2):
  - Project: resolved via the codebase resolver `_resolve_project()`
    (env -> .env -> ADC quota_project). It yields the project STRING the
    current ADC credentials can actually reach. The numeric project number
    is NOT interchangeable here (returns 403 for these credentials).
  - Database: env `FIRESTORE_DATABASE`, default `ai-advisor-app`
    (multi-region `eur3`, Native mode). Explicit, never implicit
    `(default)` — and configurable for future dev/staging/prod splits.
  - Collection: `audits`; document id == `audit_id` (uuid4).

Error contract (mirrors the AAA-56 `_error` discipline):
  - write_audit: transient errors retried 3x with exponential backoff
    (1s, 2s, 4s). On exhaustion / fatal error: log + RAISE — the archive
    is the source of truth, a lost write must never be silent.
  - read_audit: NOT retried. Any failure (incl. not-found) -> return None.
  - update_validation: same write/backoff/raise contract as write_audit.

Firestore is schemaless; `AuditArchiveDocument` is the code-side contract
only. `update_validation` is the AAA-3c-reserved hook (functional now, but
the Validation UI that drives it lands later).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from google.api_core import exceptions as gexc
from google.cloud import firestore
from pydantic import BaseModel, Field

from discovery_agent.output_schema import AuditOutput
from page_analysis.industry_classify import classify_industry
from page_analysis.translate_summary import translate_summary
from page_analysis.language_detect import is_genuine_target_language
from site_profile.gemini_analyzer import _resolve_project, get_usage

_PHASE1_LANGS = ("hu", "en")

# AAA-130 S2 — language-contract enforcement constants (forward-config for the
# AAA-83 3.5 migration).
TRANSLATE_THINKING_LEVEL = "LOW"   # budget=0 breaks HU on 3.5 (33%); LOW fixes
EN_CANONICAL_ATTEMPTS = 3          # md->EN re-translate tries (1 + 2 retries)
HU_TRANSLATE_ATTEMPTS = 3          # en->hu tries; S0 sized ~5% residual -> 3
MIN_LEN_FOR_DENSITY = 300          # below this, density is noisy: skip density
#                                    check (verbatim check still applies)

logger = logging.getLogger(__name__)

_COLLECTION = "audits"
_DEFAULT_DATABASE = "ai-advisor-app"
# Bumped 2026-05-24 (AAA-108 Sub-step 2): added optional
# audit_output.re_findings sub-tree for the RE workflow's persisted state.
# Forward-compat marker only — no reader code branches on schema_version
# today; old docs (v1, re_findings absent) remain readable unchanged.
_SCHEMA_VERSION = 2
_BACKOFF_SECONDS = (1.0, 2.0, 4.0)  # 3 retries after the initial attempt

# Transient => safe to retry an idempotent set(). Anything else is fatal and
# re-raised immediately (NotFound, PermissionDenied, InvalidArgument, ...).
_TRANSIENT = (
    gexc.ServiceUnavailable,
    gexc.DeadlineExceeded,
    gexc.InternalServerError,
    gexc.Aborted,
    gexc.TooManyRequests,
)


# --------------------------------------------------------------------------- #
# Code-side contract (Firestore itself is schemaless)
# --------------------------------------------------------------------------- #
class UserValidation(BaseModel):
    # AAA-67 hybrid model: overall 1-10 + 5 dimensions 1-10 + notes.
    # `scores` is a dict {dim_key: {score:int, notes:str}} — extensible
    # via new keys with no schema migration (forward-compat, locked).
    validated_at: str | None = None
    overall_score: int | None = None
    overall_notes: str = ""
    overall_acceptance: str | None = None  # "kept" | "anomaly" | None
    scores: dict = Field(default_factory=dict)


class ArchiveMetadata(BaseModel):
    industry_llm: str | None = None      # Sub-step 2 — LLM industry verdict
    industry_llm_model_version: str | None = None  # audit trail
    industry_user: str | None = None     # human override, later
    page_type: str = "other"             # mirror of audit_output.page_type
    brand: str | None = None             # mirror site_profile.brand
    named_people: list = Field(default_factory=list)  # mirror eeat_signals


class AuditArchiveDocument(BaseModel):
    audit_id: str
    audit_url: str
    audit_date: str                      # ISO8601 + tz
    audit_language: str = "en"           # "hu" | "en"
    audit_output: dict = Field(default_factory=dict)  # full AuditOutput
    user_validation: UserValidation = Field(default_factory=UserValidation)
    metadata: ArchiveMetadata = Field(default_factory=ArchiveMetadata)
    audit_industry_cost_usd: float = 0.0  # AAA-53: SEPARATE, never in audit_cost_usd
    audit_translation_cost_usd: float = 0.0  # AAA-53: SEPARATE (Sub-step 3)
    audit_embedding_calls: int = 0       # Sub-step 4 (parallel to audit_kg_*)
    audit_embedding_cost_usd: float = 0.0  # free tier; SEPARATE field
    schema_version: int = _SCHEMA_VERSION
    created_at: str
    updated_at: str


# --------------------------------------------------------------------------- #
# Client (singleton; sync SDK driven off the event loop via to_thread)
# --------------------------------------------------------------------------- #
_client: firestore.Client | None = None


def _db() -> firestore.Client:
    global _client
    if _client is None:
        project = _resolve_project()
        database = os.environ.get("FIRESTORE_DATABASE", _DEFAULT_DATABASE)
        _client = firestore.Client(project=project, database=database)
        logger.info(
            "Firestore client init: project=%s database=%s",
            project, database,
        )
    return _client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_language(audit_output: dict) -> str:
    """Mirror site_profile.language, normalised to the hu/en contract."""
    lang = ((audit_output.get("site_profile") or {}).get("language") or "")
    lang = str(lang).strip().lower()[:2]
    return lang if lang in ("hu", "en") else "en"


def _write_with_retry(doc_ref, payload: dict, op: str) -> None:
    """Idempotent set() with 3x exponential backoff on transient errors.

    Sync (runs inside asyncio.to_thread). Fatal errors raise immediately;
    transient errors exhaust the backoff schedule then log + raise.
    """
    last: Exception | None = None
    for attempt in range(len(_BACKOFF_SECONDS) + 1):
        try:
            doc_ref.set(payload)
            return
        except _TRANSIENT as e:
            last = e
            if attempt < len(_BACKOFF_SECONDS):
                delay = _BACKOFF_SECONDS[attempt]
                logger.warning(
                    "Firestore %s transient error (attempt %d/%d): %s — "
                    "retrying in %.0fs",
                    op, attempt + 1, len(_BACKOFF_SECONDS) + 1,
                    type(e).__name__, delay,
                )
                import time
                time.sleep(delay)
            # else: fall through to raise below
        except Exception as e:  # fatal — do not retry
            logger.error("Firestore %s fatal error: %s: %s",
                         op, type(e).__name__, e)
            raise
    logger.error(
        "Firestore %s failed after %d attempts: %s",
        op, len(_BACKOFF_SECONDS) + 1,
        type(last).__name__ if last else "unknown",
    )
    raise last if last else RuntimeError(f"Firestore {op} failed")


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
async def _build_translations(
    summary_markdown: str,
    corpus_mode: bool = False,
) -> tuple[dict[str, str], float, str, dict]:
    """Every audit gets BOTH language entries, under the AAA-130 S2 Option-A
    language contract. Returns
        (translations_dict, total_cost_usd, summary_markdown_en, flags).

    AAA-61 S3 Issue B2 INTENT: the Discovery agent SHOULD always emit EN
    summary_markdown — but it intermittently emits non-EN (e.g. HU for HU
    sites, AAA-83 S2/S0). Storing that as ['en'] silently corrupts the
    canonical, and a budget=0 EN->HU translate can return EN verbatim.
    Contract (in order):

    1) EN-canonical guard: if summary_markdown is not genuine EN, re-translate
       it to EN (assume HU source — Phase-1 only non-EN we emit) with assert +
       retry. On failure -> keep best-effort text + flags['_en_canonical_failed'].
    2) ['en'] = identity copy of the (now EN-guaranteed) summary_markdown.
    3) ['hu'] = translate(md -> hu) on thinking_level=LOW, with a
       genuine-HU assert (verbatim / low_density -> retry), 3 attempts. Final
       failure -> OMIT the hu entry + flags['_translation_failed'] (silent
       EN-as-HU is worse than a missing entry the UI can fall back from).

    Min-length guard: summaries < MIN_LEN_FOR_DENSITY have noisy density, so
    the density check is skipped for them (verbatim check still applies).
    """
    flags: dict[str, bool] = {}
    md = summary_markdown or ""
    total_cost = 0.0
    md_short = len(md.strip()) < MIN_LEN_FOR_DENSITY

    # --- Step 1: EN-canonical guard ----------------------------------------
    # Short md: skip the guard (density noisy) — treat as genuine EN.
    if md.strip() and not md_short:
        en_chk = is_genuine_target_language(md, "en")
        if not en_chk["is_genuine"]:
            # Not genuine EN. Phase-1: the only non-EN we emit is HU — confirm
            # before assuming a source for the re-translate.
            looks_hu = is_genuine_target_language(md, "hu")["is_genuine"]
            fixed = None
            if looks_hu:
                for _ in range(EN_CANONICAL_ATTEMPTS):
                    cand, _mv, c = await translate_summary(
                        md, "hu", "en",
                        thinking_level=TRANSLATE_THINKING_LEVEL,
                    )
                    total_cost += c
                    if cand and is_genuine_target_language(
                        cand, "en", source_text=md
                    )["is_genuine"]:
                        fixed = cand
                        break
            if fixed:
                logger.info("EN-canonical guard: re-translated md -> EN")
                md = fixed
            else:
                logger.warning(
                    "EN-canonical guard FAILED (looks_hu=%s) — best-effort "
                    "md kept, _en_canonical_failed set", looks_hu,
                )
                flags["_en_canonical_failed"] = True

    # --- Step 2: ['en'] = identity copy of the EN-guaranteed md ------------
    translations: dict[str, str] = {"en": md}

    # --- Step 3: ['hu'] = translate(md -> hu) with assert + retry ----------
    # AAA-75 corpus_mode: competitor corpus entries are never customer-rendered,
    # so skip the HU pass entirely. EN-canonical (Steps 1-2) stays — it is the
    # embedding source and MUST be produced.
    if corpus_mode:
        flags["_hu_translate_attempts"] = 0
        flags["_corpus_mode_hu_skipped"] = True
        return translations, round(total_cost, 6), md, flags
    hu_out = None
    hu_attempts = 0
    if md.strip():
        for hu_attempts in range(1, HU_TRANSLATE_ATTEMPTS + 1):
            cand, _mv, c = await translate_summary(
                md, "en", "hu", thinking_level=TRANSLATE_THINKING_LEVEL
            )
            total_cost += c
            if not cand or not cand.strip():
                continue
            chk = is_genuine_target_language(cand, "hu", source_text=md)
            if md_short:
                # density noisy on short text: accept unless verbatim
                if chk["reason"] != "verbatim":
                    hu_out = cand
                    break
            elif chk["is_genuine"]:
                hu_out = cand
                break
    if hu_out is not None:
        translations["hu"] = hu_out
    else:
        logger.warning(
            "EN->HU translation not genuine after %d attempts — hu entry "
            "OMITTED, _translation_failed set", hu_attempts,
        )
        flags["_translation_failed"] = True

    flags["_hu_translate_attempts"] = hu_attempts
    return translations, round(total_cost, 6), md, flags


async def write_audit(audit_output: AuditOutput | dict, audit_url: str,
                      corpus_mode: bool = False,
                      audit_id: str | None = None) -> str:
    """Persist a full audit. Returns the archive audit_id.

    Write is critical (source of truth): on failure this RAISES after the
    backoff schedule is exhausted — never silent.

    AAA-31 Sub-step 2: when audit_id is provided (the dispatcher's Cloud Tasks
    job id) it is used as the archive document id so job_id == archive_id;
    otherwise a uuid4 is minted (the legacy default — keeps existing callers
    and tests unchanged).

    AAA-75: corpus_mode=True (competitor corpus-subset archive) keeps every
    corpus-critical step (industry, EN-canonical summary, embedding) but skips
    the HU translation pass (competitors are never customer-rendered).
    """
    ao: dict = (
        audit_output.model_dump()
        if isinstance(audit_output, BaseModel)
        else dict(audit_output or {})
    )
    audit_id = audit_id or str(uuid.uuid4())  # AAA-31 S2: honour caller-supplied id
    now = _now_iso()

    sp = ao.get("site_profile") or {}
    eeat = ao.get("eeat_signals") or {}

    # AAA-61 Sub-step 2: industry classification. Cost is isolated via the
    # _USAGE["cost"] accumulator delta and stored SEPARATELY
    # (audit_industry_cost_usd) — it is NEVER folded into audit_cost_usd
    # (already frozen upstream before write_audit is called). AAA-53 pattern.
    _cost_before = get_usage().get("cost", 0.0)
    industry_llm, industry_mv = await classify_industry(
        sp, ao.get("summary_markdown") or ""
    )
    audit_industry_cost_usd = round(
        get_usage().get("cost", 0.0) - _cost_before, 6
    )

    # AAA-61 Sub-step 3: EN->HU translation (source always EN, Issue B2).
    # Cost is SEPARATE (audit_translation_cost_usd), never in audit_cost_usd.
    # audit_language is the SITE's language (distinct from summary language),
    # still recorded on the doc below.
    audit_language = _audit_language(ao)
    # AAA-130 S2: enforce the language contract. _build_translations may
    # re-translate a non-EN summary_markdown to EN (canonical guard) and
    # returns the EN-guaranteed text + flags. Overwrite the canonical and
    # carry the flags onto the audit doc.
    (translations, audit_translation_cost_usd,
     summary_markdown_en, _tr_flags) = await _build_translations(
        ao.get("summary_markdown") or "", corpus_mode=corpus_mode
    )
    if _tr_flags.get("_corpus_mode_hu_skipped"):
        ao["_corpus_mode"] = True
    ao["summary_markdown"] = summary_markdown_en
    ao["summary_translations"] = translations
    if _tr_flags.get("_en_canonical_failed"):
        ao["_en_canonical_failed"] = True
    if _tr_flags.get("_translation_failed"):
        ao["_translation_failed"] = True
    ao["_hu_translate_attempts"] = _tr_flags.get("_hu_translate_attempts")

    doc = AuditArchiveDocument(
        audit_id=audit_id,
        audit_url=audit_url,
        audit_date=now,
        audit_language=audit_language,
        audit_output=ao,
        user_validation=UserValidation(),  # empty until AAA-3c
        metadata=ArchiveMetadata(
            industry_llm=industry_llm,
            industry_llm_model_version=industry_mv,
            industry_user=None,
            page_type=ao.get("page_type") or "other",
            brand=sp.get("brand"),
            named_people=eeat.get("named_people") or [],
        ),
        audit_industry_cost_usd=audit_industry_cost_usd,
        audit_translation_cost_usd=audit_translation_cost_usd,
        schema_version=_SCHEMA_VERSION,
        created_at=now,
        updated_at=now,
    )

    ref = _db().collection(_COLLECTION).document(audit_id)
    await asyncio.to_thread(
        _write_with_retry, ref, doc.model_dump(), "write_audit"
    )
    logger.info("Audit archived: %s (%s)", audit_id, audit_url)

    # AAA-61 Sub-step 4: embed EN canonical AFTER the archive write succeeds.
    # Embedding is non-critical: failure -> embedding_metadata._error set,
    # the audit still archives and can be re-backfilled later.
    try:
        from memory.embedding_layer import (
            embed_and_upload_audit, _embedding_metadata,
        )
        emb = await embed_and_upload_audit(audit_id, doc.model_dump())
        if emb.get("_error"):
            logger.warning(
                "embedding failed for %s: %s", audit_id, emb["_error"]
            )
        await asyncio.to_thread(ref.update, {
            "audit_output.embedding_metadata": _embedding_metadata(emb),
            "audit_embedding_calls": emb["audit_embedding_calls"],
            "audit_embedding_cost_usd": emb["audit_embedding_cost_usd"],
            "updated_at": _now_iso(),
        })
    except Exception as e:  # noqa: BLE001 - never fail the archive on embed
        logger.warning("embedding step skipped for %s: %s", audit_id, e)

    return audit_id


_LIST_FIELDS = (
    "audit_id", "audit_url", "audit_date",
    "metadata.brand", "metadata.industry_llm", "metadata.page_type",
    "user_validation.validated_at", "user_validation.overall_acceptance",
)


async def list_audits(
    filter_validated: bool | None = None,
    sort_by: str = "audit_date",
    descending: bool = True,
    limit: int | None = None,
) -> list[dict]:
    """Lightweight audit summaries for the AAA-67 admin UI — NOT the full
    audit_output (Firestore field projection keeps this bandwidth-light;
    AAA-66 Area 2 verified .select() with nested paths).

    filter_validated: None=all, True=validated_at set, False=unvalidated.
    Validated-filter + sort are applied client-side (no Firestore index
    needed; fine for an n<=few-hundred admin tool, no caching by design).
    """

    def _query() -> list[dict]:
        q = _db().collection(_COLLECTION).select(list(_LIST_FIELDS))
        out: list[dict] = []
        for snap in q.stream():
            d = snap.to_dict() or {}
            md = d.get("metadata") or {}
            uv = d.get("user_validation") or {}
            out.append({
                "audit_id": d.get("audit_id") or snap.id,
                "audit_url": d.get("audit_url"),
                "brand": md.get("brand"),
                "industry_llm": md.get("industry_llm"),
                "page_type": md.get("page_type"),
                "audit_date": d.get("audit_date"),
                "validated_at": uv.get("validated_at"),
                "overall_acceptance": uv.get("overall_acceptance"),
            })
        return out

    try:
        rows = await asyncio.to_thread(_query)
    except Exception as e:  # noqa: BLE001 — list is non-critical (read path)
        logger.warning(
            "Firestore list_audits failed: %s: %s", type(e).__name__, e
        )
        return []

    if filter_validated is True:
        rows = [r for r in rows if r["validated_at"] is not None]
    elif filter_validated is False:
        rows = [r for r in rows if r["validated_at"] is None]

    rows.sort(key=lambda r: (r.get(sort_by) is None, r.get(sort_by) or ""),
              reverse=descending)
    if limit is not None:
        rows = rows[:limit]
    return rows


def list_audits_sync(**kwargs) -> list[dict]:
    """Synchronous wrapper for Streamlit (AAA-66 Area 4: no running loop in
    Streamlit's main thread -> asyncio.run() is safe)."""
    return asyncio.run(list_audits(**kwargs))


def read_audit_sync(audit_id: str) -> dict | None:
    """Sync wrapper (Streamlit) — Sub-step 2/3 detail view."""
    return asyncio.run(read_audit(audit_id))


def update_validation_sync(audit_id: str, validation: dict) -> bool:
    """Sync wrapper (Streamlit) — Sub-step 3 score write. Returns True on
    success, False on failure (UI shows st.error instead of crashing; the
    underlying critical-write contract still logs/raises internally)."""
    try:
        asyncio.run(update_validation(audit_id, validation))
        return True
    except Exception as e:  # noqa: BLE001 - surface failure to the UI
        logger.error("update_validation_sync failed: %s: %s",
                     type(e).__name__, e)
        return False


async def read_audit(audit_id: str) -> dict | None:
    """Fetch an archived audit. NOT retried — any failure -> None."""
    try:
        ref = _db().collection(_COLLECTION).document(audit_id)
        snap = await asyncio.to_thread(ref.get)
        if not snap.exists:
            return None
        return snap.to_dict()
    except Exception as e:  # noqa: BLE001 — read is non-critical by contract
        logger.warning(
            "Firestore read_audit(%s) failed: %s: %s",
            audit_id, type(e).__name__, e,
        )
        return None


async def backfill_industry(audit_id: str) -> tuple[str, str | None, float]:
    """AAA-61 Sub-step 2 — add industry_llm to an EXISTING archived doc.

    Uses Firestore update() with dotted field paths so ONLY the new leaf
    fields are written — the existing doc is not re-archived (validates the
    schema-flexibility principle). Returns (industry, model_version, cost).
    """
    existing = await read_audit(audit_id)
    if existing is None:
        raise RuntimeError(f"backfill_industry: {audit_id} not found")
    ao = existing.get("audit_output") or {}
    sp = ao.get("site_profile") or {}

    cost_before = get_usage().get("cost", 0.0)
    industry_llm, industry_mv = await classify_industry(
        sp, ao.get("summary_markdown") or ""
    )
    cost = round(get_usage().get("cost", 0.0) - cost_before, 6)

    now = _now_iso()
    patch = {
        "metadata.industry_llm": industry_llm,
        "metadata.industry_llm_model_version": industry_mv,
        "audit_industry_cost_usd": cost,
        "updated_at": now,
    }
    ref = _db().collection(_COLLECTION).document(audit_id)
    await asyncio.to_thread(ref.update, patch)
    logger.info("Industry backfilled: %s -> %s", audit_id, industry_llm)
    return industry_llm, industry_mv, cost


async def backfill_translations(audit_id: str) -> dict:
    """AAA-61 Sub-step 3 — add summary_translations to an EXISTING doc.

    Firestore update() with dotted paths writes ONLY the new leaves
    (audit_output.summary_translations + audit_translation_cost_usd +
    updated_at). summary_markdown and every other field are untouched —
    validates schema-flexibility / no re-archive.
    """
    existing = await read_audit(audit_id)
    if existing is None:
        raise RuntimeError(f"backfill_translations: {audit_id} not found")
    ao = existing.get("audit_output") or {}
    summary = ao.get("summary_markdown") or ""
    audit_language = _audit_language(ao)  # site language (for return only)

    translations, cost, summary_markdown_en, _tr_flags = (
        await _build_translations(summary)
    )

    now = _now_iso()
    patch = {
        # AAA-130 S2: also persist the EN-canonical-guarded markdown + flags so
        # the backfill retroactively hardens existing docs, not just new ones.
        "audit_output.summary_markdown": summary_markdown_en,
        "audit_output.summary_translations": translations,
        "audit_translation_cost_usd": cost,
        "updated_at": now,
    }
    if _tr_flags.get("_en_canonical_failed"):
        patch["audit_output._en_canonical_failed"] = True
    if _tr_flags.get("_translation_failed"):
        patch["audit_output._translation_failed"] = True
    ref = _db().collection(_COLLECTION).document(audit_id)
    await asyncio.to_thread(ref.update, patch)
    logger.info(
        "Translations backfilled: %s (langs=%s, cost=%.6f)",
        audit_id, sorted(translations), cost,
    )
    return {
        "audit_id": audit_id,
        "audit_language": audit_language,
        "langs": sorted(translations),
        "cost": cost,
    }


async def attach_customer_summary(audit_id: str) -> dict:
    """AAA-96 ship — render the customer-facing bilingual report and attach it as
    audit_output.customer_summary_translations = {"en": <canonical>, "hu": <translation>}.

    Runs AFTER re_findings is persisted (the comparison sections depend on it), so
    the right call site is the end of the RE flow. Dotted-path update() touches only
    the new leaves (customer_summary_translations + audit_customer_summary_cost_usd +
    updated_at) — every other field is untouched (schema-additive, no re-archive).

    Skip-finding contract: any error -> {"_error": ...} + a persisted
    audit_output._customer_summary_failed flag; NEVER raises (the audit/RE flow
    continues regardless)."""
    try:
        existing = await read_audit(audit_id)
        if existing is None:
            return {"_error": "audit not found"}
        ao = existing.get("audit_output") or {}
        from report.customer_render import build_customer_summary_translations
        res = await asyncio.to_thread(build_customer_summary_translations, ao)
        now = _now_iso()
        ref = _db().collection(_COLLECTION).document(audit_id)
        if res.get("_error"):
            await asyncio.to_thread(ref.update, {
                "audit_output._customer_summary_failed": True,
                "updated_at": now,
            })
            logger.warning("customer_summary skip-finding %s: %s", audit_id, res["_error"])
            return res
        await asyncio.to_thread(ref.update, {
            "audit_output.customer_summary_translations": {"en": res["en"], "hu": res["hu"]},
            "audit_output.audit_customer_summary_cost_usd": res.get("cost_usd", 0.0),
            "updated_at": now,
        })
        logger.info("customer_summary attached: %s (cost=%.5f)", audit_id, res.get("cost_usd", 0.0))
        return {"ok": True, "cost": res.get("cost_usd", 0.0),
                "en_chars": len(res["en"]), "hu_chars": len(res["hu"])}
    except Exception as e:  # noqa: BLE001 — skip-finding (never break the audit)
        logger.warning("attach_customer_summary(%s) failed: %s: %s",
                       audit_id, type(e).__name__, e)
        return {"_error": "%s: %s" % (type(e).__name__, e)}


async def update_validation(audit_id: str, validation: dict) -> None:
    """Attach/replace human validation on an archived audit (AAA-67).

    `validation` = {overall_score, overall_notes, overall_acceptance,
    scores}. Same write/backoff/raise contract as write_audit.

    Uses ref.update() with the WHOLE user_validation map (not
    set(merge=True)): merge deep-merges nested maps, which would leave
    stale dimension scores when Edit-after-"kept" submits Anomaly
    (scores={}). update() replaces the field cleanly and still touches no
    other doc field (update-safe).
    """
    v = validation or {}
    now = _now_iso()
    patch = {
        "user_validation": UserValidation(
            validated_at=now,
            overall_score=v.get("overall_score"),
            overall_notes=v.get("overall_notes") or "",
            overall_acceptance=v.get("overall_acceptance"),
            scores=v.get("scores") or {},
        ).model_dump(),
        "updated_at": now,
    }
    ref = _db().collection(_COLLECTION).document(audit_id)

    def _merge() -> None:
        ref.update(patch)

    last: Exception | None = None
    for attempt in range(len(_BACKOFF_SECONDS) + 1):
        try:
            await asyncio.to_thread(_merge)
            logger.info("Validation updated: %s", audit_id)
            return
        except _TRANSIENT as e:
            last = e
            if attempt < len(_BACKOFF_SECONDS):
                await asyncio.sleep(_BACKOFF_SECONDS[attempt])
        except Exception as e:
            logger.error("Firestore update_validation fatal: %s: %s",
                         type(e).__name__, e)
            raise
    logger.error("Firestore update_validation failed after retries")
    raise last if last else RuntimeError("update_validation failed")
