"""End-to-end run: ingest -> scout (Spark) -> track (SAM 3.1, parallel) -> zoom (optional) -> merge/stitch
-> audit (Spark) -> metrics -> evidence frames.  Each stage writes into runs/<id>/ and updates status.json,
which the web UI polls.
  python3 fishcount/pipeline.py <video> [--offline] [--no-scout] [--no-audit] [--zoom] [--prompts fish ...]"""
import argparse, concurrent.futures as cf, hashlib, json, os, re, shutil, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api, tracks, video, render, maskdedupe, motion
import requests
import cv2, numpy as np   # render put ~/meta-smoke/pylib on sys.path

RUNS = os.path.join(api.ROOT, "runs")
TILE_SCALE = 1.5   # a 2/3 block comes back to the clip's own size; SAM resizes internally anyway
CELL_SCALE = 3     # one 3x3 cell blown up to the clip's size: the closer look when a block finds nothing
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
{{"others":[{{"what":"your best identification","why_notable":"<=12 words","search_words":["most likely plain noun","second option","third option"],"frames":[ints],"approx_max_count":int,"cells":["regions where it appears, most visible first, from top-left|top|top-right|left|center|right|bottom-left|bottom|bottom-right"]}}],
 "signs":[{{"frame":int,"region":"one of top-left|top|top-right|left|center|right|bottom-left|bottom|bottom-right","sign":"<=12 words","possible_animal":"best guess or unknown"}}]}}
