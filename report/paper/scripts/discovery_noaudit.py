"""No-audit discovery baselines for the paper (Table 3), replayed from cache at zero cost.
  python3 report/paper/scripts/discovery_noaudit.py
  ablnoaudit_L1_<clip>    : request "fish", discovery (Spark names + SAM word ladder + zoom), no A1-A4, no motion
  ablnoauditmo_L1_<clip>  : the same plus the motion residual (Spark's animal-or-not look on moving spots), no A1-A4
Counts are per SAM word (no audit means no species label)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import pipeline  # noqa: E402

CLIPS = {"s001": "nautilus_s001_0_12.mp4", "s002": "nautilus_0_12.mp4", "s003": "nautilus_s003_0_12.mp4",
         "s004": "nautilus_s004_0_12.mp4"}
for tag, motion in (("ablnoaudit", False), ("ablnoauditmo", True)):
    for s, f in CLIPS.items():
        rid = f"{tag}_L1_{s}"
        try:
            pipeline.run_pipeline(os.path.join(ROOT, "spikes/L1/clips", f), rid, offline=True, do_scout=False,
                                  do_audit=False, do_zoom=True, prompts=["fish"], do_discover=True, do_motion=motion)
        except FileNotFoundError as e:
            print(rid, "NOT CACHED:", e); continue
        import json
        r = json.load(open(os.path.join(ROOT, "runs", rid, "result.json")))
        print(rid, {k: v["maxn"] for k, v in r["metrics"].items()},
              "tracks", len(r["tracks"]))
