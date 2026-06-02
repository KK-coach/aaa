"""AAA-83 Sub-step 0.5 — non-grounded language-drift probe.
2 models × 2 keywords = 4 Vertex calls, NO GoogleSearch/grounding tool.
Mirrors gemini_analyzer.vertex_generate config (thinking_level=LOW,
temperature=0) but parametrized by model + plain-text output."""
import asyncio, re
from google import genai
from google.genai import types
from site_profile.gemini_analyzer import _resolve_project

LOCATION = "global"
OFF_IN = 1.50 / 1_000_000
OFF_OUT = 9.00 / 1_000_000
MODELS = ["gemini-3-flash-preview", "gemini-3.5-flash"]
KEYWORDS = [("HU", "marketing ügynökség Budapest"),
            ("EN", "marketing agency London")]
PROMPT = "Write a 200-word audit summary for the following query: {kw}"

# Hungarian detection: diacritics + common HU function words
_HU_DIACRITICS = set("áéíóöőúüűÁÉÍÓÖŐÚÜŰ")
_HU_WORDS = {" és ", " az ", " egy ", " hogy ", " nem ", " ügynökség",
             " keresőoptimalizál", " vállalkozás", " marketing", " ezen ",
             " amely ", " ahol ", " való ", " kell ", " lehet "}

def detect_lang(text: str) -> str:
    t = (text or "").lower()
    diacr = sum(1 for c in text if c in _HU_DIACRITICS)
    hu_hits = sum(1 for w in _HU_WORDS if w in t)
    # EN function words
    en_hits = sum(1 for w in (" the ", " and ", " for ", " your ", " with ",
                              " this ", " that ", " business ", " of ", " to ")
                  if w in t)
    if diacr >= 3 or hu_hits >= 3:
        return f"HU (diacritics={diacr}, hu_words={hu_hits}, en_words={en_hits})"
    if en_hits >= 4 and diacr < 3:
        return f"EN (diacritics={diacr}, hu_words={hu_hits}, en_words={en_hits})"
    return f"AMBIG (diacritics={diacr}, hu_words={hu_hits}, en_words={en_hits})"

async def call(client, model, kw):
    cfg = types.GenerateContentConfig(
        temperature=0.0, response_mime_type="text/plain",
        thinking_config=types.ThinkingConfig(thinking_level="LOW"))
    resp = await client.aio.models.generate_content(
        model=model, contents=PROMPT.format(kw=kw), config=cfg)
    um = resp.usage_metadata
    itok = getattr(um, "prompt_token_count", 0) or 0
    cand = getattr(um, "candidates_token_count", 0) or 0
    tho = getattr(um, "thoughts_token_count", 0) or 0
    otok = cand + tho
    cost = itok*OFF_IN + otok*OFF_OUT
    return resp.text, itok, otok, cost

async def main():
    client = genai.Client(vertexai=True, project=_resolve_project(), location=LOCATION)
    results = {}
    for model in MODELS:
        for kwlang, kw in KEYWORDS:
            try:
                text, itok, otok, cost = await call(client, model, kw)
                lang = detect_lang(text)
            except Exception as e:
                text, itok, otok, cost, lang = f"ERROR {type(e).__name__}: {e}", 0, 0, 0.0, "ERROR"
            results[(model, kwlang)] = (lang, itok, otok, cost, text)
            print(f"\n{'='*72}\n{model}  |  input={kwlang} '{kw}'\n{'='*72}")
            print(f"  detected: {lang}")
            print(f"  tokens in/out: {itok}/{otok}  cost@official: ${cost:.6f}")
            print(f"  --- first 220 chars ---\n  {text[:220].strip()}")

    print(f"\n\n{'#'*72}\n# 2x2 MATRIX (detected response language)\n{'#'*72}")
    print(f"{'model':26s} | {'HU input':40s} | {'EN input':40s}")
    for model in MODELS:
        hu = results[(model,'HU')][0].split(' (')[0]
        en = results[(model,'EN')][0].split(' (')[0]
        print(f"{model:26s} | {hu:40s} | {en:40s}")
    tot = sum(v[3] for v in results.values())
    print(f"\nTOTAL cost @ official rates: ${tot:.6f}")

asyncio.run(main())
