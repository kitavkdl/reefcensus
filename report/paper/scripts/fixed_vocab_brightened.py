"""Like-for-like version of the fixed-vocabulary baseline on s001: the SAME 16 generic words (+ 'nautilus') run on the
BRIGHTENED clip the pipeline actually used (runs/mg2_s001/clip.mp4, = gamma 0.5 + CLAHE 2.0, md5 21d38d57...), instead
of the dark original (runs/L1_s001_v16/clip.mp4) that report/paper/scripts/fixed_vocab.py used. Scoring is the same
as fixed_vocab.py: a SAM track 'finds' the nautilus when it overlaps (IoU >= 0.3, >= 3 shared frames) a track the
audited final run counted. Reference = runs/mg2_s001/result.json (5 counted tracks, MaxN 4).
  FISH_BUDGET=<ledger+3> python3 report/paper/scripts/fixed_vocab_brightened.py     (paid: <= 17 words x 60 frames x $0.0002)
  python3 report/paper/scripts/fixed_vocab_brightened.py --offline                   (cache only)"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import api, tracks  # noqa: E402

WORDS = ["fish", "shark", "ray", "eel", "crab", "shrimp", "lobster", "octopus", "squid", "snail", "shell",
         "starfish", "jellyfish", "sea urchin", "sea cucumber", "worm"]
EXTRA = ["nautilus"]
RUN = os.path.join(ROOT, "runs", "mg2_s001")
OUT = os.path.join(ROOT, "report/paper/data/fixed_vocab_brightened")

offline = "--offline" in sys.argv
os.makedirs(OUT, exist_ok=True)
billed = []
_orig = api._log
def _spy(kind, cost, note=""):
    billed.append((note, cost)); return _orig(kind, cost, note)
api._log = _spy

res = json.load(open(os.path.join(RUN, "result.json")))
clip = os.path.join(RUN, "clip.mp4")
n = res["video"]["n_frames"]
ref = {}
for f, ks in res["frames"].items():
    for k in ks:
        if res["auto_labels"].get(k["track"]) == "nautilus":
            ref.setdefault(k["track"], {})[int(f)] = k["box"]
rows = {}
for w in WORDS + EXTRA:
    txt = api.sam_video(clip, w, n, offline=offline)
    open(os.path.join(OUT, f"s001__{w.replace(' ', '_')}.txt"), "w").write(txt)
    det = tracks.parse_boxes(txt)
    byid = {}
    for f, ds in det.items():
        for d in ds:
            byid.setdefault(d["id"], {})[f] = d["box"]
    found = unver = 0
    for tid, bx in byid.items():
        hit = any(len([f for f in bx if f in r and tracks.iou(bx[f], r[f]) >= 0.3]) >= 3 for r in ref.values())
        found += hit; unver += not hit
    rows[w] = dict(frames=len(det), maxn=tracks.max_per_frame(det), tracks=len(byid),
                   tracks_matching_counted_nautilus=found, tracks_matching_none=unver)
json.dump(rows, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
print("words with any frames:", {w: r for w, r in rows.items() if r["frames"]})
print("words with 0 frames:", [w for w, r in rows.items() if not r["frames"]])
print("live calls this process:", len(billed), "billed $%.4f" % sum(c for _, c in billed), billed)
