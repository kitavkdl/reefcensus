"""Copy finished runs into demo/runs/ (committed) so the review screen works from a fresh clone with no API key.
Only what the screen shows is copied: result.json, status.json, review.json if any, evidence jpgs, motion_sheet.jpg, thumbs/,
the sheets Spark judged (audit_*, verify_*, confirm_*),
annotated.mp4 (~2 MB a run). web/server.py seeds runs/ from demo/runs/ on start.

    python3 demo/pack_runs.py mg2_s001 mg2_s002 mg2_s003 mg2_s004
"""
import os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP = ("result.json", "status.json", "review.json", "annotated.mp4", "motion_sheet.jpg", "motion_sheet2.jpg")

for rid in sys.argv[1:]:
    src, dst = os.path.join(ROOT, "runs", rid), os.path.join(ROOT, "demo", "runs", rid)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst)
    for f in os.listdir(src):
        if f in KEEP or (f.startswith(("evidence_", "audit_", "verify_", "confirm_", "pairs_", "pairsx_")) and f.endswith(".jpg")):
            shutil.copy2(os.path.join(src, f), dst)
    if os.path.isdir(os.path.join(src, "thumbs")):
        shutil.copytree(os.path.join(src, "thumbs"), os.path.join(dst, "thumbs"))
    print(rid, sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(dst) for f in fs) // 1024, "KB")
