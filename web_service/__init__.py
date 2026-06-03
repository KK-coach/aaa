"""AAA-97 — public serving service (FastAPI). Serves the customer report HTML
from the non-public reports bucket at /report/{audit_id}?lang=<lang>, reading the
audit doc's customer_report_html_uri from Firestore. Internet-facing front door;
deliberately lean (firestore + storage only — NOT the audit-pipeline imports)."""
