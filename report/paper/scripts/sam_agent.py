"""SAM 3 Agent-style loop as a discovery baseline (protocol: report/paper/sam_agent_protocol.md).

Propose (the final run's own discovery reply) -> SAM 3.1 per phrase -> Spark looks at the boxes -> keep / revise /
drop, at most 3 SAM rounds per thing. No word ladder, zoom, reversed pass, motion residual or audit.
Writes report/paper/data/sam_agent/<clip>.json and sheets; `--score` writes summary.json (measures 2-4).

  FISH_BUDGET=<ledger cap> memcap --max 2G -- python3 report/paper/scripts/sam_agent.py [--clips ...] [--dry] [--score]
"""
import argparse, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from fishcount import api, pipeline, tracks, video  # noqa: E402  (render sets up the cv2 path)
import cv2  # noqa: E402
import numpy as np  # noqa: E402

CLIPS = [f"DH{n}" for n in range(1, 12)] + ["s001", "s002", "s003", "s004"]
OUT = "report/paper/data/sam_agent"
CAP = 3.00            # the script's own spend cap (protocol)
MAX_ROUNDS = 3
SAM_EST = 0.012       # 60 frames x $0.20/1000

REVIEW_PROMPT = """You are helping a marine ecologist find every kind of living thing other than {targets} in an underwater survey clip.
Image 1 is a contact sheet of 6 frames from the clip. Image 2 shows what a segmentation model found in the whole clip for each search phrase: one row per phrase (labelled with its id and phrase), the three frames where it found the most objects with orange boxes, or a note that it found nothing.
The segmentation model only understands plain everyday English nouns (like "shell", "shrimp", "crab", "jellyfish", "worm", "starfish", "eel"); it returns nothing for species names, colours, or vague words like "animal" or "creature".
Phrases:
{phrases}
For each phrase decide:
- "keep": the boxes are mainly on that kind of living thing;
- "revise": the boxes are wrong or there are none, but you believe that thing is in the clip; give one different plain noun to try (not one already tried);
- "drop": there is no such thing, or the boxes are on rock, weed, bait, sediment, equipment or empty water.
Return ONLY a JSON list: [{{"id":"P1","verdict":"keep|revise|drop","new_phrase":"plain noun or empty","reason":"<=12 words"}}]"""


def contact_sheet(clip, n):
    idx = sorted({int(i * (n - 1) / 5) for i in range(6)})
    fr = video.frames(clip, idx)
    return video.jpg(video.grid([video.label(fr[i], f"frame {i}") for i in idx], 3, 640), q=80)


def best_frames(dets, k=3, gap=5):
    order = sorted(dets, key=lambda f: (-len(dets[f]), f))
    out = []
    for f in order:
        if all(abs(f - g) >= gap for g in out):
            out.append(f)
        if len(out) == k:
            break
    return sorted(out)


