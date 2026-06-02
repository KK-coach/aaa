"""Site-level profile detection (locale + brand + entities + industry).

Foundation for AAA-17 (Discovery Agent) and AAA-20 (Reverse Engineering).
"""

from .profile import analyze_site_profile

__all__ = ["analyze_site_profile"]