At most 4 others (most notable first) and 3 signs. Use empty lists if there are none."""

AUDIT_PROMPT = """You are checking detections from an automatic tracker in underwater survey video. Each tile is one tracked object, labelled with its track id (e.g. T3), shown at three moments of the clip (early, middle, late; same zoom, the orange box marks the object); the detector was asked to find "{label}". Context from an earlier look at the clip: {context}
For every tile return ONLY a JSON list: [{{"track":"T3","is_target":true|false,"species":"common name or 'unknown'","confidence":0.0-1.0,"reason":"<=10 words"}}]
is_target = the tile really shows a whole or partial {target} (not seagrass, rock, bubbles, debris, a shadow, or a duplicate fragment you cannot tell apart). Use all three crops: an animal keeps its body shape while it moves; weed sways in place and sediment changes shape. A hazy or faint {target} seen through water or seagrass is still a {target}. Be honest about uncertainty: blurry tiles should get low confidence."""

# 11/2 luderick 20190618_9: with one crop per track (its largest box), a faint fish behind seagrass was called
# "only seagrass and water" and its whole 36-frame track left the count. Three crops show the same body moving.
# 11/1 s004: per-track audit saw one crop per track (its largest box) and passed them all, yet in the MaxN frame
# most "shrimp" boxes sat on hagfish bodies. So the frame that sets each MaxN is checked box by box.
VERIFY_PROMPT = """Each tile is one object that an automatic tracker counted as "{name}" in a single frame of underwater survey video; this frame sets the maximum count, so every tile matters. Tiles are labelled D1, D2, ... Each tile shows that frame in the middle ("this frame", orange box) and the same tracked object about half a second before and after (left, right) at the same zoom.
For every tile return ONLY a JSON list: [{{"tile":"D1","is_target":true|false,"what_it_is":"<=6 words"}}]
is_target = the middle crop mainly shows a whole or partial {name}. Answer false when the box is on a different animal (for example part of an eel, hagfish or fish), a net, rope, pipe, rock, sediment or empty water. Use the side crops: an animal keeps its body shape while it moves; weed sways in place. If it is too blurry to tell, answer true and say "unclear"."""

# 11/2 luderick 20190618_9 frame 35: a single crop of a faint fish behind seagrass was called "seagrass and water"
# and the fish left 11 frames. The before/after crops show the same body moving.
# 11/2 s004 frame 24: the same shrimp was boxed twice by different passes (body only + body with legs), so it was
# counted twice. Masks find the candidates (one mask >=80% inside the other), but cannot tell a duplicate from
# s003's case: SAM drew one mask over two nautiluses and a zoom tile found the rear one alone (both counts right).
PAIR_PROMPT = """Each tile is a crop from one frame of underwater survey video with two outlines drawn on it: a RED outline and a CYAN outline, made by an automatic tracker. Tiles are labelled P1, P2, ...
For every tile return ONLY a JSON list: [{{"tile":"P1","same_animal":true|false,"what":"<=8 words"}}]
same_animal = true when the cyan outline marks the same single animal as the red one (or a part of it, for example its body without the legs or its head). false when the cyan outline marks a different individual, for example a second animal next to, behind or in front of the first, even if the red outline also spills over it."""


# 11/2 s003: a sediment cloud passed on one crop; three frames per spot (a person's eye did the same).
# 11/2 s004: a shrimp that no word, tile or reversed pass ever tracked moved against the still seabed; a box drawn
# on it (no word at all) made SAM track it in 57 of 60 frames. Movement only says "look here", so Spark decides.
MOTION_PROMPT = """Each group (M1, M2, ...) shows one spot of underwater survey video three times, left to right: early, middle and late in the clip, same zoom, following the spot. The orange rectangle marks where something moved and no detector has boxed anything yet.
For every group return ONLY a JSON list: [{{"tile":"M1","is_animal":true|false,"name":"one plain everyday English noun (shrimp, crab, fish, eel, worm, starfish, snail, octopus) or none","what":"<=8 words","confidence":0.0-1.0}}]
Compare the three crops: an animal keeps about the same shape and size (it may turn or move); a sand or sediment cloud spreads, thins or changes shape from crop to crop, and a shadow changes with the light.
Black areas are outside the picture: an animal cut off by the edge of the picture still counts.
is_animal = the rectangle mainly holds a living animal, even a small, pale, blurry or partly hidden one. Answer false for sand or sediment clouds, shadows, bubbles, bait or a bait bag, rope, net, rock, seagrass, empty water, or a tentacle, fin or tail of a bigger animal whose body is clearly elsewhere in the crops."""
# 11/2 s003 v13: a motion box on the trap's net legs got audit "large striped shrimp", 0.75 - the audit context listed
# that name (a discovery guess no word ever found) and the audit took it. A motion track rests on weak signals, so before
# it counts a second Spark look must agree: other moments of the track, no label, no names from earlier steps.
CONFIRM_PROMPT = """Each group (C1, C2, ...) follows one tracked object in underwater survey video at three moments (captions under the crops), same zoom; the orange rectangle marks the object. The tracker was started from a moving spot, so it may have locked onto something that is not an animal.
For every group return ONLY a JSON list: [{{"tile":"C1","is_animal":true|false,"name":"one plain noun or none","confidence":0.0-1.0,"reason":"<=10 words"}}]
is_animal = the rectangle holds the same living animal in the crops (a whole one or most of one; small, pale or blurry is fine). Answer false when it holds a part of a trap, net, mesh, rope, cans, bait, rock, seagrass, a shadow, sediment or empty water, or only a tentacle, fin or tail of a bigger animal whose body is elsewhere. Things fixed to the trap or seabed keep the same place against them in every crop; an animal changes place or pose. Be honest: if you cannot see an animal, answer false."""
MOTION_VERSION = "v7"   # bump to recompute the cached motion decisions (the key also hashes the prompt and the boxes)
def _motion_reply(text):
    """check= for the motion sheet: JSON naming at least one M tile (else not cached, asked once more)."""
    got = api.parse_json(text)
    if not any(isinstance(v, dict) and str(v.get("tile", "")).startswith("M") for v in (got if isinstance(got, list) else [got])):
        raise ValueError("motion reply names no tile")

MOTION_ERRORS = (FileNotFoundError, RuntimeError, ValueError, KeyError, TypeError, AttributeError, requests.RequestException)

class Run:
    def __init__(self, rid):
        self.id, self.dir = rid, os.path.join(RUNS, rid)
        os.makedirs(self.dir, exist_ok=True)
        self.status = dict(id=rid, stage="queued", log=[], live_calls=0, cached_calls=0, billed_usd=0.0, started=time.time())
        self._lock = threading.Lock()   # ladders and the second look call stage() from worker threads

    def path(self, *p):
        return os.path.join(self.dir, *p)

    def stage(self, name, msg=None):
        with self._lock:
            self.status["stage"] = name
            if msg:
                self.status["log"].append(f"{time.strftime('%H:%M:%S')} {msg}")
            tmp = self.path("status.json.tmp")     # the web UI polls this file; never let it read a half-written one
            with open(tmp, "w") as f:
                json.dump(self.status, f)
            os.replace(tmp, self.path("status.json"))

    def save(self, name, obj):
        json.dump(obj, open(self.path(name), "w"))


def _counted(run, fn, *a, **k):
    """Call an api function and record whether it hit the network (this thread logged spend) or the cache."""
    before = api.thread_spent()
    try:
        return fn(*a, **k)
    finally:    # a call that raises after paying (Spark's retry of a broken reply) still counts toward the cap
        d = api.thread_spent() - before
        with run._lock:
            run.status["live_calls" if d > 0 else "cached_calls"] += 1
            run.status["billed_usd"] += d


def cell_box(cell, W, H, pad=0.15):
    r, c = divmod(CELLS.index(cell), 3)
    w, h = W / 3, H / 3
    x0, y0 = max(0, c * w - pad * w), max(0, r * h - pad * h)
    x1, y1 = min(W, (c + 1) * w + pad * w), min(H, (r + 1) * h + pad * h)
    ev = lambda v: int(v) // 2 * 2
    return ev(x0), ev(y0), ev(x1 - x0), ev(y1 - y0)


def cell_tile(cell, W, H):
    """Exactly one 3x3 cell (x, y, w, h), even sizes. 11/2 s002: a ~40 px red crustacean was 0 in the 2x2 block
    at 1.5x but tracked in this cell at 3x."""
    r, c = divmod(CELLS.index(cell), 3)
    w, h = W // 3 // 2 * 2, H // 3 // 2 * 2
    return c * w, r * h, w, h


def block_box(cell, W, H):
    """A 2x2-cell block (2/3 of each side): the four corners or the centre, whichever is nearest the cell.
    11/1 s003: this block found 3 nautiluses where one 3x3 cell (cut through them) and a tighter 2x crop found 1."""
    r, c = divmod(CELLS.index(cell), 3)
    cx, cy = (c + 0.5) / 3, (r + 0.5) / 3
    origins = [(0, 0), (1 / 3, 0), (0, 1 / 3), (1 / 3, 1 / 3), (1 / 6, 1 / 6)]
    ox, oy = min(origins, key=lambda o: (o[0] + 1 / 3 - cx) ** 2 + (o[1] + 1 / 3 - cy) ** 2)
    ev = lambda v: int(v) // 2 * 2
    return ev(ox * W), ev(oy * H), ev(W * 2 / 3), ev(H * 2 / 3)


def scout(run, clip, inf, offline):
    n = inf["n_frames"]
    idx = sorted({int(i * (n - 1) / 5) for i in range(6)})
    fr = video.frames(clip, idx)
    sheet = video.grid([video.label(fr[i], f"frame {i}") for i in idx], 3, 640)
    reply = _counted(run, api.spark, SCOUT_PROMPT.format(n=len(idx)), [video.jpg(sheet, q=80)], offline=offline, check=api.parse_json)
    return api.parse_json(reply)


def discover(run, clip, inf, targets, offline):
    n = inf["n_frames"]
    idx = sorted({int(i * (n - 1) / 5) for i in range(6)})
    fr = video.frames(clip, idx)
    sheet = video.grid([video.label(fr[i], f"frame {i}") for i in idx], 3, 640)
    reply = _counted(run, api.spark, DISCOVER_PROMPT.format(targets=", ".join(targets), n=len(idx)), [video.jpg(sheet, q=80)], offline=offline, check=api.parse_json)
    return api.parse_json(reply)


def word_ladder(run, clip, n, words, offline):
    """Try SAM with each word in turn; stop at the first that tracks anything. Returns (word|None, text, tried).
    `clip` may be a zoom tile; then frames/boxes are in tile coordinates."""
    tried = []
    for w in words:
        txt = _counted(run, api.sam_video, clip, w, n, offline=offline)
        d = tracks.parse_boxes(txt)
        tried.append(dict(word=w, frames=len(d)))
        if d:
            return w, txt, tried
    return None, "", tried


def _paths(frames):
    """{track: [(frame, box)]} in frame order."""
    out = {}
    for f in sorted(frames):
        for k in frames[f]:
            out.setdefault(k["track"], []).append((f, k["box"]))
    return out


def _ibox(b):
    return [int(round(x)) for x in b]


def _half(trio_):
    """Crop half-size for a trio: the largest box side with a quarter of padding each way (as render.crop)."""
    return max(48, int(0.75 * max(max(b[2] - b[0], b[3] - b[1]) for _, b in trio_)))


def _three_idx(L, i, span):
    """Three path indices in time order around i (span each way). At an end of the path the missing side goes to
    the other side, so the three crops are three moments (11/2 review: a track whose largest box was its first
    frame showed that frame twice)."""
    if L < 3:
        return [0, i, L - 1]
    lo, hi = i - span, i + span
    if lo < 0:
        lo, hi = 0, min(L - 1, hi - lo)
    if hi > L - 1:
        lo, hi = max(0, lo - (hi - (L - 1))), L - 1
    if lo == i:
        return [i, (i + hi + 1) // 2, hi]
    if hi == i:
        return [lo, (lo + i) // 2, i]
    return [lo, i, hi]


def audit(run, clip, frames, trk, label, context, offline, per_sheet=12, start=0, target=None):
    """Show Spark three crops per track (early, largest box, late) in sheets of 12; returns {track: verdict}.
    Each sheet is saved as audit_<label>_<n>.jpg and each track's three crops as thumbs/T<k>_trio.jpg, so a person
    sees what Spark saw."""
    paths = {t: p for t, p in _paths(frames).items() if trk[t]["label"] == label}
    best, trios = {}, {}
    for t, p in paths.items():
        i = max(range(len(p)), key=lambda j: (p[j][1][2] - p[j][1][0]) * (p[j][1][3] - p[j][1][1]))
        best[t] = (None, p[i][0], p[i][1])
        trios[t] = [(p[j][0], _ibox(p[j][1])) for j in _three_idx(len(p), i, max(1, len(p) // 3))]
    ids = sorted(best, key=lambda t: best[t][1])
    names = {t: f"T{start + i + 1}" for i, t in enumerate(ids)}
    os.makedirs(run.path("thumbs"), exist_ok=True)
    out = {}
    for i in range(0, len(ids), per_sheet):
        chunk = ids[i:i + per_sheet]
        imgs = video.frames(clip, {f for t in chunk for f, _ in trios[t]})   # one sheet's frames at a time
        groups = []
        for t in chunk:
            _, f, b = best[t]
            crop = render.crop(imgs[f], b, pad=0.25, min_side=96)
            open(run.path("thumbs", f"{names[t]}.jpg"), "wb").write(video.jpg(crop, max_w=320))
            groups.append(motion.trio(imgs, trios[t], names[t], half=_half(trios[t])))
            open(run.path("thumbs", f"{names[t]}_trio.jpg"), "wb").write(video.jpg(groups[-1], max_w=900))
        del imgs
        sheet = motion.layout(groups)
        open(run.path(f"audit_{api_safe(label)}_{i // per_sheet + 1}.jpg"), "wb").write(sheet)
        reply = _counted(run, api.spark, AUDIT_PROMPT.format(label=label, target=target or label, context=context), [sheet], offline=offline, check=api.parse_json_list)
        for v in api.parse_json_list(reply):
            out[v["track"]] = v
    return {t: dict(out.get(names[t], {}), name=names[t], frame=best[t][1], box=best[t][2]) for t in ids}


def confirm_motion(run, clip, frames, ts, offline):
    """Second look at motion tracks the audit would count: crops at other moments than the audit's (the path's first
    and last eighth and its middle), no label and no earlier names in the prompt. Saved as confirm_<n>.jpg."""
    paths = _paths(frames)
    groups, names = [], {}
    trios = {}
    for t in ts:
        p = paths[t]
        L = len(p)
        # always three crops (a frame repeats on a 1-2 frame track): motion.layout needs equal-sized groups
        # (11/2 review: a 2-frame motion track made a 2-crop group and np.vstack killed the run)
        idx = [min(L - 1, L // 8), L // 2, max(0, L - 1 - L // 8)]
        trios[t] = [(p[j][0], _ibox(p[j][1])) for j in idx]
    imgs = video.frames(clip, {f for t in ts for f, _ in trios[t]})
    for i, t in enumerate(ts):
        names[t] = f"C{i + 1}"
        groups.append(motion.trio(imgs, trios[t], names[t], half=_half(trios[t]), words=("first", "middle", "last")[:len(trios[t])]))
    del imgs
    sheet = motion.layout(groups)
    open(run.path("confirm_1.jpg"), "wb").write(sheet)
    want = set(names.values())

    def every_tile(text):     # a reply that skips a tile is not cached (it would silently drop that track forever)
        got_ = {str(v.get("tile", "")).upper() for v in api.parse_json_list(text) if isinstance(v, dict)}
        if not want <= got_:
            raise ValueError(f"confirm reply misses {sorted(want - got_)}")
        return True
    reply = _counted(run, api.spark, CONFIRM_PROMPT, [sheet], offline=offline, check=every_tile)
    got = {str(v.get("tile", "")).upper(): v for v in api.parse_json_list(reply) if isinstance(v, dict)}
    return {t: got.get(names[t], {}) for t in ts}


def run_pipeline(src, rid=None, offline=False, do_scout=True, do_audit=True, do_zoom=False, prompts=None, max_usd=1.0,
                 do_discover=False, do_motion=None):
    """do_motion: run the motion residual (default: only when audits run, since unaudited motion tracks would be
    counted unchecked). The paper's no-audit discovery baseline sets it explicitly."""
    do_motion = (do_discover and do_audit) if do_motion is None else do_motion
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
        return name, label, (tracks.from_tile(d, box, 2) if box else d), txt, box

    with cf.ThreadPoolExecutor(4) as ex:
        ladders = [ex.submit(word_ladder, run, clip, inf["n_frames"], words, offline) for _, words in others]
        results = list(ex.map(one, jobs))
        for i, ((o, _), fu) in enumerate(zip(others, ladders)):
            word, txt, tried = fu.result()
            found.append(dict(what=o["what"], why=o.get("why_notable"), word=word, tried=tried,
                              maxn_full=tracks.max_per_frame(tracks.parse_boxes(txt)), expected=o.get("approx_max_count")))
            run.stage("discover", f"{o['what']}: " + ", ".join(f"'{t['word']}' {t['frames']} frames" for t in tried))
            if word:
                results.append((f"d{i}", word, tracks.parse_boxes(txt), txt, None))
    recovered = recover(run, clip, inf, others, found, disc.get("signs", []), results, max_usd, offline) if do_discover else []
    moved = []
    if do_motion:
        try:
            moved = motion_look(run, clip, inf, results, max_usd, offline, names=[f["what"] for f in found])
        except MOTION_ERRORS as e:
            run.stage("motion", f"motion look skipped: {type(e).__name__}: {str(e)[:160]}")
        recovered += moved
    raw = {name: (txt, tile) for name, _, _, txt, tile in results}   # tile=None: full-frame text (masks drawable)
    sources = [(name, label, d) for name, label, d, _, _ in results]
    frames, trk = tracks.merge(sources)
    n0 = len(trk)
    trk = tracks.stitch(frames, trk)
    run.stage("track", f"{n0} raw tracks -> {len(trk)} after re-joining broken IDs")

    verdicts = {}
    if do_audit:
        context = (json.dumps(sc.get("objects", []))[:600] + " " + json.dumps([f["what"] for f in found])).strip() or "none"
        # a discovered word is only SAM's handle ("eel"); ask about the animal Spark named ("hagfish")
        asked = {f["word"]: f["what"] for f in found if f["word"]}
        for label in sorted({t["label"] for t in trk.values()}):
            run.stage("audit", f"Muse Spark checks every '{label}' track crop")
            verdicts.update(audit(run, clip, frames, trk, label, context, offline, start=len(verdicts), target=asked.get(label)))
        n_flag = sum(1 for v in verdicts.values() if needs_review(v))
        run.stage("audit", f"{n_flag} of {len(verdicts)} tracks need a human look")

    labels = auto_labels(trk, verdicts)
    # every word of every discovered name: "small red crab on seabed" must match an audit "small red crab" (11/2 s002 v13:
    # norm_label kept only "seabed", so the red crab the discovery step had named was dropped as "not a shrimp")
    seen = {_head(f["what"]) for f in found} - {None}
    for t, v in verdicts.items():
        # a discovered track (word ladder) that the audit confidently calls another animal the discovery step had
        # also named is that animal: two looks agree (s002: 'shrimp' word -> audit "small red crab", 0.7)
        if (trk[t]["source"].startswith("d") and v.get("is_target") is False and _conf(v) >= 0.7
                and norm_label(v.get("species") or "") in seen):
            labels[t] = v["species"].lower()
            v["relabelled"] = f"{trk[t]['label']} -> {labels[t]}"
            continue
        # a motion label is Spark's one-word guess from a small crop; when the audit says "not a <guess>" but
        # confidently names an animal the discovery step had already named on its own, the track is that animal
        # (11/2 s001 v13: "snail" -> audit "not a snail; nautilus, shell and tentacles clear", 0.9). The peak check
        # below then checks its boxes under the new name.
        if (trk[t]["source"].startswith("m") and v.get("is_target") is False and _conf(v) >= 0.7
                and norm_label(v.get("species") or "") in seen):
            labels[t] = v["species"].lower()
            v["relabelled"] = f"{trk[t]['label']} -> {labels[t]}"
            continue
        # a motion track rests on two weak signals (it moved; Spark thought one crop looked alive), so it is counted
        # only on a confident audit yes. Otherwise it stays in Needs a person, where a human can restore it.
        # 11/2 s004 v11: a box that drifted onto net mesh and hagfish got "obscured shrimp", confidence 0.4.
        if trk[t]["source"].startswith("m") and needs_review(v):
            labels[t] = None
    if do_audit:
        for f in os.listdir(run.path()):
            if f.startswith("confirm_") and f.endswith(".jpg"):
                os.remove(run.path(f))
        # motion tracks, and discovered tracks relabelled from a primed audit (its context lists the discovery names)
        sure = [t for t in verdicts if labels.get(t) and (trk[t]["source"].startswith("m") or verdicts[t].get("relabelled"))]
        if sure:
            said = confirm_motion(run, clip, frames, sure, offline)
            for t in sure:
                c = said.get(t, {})
                verdicts[t]["confirm"] = c
                # this look only asks "animal or not" (net, shadow); the species confidence (>= 0.7) is the audit's
                # job, so a plain yes is enough here (11/2 s004 v14: two shrimp the eye confirms got yes at 0.6/0.65)
                if not (c.get("is_animal") is True and _conf(c) >= 0.5):
                    labels[t] = None
            run.stage("audit", f"second look at {len(sure)} motion or renamed track(s) before they count: "
                      + ", ".join(f"{verdicts[t]['name']} {'yes' if labels[t] else 'no'} ({said.get(t, {}).get('reason', 'no answer')})" for t in sure))
    for mv in moved:
        if mv.get("source"):
            mine_t = [t for t, v in trk.items() if v["source"] == mv["source"]]
            mv["counted"] = any(labels.get(t, trk[t]["label"]) for t in mine_t)
    dups = []
    if do_audit:
        dec = maskdedupe.decode_sources(raw, inf["width"], inf["height"])
        dups = same_animal_pairs(run, clip, frames, trk, labels, dec, offline)
        if dups:
            run.stage("verify", f"Muse Spark looks at {len(dups)} pairs of nested outlines: {sum(d['same'] for d in dups)} are one animal counted twice"
                      + "".join(f"; kept apart: {d['said']}" for d in dups if not d["same"]))
    checks = verify_peaks(run, clip, frames, trk, labels, inf["n_frames"], inf["fps"], offline) if do_audit else []
    m = tracks.metrics(frames, trk, inf["n_frames"], inf["fps"], labels)
    for name, mm in m.items():
        mm["peak_checked"] = any(c["label"] == name and c["frame"] == mm["maxn_frame"] for c in checks)
    result = dict(id=rid, source=os.path.basename(src), video=inf, prompts=plist, jobs=[dict(name=j[0], label=j[1], prompt=j[2], tile=j[4]) for j in jobs], scout=sc,
                  tracks={t: dict(v, n=len(v["frames"]), first=min(v["frames"]), last=max(v["frames"]), frames=None) for t, v in trk.items()},
                  verdicts=verdicts, auto_labels=labels, metrics=m,
                  discovered=found, signs=disc.get("signs", []), recovered=recovered, peak_checks=checks, duplicates=dups,
                  frames={str(f): [dict(track=k["track"], box=[round(x, 1) for x in k["box"]]) for k in ks] for f, ks in frames.items()})
    run.save("result.json", result)
    run.stage("render", "drawing evidence frames")
    for name, mm in m.items():
        if mm["maxn_frame"] is not None:
            render.evidence(clip, raw, result, mm["maxn_frame"], run.path(f"evidence_{api_safe(name)}.jpg"))
    run.stage("render", "drawing the annotated video")
    render.annotate(clip, raw, result, run.path("annotated.mp4"))
    run.status["done"] = time.time()
    run.stage("done", f"finished in {run.status['done'] - run.status['started']:.0f}s; live calls {run.status['live_calls']}, cached {run.status['cached_calls']}, billed ${run.status['billed_usd']:.3f}")
    return result


