"""AAA-118 Sub-step 2.1 pre-flight: URL normalization unit-test probe.

4 spec'd test cases + cache-equivalence verification + edge-case handling.
Cost: $0 (no LLM calls).
"""
from page_analysis.serp_fit_classify import (
    _normalize_url_for_cache, _cache_key,
)

CASES = [
    ("https://webaruhaz.habi.hu/?srsltid=AAABCdefghij",
     "https://webaruhaz.habi.hu/"),
    ("https://example.com/path?utm_source=foo&id=42&utm_medium=bar",
     "https://example.com/path?id=42"),
    ("https://Example.com/Path?gclid=xyz#section",
     "https://example.com/Path"),
    ("https://kk.coach/services",
     "https://kk.coach/services"),
]

EDGE_CASES = [
    ("", ""),                                              # empty
    ("not-a-url", "not-a-url"),                            # malformed (no scheme)
    ("https://example.com", "https://example.com"),        # no path, no query
    ("https://example.com/?",                              # empty query
     "https://example.com/"),
    ("https://x.com/?utm_source=a&srsltid=b",              # all tracking
     "https://x.com/"),
    ("https://x.com/?b=2&a=1",                             # preserve order, NOT alphabetized
     "https://x.com/?b=2&a=1"),
    ("https://x.com/?ref=foo&q=keep",                      # `ref` stripped, q kept
     "https://x.com/?q=keep"),
    ("https://x.com/path/",                                # trailing slash preserved
     "https://x.com/path/"),
    ("https://x.com/path",                                 # NO trailing slash preserved
     "https://x.com/path"),
]


def main():
    print("=== Spec'd 4 cases ===")
    pass_count = 0
    for src, expected in CASES:
        actual = _normalize_url_for_cache(src)
        ok = actual == expected
        if ok: pass_count += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {src!r}")
        print(f"           expected → {expected!r}")
        print(f"           actual   → {actual!r}")
    print(f"\nSpec'd pass: {pass_count}/{len(CASES)}")

    print("\n=== Edge cases ===")
    edge_pass = 0
    for src, expected in EDGE_CASES:
        actual = _normalize_url_for_cache(src)
        ok = actual == expected
        if ok: edge_pass += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {src!r:60s} → {actual!r}  (expected {expected!r})")
    print(f"\nEdge-case pass: {edge_pass}/{len(EDGE_CASES)}")

    print("\n=== Cache-equivalence verification ===")
    # Two URLs differing only in srsltid → same cache key
    url_a = "https://webaruhaz.habi.hu/?srsltid=AAABCdefghij"
    url_b = "https://webaruhaz.habi.hu/?srsltid=ZZZZZqwertyuiop"
    key_a = _cache_key(url_a, "topic", "category")
    key_b = _cache_key(url_b, "topic", "category")
    eq_pass = key_a == key_b
    print(f"  url_a = {url_a}")
    print(f"  url_b = {url_b}")
    print(f"  key_a = {key_a}")
    print(f"  key_b = {key_b}")
    print(f"  [{'PASS' if eq_pass else 'FAIL'}] cache_key(url_a) == cache_key(url_b)")

    # Different topic_cluster → DIFFERENT key (cache key still differentiates context)
    key_c = _cache_key(url_a, "DIFFERENT_topic", "category")
    ctx_pass = key_a != key_c
    print(f"  key_c (different topic_cluster) = {key_c}")
    print(f"  [{'PASS' if ctx_pass else 'FAIL'}] cache_key differs when topic_cluster differs")

    # Different non-tracking param → DIFFERENT key
    url_d = "https://webaruhaz.habi.hu/?id=42"
    key_d = _cache_key(url_d, "topic", "category")
    nontrack_pass = key_a != key_d
    print(f"  key_d (non-tracking param) = {key_d}")
    print(f"  [{'PASS' if nontrack_pass else 'FAIL'}] cache_key differs when non-tracking param differs")

    total_pass = pass_count + edge_pass + int(eq_pass) + int(ctx_pass) + int(nontrack_pass)
    total_n = len(CASES) + len(EDGE_CASES) + 3
    print(f"\n=== TOTAL: {total_pass}/{total_n} passed ===")
    return total_pass == total_n


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
