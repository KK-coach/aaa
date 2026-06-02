"""AAA-130 S0 Part B — translate EN->HU multi-run failure characterization.
N=5 per (site × model × thinking-config). Classify: genuine HU / EN-verbatim
passthrough / wrong-lang. HU-only function-word count + verbatim check."""
import asyncio, json
from google import genai
from google.genai import types
from site_profile.gemini_analyzer import _resolve_project
from page_analysis.translate_summary import _PROMPT, _LANG_NAME

N = 5
MODELS = ["gemini-3-flash-preview", "gemini-3.5-flash"]
CONFIGS = ["budget0", "level_low"]  # budget0 = current prod translate config
SRC = json.load(open("aaa130_s0_en_sources.json", encoding="utf-8"))

HU_ONLY = [" és "," egy "," az "," hogy "," nem "," való "," amely "," vagy ",
           " mely "," által "," webáruház"," című "," során "," ezen "," kell ",
           " lehet "," felism"," márk"," oldal"," kereső"]
def huwords(t):
    tl = (t or "").lower()
    return sum(tl.count(w) for w in HU_ONLY)

def classify(src, out):
    if not out or not out.strip():
        return "empty"
    if out.strip() == src.strip():
        return "passthrough"   # EN verbatim (output == EN source)
    hw = huwords(out)
    # also: substantial char-overlap with source = near-passthrough
    if hw >= 8:
        return "genuine_HU"
    if huwords(src) == 0 and hw < 3:
        return "wrong_lang_EN"   # output has ~no HU markers => still English
    return "ambiguous"

async def one(client, model, cfg, src):
    think = (types.ThinkingConfig(thinking_budget=0) if cfg=="budget0"
             else types.ThinkingConfig(thinking_level="LOW"))
    prompt = _PROMPT.format(src_name=_LANG_NAME["en"], tgt_name=_LANG_NAME["hu"], summary=src)
    try:
        resp = await client.aio.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0, response_mime_type="text/plain", thinking_config=think))
        return classify(src, resp.text or "")
    except Exception as e:
        return f"ERR:{type(e).__name__}"

async def main():
    client = genai.Client(vertexai=True, project=_resolve_project(), location="global")
    results = {}
    for model in MODELS:
        for cfg in CONFIGS:
            for site, src in SRC.items():
                runs = []
                for _ in range(N):
                    runs.append(await one(client, model, cfg, src))
                key = (model, cfg, site)
                results[key] = runs
                from collections import Counter
                c = Counter(runs)
                print(f"{model:24s} {cfg:10s} {site:9s} N={N}: {dict(c)}")
    # Aggregate per model×config: passthrough/wrong-lang frequency
    print("\n=== PASSTHROUGH+WRONGLANG FREQUENCY (per model×config, across 3 sites×5=15) ===")
    from collections import Counter
    for model in MODELS:
        for cfg in CONFIGS:
            allruns = []
            for site in SRC: allruns += results[(model,cfg,site)]
            c = Counter(allruns)
            fail = c.get("passthrough",0) + c.get("wrong_lang_EN",0)
            print(f"  {model:24s} {cfg:10s}: fail={fail}/15 ({100*fail/15:.0f}%)  breakdown={dict(c)}")
    json.dump({f"{m}|{cf}|{s}":results[(m,cf,s)] for (m,cf,s) in results},
              open("aaa130_s0_failrate_out.json","w",encoding="utf-8"), ensure_ascii=False, indent=2)

asyncio.run(main())