def recover(run, clip, inf, others, found, signs, results, max_usd, offline, max_tiles=3):
    """Second look for discovered animals (11/1 s003: full frame 'nautilus' tracked 1 of 3; a zoomed crop tracked
    all 3, and a reversed pass back-filled the frames before SAM first recognised it).
      backfill: the word that worked, run again on the reversed clip;
      zoom:     Spark expected more than SAM found -> crop the cells Spark named and run the ladder there;
      sign:     an indirect sign (sand puff, shadow) -> crop that cell and try the words for the suspected animal.
    Appends (name, label, dets, text, tile) to `results`; returns a log for the UI."""
    n, W, H = inf["n_frames"], inf["width"], inf["height"]
    jobs, log = [], []
    for i, ((o, words), f) in enumerate(zip(others, found)):
        if f["word"]:
            jobs.append(dict(kind="backfill", name=f"d{i}rev", what=o["what"], words=[f["word"]], cell=None))
        if (f["maxn_full"] or 0) < int(o.get("approx_max_count") or 1):
            ladder = ([f["word"]] if f["word"] else []) + [w for w in words if w != f["word"]]
            for cell in [c for c in o.get("cells", []) if c in CELLS][:2]:
                jobs.append(dict(kind="zoom", name=f"d{i}z-{cell}", what=o["what"], words=ladder[:2], ladder=ladder[:3], cell=cell))
    for j, sg in enumerate(signs):
        guess = (sg.get("possible_animal") or "").lower()
        if sg.get("region") not in CELLS or "unknown" in guess:
            continue
        match = next((f for f in found if f["word"] and (f["word"] in guess or guess in f["what"].lower())), None)
        words = [match["word"]] if match else [w for w in guess.split()[-1:] if w.isalpha()]
        if words:
            jobs.append(dict(kind="sign", name=f"s{j}-{sg['region']}", what=sg.get("sign", ""), words=words, cell=sg["region"]))
    seen, todo = set(), []
    for jb in jobs:     # one tile per (block, first word); backfills always kept, tiles capped
        key = (jb["cell"] and block_box(jb["cell"], W, H), jb["words"][0])
        if key in seen or (jb["cell"] and sum(1 for t in todo if t["cell"]) >= max_tiles):
            continue
        seen.add(key)
        todo.append(jb)
    est = sum(len(jb["words"]) for jb in todo) * max(api.SAM_MIN_FRAMES, n) * api.SAM_PER_FRAME
    if not todo:
        return log
    if run.status["billed_usd"] + est > max_usd and not offline:
        run.stage("recover", f"skipped second look: est ${est:.2f} would pass the per-video cap ${max_usd:.2f}")
        return log
    run.stage("recover", "second look: " + ", ".join(f"{jb['kind']} {jb['cell'] or ''} {jb['words']}".replace("  ", " ") for jb in todo))
    rev = run.path("clip_rev.mp4")
    if any(jb["kind"] == "backfill" for jb in todo):
        video.reverse(clip, rev)
    for jb in todo:
        if jb["cell"]:
            jb["box"] = block_box(jb["cell"], W, H)
            jb["path"] = run.path(f"tile_{jb['name']}.mp4")
            video.crop_tile(clip, jb["path"], jb["box"], scale=TILE_SCALE)
        else:
            jb["box"], jb["path"] = None, rev

    def one(jb):
        word, txt, tried = word_ladder(run, jb["path"], video.info(jb["path"])["n_frames"], jb["words"], offline)
        return jb, word, txt, tried

    with cf.ThreadPoolExecutor(3) as ex:
        for jb, word, txt, tried in ex.map(one, todo):
            entry = dict(kind=jb["kind"], what=jb["what"], cell=jb["cell"], tried=tried, word=word)
            if word:
                if jb["box"]:
                    d = tracks.from_tile(tracks.parse_boxes(txt), jb["box"], TILE_SCALE)
                else:
                    txt = tracks.reverse_text(txt, n)
                    d = tracks.parse_boxes(txt)
                entry.update(frames=len(d), max_per_frame=tracks.max_per_frame(d))
                results.append((jb["name"], word, d, txt, jb["box"]))
            log.append(entry)
            run.stage("recover", f"{jb['kind']} {jb['cell'] or 'reversed'}: " + ", ".join(f"'{t['word']}' {t['frames']} frames" for t in tried))
    closer = [dict(jb, kind="cell", name=jb["name"].replace("z-", "c-"), words=jb["ladder"]) for jb in todo
              if jb["kind"] == "zoom" and not any(e["kind"] == "zoom" and e["what"] == jb["what"] and e["cell"] == jb["cell"] and e["word"] for e in log)]
    if closer:
        log += closer_look(run, clip, inf, closer, results, max_usd, offline)
    return log


