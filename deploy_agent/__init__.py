"""AAA-31 — Agent-Runtime deploy dispatcher (front-door agent + job-state +
Cloud Tasks enqueue). The heavy ~20-min run_one runs in a SEPARATE worker
(Sub-step 2). This package builds the dispatcher only; it does NOT deploy."""
