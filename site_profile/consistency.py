"""Cross-signal consistency checks for site-level location detection.

v1 focuses on the most common real-world pattern: an "orphan" og:locale
(e.g. Yoast/WordPress auto-defaulting to en_GB) that no other country
signal supports. Such a signal should be treated as soft, not strong, and
surfaced as an actionable audit finding.
"""

from __future__ import annotations


def _phone_countries(loc: dict) -> list[str]:
    return [p["country"] for p in loc.get("phone_prefixes", []) or []]


def check_og_locale_consistency(loc: dict, gem: dict) -> dict | None:
    """Return an 'isolated og:locale' conflict dict, or None if consistent.

    og:locale is considered ISOLATED when it declares a country that ZERO
    other country signals (ccTLD, schema address, phone prefix, hreflang
    country, Gemini content read) corroborate.
    """
    og_country = loc.get("og_locale_country")
    if not og_country:
        return None

    gem_loc = gem.get("location") if gem.get("available") else None

    supporting = 0
    evidence_against: list[str] = []

    if loc.get("tld_country") == og_country:
        supporting += 1
    else:
        evidence_against.append(
            f"TLD '{loc.get('tld') or 'n/a'}' does not map to {og_country}"
        )

    if loc.get("schema_address_country") == og_country:
        supporting += 1
    else:
        evidence_against.append(
            f"no schema addressCountry for {og_country} "
            f"(found: {loc.get('schema_address_country') or 'none'})"
        )

    if og_country in _phone_countries(loc):
        supporting += 1
    else:
        evidence_against.append(
            f"no phone prefix indicating {og_country}"
        )

    if og_country in (loc.get("hreflang_countries") or []):
        supporting += 1
    else:
        evidence_against.append(
            f"no hreflang region variant for {og_country}"
        )

    if gem_loc == og_country:
        supporting += 1
    else:
        evidence_against.append(
            f"Gemini content read = {gem_loc or 'AMBIGUOUS'} (not {og_country})"
        )

    if supporting > 0:
        return None  # at least one corroborating signal -> not isolated

    return {
        "field": "og:locale",
        "declared": loc.get("og_locale") or og_country,
        "evidence_against": evidence_against,
        "severity": "medium",
        "recommendation": (
            f"Your og:locale tag declares {og_country} but no other country "
            f"signals (address, phone, hreflang, schema, content) support "
            f"this. This is often an automatic default (e.g. Yoast/WordPress "
            f"en_GB) that can misdirect search engines and AI systems. "
            f"Update og:locale to match your actual target market, or remove "
            f"it if you serve a global English audience."
        ),
    }


def build_signal_consistency(loc: dict, gem: dict) -> tuple[dict, bool]:
    """Return (signal_consistency_dict, og_locale_isolated_flag)."""
    conflicts = []
    og_conflict = check_og_locale_consistency(loc, gem)
    if og_conflict:
        conflicts.append(og_conflict)

    return (
        {
            "is_consistent": not conflicts,
            "conflicts": conflicts,
        },
        og_conflict is not None,
    )