def _head(name):
    """Head noun of a discovered name: last word before a place phrase. "small red crab on seabed" -> "crab"
    (norm_label alone gave "seabed"; 11/2 review: matching every word would let an audit species "seabed" or "bait"
    relabel a weed track into a counted row)."""
    ws = re.sub(r"[^a-z ]", " ", (name or "").lower()).split()
    for i, w in enumerate(ws):
        if w in ("on", "at", "in", "near", "by", "under", "over", "with", "from", "behind", "inside", "beside", "among"):
            ws = ws[:i]
            break
    return norm_label(" ".join(ws))


def norm_label(name):
    """Spark's name -> one SAM-style label: lowercase last word, plural dropped, vague words refused."""
    ws = re.sub(r"[^a-z ]", " ", (name or "").lower()).split()
    if not ws:
        return None
    w = ws[-1]
    if w in ("none", "unknown", "animal", "creature", "thing", "object", "organism", "unclear"):
        return None
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"                       # jellies -> jelly
    elif len(w) > 4 and w.endswith(("shes", "ches", "xes")):
        w = w[:-2]                             # fishes -> fish
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    return w


def _absorb(d, prior, thr=0.3, min_frames=3):
    """A motion track lying on an existing track (IoU >= thr) in `min_frames` or more frames takes that track's
    label (11/2 review: 'crab' over a tracked 'shrimp' in a few frames was counted twice under two names). The
    overlapping frames are removed either way; merge() only catches IoU >= 0.5 and only within one label."""
    hits, out = {}, {}
    for f, ds in d.items():
        keep, hit_here = [], set()
        for det in ds:
            best = max(((tracks.iou(det["box"], k["box"]), lab) for _, lab, pd, _, _ in prior for k in pd.get(f, [])),
                       key=lambda t: t[0], default=(0, None))
            if best[0] >= thr:
                hit_here.add(best[1])
            else:
                keep.append(det)
        for lab in hit_here:
            hits[lab] = hits.get(lab, 0) + 1
        out[f] = keep
    lab, n = max(hits.items(), key=lambda t: t[1], default=(None, 0))
    return out, (lab if n >= min_frames else None), sum(1 for f, ds in d.items() if len(out[f]) < len(ds))


