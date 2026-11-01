"""Import saved ~/meta-smoke responses into the SAM cache so development and demos re-use them for free."""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api

SMOKE = os.path.expanduser("~/meta-smoke")
for f in sorted(glob.glob(f"{SMOKE}/out/fish_*.json")):
    r = json.load(open(f))
    if r.get("status") != "completed":
        continue
    clip = f"{SMOKE}/clips/{r['clip']}.mp4"
    payload = {"clip": api.file_sha(clip), "prompt": r["prompt"]}
    cp = api._cache_path("sam", payload)
    if not os.path.exists(cp):
        json.dump({"payload": payload, "output_text": r["output_text"], "usage": r.get("usage")}, open(cp, "w"))
        print("seeded", os.path.basename(f))
