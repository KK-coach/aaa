"""AAA-56 Sub-step 3 — pick entities for KG validation.

Pure data -> candidates mapping (no KG calls here). Page-type-gated author/
team selection + always-on brand. Max 3 candidates.

Phase-1 minimum-viable. Known latent items deliberately NOT handled here
(logged as future tickets):
  - Ticket A: prefer byline sources over entities.people for role=author
    (named_people[0] trusts upstream ordering).
  - Ticket B: strip trailing "Blog"/"Shop"/"Home" from site_profile.brand.
"""

from __future__ import annotations

from dataclasses import dataclass

_PERSON_TYPES = ("Person", "Thing")
_BRAND_TYPES = ("Organization", "Corporation")
_AUTHOR_PAGE_TYPES = {"blog_post", "article"}
_TEAM_PAGE_TYPES = {"about_page", "team_page"}
_MAX_CANDIDATES = 3


@dataclass(frozen=True)
class ValidationCandidate:
    name: str
    expected_kg_types: tuple[str, ...]
    role: str  # "author" | "brand" | "team_member"  (founder reserved)


def select_entities_for_validation(
    eeat_signals: dict,
    page_type: str,
    site_profile: dict,
) -> list[ValidationCandidate]:
    eeat_signals = eeat_signals or {}
    site_profile = site_profile or {}
    named = [n for n in (eeat_signals.get("named_people") or []) if n]
    candidates: list[ValidationCandidate] = []

    # --- person selection, gated by page_type ---
    if page_type in _AUTHOR_PAGE_TYPES:
        if named:
            candidates.append(
                ValidationCandidate(named[0], _PERSON_TYPES, "author")
            )
    elif page_type in _TEAM_PAGE_TYPES:
        for person in named[:2]:
            candidates.append(
                ValidationCandidate(person, _PERSON_TYPES, "team_member")
            )
    # all other page_types: no person candidate (absence is not a deficit)

    # --- brand selection, always ---
    brand = site_profile.get("brand")
    if not brand:
        mentions = eeat_signals.get("brand_mentions") or []
        brand = mentions[0] if mentions else None
    if brand:
        candidates.append(
            ValidationCandidate(brand, _BRAND_TYPES, "brand")
        )

    return candidates[:_MAX_CANDIDATES]
