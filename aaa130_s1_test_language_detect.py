"""AAA-130 S1 unit tests for is_genuine_target_language. $0, no model calls.

Fixtures (aaa130_s1_fixtures.json) are real stored summary texts:
  genuine_hu                 : agrobook ctrl HU translation (genuine Hungarian)
  en_quoting_hu_propernouns  : agrobook ctrl EN markdown (English; quotes
                               Csávoly, Kft. -> the diacritic trap)
  verbatim_text/_source      : aboutyou newT md (text == source passthrough)
  near_english_fail          : aboutyou newT hu field (English passthrough shape)
  genuine_en                 : kk.coach ctrl EN markdown (genuine English)
"""
import json
from pathlib import Path

from page_analysis.language_detect import (
    is_genuine_target_language,
    HU_EXCLUSIVE, EN_EXCLUSIVE, DENSITY_THRESHOLD_PER_1000,
)

FX = json.loads(Path("aaa130_s1_fixtures.json").read_text(encoding="utf-8"))

CASES = [
    # (name, text, target, source, expect_genuine, expect_reason)
    ("genuine HU prose",                     FX["genuine_hu"],                "hu", None,                  True,  "ok"),
    ("EN quoting HU proper nouns (TRAP)",    FX["en_quoting_hu_propernouns"], "hu", None,                  False, "low_density"),
    ("verbatim passthrough (text==source)",  FX["verbatim_text"],             "hu", FX["verbatim_source"], False, "verbatim"),
    ("near-English cosmetic HU fail",        FX["near_english_fail"],         "hu", None,                  False, "low_density"),
    ("genuine EN prose",                     FX["genuine_en"],                "en", None,                  True,  "ok"),
    # extra guards
    ("empty text",                           "",                              "hu", None,                  False, "empty"),
    ("unsupported target lang",              "valami szöveg",                 "de", None,                  True,  "unsupported_lang"),
]


def run():
    print(f"stoplist overlap (must be empty): {HU_EXCLUSIVE & EN_EXCLUSIVE or 'NONE'}")
    print(f"HU_EXCLUSIVE={len(HU_EXCLUSIVE)} tokens  EN_EXCLUSIVE={len(EN_EXCLUSIVE)} tokens")
    print(f"threshold = {DENSITY_THRESHOLD_PER_1000}/1000 chars\n")
    n_pass = 0
    densities = {}
    for name, text, tgt, src, exp_gen, exp_reason in CASES:
        r = is_genuine_target_language(text, tgt, src)
        ok = (r["is_genuine"] == exp_gen and r["reason"] == exp_reason)
        n_pass += ok
        densities[name] = r["density"]
        print(f"[{'PASS' if ok else 'FAIL'}] {name:40s} "
              f"-> genuine={r['is_genuine']!s:5s} reason={r['reason']:16s} "
              f"density={r['density']:.2f}  (expected genuine={exp_gen}, {exp_reason})")
    print(f"\n{n_pass}/{len(CASES)} cases passed")

    # Density gap summary on the fixtures
    print("\n--- density gap (matches/1000 chars) ---")
    g_hu = densities["genuine HU prose"]
    trap = densities["EN quoting HU proper nouns (TRAP)"]
    near = densities["near-English cosmetic HU fail"]
    g_en = densities["genuine EN prose"]
    print(f"  genuine HU        : {g_hu:.2f}")
    print(f"  EN-trap (target hu): {trap:.2f}")
    print(f"  near-English (hu) : {near:.2f}")
    print(f"  genuine EN        : {g_en:.2f}")
    print(f"  HU genuine/fail gap: {g_hu:.2f} vs ~{max(trap,near):.2f}  "
          f"= {g_hu/max(trap,near,0.01):.0f}x   (threshold {DENSITY_THRESHOLD_PER_1000})")
    return n_pass == len(CASES)


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
