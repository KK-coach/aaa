"""Google PageSpeed Insights API client (free, ~25k calls/day).

Pure async utility — intended to be wired in as a Discovery-agent tool.
"""

from .client import get_pagespeed_score

__all__ = ["get_pagespeed_score"]
