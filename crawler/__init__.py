"""Independent SEO/GEO crawler utility.

Pure Python — no ADK imports. Intended to be called by multiple ADK agents.
"""

from .crawler import crawl_html

__all__ = ["crawl_html"]
