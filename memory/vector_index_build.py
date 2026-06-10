"""AAA-202 Gate 1 S3 — Vertex AI Vector Search index over the audit corpus.

Approved config (Krisztián): 1 replica, NO multi-zone, Public Endpoint (no VPC),
europe-west3, smallest viable machine (e2-standard-2) — target ~$67/month.

Input: every archive doc with an EN-canonical summary, EXCLUDING
_en_canonical_failed docs. Off-type (gov) docs ARE embedded — the off-type rule
gates the SUCCESS label/filter, not index membership.

Embedding: gemini-embedding-001 (3072-dim, verified available europe-west3).
Datapoint restricts (for query-time filtering):
  numeric  serp_position  (success_serp_position; absent if None)
  category ai_cited       ("true"/"false")
  category language       (audit_language)
  category page_type
  category excluded       ("true"/"false")  — off-type success exclusion
  category url_norm       (normalized URL — query-time dedup)
Datapoint id = Firestore doc id (the payload pointer).
"""

from __future__ import annotations

import os
import time

REGION = "europe-west3"
EMBED_MODEL = "gemini-embedding-001"
DIMS = 3072
INDEX_DISPLAY = "aaa-success-corpus-v1"
ENDPOINT_DISPLAY = "aaa-success-corpus-ep-v1"
MACHINE = "e2-standard-2"          # smallest viable; ~$0.094/node-hr ≈ $68/mo
REPLICAS = 1


def _project():
    from site_profile.gemini_analyzer import _resolve_project
    return _resolve_project()


def load_eligible(db):
    """[(doc_id, summary_text, restricts_dict)] for all eligible docs."""
    out = []
    for d in db.collection("audits").stream():
        doc = d.to_dict() or {}
        ao = doc.get("audit_output") or {}
        if doc.get("_en_canonical_failed") or ao.get("_en_canonical_failed"):
            continue
        text = (ao.get("summary_markdown") or "").strip()
        if not text:
            continue
        out.append((d.id, text[:9000], {
            "serp_position": doc.get("success_serp_position"),
            "ai_cited": bool(doc.get("success_ai_cited")),
            "language": (doc.get("audit_language") or "en")[:2],
            "page_type": (ao.get("page_type") or "unknown"),
            "excluded": bool(doc.get("success_excluded")),
            "url_norm": doc.get("success_url_normalized") or "",
        }))
    return out


def embed_texts(texts, project):
    import vertexai
    from vertexai.language_models import TextEmbeddingModel
    vertexai.init(project=project, location=REGION)
    m = TextEmbeddingModel.from_pretrained(EMBED_MODEL)
    vecs = []
    B = 4  # small batches — long summaries
    for i in range(0, len(texts), B):
        for attempt in range(3):
            try:
                res = m.get_embeddings(texts[i:i + B])
                vecs.extend([e.values for e in res])
                break
            except Exception:  # noqa: BLE001 — transient quota/5xx
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
    return vecs


def to_datapoint(doc_id, vec, r):
    restricts = [
        {"namespace": "ai_cited", "allow_list": [str(r["ai_cited"]).lower()]},
        {"namespace": "language", "allow_list": [r["language"]]},
        {"namespace": "page_type", "allow_list": [r["page_type"]]},
        {"namespace": "excluded", "allow_list": [str(r["excluded"]).lower()]},
        {"namespace": "url_norm", "allow_list": [r["url_norm"][:120] or "none"]},
    ]
    numeric = []
    if isinstance(r["serp_position"], int):
        numeric.append({"namespace": "serp_position",
                        "value_int": r["serp_position"]})
    return {"datapoint_id": doc_id, "feature_vector": list(vec),
            "restricts": restricts, "numeric_restricts": numeric}


def build(db):
    from google.cloud import aiplatform
    project = _project()
    aiplatform.init(project=project, location=REGION)

    items = load_eligible(db)
    print(f"eligible docs: {len(items)}")
    vecs = embed_texts([t for _, t, _ in items], project)
    print(f"embedded: {len(vecs)} x {len(vecs[0])} dims")

    index = aiplatform.MatchingEngineIndex.create_tree_ah_index(
        display_name=INDEX_DISPLAY,
        dimensions=DIMS,
        approximate_neighbors_count=10,
        # explicit tree-AH algorithmConfig — required by the API ("algorithmConfig
        # is required but missing from the metadata" without these two).
        leaf_node_embedding_count=500,
        leaf_nodes_to_search_percent=10,
        distance_measure_type="COSINE_DISTANCE",
        index_update_method="STREAM_UPDATE",
        shard_size="SHARD_SIZE_SMALL",
    )
    print("index:", index.resource_name)

    dps = [to_datapoint(i, v, r) for (i, _, r), v in zip(items, vecs)]
    B = 100
    for j in range(0, len(dps), B):
        index.upsert_datapoints(datapoints=dps[j:j + B])
    print(f"upserted {len(dps)} datapoints")

    ep = aiplatform.MatchingEngineIndexEndpoint.create(
        display_name=ENDPOINT_DISPLAY, public_endpoint_enabled=True)
    print("endpoint:", ep.resource_name)
    ep.deploy_index(index=index, deployed_index_id="aaa_success_v1",
                    machine_type=MACHINE,
                    min_replica_count=REPLICAS, max_replica_count=REPLICAS)
    print("deployed: aaa_success_v1 on", MACHINE, "x", REPLICAS)
    return index.resource_name, ep.resource_name


if __name__ == "__main__":
    os.environ.setdefault("FIRESTORE_DATABASE", "ai-advisor-app")
    from google.cloud import firestore
    db = firestore.Client(project=_project(), database="ai-advisor-app")
    build(db)
