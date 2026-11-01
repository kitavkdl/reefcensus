"""End-to-end run: ingest -> scout (Spark) -> track (SAM 3.1, parallel) -> zoom (optional) -> merge/stitch
-> audit (Spark) -> metrics -> evidence frames.  Each stage writes into runs/<id>/ and updates status.json,
which the web UI polls.
  python3 fishcount/pipeline.py <video> [--offline] [--no-scout] [--no-audit] [--zoom] [--prompts fish ...]"""
import argparse, concurrent.futures as cf, json, os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api, tracks, video, render

RUNS = os.path.join(api.ROOT, "runs")
CELLS = ["top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right"]

SCOUT_PROMPT = """You are assisting a marine ecologist counting animals in underwater survey video. The image is a contact sheet of {n} frames from one clip (frame index in each top-left label).
Return ONLY JSON:
{{"objects":[{{"name":"common name or best guess","sam_prompt":"ONE generic category word only: fish, shark, ray, crab, lobster, octopus, squid, seal, turtle, eel (never colours or species names; a segmentation model only understands generic words)","approx_max_count":int,"where":"where in the frame"}}],
 "faint_regions":[{{"frame":int,"region":"one of top-left|top|top-right|left|center|right|bottom-left|bottom|bottom-right","note":"small, distant, dark or partly hidden"}}],
 "visibility":"clear|moderate|murky"}}
List each distinct kind of animal separately (fish species or groups, rays, sharks, crustaceans). Only list faint regions where you think a detector would likely miss an animal."""

# tested 11/1 (spikes/L1): SAM finds nothing for "animal", so it cannot look for what nobody named. Spark looks
# first, names what the user did not ask about, and offers plain nouns; SAM tries them in order (word ladder).
DISCOVER_PROMPT = """You are helping a marine ecologist review underwater survey video. They asked only to count: {targets}.
The image is a contact sheet of {n} frames from one clip (frame index in each top-left label). Look for every OTHER kind of living thing that the request did not ask about, including small, partly hidden or unusual ones.
A segmentation model will search the video for each thing, but it only understands plain everyday English nouns (like "shell", "shrimp", "crab", "jellyfish", "worm", "starfish", "eel"); it returns nothing for species names, colours, or vague words like "animal" or "creature".
Also report indirect signs that an animal may be present but hard to see: sand or sediment puffs, a moving shadow, bubbles, bait being disturbed, a burrow opening.
Return ONLY JSON:
{{"others":[{{"what":"your best identification","why_notable":"<=12 words","search_words":["most likely plain noun","second option","third option"],"frames":[ints]}}],
 "signs":[{{"frame":int,"region":"one of top-left|top|top-right|left|center|right|bottom-left|bottom|bottom-right","sign":"<=12 words","possible_animal":"best guess or unknown"}}]}}
At most 4 others (most notable first) and 3 signs. Use empty lists if there are none."""

AUDIT_PROMPT = """You are checking detections from an automatic tracker in underwater survey video. Each tile is one tracked object, labelled with its track id (e.g. T3); the detector was asked to find "{label}". Context from an earlier look at the clip: {context}
For every tile return ONLY a JSON list: [{{"track":"T3","is_target":true|false,"species":"common name or 'unknown'","confidence":0.0-1.0,"reason":"<=10 words"}}]
is_target = the tile really shows a whole or partial {label} (not seagrass, rock, bubbles, debris, a shadow, or a duplicate fragment you cannot tell apart). Be honest about uncertainty: blurry tiles should get low confidence."""


class Run:
    def __init__(self, rid):
        self.id, self.dir = rid, os.path.join(RUNS, rid)
        os.makedirs(self.dir, exist_ok=True)
        self.status = dict(id=rid, stage="queued", log=[], live_calls=0, cached_calls=0, billed_usd=0.0, started=time.time())

    def path(self, *p):
        return os.path.join(self.dir, *p)

    def stage(self, name, msg=None):
        self.status["stage"] = name
        if msg:
            self.status["log"].append(f"{time.strftime('%H:%M:%S')} {msg}")
        json.dump(self.status, open(self.path("status.json"), "w"))

    def save(self, name, obj):
        json.dump(obj, open(self.path(name), "w"))


