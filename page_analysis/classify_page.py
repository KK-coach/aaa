"""AAA-55 page-type classifier (LLM, single-shot, structure-not-reputation).

Replaces the 3a URL/schema heuristic. One vertex_generate call
(temperature=0, thinking_level=LOW) -> one enum label. Cost + _model_version
are tracked automatically via vertex_generate (AAA-50). Bias-to-"other":
any parse/validation failure returns "other", which keeps Rule B silent so
a classifier failure can never create a false absence finding.
"""

from __future__ import annotations

from site_profile.gemini_analyzer import _parse, vertex_generate

PAGE_TYPES = (
    "blog_post", "article", "news", "about_page", "team_page",
    "landing_page", "product_page", "category_page", "service_page",
    "contact_page", "other",
)

# NOTE: final line requests JSON (not a bare word) because vertex_generate
# hard-sets response_mime_type=application/json. Semantics unchanged.
_PROMPT = """\
You classify ONE web page into exactly one category:
[blog_post, article, news, about_page, team_page, landing_page,
 product_page, category_page, service_page, contact_page, other]

CLASSIFY BY STRUCTURE, NOT BY BRAND IDENTITY:
- The URL path and Title below ARE provided data - use them.
- "Prior knowledge" you must NOT use = facts about the company/product that
  are NOT in the data below (what the brand is famous for, what it sells).
  Classify the PAGE'S FORM, not the company's reputation.
- If main_content is under ~50 words AND the URL path gives no unambiguous
  structural cue (e.g. /blog/, /products/, /about), answer "other".
- Marketing copy without article narrative -> landing_page / product_page /
  service_page, NOT blog_post/article.
- news = has an explicit publication date AND reports a time-bound event or
  announcement. article/blog_post = evergreen how-to/opinion/reference
  (blog_post = informal/blog-section; article = formal/editorial).

PAGE DATA:
URL: {url}
Title: {title}
H1: {h1}
Content excerpt (first 500 words of main_content):
{excerpt}

Return ONLY JSON: {{"page_type": "<one category from the list>"}}
"""


async def classify_page_type(
    url: str, title: str, h1: str, excerpt: str
) -> tuple[str, str | None]:
    """Return (page_type, _model_version). Failures -> ("other", mv|None)."""
    prompt = _PROMPT.format(
        url=url or "",
        title=(title or "")[:300],
        h1=(h1 or "")[:300],
        excerpt=" ".join((excerpt or "").split()[:500]) or "[none]",
    )
    text, model_version, err = await vertex_generate(
        prompt, temperature=0.0, thinking_level="LOW"
    )
    if err or not text:
        return "other", model_version
    try:
        data = _parse(text)
        pt = (data.get("page_type") or "").strip().lower()
    except Exception:  # noqa: BLE001 - bias-to-other on any parse failure
        return "other", model_version
    if pt not in PAGE_TYPES:
        return "other", model_version
    return pt, model_version
