"""Playwright proof-of-concept.

Standalone — NOT integrated with the crawler. Used only to compare what raw
HTML (httpx) sees versus what a JS-rendered browser sees.
"""

from .render import render_url

__all__ = ["render_url"]