def _named(v, names):
    """Label for a motion spot: a discovered name that Spark's own description uses wins over its one-word name
    (11/2 s001 v12: 'striped nautilus shell approaching' got name 'snail', because the prompt's example nouns
    leave out nautilus, so the nautilus track was counted as 'snail')."""
    words = set(re.sub(r"[^a-z ]", " ", str(v.get("what") or "").lower()).split())
    for nm in names:
        lab = norm_label(nm)
        if lab and (lab in words or lab + "s" in words or lab + "es" in words):
            return lab
    return norm_label(v.get("name") if isinstance(v.get("name"), str) else "")


def motion_look(run, clip, inf, results, max_usd, offline, k=8, max_boxes=5, min_conf=0.6, names=()):
    """Look where pixels moved but nothing was boxed (fishcount/motion.py): up to `k` spots go to Spark on one
    sheet; up to `max_boxes` it calls animals go to SAM as box prompts, no word. Appends ("m<i>", label, dets,
    text, None) to `results`; returns log entries for the UI. Spark's verdict and the chosen boxes are cached per
    clip (cache/motion_<sha>_<ver>.json), so a free replay does not depend on re-deriving the same sheet bytes."""
    n, W, H = inf["n_frames"], inf["width"], inf["height"]
    known = {}
    for _, _, d, _, _ in results:            # +-3 frames: a box SAM lost for a frame still covers its animal
        for f, ds in d.items():
            for g in range(max(0, f - 3), min(n, f + 4)):
                known.setdefault(g, []).extend(list(det["box"]) for det in ds)
    # keyed by what decides the spots (clip, boxes already found, prompt), so a free replay of the same run finds
    # it and a run with other prompts does not reuse it
    kb = json.dumps(sorted((f, sorted([round(v) for v in b] for b in bs)) for f, bs in known.items()))
    key = hashlib.sha256((api.file_sha(clip) + kb + MOTION_PROMPT + MOTION_VERSION).encode()).hexdigest()[:24]
    cpath = os.path.join(api.CACHE, f"motion_{key}.json")
    sheet_jpg = run.path("motion_sheet.jpg")
    est = 0.04 + max_boxes * max(api.SAM_MIN_FRAMES, n) * api.SAM_PER_FRAME
    if run.status["billed_usd"] + est > max_usd and not offline:
        run.stage("motion", f"skipped motion look: est ${est:.2f} would pass the per-video cap ${max_usd:.2f}")
        return []
    if os.path.exists(cpath):
        mc = json.load(open(cpath))
        if mc.get("sheet"):
            shutil.copy(os.path.join(api.CACHE, mc["sheet"]), sheet_jpg)
        run.stage("motion", f"motion look (saved): {mc['n_candidates']} moving spots outside every box, Spark saw {len(mc['said'])}")
    elif offline:
        run.stage("motion", "motion look not cached for this clip: skipped in the free replay")
        return [dict(kind="motion-scan", what="Movement outside every box", tried=[], word=None, note="not cached")]
    else:
        run.stage("motion", "looking for movement outside every box (pixels only, no model)")
        cands, _ = motion.candidates(clip, known)
        picks = motion.pick(cands, k=k)
        said, meta, sheet_name = {}, [], None
        if picks:
            jpg, meta = motion.sheet(clip, picks, W, H, n=n)
            sheet_name = f"motion_{key}.jpg"
            open(os.path.join(api.CACHE, sheet_name), "wb").write(jpg)
            open(sheet_jpg, "wb").write(jpg)
            run.stage("motion", f"{len(cands)} moving spots outside every box; Muse Spark looks at the {len(picks)} longest-lived")
            reply = _counted(run, api.spark, MOTION_PROMPT, [jpg], offline=offline, check=_motion_reply)
            got = api.parse_json(reply)
            for v in (got if isinstance(got, list) else [got]):
                if isinstance(v, dict):
                    said[str(v.get("tile"))] = v
            if not any(f"M{i}" in said for i, _, _ in meta):
                raise ValueError(f"Spark's motion reply named no tile: {reply[:120]!r}")   # _motion_reply kept it out of the cache
        mc = dict(n_candidates=len(cands), sheet=sheet_name,
                  said=[dict(said.get(f"M{i}", {}), tile=f"M{i}", frame=t, box=b) for i, t, b in meta])
        with open(cpath + ".tmp", "w") as fh:
            json.dump(mc, fh)
        os.replace(cpath + ".tmp", cpath)
    def conf(v):
        try:
            return float(v.get("confidence") or 0)
        except (TypeError, ValueError):
            return 0.0
    chosen = []
    # most confident first (11/2 review: in sheet order three boxes used the cap before a likelier spot was tried)
    for v in sorted(mc["said"], key=lambda v: -conf(v)):
        lab = _named(v, names)
        if v.get("is_animal") is not True or conf(v) < min_conf or not lab:
            continue
        # two spots on one animal (11/2 review): one SAM call, not two
        # (>= 0.3 as for "already followed" below; 11/2 s001 v13: two nautiluses passing each other, boxes touching
        # by 16 px at frames 40 and 44, were taken for one and the second was never tracked)
        if any(abs(v["frame"] - c["frame"]) <= 5 and tracks.overlap(v["box"], c["box"]) >= 0.3 for c in chosen):
            continue
        chosen.append(dict(v, label=lab))
        if len(chosen) >= max_boxes + 2:    # spare ones in case an earlier box already followed the animal
            break
    log = [dict(kind="motion-scan", what="Movement outside every box", tried=[], word=None, candidates=mc["n_candidates"],
                shown=len(mc["said"]), animals=sum(1 for v in mc["said"] if v.get("is_animal") is True),
                said=[dict(tile=v["tile"], is_animal=v.get("is_animal"), what=v.get("what"), confidence=v.get("confidence")) for v in mc["said"]])]
    if not chosen:
        run.stage("motion", "Spark: none of the moving spots is an animal")
        return log
    run.stage("motion", "SAM 3.1 tracks from a box, no word: " + ", ".join(f"{c['tile']} {c['what']} (frame {c['frame']})" for c in chosen))

    def one(c):
        prompt = motion.box_prompt(c["frame"], c["box"], W, H)
        return c, _counted(run, api.sam_video, clip, prompt, n, offline=offline)

    # one at a time: SAM tracks a box both ways through the clip, so a later spot may be the animal an earlier box
    # already followed (11/2 s004: M4 at frame 34 and M7 at frame 50 were one red shrimp) -> skip, no second call
    prior, mine, calls = list(results), [], 0
    for i, c in enumerate(chosen):
        entry = dict(kind="motion", tile=c["tile"], what=c.get("what") or c["label"], cell=None, frame=c["frame"], box=c["box"],
                     tried=[dict(word="box", frames=None)], word=None)
        if calls >= max_boxes:      # failed calls count too: the estimate above covers max_boxes
            break
        same = next((t for t, d in mine if any(tracks.overlap(c["box"], k["box"]) >= 0.3 for k in d.get(c["frame"], []))), None)
        if same:
            entry.update(note=f"already followed by {same}")
            log.append(entry)
            run.stage("motion", f"{c['tile']}: already followed by the {same} box, no second call")
            continue
        calls += 1
        try:
            _, txt = one(c)
        except MOTION_ERRORS as e:
            entry["note"] = f"{type(e).__name__}: {str(e)[:120]}"
            log.append(entry)
            run.stage("motion", f"{c['tile']}: SAM box prompt failed ({entry['note']})")
            continue
        d0 = tracks.parse_boxes(txt)
        d, took, clash = _absorb(d0, prior)
        label = took or c["label"]
        k_frames = sum(1 for ds in d.values() if ds)
        entry.update(word=label if k_frames else None, frames=k_frames, max_per_frame=tracks.max_per_frame(d),
                     raw_frames=sum(1 for ds in d0.values() if ds), overlapped=clash, absorbed_into=took)
        entry["tried"] = [dict(word="box", frames=k_frames)]
        mine.append((c["tile"], d0))
        if k_frames:
            results.append((f"m{i}", label, d, txt, None))
            entry["source"] = f"m{i}"
        log.append(entry)
        run.stage("motion", f"{c['tile']} box -> '{label}' tracked in {k_frames} of {n} frames"
                  + (f" ({clash} frames already tracked removed" + (f", joined '{took}')" if took else ")") if clash else ""))
    return log


