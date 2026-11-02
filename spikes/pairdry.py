"""Dry run of the nested-pair check with Spark mocked ($0): replays a run offline, saves every pair sheet the
pipeline would send, and answers 'same animal' per a fixed rule so the downstream counting can be inspected.
  python3 spikes/pairdry.py <clip> <run-id> <out-dir> [same|different]"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import pipeline, api, render
clip, rid, out, mode = sys.argv[1], sys.argv[2], sys.argv[3], (sys.argv[4] if len(sys.argv) > 4 else "same")
os.makedirs(out, exist_ok=True)
real, n, miss = api.spark, [0], [0]
def fake(prompt, imgs, offline=False, **k):
    if prompt is pipeline.PAIR_PROMPT:
        n[0] += 1
        open(os.path.join(out, f"pairsheet_{n[0]}.jpg"), "wb").write(imgs[0])
        import re
        return json.dumps([dict(tile=f"P{i}", same_animal=(mode == "same"), what="mock") for i in range(1, 17)])
    try:
        return real(prompt, imgs, offline=offline, **k)
    except FileNotFoundError:   # a new peak frame after de-duplication: box check not cached -> mock "all true"
        miss[0] += 1
        return json.dumps([dict(tile=f"D{i}", is_target=True, what_it_is="mock") for i in range(1, 17)])
api.spark = fake
render.annotate = lambda *a, **k: None
render.evidence = lambda *a, **k: 0
res = pipeline.run_pipeline(clip, rid, offline=True, do_scout=False, do_discover=True)
print("pair sheets", n[0], "uncached box checks mocked", miss[0])
print({k: v["maxn"] for k, v in res["metrics"].items()})
for d in res["duplicates"]:
    print(d)
