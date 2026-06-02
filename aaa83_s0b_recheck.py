"""Re-check: detect BODY language with keyword echo stripped."""
import asyncio, re
from google import genai
from google.genai import types
from site_profile.gemini_analyzer import _resolve_project

MODELS = ["gemini-3-flash-preview", "gemini-3.5-flash"]
KW_HU = "marketing ügynökség Budapest"
PROMPT = f"Write a 200-word audit summary for the following query: {KW_HU}"
_HU_D = set("áéíóöőúüűÁÉÍÓÖŐÚÜŰ")

async def main():
    client = genai.Client(vertexai=True, project=_resolve_project(), location="global")
    for model in MODELS:
        cfg = types.GenerateContentConfig(temperature=0.0,
            response_mime_type="text/plain",
            thinking_config=types.ThinkingConfig(thinking_level="LOW"))
        resp = await client.aio.models.generate_content(model=model, contents=PROMPT, config=cfg)
        text = resp.text or ""
        # Strip every occurrence of the keyword (and its diacritic word) to remove echo
        body = text.replace("ügynökség", "").replace("Ügynökség", "")
        for w in ["marketing ügynökség Budapest", "ügynökség"]:
            body = body.replace(w, "")
        diacr_total = sum(1 for c in text if c in _HU_D)
        diacr_body = sum(1 for c in body if c in _HU_D)
        # sentence-level: is the FIRST full sentence HU or EN?
        first_sent = re.split(r'(?<=[.!?])\s', text.strip().split('\n')[0] if '\n' in text[:50] else text.strip())[0]
        print(f"\n{'='*70}\n{model}  (HU keyword input)\n{'='*70}")
        print(f"  diacritics total={diacr_total}  diacritics after stripping 'ügynökség'={diacr_body}")
        print(f"  => body language: {'HU' if diacr_body>=3 else 'EN'}")
        print(f"  --- full response ({len(text)} chars) ---")
        print(text)

asyncio.run(main())
