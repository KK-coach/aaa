"""AAA-61 Sub-step 2 — industry classifier (LLM, single-shot).

One vertex_generate call (temperature=0, thinking_level=LOW) -> one enum
label from a 10-value starter set. Mirrors the AAA-55 page-type classifier
pattern exactly: bias-to-"other" on ANY parse/validation failure, so a
classifier failure can never write a confidently-wrong industry into the
archive. Cost is auto-accrued by vertex_generate into the shared _USAGE
accumulator; the caller (write_audit) isolates this call's delta into a
SEPARATE audit_industry_cost_usd (AAA-53 cost-separation pattern) — it is
NEVER folded into audit_cost_usd.

Classifies the SITE/BUSINESS, not the single page's form (that is
page_type's job). Grounded in site_profile + the audit summary excerpt.
"""

from __future__ import annotations

from site_profile.gemini_analyzer import _parse, vertex_generate

INDUSTRIES = (
    "ecommerce", "saas", "consulting", "blog", "service",
    "agricultural", "education", "media", "manufacturing", "other",
)

_PROMPT = """\
You classify ONE business/site into exactly one industry category:
[ecommerce, saas, consulting, blog, service, agricultural, education,
 media, manufacturing, other]

CLASSIFY THE BUSINESS, NOT THE PAGE FORM:
- Use ONLY the signals provided below. Do NOT use outside knowledge about
  the brand's reputation.
- Disambiguation guidance:
  - ecommerce = sells physical/digital goods via an online store/catalog.
  - saas = subscription software product / developer platform / cloud tool.
  - consulting = advisory/coaching/professional expertise sold as engagements.
  - service = local or operational services (not advisory consulting).
  - agricultural = farming, agri-machinery, agri-supply, agronomy.
  - blog = primarily editorial/personal content, no clear product/service
    monetization signal.
  - education = courses, training, academic institutions.
  - media = news/publishing/entertainment outlet.
  - manufacturing = produces physical goods (factory/industrial).
- If the signals are too thin or genuinely ambiguous, answer "other".

SITE SIGNALS:
Brand: {brand}
Self-described industry (free text): {industry}
Audience: {audience}
Key entities: {entities}
Audit summary excerpt:
{excerpt}

Return ONLY JSON: {{"industry": "<one category from the list>"}}
"""


def _join(v) -> str:
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v if x)[:400]
    return str(v or "")[:400]


async def classify_industry(
    site_profile: dict,
    summary_excerpt: str,
) -> tuple[str, str | None]:
    """Return (industry, _model_version). Failures -> ("other", mv|None)."""
    sp = site_profile or {}
    prompt = _PROMPT.format(
        brand=_join(sp.get("brand")),
        industry=_join(sp.get("industry")),
        audience=_join(sp.get("audience")),
        entities=_join(sp.get("main_entities")),
        excerpt=" ".join((summary_excerpt or "").split()[:400]) or "[none]",
    )
    text, model_version, err = await vertex_generate(
        prompt, temperature=0.0, thinking_level="LOW"
    )
    if err or not text:
        return "other", model_version
    try:
        data = _parse(text)
        ind = (data.get("industry") or "").strip().lower()
    except Exception:  # noqa: BLE001 - bias-to-other on any parse failure
        return "other", model_version
    if ind not in INDUSTRIES:
        return "other", model_version
    return ind, model_version
