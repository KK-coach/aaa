"""AAA-83 S2 pre-flight: does gemini-3.5-flash honor thinking_budget=0
(a 3-preview-era param used by vertex_generate/translate_summary)?
Compare thinking_budget=0 vs thinking_level=LOW on BOTH models."""
import asyncio, time
from google import genai
from google.genai import types
from site_profile.gemini_analyzer import _resolve_project

PROMPT = 'Return a JSON object {"ok": true, "lang": "en"}. Nothing else.'

async def call(client, model, cfg_kind):
    if cfg_kind == "budget0":
        think = types.ThinkingConfig(thinking_budget=0)
    else:
        think = types.ThinkingConfig(thinking_level="LOW")
    cfg = types.GenerateContentConfig(
        temperature=0.0, response_mime_type="application/json",
        thinking_config=think)
    t0 = time.perf_counter()
    try:
        resp = await client.aio.models.generate_content(model=model, contents=PROMPT, config=cfg)
        lat = round(time.perf_counter()-t0, 2)
        um = resp.usage_metadata
        return {"ok": True, "lat": lat,
                "in": getattr(um,"prompt_token_count",0) or 0,
                "cand": getattr(um,"candidates_token_count",0) or 0,
                "thoughts": getattr(um,"thoughts_token_count",0) or 0,
                "text": (resp.text or "")[:60]}
    except Exception as e:
        return {"ok": False, "lat": round(time.perf_counter()-t0,2), "err": f"{type(e).__name__}: {str(e)[:160]}"}

async def main():
    client = genai.Client(vertexai=True, project=_resolve_project(), location="global")
    for model in ["gemini-3-flash-preview", "gemini-3.5-flash"]:
        for kind in ["budget0", "level_low"]:
            r = await call(client, model, kind)
            tag = f"{model:24s} {kind:10s}"
            if r["ok"]:
                print(f"{tag} OK  lat={r['lat']}s in={r['in']} cand={r['cand']} thoughts={r['thoughts']}  text={r['text']!r}")
            else:
                print(f"{tag} ERROR  {r['err']}")

asyncio.run(main())
