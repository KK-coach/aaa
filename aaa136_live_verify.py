"""AAA-136 live verify: real DataForSEO site:<url> indexing check on 3 URLs
via the shipped check_indexing_status_tool (mock ToolContext)."""
import asyncio, json, types
from discovery_agent.tools import check_indexing_status_tool

class Ctx:  # minimal ToolContext stand-in: just needs .state (dict)
    def __init__(self, lang): self.state = {"site_profile": {"language": lang}}

CASES = [
    ("agrobook.hu (expect indexed:true)",        "https://agrobook.hu",                                                "hu"),
    ("control major page (expect true)",         "https://en.wikipedia.org/wiki/Search_engine_optimization",           "en"),
    ("nonexistent (exercise false)",             "https://agrobook.hu/this-page-does-not-exist-xyz-20260528-aaa136",   "hu"),
]

async def main():
    total=0.0
    rows=[]
    for label,url,lang in CASES:
        ctx=Ctx(lang)
        r=await check_indexing_status_tool(url, ctx)
        total+=float(r.get("cost_usd") or 0.0)
        rows.append((label,r))
        print(f"\n=== {label} ===")
        print(f"  query      : {r['query']}")
        print(f"  indexed    : {r['indexed']}")
        print(f"  matched_url: {r['matched_url']}")
        print(f"  position   : {r['position']}")
        print(f"  method     : {r['method']}")
        print(f"  cost_usd   : {r['cost_usd']}")
        if r.get('_error'): print(f"  _error     : {r['_error']}")
        # confirm stub note is gone
        assert 'note' not in r, "old stub note still present!"
    print(f"\nTOTAL cost: ${total:.6f}")
    print("old stub 'note' key absent on all: PASS")

asyncio.run(main())