def result_sheet(clip, rows):
    """rows: [(pid, phrase, dets)] -> one jpg, one row per phrase."""
    lines = []
    for pid, phrase, dets in rows:
        fs = best_frames(dets)
        if not fs:
            panel = np.zeros((140, 3 * 640, 3), np.uint8)
            cv2.putText(panel, f"{pid} '{phrase}': found nothing in any frame", (30, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
            lines.append(panel)
            continue
        else:
            fr = video.frames(clip, fs)
            cells = []
            for f in fs:
                im = fr[f].copy()
                for d in dets[f]:
                    x0, y0, x1, y1 = (int(v) for v in d["box"])
                    cv2.rectangle(im, (x0, y0), (x1, y1), (0, 140, 255), 4)
                cells.append(video.label(im, f"{pid} '{phrase}' frame {f}: {len(dets[f])} boxes"))
        lines.append(video.grid(cells + [cells[0] * 0] * (3 - len(cells)), 3, 640))
    return video.jpg(np.vstack(lines), q=80)


def run_clip(c, dry, state):
    clip = f"runs/vswap_{c}/clip.mp4"
    inf = video.info(clip)
    n = inf["n_frames"]
    disc = json.load(open(f"runs/vswap_{c}/discover.json"))
    others = [o for o in (disc.get("others") or [])[:4] if o.get("search_words")]
    things = [dict(pid=f"P{i + 1}", what=o.get("what"), tried=[], phrase=o["search_words"][0].strip().lower(),
                   status="open") for i, o in enumerate(others)]
    sheet1 = contact_sheet(clip, n)
    rec = dict(clip=c, n_frames=n, things=things, rounds=[], sam_calls=0, sam_cached=0, spark_calls=0, stopped=None)
    for rnd in range(1, MAX_ROUNDS + 1):
        open_ = [t for t in things if t["status"] == "open"]
        if not open_:
            break
        rows = []
        for t in open_:
            cached = os.path.exists(api._cache_path("sam", {"clip": api.file_sha(clip), "prompt": t["phrase"]}))
            if not cached and not dry and state["usd"] + SAM_EST > CAP:
                rec["stopped"] = f"cap before SAM '{t['phrase']}' round {rnd}"
                return rec
            before = api.thread_spent()
            try:
                txt = api.sam_video(clip, t["phrase"], n, offline=dry)
            except FileNotFoundError:
                txt = None
            state["usd"] += api.thread_spent() - before
            rec["sam_calls"] += 1
            rec["sam_cached"] += int(cached)
            dets = tracks.parse_boxes(txt) if txt else {}
            t["tried"].append(dict(phrase=t["phrase"], round=rnd, frames=len(dets), cached=cached,
                                   tracks=len({d["id"] for ds in dets.values() for d in ds}),
                                   maxn=tracks.max_per_frame(dets), missing=txt is None))
            t["dets"] = {str(f): [dict(id=d["id"], box=list(d["box"])) for d in ds] for f, ds in dets.items()}
            rows.append((t["pid"], t["phrase"], dets))
        sheet2 = result_sheet(clip, rows)
        open(os.path.join(OUT, f"{c}_round{rnd}.jpg"), "wb").write(sheet2)
        phrases = "\n".join(
            f"{t['pid']} '{t['phrase']}' (looking for: {t['what']}"
            + (f"; tried before: {', '.join(repr(x['phrase']) + ' ' + str(x['frames']) + ' frames' for x in t['tried'][:-1])}"
               if len(t["tried"]) > 1 else "") + ")" for t in open_)
        prompt = REVIEW_PROMPT.format(targets="fish", phrases=phrases)
        if not dry and state["usd"] + 0.02 > CAP:
            rec["stopped"] = f"cap before Spark round {rnd}"
            return rec
        before = api.thread_spent()
        try:
            reply = api.spark(prompt, [sheet1, sheet2], offline=dry, check=api.parse_json_list)
        except FileNotFoundError:
            rec["rounds"].append(dict(round=rnd, prompt=prompt, reply=None, dry=True))
            break
        state["usd"] += api.thread_spent() - before
        rec["spark_calls"] += 1
        verdicts = {v.get("id"): v for v in api.parse_json_list(reply)}
        rec["rounds"].append(dict(round=rnd, prompt=prompt, reply=reply))
        for t in open_:
            v = verdicts.get(t["pid"]) or {}
            t.setdefault("verdicts", []).append(v)
            verdict = (v.get("verdict") or "").lower()
            new = (v.get("new_phrase") or "").strip().lower()
            if verdict == "keep":
                t["status"] = "kept"
            elif verdict == "revise" and new and new not in [x["phrase"] for x in t["tried"]] and rnd < MAX_ROUNDS:
                t["phrase"] = new
            elif verdict == "revise":
                t["status"] = "revise_exhausted"
            else:
                t["status"] = "dropped" if verdict == "drop" else f"no_verdict:{verdict or '-'}"
    for t in things:
        if t["status"] == "open":
            t["status"] = "revise_exhausted"
    return rec


def score():
    from open_detector import counted_nonfish   # same pipeline reference and overlap rule
    summ = {}
    for c in CLIPS:
        p = os.path.join(OUT, f"{c}.json")
        if not os.path.exists(p):
            continue
        rec = json.load(open(p))
        ref, r = counted_nonfish(c)
        allboxes = {int(f): [k["box"] for k in ks] for f, ks in r["frames"].items()}
        kept = [t for t in rec["things"] if t["status"] == "kept"]
        kept_boxes = {}
        for t in kept:
            for f, ds in t.get("dets", {}).items():
                kept_boxes.setdefault(int(f), []).extend(d["box"] for d in ds)
        found = {}
        for tid, rr in ref.items():
            hits = [f for f, b in rr["boxes"].items() if any(tracks.iou(x, b) >= 0.3 for x in kept_boxes.get(f, []))]
            found[rr["label"] + f" [{tid}]"] = len(hits) >= 3
        loose = []
        for t in kept:
            if not any(tracks.iou(d["box"], b) >= 0.3 for f, ds in t.get("dets", {}).items() for d in ds
                       for b in allboxes.get(int(f), [])):
                loose.append(t["phrase"])
        summ[c] = dict(
            kept=[dict(phrase=t["phrase"], what=t["what"], frames=t["tried"][-1]["frames"], maxn=t["tried"][-1]["maxn"],
                       revised=len(t["tried"]) - 1) for t in kept],
            dropped=[t["phrase"] for t in rec["things"] if t["status"] == "dropped"],
            other_status={t["phrase"]: t["status"] for t in rec["things"] if t["status"] not in ("kept", "dropped")},
            revised_things=sum(1 for t in rec["things"] if len(t["tried"]) > 1),
            kept_after_revision=sum(1 for t in kept if len(t["tried"]) > 1),
            pipeline_counted_nonfish=len(ref), pipeline_tracks_overlapped=sum(found.values()),
            overlapped=[k for k, v in found.items() if v], not_overlapped=[k for k, v in found.items() if not v],
            loose_kept_phrases=loose, sam_calls=rec["sam_calls"], sam_cached=rec["sam_cached"],
            spark_calls=rec["spark_calls"], usd=rec.get("usd"), stopped=rec["stopped"])
    json.dump(summ, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
    return summ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", nargs="*", default=CLIPS)
    ap.add_argument("--dry", action="store_true", help="cache only: checks round-1 SAM calls and sheets, $0")
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if a.score:
        for c, row in score().items():
            print(c, json.dumps(row)[:400])
        return
    state = {"usd": 0.0}
    for c in a.clips:
        if not a.dry and os.path.exists(os.path.join(OUT, f"{c}.json")):
            continue
        before = state["usd"]
        rec = run_clip(c, a.dry, state)
        rec["usd"] = round(state["usd"] - before, 5)
        name = f"{c}_dry.json" if a.dry else f"{c}.json"
        json.dump(rec, open(os.path.join(OUT, name), "w"), indent=1)
        print(c, "SAM", rec["sam_calls"], f"(cached {rec['sam_cached']})", "Spark", rec["spark_calls"],
              {t["phrase"]: t["status"] for t in rec["things"]}, f"${rec['usd']}", rec["stopped"] or "", flush=True)
        if rec["stopped"]:
            break
    print("script total", round(state["usd"], 4), "ledger", round(api.spent(), 4))


if __name__ == "__main__":
    main()
