"""11/2: measure mask containment |A&B|/min(|A|,|B|) between same-frame kept detections of a run, replayed
from the cache (offline, $0). Hooks render so the pipeline hands over its SAM texts. Usage:
  python3 spikes/maskdup.py <clip> <run-id> [frame ...]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import pipeline, render, maskdedupe

clip, rid, only = sys.argv[1], sys.argv[2], {int(x) for x in sys.argv[3:]}

def hook(clip, raw, result, out_path):
    lab = lambda t: result["auto_labels"].get(t, result["tracks"].get(t, {}).get("label"))
    W, H = result["video"]["width"], result["video"]["height"]
    frames = {int(f): ks for f, ks in result["frames"].items() if not only or int(f) in only}
    dec = maskdedupe.decode_sources(raw, W, H)
    hist = []
    for f, i, j, c in maskdedupe.pairs(frames, dec):
        a, b = frames[f][i], frames[f][j]
        hist.append(c)
        if c >= 0.3 or only:
            ma = maskdedupe.det_mask(dec, a["track"].split(":")[0], f, a["box"])
            mb = maskdedupe.det_mask(dec, b["track"].split(":")[0], f, b["box"])
            r = max(ma[0].sum(), mb[0].sum()) / max(1, min(ma[0].sum(), mb[0].sum()))
            print(f, f"{a['track']}({lab(a['track'])})", f"{b['track']}({lab(b['track'])})", f"ratio={r:.2f}", f"maskC={c:.2f}")
    import collections
    print("histogram (0.1 bins):", sorted(collections.Counter(int(c * 10) for c in hist).items()))

render.annotate = hook
render.evidence = lambda *a, **k: 0
pipeline.run_pipeline(clip, rid, offline=True, do_scout=False, do_discover=True)