def _counted(run, fn, *a, **k):
    """Call an api function and record whether it hit the network (this thread logged spend) or the cache."""
    before = api.thread_spent()
    out = fn(*a, **k)
    d = api.thread_spent() - before
    run.status["live_calls" if d > 0 else "cached_calls"] += 1
    run.status["billed_usd"] += d
    return out


def cell_box(cell, W, H, pad=0.15):
    r, c = divmod(CELLS.index(cell), 3)
    w, h = W / 3, H / 3
    x0, y0 = max(0, c * w - pad * w), max(0, r * h - pad * h)
    x1, y1 = min(W, (c + 1) * w + pad * w), min(H, (r + 1) * h + pad * h)
    ev = lambda v: int(v) // 2 * 2
    return ev(x0), ev(y0), ev(x1 - x0), ev(y1 - y0)


def scout(run, clip, inf, offline):
    n = inf["n_frames"]
    idx = sorted({int(i * (n - 1) / 5) for i in range(6)})
    fr = video.frames(clip, idx)
    sheet = video.grid([video.label(fr[i], f"frame {i}") for i in idx], 3, 640)
    reply = _counted(run, api.spark, SCOUT_PROMPT.format(n=len(idx)), [video.jpg(sheet, q=80)], offline=offline)
    return api.parse_json(reply)


def discover(run, clip, inf, targets, offline):
    n = inf["n_frames"]
    idx = sorted({int(i * (n - 1) / 5) for i in range(6)})
    fr = video.frames(clip, idx)
    sheet = video.grid([video.label(fr[i], f"frame {i}") for i in idx], 3, 640)
    reply = _counted(run, api.spark, DISCOVER_PROMPT.format(targets=", ".join(targets), n=len(idx)), [video.jpg(sheet, q=80)], offline=offline)
    return api.parse_json(reply)


def word_ladder(run, clip, n, words, offline):
    """Try SAM with each word in turn; stop at the first that tracks anything. Returns (word|None, text, tried)."""
    tried = []
    for w in words:
        txt = _counted(run, api.sam_video, clip, w, n, offline=offline)
        d = tracks.parse_boxes(txt)
        tried.append(dict(word=w, frames=len(d)))
        if d:
            return w, txt, tried
    return None, "", tried


def audit(run, clip, frames, trk, label, context, offline, per_sheet=12, start=0):
    """Show Spark one crop per track (largest box) in sheets of 12; returns {track: verdict}."""
    best = {}
    for f, ks in frames.items():
        for k in ks:
            if trk[k["track"]]["label"] != label:
                continue
            b = k["box"]
            a = (b[2] - b[0]) * (b[3] - b[1])
            if k["track"] not in best or a > best[k["track"]][0]:
                best[k["track"]] = (a, f, b)
    ids = sorted(best, key=lambda t: best[t][1])
    names = {t: f"T{start + i + 1}" for i, t in enumerate(ids)}
    imgs = video.frames(clip, {best[t][1] for t in ids})
    os.makedirs(run.path("thumbs"), exist_ok=True)
    crops = {}
    for t in ids:
        _, f, b = best[t]
        crop = render.crop(imgs[f], b, pad=0.25, min_side=96)
        open(run.path("thumbs", f"{names[t]}.jpg"), "wb").write(video.jpg(crop, max_w=320))
        crops[t] = video.label(render.square(crop, 256), names[t])
    out = {}
    for i in range(0, len(ids), per_sheet):
        chunk = ids[i:i + per_sheet]
        sheet = video.grid([crops[t] for t in chunk], 4, 256)
        reply = _counted(run, api.spark, AUDIT_PROMPT.format(label=label, context=context), [video.jpg(sheet, q=85)], offline=offline)
        for v in api.parse_json(reply):
            out[v["track"]] = v
    return {t: dict(out.get(names[t], {}), name=names[t], frame=best[t][1], box=best[t][2]) for t in ids}


