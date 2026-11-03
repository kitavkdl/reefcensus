"""Spark's own cost on the questions of the Wonder comparison (vlm_swap.py), from the usage stored with each cached
reply. Same offline replay as vlm_swap.py, no second model, $0. The 14 motion looks are saved without usage
(cache/motion_*.json), so they are not in this figure.

  memcap --max 2G -- python3 report/paper/scripts/vlm_swap_spark_cost.py
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "report/paper/scripts"))
from fishcount import api, pipeline  # noqa: E402
from vlm_swap import CLIPS, FLAGS, kind_of  # noqa: E402

_orig = api.spark
rows = []


def recorder(clip):
    def rec(prompt, images=(), **kw):
        kw.pop("offline", None)
        text = _orig(prompt, images, offline=True, **kw)
        u = getattr(api._tl, "last_usage", {}) or {}
        rows.append({"clip": clip, "kind": kind_of(prompt), "in": u.get("prompt_tokens", 0),
                     "out": u.get("completion_tokens", 0)})
        return text
    return rec


for clip in CLIPS:
    api.spark = recorder(clip)
    try:
        pipeline.run_pipeline(CLIPS[clip], f"vswap_{clip}", True, max_usd=1.0, lowlight="auto", **FLAGS)
    finally:
        api.spark = _orig
usd = sum(r["in"] * api.SPARK_IN + r["out"] * api.SPARK_OUT for r in rows)
missing = sum(1 for r in rows if not (r["in"] or r["out"]))
out = {"calls": len(rows), "calls_without_usage": missing, "spark_usd": round(usd, 4),
       "spark_usd_per_call": round(usd / max(len(rows) - missing, 1), 5),
       "by_kind": {k: sum(1 for r in rows if r["kind"] == k) for k in sorted({r["kind"] for r in rows})}}
json.dump(out, open("report/paper/data/vlm_swap/spark_cost.json", "w"), indent=1)
print(json.dumps(out))
