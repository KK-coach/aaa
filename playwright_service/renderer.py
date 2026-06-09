"""Headless-Chromium rendering core (server-side).

This is the rendering logic formerly in ``playwright_poc/render.py`` (the
in-process POC), moved here verbatim in behaviour and renamed
``render_in_process``. It runs ONLY inside the Playwright microservice image
(the one place Chromium is bundled) and, as a local-dev convenience, as the
optional in-process fallback in ``playwright_poc.render.render_url`` when
``PLAYWRIGHT_URL`` is unset and a local browser happens to be installed.

The renderer is intentionally defensive: a flaky ``networkidle`` degrades to
usable DOM rather than failing the whole render, and ANY launch/navigation
failure is returned as ``{"url", "error", "error_type"}`` — it never raises.
"""

from __future__ import annotations

import re
import time

from selectolax.parser import HTMLParser

from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

# Realistic Chrome desktop UA — deliberately NOT a bot string, so sites serve
# the same markup a real user would get.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

VIEWPORT = {"width": 1920, "height": 1080}
TIMEOUT_MS = 30_000
VALID_WAIT = {"networkidle", "domcontentloaded", "load"}


def _words(text: str) -> int:
    return len(text.split())


def _dom_text(rendered_html: str) -> str:
    """All text in the rendered DOM, mirroring the crawler's visible_text.

    Same logic as crawler.crawl_html: parse the (post-JS) HTML, strip
    script/style/noscript, take body text, collapse whitespace. This is the
    apples-to-apples counterpart to httpx's content.visible_text.
    """
    tree = HTMLParser(rendered_html)
    for node in tree.css("script, style, noscript"):
        node.decompose()
    body = tree.css_first("body")
    text = (body.text(separator=" ", strip=True) if body else "") or ""
    return re.sub(r"\s+", " ", text).strip()


def _classify_error(exc: Exception) -> str:
    msg = str(exc)
    if isinstance(exc, PlaywrightTimeoutError):
        return "timeout"
    if "net::" in msg or "NS_ERROR" in msg or "ERR_" in msg:
        return "network_error"
    return "render_error"


# AAA-179: requested locale -> (BCP-47 context locale, Accept-Language header).
# Mirrors crawler.ACCEPT_LANGUAGE_BY_LOCALE; kept local to avoid the renderer
# microservice importing the crawler package.
_LOCALE_CTX = {
    "hu": ("hu-HU", "hu-HU,hu;q=0.9"),
    "en": ("en-US", "en-US,en;q=0.9"),
    "de": ("de-DE", "de-DE,de;q=0.9"),
    "es": ("es-ES", "es-ES,es;q=0.9"),
}


async def render_in_process(url: str, wait_for: str = "networkidle",
                            locale: str | None = None) -> dict:
    """Render a URL with Playwright Chromium headless and return structured data.

    ``wait_for`` is one of ``networkidle`` | ``domcontentloaded`` | ``load``.
    AAA-179: ``locale`` (e.g. 'hu') hard-sets the browser context locale +
    Accept-Language so the render fetch negotiates the right page language;
    unsupported/absent locale → omitted (site serves its own default). On
    failure returns ``{"url", "error", "error_type"}`` where ``error_type``
    is ``timeout`` | ``render_error`` | ``network_error``.
    """
    if wait_for not in VALID_WAIT:
        wait_for = "networkidle"

    ctx_kwargs = {"viewport": VIEWPORT, "user_agent": USER_AGENT}
    _lc = _LOCALE_CTX.get((locale or "").strip().lower().replace("_", "-").split("-")[0])
    if _lc:
        ctx_kwargs["locale"] = _lc[0]
        ctx_kwargs["extra_http_headers"] = {"Accept-Language": _lc[1]}

    start = time.perf_counter()
    browser = None
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(**ctx_kwargs)
            page = await context.new_page()
            page.set_default_timeout(TIMEOUT_MS)

            # Two-phase load: first reach a guaranteed state so we always get a
            # Response (status code) and a parseable DOM. Then *upgrade* to the
            # requested wait state. If the upgrade (commonly "networkidle" on
            # pages with long-poll/analytics sockets) times out, we keep the
            # DOM we already have instead of failing the whole render.
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=TIMEOUT_MS
            )
            effective_strategy = "domcontentloaded"

            if wait_for != "domcontentloaded":
                elapsed_ms = (time.perf_counter() - start) * 1000
                remaining = max(1000, TIMEOUT_MS - int(elapsed_ms))
                try:
                    await page.wait_for_load_state(wait_for, timeout=remaining)
                    effective_strategy = wait_for
                except PlaywrightTimeoutError:
                    # Degrade gracefully — keep the DOM we already have.
                    effective_strategy = f"domcontentloaded (fallback: {wait_for} timed out)"

            render_time_ms = int((time.perf_counter() - start) * 1000)

            final_url = page.url
            status_code = response.status if response is not None else 0

            rendered_html = await page.content()

            body = page.locator("body")
            if await body.count() > 0:
                visible_text = await body.inner_text()
            else:
                visible_text = await page.evaluate(
                    "() => document.documentElement.innerText || ''"
                )
            visible_text = re.sub(r"\s+", " ", visible_text or "").strip()

            dom_text = _dom_text(rendered_html)

            actual_ua = await page.evaluate("() => navigator.userAgent")

            await context.close()
            await browser.close()
            browser = None

            return {
                "url": final_url,
                "status_code": status_code,
                "render_time_ms": render_time_ms,
                "page_load_strategy": effective_strategy,
                "rendered_html_bytes": len(rendered_html.encode("utf-8")),
                "rendered_html": rendered_html,
                "visible_text": visible_text,
                "visible_text_chars": len(visible_text),
                "visible_text_words": _words(visible_text),
                "dom_text": dom_text,
                "dom_text_chars": len(dom_text),
                "dom_text_words": _words(dom_text),
                "viewport": dict(VIEWPORT),
                "user_agent": actual_ua or USER_AGENT,
            }

    except (PlaywrightTimeoutError, PlaywrightError, Exception) as exc:
        return {
            "url": url,
            "error": f"{type(exc).__name__}: {exc}".strip(),
            "error_type": _classify_error(exc),
        }
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
