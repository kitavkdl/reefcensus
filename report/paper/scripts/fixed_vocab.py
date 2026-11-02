"""Discovery baseline asked for by the second review: no VLM naming, SAM 3.1 prompted on the full frame with a FIXED
list of basic-level nouns for animals seen on baited cameras. The list was written before any of these calls, from
general knowledge, without looking at Spark's names for these clips; "nautilus" is not in it (a generic list would not
have it), and a second variant adds it as the survey's known target.
  FISH_BUDGET=<ledger+1> python3 report/paper/scripts/fixed_vocab.py          (paid: up to 16 words x 4 clips x $0.012)
  python3 report/paper/scripts/fixed_vocab.py --offline                         (cache / bundle only)
Scoring, automatic: a SAM track of word w 'finds' a person-listed taxon when it overlaps (IoU >= 0.3, >= 3 shared
frames) a track the audited final run counted under that taxon. A track of a counted word that overlaps no such track
is an unverified label (a real unlisted animal or a false one; the baseline itself cannot tell)."""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import api, tracks  # noqa: E402

WORDS = ["fish", "shark", "ray", "eel", "crab", "shrimp", "lobster", "octopus", "squid", "snail", "shell",
         "starfish", "jellyfish", "sea urchin", "sea cucumber", "worm"]
EXTRA = ["nautilus"]
CLIPS = {"s001": "L1_s001_v16", "s002": "L1_s002_v16", "s003": "L1_s003_v16", "s004": "L1_s004_v16"}
PERSON = {"s001": ["nautilus"], "s002": ["nautilus", "red crustacean"], "s003": ["nautilus"],
          "s004": ["nautilus", "shrimp", "hagfish"]}
TAXON = {"chambered nautilus": "nautilus", "nautilus": "nautilus", "small red crab": "red crustacean",
         "caridean shrimp": "shrimp", "shrimp (unidentified)": "shrimp", "hagfish": "hagfish"}
RIGHT = {"nautilus": {"nautilus"}, "red crustacean": {"crab", "shrimp", "lobster"}, "shrimp": {"shrimp"},
         "hagfish": set()}
OUT = os.path.join(ROOT, "report/paper/data/fixed_vocab")


def main():
    offline = "--offline" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    rows = {}
    for cid, run in CLIPS.items():
        rd = os.path.join(ROOT, "runs", run)
        res = json.load(open(os.path.join(rd, "result.json")))
        n = res["video"]["n_frames"]
        # counted tracks of the audited final run, per taxon: {track: {frame: box}}
        ref = {}
        for f, ks in res["frames"].items():
            for k in ks:
                lab = res["auto_labels"].get(k["track"])
                if lab in TAXON:
                    ref.setdefault(k["track"], {"taxon": TAXON[lab], "boxes": {}})["boxes"][int(f)] = k["box"]
        rows[cid] = {}
        for w in WORDS + EXTRA:
            bp = os.path.join(OUT, f"{cid}__{w.replace(' ', '_')}.txt")
            if offline and not os.path.exists(os.path.join(rd, "clip.mp4")):
                txt = open(bp).read()
            else:
                txt = api.sam_video(os.path.join(rd, "clip.mp4"), w, n, offline=offline)
                open(bp, "w").write(txt)
            det = tracks.parse_boxes(txt)
            byid = {}
            for f, ds in det.items():
                for d in ds:
                    byid.setdefault(d["id"], {})[f] = d["box"]
            maxn = tracks.max_per_frame(det)
            found, unver = set(), 0
            for tid, bx in byid.items():
                hit = None
                for r in ref.values():
                    shared = [f for f in bx if f in r["boxes"] and tracks.iou(bx[f], r["boxes"][f]) >= 0.3]
                    if len(shared) >= 3:
                        hit = r["taxon"]; break
                if hit:
                    found.add(hit)
                else:
                    unver += 1
            rows[cid][w] = dict(frames=len(det), maxn=maxn, tracks=len(byid), found=sorted(found), unverified=unver)
    json.dump(rows, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
    for variant, ws in (("generic list", WORDS), ("generic list + 'nautilus'", WORDS + EXTRA)):
        got, wrong, unv = set(), [], []
        for cid in CLIPS:
            for w in ws:
                r = rows[cid][w]
                for t in r["found"]:
                    if t in PERSON[cid]:
                        got.add((cid, t))
                        if w not in RIGHT[t]:
                            wrong.append(f"{cid} {t} as '{w}'")
                if r["unverified"] and w != "fish":
                    unv.append(f"{cid} '{w}' {r['unverified']} track(s), MaxN {r['maxn']}")
        names_ok = {(c, t) for c, t in got if any(t in rows[c][w]["found"] and w in RIGHT[t] for w in ws)}
        print(f"\n== {variant} ==")
        print(f"taxa found: {len(got)} of 7  {sorted(got)}")
        print(f"... found under a right word at least once: {len(names_ok)}; wrong-word finds: {wrong}")
        print(f"non-fish words with tracks matching no counted animal: {unv}")
    print("\nper clip, words with any frames:")
    for cid in CLIPS:
        print(cid, {w: (r["frames"], r["found"]) for w, r in rows[cid].items() if r["frames"]})


main()