def run_pipeline(src, rid=None, offline=False, do_scout=True, do_audit=True, do_zoom=False, prompts=None, max_usd=1.0,
                 do_discover=False):
    rid = rid or time.strftime("%m%d-%H%M%S")
    run = Run(rid)
    clip = run.path("clip.mp4")
    run.stage("ingest", f"re-encoding {os.path.basename(src)} to 5 fps")
    if src.endswith(".mp4") and video.info(src)["fps"] == 5.0:
        shutil.copy(src, clip)      # already analysis-ready (keeps the cache key stable)
    else:
        video.ingest(src, clip)
    inf = video.info(clip)
    run.status["video"] = inf
    run.stage("ingest", f"{inf['n_frames']} frames {inf['width']}x{inf['height']}")

    sc = {}
    if do_scout:
        run.stage("scout", "Muse Spark looks at 6 frames and proposes what to track")
        sc = scout(run, clip, inf, offline)
        run.save("scout.json", sc)
        run.stage("scout", "Spark sees: " + ", ".join(f"{o['name']} (~{o.get('approx_max_count')})" for o in sc.get("objects", [])))
    # specific kinds first (they win overlaps and give the label), plain "fish" last as the catch-all
    plist = []
    # tested 11/1: descriptive species prompts ("pink seabream") make SAM find nothing; generic words work.
    # So SAM gets generic categories (non-fish first so they win overlaps), species come from the audit.
    for o in sc.get("objects", []):
        p = (o.get("sam_prompt") or "").strip().lower()
        if p and p != "fish" and len(p.split()) == 1 and p not in [q for _, q in plist] and len(plist) < 2:
            plist.append((p, p))
    for p in prompts or ["fish"]:
        if p not in [q for _, q in plist]:
            plist.append((p, p))
    jobs = [(f"p{i}", lab, p, clip, None) for i, (lab, p) in enumerate(plist)]
    disc, others, found = {}, [], []
    if do_discover:
        run.stage("discover", "Muse Spark looks for anything the request did not ask about")
        disc = discover(run, clip, inf, [q for _, q in plist], offline)
        run.save("discover.json", disc)
        used = {q for _, q in plist}
        for o in disc.get("others", []):
            # 11/1 s003: 'shell' found nothing but Spark's own name 'nautilus' tracked, so a short name goes first
            name = o.get("what", "").strip().lower().split()[-1:] if len(o.get("what", "").split()) <= 2 else []
            words = []
            for w in name + o.get("search_words", []):
                w = w.strip().lower()
                if w and w not in used and w not in words:
                    words.append(w)
            words = words[:3]
            if words and len(others) < 3:
                others.append((o, words))
        run.stage("discover", "Spark also sees: " + (", ".join(f"{o['what']} -> try {w}" for o, w in others) or "nothing else"))
    if do_zoom:
        cells = []
        for r in sc.get("faint_regions", []):
            if r.get("region") in CELLS and r["region"] not in cells:
                cells.append(r["region"])
        for cell in cells[:2]:
            box = cell_box(cell, inf["width"], inf["height"])
            tp = run.path(f"tile_{cell}.mp4")
            video.crop_tile(clip, tp, box, scale=2)
            jobs.append((f"zoom-{cell}", plist[-1][0], "fish", tp, box))
    est = (len(jobs) + sum(len(w) for _, w in others)) * max(api.SAM_MIN_FRAMES, inf["n_frames"]) * api.SAM_PER_FRAME
    run.stage("track", f"SAM 3.1 tracking {len(jobs)} prompt(s)/tile(s) in parallel: {[(j[2], j[0]) for j in jobs]} (est ${est:.2f} if not cached)")
    if est > max_usd and not offline:
        raise api.BudgetExceeded(f"estimate ${est:.2f} > per-video cap ${max_usd:.2f}")

    def one(job):
        name, label, prompt, path, box = job
        txt = _counted(run, api.sam_video, path, prompt, video.info(path)["n_frames"], offline=offline)
        d = tracks.parse_boxes(txt)
        return name, label, (tracks.from_tile(d, box, 2) if box else d), txt

    with cf.ThreadPoolExecutor(4) as ex:
        ladders = [ex.submit(word_ladder, run, clip, inf["n_frames"], words, offline) for _, words in others]
        results = list(ex.map(one, jobs))
        for i, ((o, _), fu) in enumerate(zip(others, ladders)):
            word, txt, tried = fu.result()
            found.append(dict(what=o["what"], why=o.get("why_notable"), word=word, tried=tried))
            run.stage("discover", f"{o['what']}: " + ", ".join(f"'{t['word']}' {t['frames']} frames" for t in tried))
            if word:
                results.append((f"d{i}", word, tracks.parse_boxes(txt), txt))
    raw = {name: (txt, next((j[4] for j in jobs if j[0] == name), None)) for name, _, _, txt in results}
    sources = [(name, label, d) for name, label, d, _ in results]
    frames, trk = tracks.merge(sources)
    n0 = len(trk)
    trk = tracks.stitch(frames, trk)
    run.stage("track", f"{n0} raw tracks -> {len(trk)} after re-joining broken IDs")

    verdicts = {}
    if do_audit:
        context = (json.dumps(sc.get("objects", []))[:600] + " " + json.dumps([f["what"] for f in found if f["word"]])).strip() or "none"
        for label in sorted({t["label"] for t in trk.values()}):
            run.stage("audit", f"Muse Spark checks every '{label}' track crop")
            verdicts.update(audit(run, clip, frames, trk, label, context, offline, start=len(verdicts)))
        n_flag = sum(1 for v in verdicts.values() if needs_review(v))
        run.stage("audit", f"{n_flag} of {len(verdicts)} tracks need a human look")

    labels = auto_labels(trk, verdicts)
    m = tracks.metrics(frames, trk, inf["n_frames"], inf["fps"], labels)
    result = dict(id=rid, source=os.path.basename(src), video=inf, prompts=plist, jobs=[dict(name=j[0], label=j[1], prompt=j[2], tile=j[4]) for j in jobs], scout=sc,
                  tracks={t: dict(v, n=len(v["frames"]), first=min(v["frames"]), last=max(v["frames"]), frames=None) for t, v in trk.items()},
                  verdicts=verdicts, auto_labels=labels, metrics=m,
                  discovered=found, signs=disc.get("signs", []),
                  frames={str(f): [dict(track=k["track"], box=[round(x, 1) for x in k["box"]]) for k in ks] for f, ks in frames.items()})
    run.save("result.json", result)
    run.stage("render", "drawing evidence frames")
    for name, mm in m.items():
        if mm["maxn_frame"] is not None:
            render.evidence(clip, raw, result, mm["maxn_frame"], run.path(f"evidence_{api_safe(name)}.jpg"))
    run.status["done"] = time.time()
    run.stage("done", f"finished in {run.status['done'] - run.status['started']:.0f}s; live calls {run.status['live_calls']}, cached {run.status['cached_calls']}, billed ${run.status['billed_usd']:.3f}")
    return result


