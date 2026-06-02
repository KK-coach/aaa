"""Pydantic models for the Reverse Engineering Agent output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReverseEngineeringOutput(BaseModel):
    client_url: str
    target_country: str = ""
    primary_keyword: str = ""
    category_keyword: str = ""
    serps_identical: bool = False
    serp_result_branded: dict = Field(default_factory=dict)
    serp_result_category: dict = Field(default_factory=dict)
    serp_result: dict = Field(default_factory=dict)  # back-compat (= category)
    branded_competitors: list[str] = Field(default_factory=list)
    category_competitors: list[str] = Field(default_factory=list)
    competitor_urls: list[str] = Field(default_factory=list)
    client_ranking_status_branded: dict = Field(default_factory=dict)
    client_ranking_status_category: dict = Field(default_factory=dict)
    client_ranking_status: dict = Field(default_factory=dict)  # back-compat
    client_audit: dict = Field(default_factory=dict)
    competitor_audits: list[dict] = Field(default_factory=list)
    comparison: dict = Field(default_factory=dict)
    audit_metadata: dict = Field(default_factory=dict)
    summary_markdown: str = ""
    agent_summary_raw: str = ""
