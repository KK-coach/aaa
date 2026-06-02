"""AAA-56 Sub-step 4 — deterministic E-E-A-T finding generation.

Pure code. NO LLM, NO judgment. Only fixed-template interpolation of
{name}, {role_label}, {description}, {page_type}. 10 KG-based + 3 standalone
templates (Phase-1 ceiling).

Hard contract (Gate 2): a kg_result whose `_error` is not None yields ZERO
findings for that candidate — an API error is NOT evidence of absence, so we
never fabricate a "not in KG" weakness from a failed lookup.

team_member is strengths-only (high/medium): a team/about page naming N
people should not emit N-1 "not in KG" weaknesses (most employees aren't in
KG) — that is the AAA-55-class multi-flag noise this system exists to remove.
author keeps full coverage (singular content-authority signal).

Ticket B (hypothesis, watch): suffix-stripping for brand-title bleed (e.g.
"Shoprenter Blog") is unproven — the Shoprenter case measured a TRUE
no_match even when cleaned to "Shoprenter", not a suffix artifact. File only
if a genuine suffix-bleed false-negative is later observed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from page_analysis.select_validation_entities import ValidationCandidate

# --- Person templates (role in {author, team_member}; role_label varies) ---
_PERSON_HIGH = (
    '{role_label} **{name}** is recognized by Google Knowledge Graph — '
    'described there as "{description}" — with established authority context '
    "(Wikipedia-backed). This is a strong E-E-A-T signal."
)
_PERSON_MEDIUM = (
    '{role_label} **{name}** is recognized by Google Knowledge Graph — '
    'described there as "{description}". This supports content authority.'
)
_PERSON_STUB = (
    "{role_label} **{name}** exists in Google Knowledge Graph but without "
    "authority context (no description, no Wikipedia). Consider strengthening "
    "their authority signals: a detailed LinkedIn profile, author bio with "
    "credentials, schema:Person markup linking to authoritative external "
    "profiles, and ideally a Wikipedia article. The goal is to elevate from "
    "listing to recognized authority."
)
_PERSON_AMBIGUOUS = (
    "{role_label} **{name}** matches multiple stub entries in Google "
    "Knowledge Graph (common name, no clear authority context). Consider "
    "stronger disambiguation: schema:Person markup with unique identifiers "
    "(jobTitle, worksFor, sameAs links to verified profiles), distinctive "
    "professional positioning, or a Wikipedia article that anchors this "
    "specific person."
)
_PERSON_NO_MATCH = (
    "{role_label} **{name}** is not present in Google Knowledge Graph. Build "
    "foundational authorship signals: detailed author bio, LinkedIn profile, "
    "schema:Person markup, and external bylines on recognized publications. "
    "KG inclusion typically follows established authority elsewhere."
)

# --- Brand templates (role == brand) ---
_BRAND_HIGH = (
    'Brand **{name}** is recognized by Google Knowledge Graph — described '
    'there as "{description}" — with established authority context '
    "(Wikipedia-backed). This is a strong E-E-A-T signal."
)
_BRAND_MEDIUM = (
    'Brand **{name}** is recognized by Google Knowledge Graph — described '
    'there as "{description}". This supports brand authority.'
)
_BRAND_STUB = (
    "Brand **{name}** exists in Google Knowledge Graph but without authority "
    "context (no description, no Wikipedia). Consider writing a Wikipedia "
    "article about the brand, enriching schema:Organization markup with "
    "sameAs links to authoritative profiles (LinkedIn, Crunchbase, industry "
    "directories), and consistent brand mentions on recognized external "
    "sites. The goal is to elevate from listing to recognized authority."
)
_BRAND_AMBIGUOUS = (
    "Brand **{name}** matches multiple stub entries in Google Knowledge "
    "Graph (common name or term, no clear authority context). Consider "
    "stronger brand disambiguation: distinctive schema:Organization markup "
    "with unique identifiers (legalName, founder, foundingDate), consistent "
    "branded terminology across the site, and authoritative external "
    "references that anchor this specific entity."
)
_BRAND_NO_MATCH = (
    "Brand **{name}** is not present in Google Knowledge Graph. Build "
    "foundational brand presence: consistent schema:Organization markup, "
    "sameAs links across verified social profiles, branded mentions on "
    "recognized external sites, and a clear, unique brand identity. KG "
    "inclusion typically follows established presence."
)

# --- Standalone (KG-independent, page-type-gated) ---
_STANDALONE_NO_AUTHOR = (
    "This {page_type} has no identified author. Adding a clear byline (with "
    "author name in meta tags, schema:Person, visible byline on page) is a "
    "foundational content E-E-A-T improvement."
)
_STANDALONE_NO_TEAM = (
    "This about page does not name any team members or owner. Identifying "
    "key people (founder, leadership, key contributors) is a primary purpose "
    "of an about page and a strong E-E-A-T signal."
)
_STANDALONE_TEAM_ANOMALY = (
    "This appears to be a team page but no team members were detected. The "
    "extraction may have missed structured data — consider manual "
    "verification of the page content."
)

_ROLE_LABEL = {"author": "Author", "team_member": "Team member",
               "brand": "Brand"}
_PERSON_BY_CAT = {
    "high": (_PERSON_HIGH, "strength"),
    "medium": (_PERSON_MEDIUM, "strength"),
    "stub": (_PERSON_STUB, "weakness"),
    "ambiguous": (_PERSON_AMBIGUOUS, "weakness"),
    "no_match": (_PERSON_NO_MATCH, "weakness"),
}
_BRAND_BY_CAT = {
    "high": (_BRAND_HIGH, "strength"),
    "medium": (_BRAND_MEDIUM, "strength"),
    "stub": (_BRAND_STUB, "weakness"),
    "ambiguous": (_BRAND_AMBIGUOUS, "weakness"),
    "no_match": (_BRAND_NO_MATCH, "weakness"),
}
# team_member: strengths only — high/medium emit, everything else silent.
_TEAM_MEMBER_EMIT = {"high", "medium"}


@dataclass(frozen=True)
class Finding:
    type: Literal["strength", "weakness", "anomaly"]
    text: str
    entity: str | None  # candidate name; None for standalone
    role: str | None    # author/brand/team_member; None for standalone
    category: str | None  # KG category; None for standalone


def _humanize(page_type: str) -> str:
    return (page_type or "page").replace("_", " ")


def generate_eeat_findings(
    candidates: list[ValidationCandidate],
    kg_results: dict[str, dict],
    page_type: str,
    eeat_signals: dict,
) -> list[Finding]:
    findings: list[Finding] = []

    for c in candidates or []:
        kg = (kg_results or {}).get(c.name) or {}
        # Hard contract: API error -> NO finding for this candidate.
        if kg.get("_error") is not None:
            continue
        cat = kg.get("category")
        if cat is None:
            continue
        desc = kg.get("description")

        if c.role == "brand":
            tmpl, ftype = _BRAND_BY_CAT.get(cat, (None, None))
            if tmpl is None:
                continue
            findings.append(Finding(
                type=ftype,
                text=tmpl.format(name=c.name, description=desc),
                entity=c.name, role="brand", category=cat,
            ))
        elif c.role in ("author", "team_member"):
            if c.role == "team_member" and cat not in _TEAM_MEMBER_EMIT:
                continue  # team_member: strengths only, else silent
            tmpl, ftype = _PERSON_BY_CAT.get(cat, (None, None))
            if tmpl is None:
                continue
            findings.append(Finding(
                type=ftype,
                text=tmpl.format(
                    role_label=_ROLE_LABEL.get(c.role, c.role.title()),
                    name=c.name, description=desc,
                ),
                entity=c.name, role=c.role, category=cat,
            ))
        # other roles (e.g. reserved "founder") -> no template, skip

    # --- standalone, KG-independent, page-type-gated ---
    named = (eeat_signals or {}).get("named_people") or []
    if not named:
        if page_type in ("blog_post", "article"):
            findings.append(Finding(
                "weakness",
                _STANDALONE_NO_AUTHOR.format(page_type=_humanize(page_type)),
                None, None, None,
            ))
        elif page_type == "about_page":
            findings.append(Finding(
                "weakness", _STANDALONE_NO_TEAM, None, None, None))
        elif page_type == "team_page":
            findings.append(Finding(
                "anomaly", _STANDALONE_TEAM_ANOMALY, None, None, None))

    return findings
