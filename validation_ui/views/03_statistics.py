"""AAA-204 S1 — Statisztikák page.

Headline tiles -> daily run chart -> language split -> filterable run table.
All aggregates + the table recompute from the SAME filtered row set (tiles
show the unfiltered total as a caption). Multi-dim fields missing on
pre-AAA-113 docs render and filter as an explicit "(not classified)" bucket
— no doc is excluded silently.
"""

import datetime

import pandas as pd
import streamlit as st

from validation_ui.lib.stats_loader import (
    load_job_status_counts,
    load_stats_rows,
)

NOT_CLASSIFIED = "(not classified)"

st.title("Statisztikák")

rows = load_stats_rows()
if not rows:
    st.warning("Nincs audit az archívumban.")
    st.stop()

df = pd.DataFrame(rows)
# explicit bucket for the pre-AAA-113 docs (33% of corpus) — filterable, never hidden
_DIM_COLS = ["language", "business_model", "page_type", "topic_domain",
             "locality", "audience_relationship_primary"]
for c in _DIM_COLS:
    df[c] = df[c].fillna(NOT_CLASSIFIED)
df["row_type"] = df["is_client"].map({True: "client", False: "competitor"})

# ---------------------------------------------------------------- filters
with st.expander("Szűrők", expanded=True):
    c1, c2, c3 = st.columns(3)
    f_lang = c1.multiselect("Nyelv (audit_language)", sorted(df["language"].unique()))
    f_bm = c2.multiselect("business_model", sorted(df["business_model"].unique()))
    f_pt = c3.multiselect("page_type", sorted(df["page_type"].unique()))
    c4, c5, c6 = st.columns(3)
    f_td = c4.multiselect("topic_domain", sorted(df["topic_domain"].unique()))
    f_loc = c5.multiselect("locality", sorted(df["locality"].unique()))
    f_ar = c6.multiselect("audience_relationship_primary",
                          sorted(df["audience_relationship_primary"].unique()))
    c7, c8, c9 = st.columns(3)
    days = sorted(d for d in df["day"].unique() if d)
    d_min = datetime.date.fromisoformat(days[0])
    d_max = datetime.date.fromisoformat(days[-1])
    f_range = c7.date_input("Dátumtartomány", value=(d_min, d_max),
                            min_value=d_min, max_value=d_max)
    f_type = c8.multiselect("Sortípus", ["client", "competitor"])
    f_success = c9.multiselect(
        "Siker-jelzők / validálás",
        ["SERP top-3 (success_serp_position ≤ 3)",
         "AI-cited (success_ai_cited)",
         "Validált", "Nem validált"])

flt = df
if f_lang:
    flt = flt[flt["language"].isin(f_lang)]
if f_bm:
    flt = flt[flt["business_model"].isin(f_bm)]
if f_pt:
    flt = flt[flt["page_type"].isin(f_pt)]
if f_td:
    flt = flt[flt["topic_domain"].isin(f_td)]
if f_loc:
    flt = flt[flt["locality"].isin(f_loc)]
if f_ar:
    flt = flt[flt["audience_relationship_primary"].isin(f_ar)]
if f_type:
    flt = flt[flt["row_type"].isin(f_type)]
if isinstance(f_range, tuple) and len(f_range) == 2:
    lo, hi = (f_range[0].isoformat(), f_range[1].isoformat())
    flt = flt[(flt["day"] >= lo) & (flt["day"] <= hi)]
if "SERP top-3 (success_serp_position ≤ 3)" in f_success:
    flt = flt[flt["success_serp_position"].apply(
        lambda v: v is not None and not pd.isna(v) and v <= 3)]
if "AI-cited (success_ai_cited)" in f_success:
    flt = flt[flt["success_ai_cited"] == True]  # noqa: E712 — NaN-safe mask
if "Validált" in f_success:
    flt = flt[flt["validated"]]
if "Nem validált" in f_success:
    flt = flt[~flt["validated"]]

# ------------------------------------------------------- headline tiles
# tiles recompute on filter; the unfiltered total stays visible as caption
def _tile(col, label, filtered_val, total_val):
    col.metric(label, filtered_val)
    col.caption(f"összes: {total_val}")


def _counts(frame: pd.DataFrame) -> dict:
    comp_ids = set()
    for ids in frame["competitor_audit_ids"]:
        comp_ids.update(ids)
    client_hosts = set(frame.loc[frame["is_client"], "host"].dropna())
    return {
        "runs": len(frame),
        "client_domains": len(client_hosts),
        "competitor_datasets": len(comp_ids),
        "domains": frame["host"].dropna().nunique(),
        "cost": frame["cost_usd"].sum(),
    }


tot, cur = _counts(df), _counts(flt)
t1, t2, t3, t4, t5 = st.columns(5)
_tile(t1, "Futások", cur["runs"], tot["runs"])
_tile(t2, "Ügyfél-domainek", cur["client_domains"], tot["client_domains"])
_tile(t3, "Versenytárs-adatkészletek", cur["competitor_datasets"],
      tot["competitor_datasets"])
_tile(t4, "Összes domain", cur["domains"], tot["domains"])
_tile(t5, "Σ költség (USD)", f"${cur['cost']:.2f}", f"${tot['cost']:.2f}")

jobs = load_job_status_counts()
st.caption("Web-beküldött futások (audit_jobs): "
           + (", ".join(f"{k}: {v}" for k, v in sorted(jobs.items())) or "—"))

# ------------------------------------------------------ daily run chart
st.subheader("Napi futások")
daily = flt.groupby("day").size().rename("futások")
st.bar_chart(daily)

# ------------------------------------------------------- language split
st.subheader("Nyelvi megoszlás")
lang_counts = flt.groupby("language").size().rename("audit")
lc1, lc2 = st.columns([1, 2])
lc1.dataframe(lang_counts)
lc2.bar_chart(lang_counts)

# ----------------------------------------------------------- run table
st.subheader(f"Futások ({len(flt)} sor, napi csoportosítás, legutóbbi elöl)")
table = flt.sort_values("audit_date", ascending=False)[[
    "day", "audit_date", "url", "report_url", "row_type", "language",
    "business_model", "page_type", "cost_usd",
]]
st.dataframe(
    table,
    hide_index=True,
    column_config={
        "day": st.column_config.TextColumn("Nap"),
        "audit_date": st.column_config.TextColumn("Időpont"),
        "url": st.column_config.TextColumn("Auditált URL", width="large"),
        # LinkColumn: None -> empty cell (no dead link is ever rendered)
        "report_url": st.column_config.LinkColumn(
            "Riport", display_text="riport →"),
        "row_type": st.column_config.TextColumn("Típus"),
        "language": st.column_config.TextColumn("Nyelv"),
        "business_model": st.column_config.TextColumn("business_model"),
        "page_type": st.column_config.TextColumn("page_type"),
        "cost_usd": st.column_config.NumberColumn("Költség", format="$%.4f"),
    },
)