def needs_review(v):
    return not v or v.get("confidence", 0) < 0.7 or v.get("is_target") is False


def auto_labels(trk, verdicts):
    """Confident Spark verdicts set the species label; confident rejections drop the track; everything else keeps
    "<category> (unidentified)" and goes to the human queue. A human edit overrides any of these."""
    out = {}
    for t, v in verdicts.items():
        conf = v.get("confidence", 0)
        if v.get("is_target") is False and conf >= 0.7:
            out[t] = None
        elif conf >= 0.7 and v.get("species") and v["species"] != "unknown":
            out[t] = v["species"].lower()
        else:
            out[t] = f"{trk[t]['label']} (unidentified)"
    return out


def api_safe(s):
    return "".join(ch if ch.isalnum() else "_" for ch in s)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--id")
    ap.add_argument("--offline", action="store_true", help="cache only, never call the API")
    ap.add_argument("--no-scout", action="store_true")
    ap.add_argument("--no-audit", action="store_true")
    ap.add_argument("--zoom", action="store_true")
    ap.add_argument("--discover", action="store_true", help="Spark names what was not asked for; SAM word ladder")
    ap.add_argument("--prompts", nargs="*")
    ap.add_argument("--max-usd", type=float, default=1.0)
    a = ap.parse_args()
    r = run_pipeline(a.video, a.id, a.offline, not a.no_scout, not a.no_audit, a.zoom, a.prompts, a.max_usd, a.discover)
    print(json.dumps({k: {x: y for x, y in v.items() if x != "curve"} for k, v in r["metrics"].items()}, indent=1))
