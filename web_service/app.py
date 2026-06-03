# -*- coding: utf-8 -*-
"""AAA-97 public serving service.

Routes:
  GET  /                     locale-aware audit input form (url + email)
  POST /submit               validate email + dispatch + lead capture (+ quota flag)
  GET  /report/{audit_id}    serve the rendered customer report from GCS
  GET  /health

Lean by design: reads/writes Firestore + GCS directly and reuses ONLY the lean
deploy_agent.tasks_enqueue.enqueue_audit_task (job-record creation is inlined to
avoid importing deploy_agent.job_state, which drags the heavy audit pipeline via
memory.firestore_archive). Runs as the aaa-web SA.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone

import tldextract
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, Response
from google.cloud import firestore, storage

DATABASE = os.environ.get("FIRESTORE_DATABASE", "ai-advisor-app")
COLLECTION = "audits"
JOBS_COLLECTION = "audit_jobs"
LEADS_COLLECTION = "leads"
SCHEMA_VERSION = 1

# Bundled public-suffix snapshot: suffix_list_urls=() => no network; cache_dir=None
# => no disk-cache write (the Cloud Run FS is read-only).
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
QUEUE_NAME = "audit-jobs"

# Free webmail providers (no company match possible) — rejected.
FREE_PROVIDERS = {
    "gmail.com", "googlemail.com", "freemail.hu", "citromail.hu", "yahoo.com",
    "yahoo.co.uk", "outlook.com", "hotmail.com", "live.com", "msn.com",
    "protonmail.com", "proton.me", "indamail.hu", "vipmail.hu", "icloud.com",
    "aol.com", "gmx.com", "gmx.net", "mail.com", "zoho.com", "yandex.com",
}
# Common disposable/throwaway providers (bundled minimal list) — rejected.
DISPOSABLE = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "temp-mail.org",
    "tempmail.com", "throwawaymail.com", "yopmail.com", "getnada.com",
    "trashmail.com", "sharklasers.com", "dispostable.com", "maildrop.cc",
    "fakeinbox.com", "mintemail.com", "mohmal.com", "spamgourmet.com",
    "tempinbox.com", "emailondeck.com", "tempmailo.com", "minuteinbox.com",
}

app = FastAPI(title="aaa-web", version="2")
_fs = None
_gcs = None


def _db() -> firestore.Client:
    global _fs
    if _fs is None:
        _fs = firestore.Client(database=DATABASE)
    return _fs


def _storage() -> storage.Client:
    global _gcs
    if _gcs is None:
        _gcs = storage.Client()
    return _gcs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# i18n string table (mirrors the report-chrome minimal style)
# --------------------------------------------------------------------------
STR = {
    "en": {
        "title": "Free SEO / AI-Visibility Audit",
        "intro": "Get a free audit of how your website performs in Google and AI search.",
        "url_label": "Your website URL",
        "email_label": "Your work email (must match the website domain)",
        "submit": "Start my audit",
        "err_email": "Please enter a valid email address.",
        "err_url": "Please enter a valid website URL.",
        "err_free": "Please use your company email — free webmail (Gmail, Outlook, …) and disposable addresses aren't accepted.",
        "err_mismatch": "Your email domain must match the website you're auditing (e.g. you@yourcompany.com for yourcompany.com).",
        "err_quota": "This company has already requested an audit. Please contact us if you need another.",
        "ok_title": "Audit started",
        "ok_msg": "Thanks! Your report is being generated (~15-20 minutes). It will be available here:",
        "ok_bookmark": "Bookmark this page and revisit the link — your report will appear automatically when it's ready.",
    },
    "hu": {
        "title": "Ingyenes SEO / AI-láthatósági audit",
        "intro": "Kérjen ingyenes elemzést arról, hogyan teljesít weboldala a Google és az AI-keresőkben.",
        "url_label": "Az Ön weboldalának URL-je",
        "email_label": "Céges e-mail címe (egyeznie kell a weboldal domainjével)",
        "submit": "Audit indítása",
        "err_email": "Kérjük, adjon meg egy érvényes e-mail címet.",
        "err_url": "Kérjük, adjon meg egy érvényes weboldal URL-t.",
        "err_free": "Kérjük, céges e-mail címet használjon — ingyenes (Gmail, Outlook, …) és eldobható címeket nem fogadunk el.",
        "err_mismatch": "Az e-mail domainjének egyeznie kell az auditált weboldaléval (pl. on@oncege.hu az oncege.hu-hoz).",
        "err_quota": "Ehhez a céghez már indult audit. Ha újabbra van szüksége, vegye fel velünk a kapcsolatot.",
        "ok_title": "Az audit elindult",
        "ok_msg": "Köszönjük! A jelentése készül (~15-20 perc). Itt lesz elérhető:",
        "ok_bookmark": "Mentse el ezt az oldalt, és térjen vissza a linkre — a jelentés automatikusan megjelenik, amint elkészül.",
    },
}


def _pick_locale(accept_language: str | None) -> str:
    """hu if the Accept-Language is hu-leaning, else en (en default)."""
    al = (accept_language or "").lower()
    return "hu" if "hu" in al else "en"


def _etld1(s: str) -> str:
    """eTLD+1 (registrable domain) of a URL or bare domain, lowercased; '' if none."""
    try:
        return (_EXTRACT(s or "").registered_domain or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if u and not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
_SHELL = (
    "<!doctype html><html lang=\"%s\"><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
    "<title>%s</title><style>"
    "body{font:16px/1.5 system-ui,Segoe UI,Arial,sans-serif;background:#f6f8fc;color:#1f2733;"
    "margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:20px}"
    ".box{background:#fff;border:1px solid #e3e8f0;border-radius:14px;padding:34px 38px;max-width:480px;"
    "width:100%%;box-shadow:0 1px 3px rgba(0,0,0,.06)}h1{font-size:22px;margin:0 0 6px}"
    "p.intro{color:#566;margin:0 0 22px}label{display:block;font-size:14px;font-weight:600;margin:14px 0 4px}"
    "input{width:100%%;box-sizing:border-box;padding:11px 12px;border:1px solid #cdd6e4;border-radius:8px;font:inherit}"
    "button{margin-top:20px;width:100%%;padding:12px;border:0;border-radius:8px;background:#2c6cf0;color:#fff;"
    "font:inherit;font-weight:600;cursor:pointer}button:hover{background:#1f5be0}"
    ".err{background:#fdecec;border:1px solid #f5c2c2;color:#a12;padding:10px 12px;border-radius:8px;margin:0 0 8px;font-size:14px}"
    ".ok{color:#566}</style></head><body><div class=\"box\">%s</div></body></html>"
)


def _form_page(lang: str, err: str = "", url: str = "", email: str = "", status: int = 200) -> HTMLResponse:
    t = STR[lang]
    err_html = ('<div class="err">%s</div>' % _esc(err)) if err else ""
    body = (
        "<h1>%s</h1><p class=\"intro\">%s</p>%s"
        "<form method=\"post\" action=\"/submit\">"
        "<label>%s</label><input name=\"url\" type=\"text\" value=\"%s\" placeholder=\"https://...\" required>"
        "<label>%s</label><input name=\"email\" type=\"email\" value=\"%s\" required>"
        "<button type=\"submit\">%s</button></form>" % (
            _esc(t["title"]), _esc(t["intro"]), err_html, _esc(t["url_label"]),
            _esc(url), _esc(t["email_label"]), _esc(email), _esc(t["submit"]))
    )
    return HTMLResponse(_SHELL % (lang, _esc(t["title"]), body), status_code=status)


def _confirm_page(lang: str, report_link: str) -> HTMLResponse:
    t = STR[lang]
    body = (
        "<h1>%s</h1><p class=\"ok\">%s</p>"
        "<p><a href=\"%s\">%s</a></p>"
        "<p class=\"ok\">%s</p>" % (
            _esc(t["ok_title"]), _esc(t["ok_msg"]),
            _esc(report_link), _esc(report_link), _esc(t["ok_bookmark"]))
    )
    return HTMLResponse(_SHELL % (lang, _esc(t["ok_title"]), body), status_code=200)


def _base_url(request: Request) -> str:
    """Absolute origin for building the bookmarkable report link. PUBLIC_BASE_URL
    env wins (deterministic behind Cloud Run's proxy); else the request origin."""
    return os.environ.get("PUBLIC_BASE_URL") or str(request.base_url).rstrip("/")


def _msg_page(title: str, message: str, status: int, lang: str = "en") -> HTMLResponse:
    body = "<h1>%s</h1><p class=\"ok\">%s</p>" % (_esc(title), _esc(message))
    return HTMLResponse(_SHELL % (lang, _esc(title), body), status_code=status)


# Localized /report status pages (pending / not-found / error).
REP = {
    "en": {
        "pending_t": "Report not available yet",
        "pending_m": "Your report is still being prepared (~15-20 minutes). Please check back shortly.",
        "notfound_t": "Report not found",
        "notfound_m": "We couldn't find a report for this link. Please check the URL.",
        "error_t": "Something went wrong",
        "error_m": "We could not load this report right now. Please try again later.",
    },
    "hu": {
        "pending_t": "A jelentés még készül",
        "pending_m": "A jelentése még készül (~15-20 perc). Kérjük, nézzen vissza hamarosan.",
        "notfound_t": "A jelentés nem található",
        "notfound_m": "Ehhez a linkhez nem találtunk jelentést. Kérjük, ellenőrizze az URL-t.",
        "error_t": "Hiba történt",
        "error_m": "A jelentést most nem tudtuk betölteni. Kérjük, próbálja újra később.",
    },
}


def _status_page(lang: str, kind: str, status: int) -> HTMLResponse:
    r = REP["hu"] if lang == "hu" else REP["en"]
    return _msg_page(r[kind + "_t"], r[kind + "_m"], status, lang="hu" if lang == "hu" else "en")


def _esc(x) -> str:
    import html
    return html.escape("" if x is None else str(x))


# --------------------------------------------------------------------------
# lean dispatch helpers (inlined create_job; reused enqueue_audit_task)
# --------------------------------------------------------------------------
def _create_job(url: str, locale: str, email: str | None) -> str:
    """Lean inline equivalent of deploy_agent.job_state.create_job (same schema),
    avoiding the heavy firestore_archive import in this public image."""
    aid = str(uuid.uuid4())
    now = _now()
    _db().collection(JOBS_COLLECTION).document(aid).set({
        "audit_id": aid, "url": url, "status": "queued", "locale": locale,
        "requester_email": email, "report_uri": None, "submitted_at": now,
        "started_at": None, "finished_at": None, "error": None,
        "schema_version": SCHEMA_VERSION,
    })
    return aid


def _project() -> str:
    p = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if p:
        return p
    import google.auth
    return google.auth.default()[1]


def _enqueue_audit_task(audit_id: str, url: str, locale: str, email: str | None) -> None:
    """Lean inline equivalent of deploy_agent.tasks_enqueue.enqueue_audit_task
    (the self-contained web image does not bundle deploy_agent). Creates the
    worker HTTP task: POST <WORKER_URL>/run with OIDC (SA=WORKER_INVOKER_SA,
    audience=worker base) on the audit-jobs queue."""
    from google.cloud import tasks_v2
    location = os.environ.get("CLOUD_TASKS_LOCATION", "europe-west3")
    base = (os.environ.get("WORKER_URL", "")).rstrip("/")
    invoker = os.environ.get("WORKER_INVOKER_SA", "")
    cl = tasks_v2.CloudTasksClient()
    queue_path = cl.queue_path(_project(), location, QUEUE_NAME)
    payload = {"audit_id": audit_id, "url": url, "locale": locale, "email": email}
    task = {"http_request": {
        "http_method": tasks_v2.HttpMethod.POST,
        "url": base + "/run",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload).encode("utf-8"),
        "oidc_token": {"service_account_email": invoker, "audience": base},
    }}
    cl.create_task(parent=queue_path, task=task)