def closer_look(run, clip, inf, jobs, results, max_usd, offline):
    """A block found nothing: crop just the cell Spark named at 3x and try every word, keeping the one tracked in
    the most frames (11/2 s002: 'crab' fired 5 frames on the nautilus' shell edge, 'shrimp' 12 frames on the real
    crustacean; stopping at the first hit would keep the wrong one). Then the same word on the reversed cell
    back-fills the frames before SAM recognised it (s002: 12 -> 58 of 60 frames, one track)."""
    n, W, H = inf["n_frames"], inf["width"], inf["height"]
    jobs = jobs[:2]
    est = sum(len(jb["words"]) + 1 for jb in jobs) * max(api.SAM_MIN_FRAMES, n) * api.SAM_PER_FRAME
    if run.status["billed_usd"] + est > max_usd and not offline:
        run.stage("recover", f"skipped closer look: est ${est:.2f} would pass the per-video cap ${max_usd:.2f}")
        return []
    run.stage("recover", "closer look, one cell at 3x: " + ", ".join(f"{jb['what']} in {jb['cell']} {jb['words']}" for jb in jobs))

    def one(jb):
        box = cell_tile(jb["cell"], W, H)
        path = run.path(f"tile_{jb['name']}.mp4")
        video.crop_tile(clip, path, box, scale=CELL_SCALE)
        tried, best = [], (0, None, "")
        for w in jb["words"]:
            try:
                txt = _counted(run, api.sam_video, path, w, n, offline=offline)
            except FileNotFoundError:   # free replay of a run made before this step existed
                tried.append(dict(word=w, frames=None, note="not cached"))
                return jb, box, (0, None, ""), tried, ""
            k = sum(1 for ds in tracks.parse_boxes(txt).values() if ds)
            tried.append(dict(word=w, frames=k))
            if k > best[0]:
                best = (k, w, txt)
        rev = ""
        if best[1]:
            rp = run.path(f"tile_{jb['name']}_rev.mp4")
            video.reverse(path, rp)
            rev = tracks.reverse_text(_counted(run, api.sam_video, rp, best[1], n, offline=offline), n)
        return jb, box, best, tried, rev

    log = []
    with cf.ThreadPoolExecutor(2) as ex:
        for jb, box, (k, word, txt), tried, rev in ex.map(one, jobs):
            entry = dict(kind="cell", what=jb["what"], cell=jb["cell"], tried=tried, word=word)
            if word:
                fw = tracks.from_tile(tracks.parse_boxes(txt), box, CELL_SCALE)
                bw = tracks.from_tile(tracks.parse_boxes(rev), box, CELL_SCALE)
                results.append((jb["name"], word, fw, txt, box))
                results.append((jb["name"] + "rev", word, bw, rev, box))
                both = {f for f, ds in list(fw.items()) + list(bw.items()) if ds}
                entry.update(frames=len(both), max_per_frame=max(tracks.max_per_frame(fw), tracks.max_per_frame(bw)))
            log.append(entry)
            run.stage("recover", f"cell {jb['cell']} 3x: " + ", ".join(f"'{t['word']}' {t['frames'] if t['frames'] is not None else 'not cached'}" + (" frames" if t["frames"] is not None else "") for t in tried)
                      + (f"; '{word}' reversed fills {entry['frames']} of {n} frames" if word else ""))
    return log


def _sides(ps, f, gap):
    """[(frame, caption)] x3 for checking frame f of a track with frames `ps`: before / this frame / after, "this
    frame" always in the middle. When the track starts or ends at f, the missing side repeats f.
    11/2 v13 tried moving "this frame" to the first/last crop with two crops on the other side (review: a repeated
    frame wastes a crop): luderick 20190618_9 frame 35, where a faint fish's track starts, was rejected as
    "seagrass, no fish" again and recall fell 97.4 -> 96.3%. With the frame repeated Spark sees the faint fish twice."""
    before = max((g for g in ps if g <= f - gap), default=min(ps))
    after = min((g for g in ps if g >= f + gap), default=max(ps))
    return [(before, "before"), (f, "this frame"), (after, "after")]


def verify_peaks(run, clip, frames, trk, labels, n, fps, offline, rounds=3, window=5, per_sheet=12, side_gap=3):
    """Spark checks every box in the frame that sets each label's MaxN, each with the same track `side_gap` frames
    before and after. A rejected box removes that track for +-`window` frames (1 s at 5 fps), the curve is
    recomputed, and the new peak frame is checked, up to `rounds`. Mutates `frames`; returns one log entry per
    checked frame."""
    log, done = [], set()
    lab = lambda t: labels.get(t, trk[t]["label"])
    for _ in range(rounds):
        m = tracks.metrics(frames, trk, n, fps, labels)
        todo = [(name, mm["maxn_frame"]) for name, mm in m.items() if mm["maxn_frame"] is not None and (name, mm["maxn_frame"]) not in done]
        if not todo:
            break
        paths = _paths(frames)
        trios = {}
        for name, f in todo:
            for k in frames[f]:
                if lab(k["track"]) != name:
                    continue
                p = dict(paths[k["track"]])
                gw = _sides(sorted(p), f, side_gap)
                trios[(f, k["track"])] = ([(g, _ibox(p[g] if g != f else k["box"])) for g, _ in gw], tuple(w for _, w in gw))
        imgs = video.frames(clip, {g for tr, _ in trios.values() for g, _ in tr} | {f for _, f in todo})
        for name, f in todo:
            done.add((name, f))
            ks = [k for k in frames[f] if lab(k["track"]) == name]
            groups = [motion.trio(imgs, trios[(f, k["track"])][0], f"D{i + 1}", half=_half(trios[(f, k["track"])][0]),
                                  words=trios[(f, k["track"])][1]) for i, k in enumerate(ks)]
            said = {}
            word = name.replace(" (unidentified)", "")
            # ask about the requested category, not the species the audit proposed: asked "striped seabream?", Spark
            # removed a real fish as "other fish" (paper Table 4b), and it is then counted under no label at all
            if ks and all(trk[k["track"]]["source"].startswith("p") for k in ks):
                word = trk[ks[0]["track"]]["label"]
            for i in range(0, len(groups), per_sheet):
                sheet = motion.layout(groups[i:i + per_sheet])
                open(run.path(f"verify_{api_safe(name)}_f{f}_{i // per_sheet + 1}.jpg"), "wb").write(sheet)
                reply = _counted(run, api.spark, VERIFY_PROMPT.format(name=word), [sheet], offline=offline, check=api.parse_json_list)
                for v in api.parse_json_list(reply):
                    said[v.get("tile")] = v
            bad = [(k, said[f"D{i + 1}"]) for i, k in enumerate(ks) if said.get(f"D{i + 1}", {}).get("is_target") is False]
            drop = {k["track"] for k, _ in bad}
            for g in range(max(0, f - window), f + window + 1):
                if g in frames:
                    frames[g] = [k for k in frames[g] if k["track"] not in drop]
            log.append(dict(label=name, frame=f, checked=len(ks), kept=len(ks) - len(bad),
                            rejected=[dict(track=k["track"], box=[round(x) for x in k["box"]], said=v.get("what_it_is")) for k, v in bad]))
            run.stage("verify", f"{name}: Spark checks all {len(ks)} boxes in peak frame {f} (with the track just before and after), rejects {len(bad)}"
                      + (": " + "; ".join(sorted({v.get('what_it_is', '?') for _, v in bad})) if bad else ""))
    return log