def _enforce_one_per_company() -> bool:
    """config/global.enforce_one_per_company — default False if doc/field absent."""
    try:
        snap = _db().collection("config").document("global").get()
        return bool((snap.to_dict() or {}).get("enforce_one_per_company")) if snap.exists else False
    except Exception:  # noqa: BLE001 — fail open (do not block on config read error)
        return False


def _company_exists(etld1: str) -> bool:
    return _db().collection(LEADS_COLLECTION).document(etld1).get().exists


def _capture_lead(etld1: str, entry: dict) -> None:
    """Append the submission to leads/{etld1}.audits[] (create doc if absent;
    keep company_domain + first_seen stable)."""
    ref = _db().collection(LEADS_COLLECTION).document(etld1)
    snap = ref.get()
    if snap.exists:
        ref.update({"audits": firestore.ArrayUnion([entry])})
    else:
        ref.set({"company_domain": etld1, "first_seen": entry.get("submitted_at"),
                 "audits": [entry]})


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Response:
    return _form_page(_pick_locale(request.headers.get("accept-language")))


@app.post("/submit", response_class=HTMLResponse)
def submit(request: Request, url: str = Form(""), email: str = Form("")) -> Response:
    lang = _pick_locale(request.headers.get("accept-language"))
    t = STR[lang]
    url_raw, email = (url or "").strip(), (email or "").strip().lower()

    # (b) validation
    if not _EMAIL_RE.match(email):
        return _form_page(lang, t["err_email"], url_raw, email, status=400)
    url_norm = _normalize_url(url_raw)
    url_etld1 = _etld1(url_norm)
    if not url_etld1:
        return _form_page(lang, t["err_url"], url_raw, email, status=400)
    email_domain = email.rsplit("@", 1)[-1]
    if email_domain in FREE_PROVIDERS or email_domain in DISPOSABLE:
        return _form_page(lang, t["err_free"], url_raw, email, status=400)
    if _etld1(email_domain) != url_etld1:
        return _form_page(lang, t["err_mismatch"], url_raw, email, status=400)

    # (c) quota check (flag-gated; default OFF)
    if _enforce_one_per_company() and _company_exists(url_etld1):
        return _form_page(lang, t["err_quota"], url_raw, email, status=409)

    # (d) dispatch — inline job-record + reused enqueue
    audit_id = _create_job(url_norm, lang, email)
    try:
        _enqueue_audit_task(audit_id, url_norm, lang, email)
    except Exception as e:  # noqa: BLE001 — surface as job error, still show friendly page
        try:
            _db().collection(JOBS_COLLECTION).document(audit_id).update(
                {"status": "error", "error": "enqueue failed: %s: %s" % (type(e).__name__, e)})
        except Exception:  # noqa: BLE001
            pass

    # (e) lead capture
    try:
        _capture_lead(url_etld1, {
            "audit_id": audit_id, "url": url_norm, "email": email, "lang": lang,
            "browser_locale": request.headers.get("accept-language") or "",
            "user_agent": request.headers.get("user-agent") or "", "submitted_at": _now(),
        })
    except Exception:  # noqa: BLE001 — lead capture is non-fatal to the dispatch
        pass

    # (f) confirmation — surface the bookmarkable report link (email is AAA-149).
    report_link = "%s/report/%s?lang=%s" % (_base_url(request), audit_id, lang)
    return _confirm_page(lang, report_link)