def same_animal_pairs(run, clip, frames, trk, labels, dec, offline, contain=0.8):
    """Every nested pair in the clip (two counted detections of the same SAM word, one mask >= `contain` inside
    the other) goes to Spark once, shown in the frame where it nests most, as "same animal or two?". For a
    duplicate the smaller-mask track is removed from each frame where it nests inside the other.
    Mutates `frames`; returns [dict(outer, inner, frame, containment, same, said)]."""
    lab = lambda t: labels.get(t, trk[t]["label"])
    best = {}   # (outer, inner) -> (containment, frame, outer mask, inner mask)
    for f, ks in frames.items():
        ms = [maskdedupe.det_mask(dec, k["track"].split(":")[0], f, k["box"]) for k in ks]
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                a, b = ks[i]["track"], ks[j]["track"]
                if a == b or not (lab(a) and lab(b)) or trk[a]["label"] != trk[b]["label"] or tracks.overlap(ks[i]["box"], ks[j]["box"]) <= 0:
                    continue
                c = maskdedupe.containment(ms[i], ms[j])
                if c is None or c < contain:
                    continue
                o, n_ = (i, j) if ms[i][0].sum() >= ms[j][0].sum() else (j, i)
                key = (ks[o]["track"], ks[n_]["track"])
                if key[::-1] in best:   # sizes swap between frames: keep one orientation per pair
                    key, o, n_ = key[::-1], n_, o
                if key not in best or c > best[key][0]:
                    best[key] = (c, f, ms[o], ms[n_])
    if not best:
        return []
    pairs = sorted(best, key=lambda k: best[k][1])
    imgs = video.frames(clip, {best[k][1] for k in pairs})
    tiles = [video.label(render.square(pair_tile(imgs[best[k][1]], best[k][2], best[k][3]), 256), f"P{i + 1}") for i, k in enumerate(pairs)]
    said = {}
    for i in range(0, len(tiles), 16):
        sheet = video.jpg(video.grid(tiles[i:i + 16], 4, 256), q=85)
        open(run.path(f"pairs_{i // 16 + 1}.jpg"), "wb").write(sheet)
        reply = _counted(run, api.spark, PAIR_PROMPT, [sheet], offline=offline, check=api.parse_json_list)
        for v in api.parse_json_list(reply):
            said[v.get("tile")] = v
    out = []
    for i, (o, in_) in enumerate(pairs):
        v = said.get(f"P{i + 1}", {})
        same = v.get("same_animal") is True
        out.append(dict(outer=o, inner=in_, frame=best[(o, in_)][1], containment=round(best[(o, in_)][0], 2), same=same, said=v.get("what")))
        if same:
            drop_nested(frames, dec, o, in_, contain)
    return out


def pair_tile(img, mo, mi, pad=0.3):
    """Crop around a nested pair with the outer mask outlined red and the inner one cyan."""
    H, W = img.shape[:2]
    out = img.copy()
    boxes = []
    for (m, x0, y0), col in ((mo, (0, 0, 255)), (mi, (255, 255, 0))):
        cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, [c + (x0, y0) for c in cs], -1, col, 3)
        boxes.append((x0, y0, x0 + m.shape[1], y0 + m.shape[0]))
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    return render.crop(out, (x0, y0, x1, y1), pad=pad, min_side=96)


def drop_nested(frames, dec, outer, inner, contain):
    """Remove `inner` from each frame where both tracks are present and inner's mask lies inside outer's."""
    for g, ks in frames.items():
        ko = next((k for k in ks if k["track"] == outer), None)
        ki = next((k for k in ks if k["track"] == inner), None)
        if not ko or not ki:
            continue
        mo = maskdedupe.det_mask(dec, outer.split(":")[0], g, ko["box"])
        mi = maskdedupe.det_mask(dec, inner.split(":")[0], g, ki["box"])
        c = maskdedupe.containment(mo, mi)
        if c is not None and c >= contain:
            frames[g] = [k for k in ks if k is not ki]


def _conf(v):
    try:
        return float(v.get("confidence") or 0)
    except (TypeError, ValueError):     # Spark sometimes quotes numbers
        return 0.0


def needs_review(v):
    """True = the track sits in the human queue. A confirmed second look decides for motion and relabelled tracks:
    a relabelled track is counted under its new name, so it must not also wait as "not a <label>" (11/2 review), and
    a track the second look rejected must stay where a person can restore it."""
    if not v:
        return True
    c = v.get("confirm")
    if c is not None:
        return not (c.get("is_animal") is True and _conf(c) >= 0.5) or _conf(v) < 0.7
    if v.get("relabelled"):
        return False
    return _conf(v) < 0.7 or v.get("is_target") is False


def auto_labels(trk, verdicts):
    """Confident Spark verdicts set the species label; confident rejections drop the track; everything else keeps
    "<category> (unidentified)". Which tracks are queued is needs_review(): a confident yes without a species is
    counted as "(unidentified)" but not queued (paper 4.7). A human edit overrides any of these."""
    out = {}
    for t, v in verdicts.items():
        conf = _conf(v)
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