@app.get("/report/{audit_id}", response_class=HTMLResponse)
def report(audit_id: str, lang: str = "") -> Response:
    try:
        snap = _db().collection(COLLECTION).document(audit_id).get()
    except Exception:  # noqa: BLE001
        return _status_page(lang, "error", 503)
    if not snap.exists:
        # The archived audit doc is written partway through the ~20-min run. If
        # it's not there yet, fall back to the job-state: a known job (queued/
        # running) -> friendly "still being prepared"; truly unknown -> 404.
        try:
            job = _db().collection(JOBS_COLLECTION).document(audit_id).get()
        except Exception:  # noqa: BLE001
            return _status_page(lang, "error", 503)
        if job.exists:
            return _status_page(lang, "pending", 200)
        return _status_page(lang, "notfound", 404)
    ao = (snap.to_dict() or {}).get("audit_output") or {}
    uri = ao.get("customer_report_html_uri")
    if ao.get("_customer_report_html_failed") is not None or not isinstance(uri, dict):
        return _status_page(lang, "pending", 200)
    objects = uri.get("objects") or {}
    chosen = lang if lang in objects else uri.get("default_lang")
    key = objects.get(chosen) if chosen else None
    if not key:
        return _status_page(lang, "pending", 200)
    try:
        data = _storage().bucket(uri.get("bucket")).blob(key).download_as_bytes()
    except Exception:  # noqa: BLE001
        return _status_page(lang, "error", 503)
    return Response(content=data, media_type="text/html; charset=utf-8")


if __name__ == "__main__":  # local dev only
    import uvicorn
    uvicorn.run("web_service.app:app", host="0.0.0.0", port=8080, reload=False)
