"""End-to-end run: ingest -> scout (Spark) -> track (SAM 3.1, parallel) -> zoom (optional) -> merge/stitch
-> audit (Spark) -> metrics -> evidence frames.  Each stage writes into runs/<id>/ and updates status.json,
which the web UI polls.
  python3 fishcount/pipeline.py <video> [--offline] [--no-scout] [--no-audit] [--zoom] [--prompts fish ...]"""
import argparse, concurrent.futures as cf, hashlib, json, math, os, re, shutil, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api, tracks, video, render, maskdedupe, motion
import requests
import cv2, numpy as np   # render set up the optional FISH_PYLIB path

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
# 11/2 (paper Table 4b): the example "part of an eel, hagfish or fish" named the category itself, and a real fish of
# another species was called "other fish" in 4 of 25 calls; "an eel or hagfish" kept it in 25 of 25.
VERIFY_PROMPT = """Each tile is one object that an automatic tracker counted as "{name}" in a single frame of underwater survey video; this frame sets the maximum count, so every tile matters. Tiles are labelled D1, D2, ... Each tile shows that frame in the middle ("this frame", orange box) and the same tracked object about half a second before and after (left, right) at the same zoom.
For every tile return ONLY a JSON list: [{{"tile":"D1","is_target":true|false,"what_it_is":"<=6 words"}}]
is_target = the middle crop mainly shows a whole or partial {name}. Answer false when the box is on a different animal (for example part of an eel or hagfish), a net, rope, pipe, rock, sediment or empty water. Use the side crops: an animal keeps its body shape while it moves; weed sways in place. If it is too blurry to tell, answer true and say "unclear"."""

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
# 11/3 TF_52 (--camo): two fish on a rock are the rock's colour. No still frame shows them, to SAM or to a person;
# the person saw them swim. So the sheet shows what changed between frames under each still crop.
CAMO_PROMPT = """Each group (K1, K2, ...) shows one spot of underwater survey video. Top row: the picture at three moments (early, middle, late), same zoom, following the spot. Bottom row ("moved"): the same crops showing only what changed between nearby frames - bright means the pixels changed, black means still. The orange rectangle marks the moving spot; no detector has boxed anything there.
An animal camouflaged against rock or sand can be invisible in the top row; then judge by the bottom row. A swimming animal is one compact bright shape in the bottom row that keeps about the same size and outline (a fish shape, for example) and moves from crop to crop. Not an animal: a single tiny bright dot or speck (floating particles), a large soft patch with no outline, a dark shadow on the seabed (the top row shows it as a darker area), waving weed or seagrass (thin strands that stay rooted in place), sediment that spreads or thins, or flicker of light.
For every group return ONLY a JSON list: [{{"tile":"K1","is_animal":true|false,"name":"one plain everyday English noun (fish, shrimp, crab, eel, octopus, ray) or none","what":"<=8 words","confidence":0.0-1.0}}]"""
CAMO_VERSION = "c1"   # bump to recompute cached camo decisions (the key also hashes the prompt and the boxes)
# 11/3 TF_52 v5 (대표님: "물고기의 그림자를 보고 오인"): on sunlit sand every fish casts a dark shadow of its own
# outline, SAM boxes it as "fish" and the audit said "faint dark silhouette holds shape". A counted track whose box is
# darker than the seabed around it and holds no highlight gets one more look with a wide view, where the fish that
# casts it is usually in the picture. Thresholds from demo_TF52g: the 6 shadows had box median L 12-43 below the ring
# and 95th percentile L at most 8 above it; dark-water camo fish are not darker than their ring.
SHADOW_DARK = -10       # box median Lab L minus the surrounding ring's median
SHADOW_BRIGHT = 10      # box 95th percentile L minus the ring's median: a fish has an eye, fin edge or pale belly
# 11/3 TF_52 T50 (the 7 s shadow): Spark, close and wide view, said "faint vertical fish in water column". The fish that
# casts it is tracked (crowd-r1c1:0, just above and right), and the two keep the same offset: spread 0.06 of the shadow's
# size, distance 1.1 sizes, the fish above. Among the real dark fish (luderick dev + holdout, DH8's school of 23) the
# closest any counted fish came was a spread of 0.21 at about the same height, so a rigid companion above is the cue.
SHADOW_PAIR_SPREAD = 0.12   # std of the companion's offset over shared frames, in the dark box's size
SHADOW_PAIR_DIST = 2.0      # mean offset at most this many sizes
SHADOW_PAIR_ABOVE = 0.2     # the companion's centre at least this many sizes higher in the picture (sun from above)
SHADOW_PAIR_RATIO = (0.6, 1.6)   # companion size over the dark box's size
SHADOW_PROMPT = """Each group (S1, S2, ...) follows one tracked object in underwater survey video at three moments (captions under the crops); the orange rectangle marks the object. Top row: close view. Bottom row: the same moments in a wide view around it. The object is darker than its surroundings, so it may be a fish or only the shadow that a fish casts on the seabed in sunlight.
For every group return ONLY a JSON list: [{{"tile":"S1","is_animal":true|false,"what":"fish|shadow|sand|water|other","confidence":0.0-1.0,"reason":"<=10 words"}}]
is_animal = the rectangle itself holds an animal: a small, faint or distant fish in open water still counts, and even a dark fish shows an eye, fins, a lighter belly or highlights, or keeps a body outline in front of other things. what = "shadow" only for a dark patch lying on the seabed (evenly dark, soft edges, no eye, fin edge or lighter parts, flat on the sand, often with a lighter fish of the same outline nearby moving the same way). If you cannot tell, answer true with low confidence."""
COUNT_MIDCONF_MOTION = True   # see run_pipeline: mid-confidence motion tracks get a second look of their own
# a discovered track whose audit says "not a <search word>" and names, at mid confidence (0.5-0.7), an animal the
# discovery step had named gets the unprimed second look and is renamed only on its confident yes; the count is the
# same either way, only the name changes (11/4 s002 rehearsals: 'shrimp' word, audit "small red crab" 0.6 and 0.65,
# shown as "shrimp (unidentified)"; the demo run had 0.7 and was renamed)
RELABEL_MIDCONF_DISCOVERED = True
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
        self.capped = []                # stages skipped at the per-video cap (_capped), result["capped"] when any

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


TEMP_PREFIXES = ("tile_", "seg_", "probe_", "peak+", "box_")     # working cuts sent to SAM, made again on any re-run


def drop_temp(d):
    """Remove a finished run's working videos: the reversed clip and the tile / refill / probe / peak / box cuts sent to
    SAM. Nothing reads them after the run (the cache is keyed by the bytes, which a re-run makes again; run_pipeline
    starts from fresh files), and they were 8.85 of the 27.7 GB in runs/ on 11/21 (32%), which caps how many hours a
    disk holds. The review screen's files (clip.mp4, clip_original.mp4, annotated.mp4, jpg, json) stay.
    FISH_KEEP_TEMP=1 keeps them (to look at what SAM was sent). -> names removed."""
    if os.environ.get("FISH_KEEP_TEMP") == "1":
        return []
    gone = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".mp4") and (f == "clip_rev.mp4" or f.startswith(TEMP_PREFIXES)):
            os.remove(os.path.join(d, f))
            gone.append(f)
    return gone


def _capped(run, stage, msg, **extra):
    """A stage skipped because it would pass the per-video cap: logged as before and listed in result["capped"], so a
    half-analysed segment is marked (a long video gives each segment its share of the video cap). extra: item (the
    first-pass job a cap left unsent: an offline replay leaves it out too), reason "fish" (FISH_BUDGET, not the cap:
    --resume runs that segment again whatever the cap). The --crowd-peak second pass makes the first pass's skips
    again in the same run: an entry already listed is not listed twice."""
    if not hasattr(run, "capped"):      # stand-in runs (tests) built without Run.__init__
        run.capped = []
    c = dict(stage=stage, msg=msg, **extra)
    if c not in run.capped:
        run.capped.append(c)
    run.stage(stage, msg)


def _skip_stage(run, stage, msg, e):
    """A stage given up on error e: a FISH_BUDGET stop (BudgetExceeded is a RuntimeError) is a stage skipped at a cap
    too, so it is listed in result["capped"] (reason "fish"); any other error is only logged."""
    if isinstance(e, api.BudgetExceeded):
        _capped(run, stage, msg, reason="fish")
    else:
        Run.stage(run, stage, msg)


def _counted(run, fn, *a, **k):
    """Call an api function and record whether it hit the network (this thread logged spend) or the cache. A paid
    call's ledger line names the run and the stage (the function that called _counted: scout, refill, ...), so a
    ledger shared by many videos can be split by video and stage (round 3); the line's other keys are unchanged."""
    before = api.thread_spent()
    rid = getattr(run, "id", None)
    prev = api.set_tag(dict(run=rid, stage=sys._getframe(1).f_code.co_qualname.split(".")[0]) if rid else None)
    try:
        return fn(*a, **k)
    finally:    # a call that raises after paying (Spark's retry of a broken reply) still counts toward the cap
        api.set_tag(prev)
        d = api.thread_spent() - before
        with run._lock:
            run.status["live_calls" if d > 0 else "cached_calls"] += 1
            run.status["billed_usd"] += d
            if d > 0 and fn is api.spark:       # a long video's budget warning splits SAM from Spark
                run.status["spark_usd"] = run.status.get("spark_usd", 0.0) + d


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


# Opt-in (--probe-window): a discovered word is first tried on short windows around the frames Spark named for the
# animal; only a word that finds something there is sent with the whole clip. 11/21 night, every saved run with a
# discovery ladder: all 347 words that tracked anything on the whole clip had boxes within 25 frames of a frame
# Spark named (a window on only the first two of Spark's frames missed 47: the s004 nautilus, Spark frames 0, 11,
# ..., tracked from frame 44), and the 12 words that found nothing on clips over 300 frames billed 31,896 frames
# ($6.38; LONG1_cr9 S2 "dark lump on seabed": 8 whole-segment calls, $4.25, all empty) -> 612 in windows.
PROBE_WINDOW = 25       # frames on each side of a frame Spark named
PROBE_MAX_SHARE = 0.5   # windows longer than this share of the clip: the word goes straight to the whole clip
PROBE_MIN_FRAMES = 300  # shorter clips (1 min at 5 fps) keep the plain ladder: on saved short clips the windows gave
                        # back 1,379 frames over 1,162 runs and held every miss (s004 nautilus; DH7 crab from frame 28
                        # after a sign at frame 0)


def _probe_windows(frames, n, half):
    """[(start, length)] windows of +-half frames around every frame Spark named (overlaps joined); [] when Spark
    named none or the windows add up to more than half the clip (a short clip: the word goes straight to the whole
    clip, as without the option, so a word that is found costs at most 1.5 whole-clip calls) or the clip is shorter
    than PROBE_MIN_FRAMES."""
    if n < PROBE_MIN_FRAMES:
        return []
    fs = sorted({int(f) for f in list(frames or []) if isinstance(f, (int, float)) and not isinstance(f, bool) and 0 <= f < n})
    ws = []
    for f in fs:
        s, e = max(0, f - half), min(n, f + half + 1)
        if ws and s <= ws[-1][1]:
            ws[-1][1] = max(ws[-1][1], e)
        else:
            ws.append([s, e])
    if not ws or sum(e - s for s, e in ws) > PROBE_MAX_SHARE * n:
        return []
    return [(s, e - s) for s, e in ws]


def _probe(run, path, word, windows, offline):
    """True when SAM finds `word` in one of the windows of `path` (cut with video.segment), False when in none."""
    base = os.path.splitext(os.path.basename(path))[0] + "_" + re.sub(r"[^A-Za-z0-9]+", "_", word)
    for s, m in windows:
        seg = run.path(f"probe_{base}+{s}.mp4")
        video.segment(path, seg, s, length=m)
        try:
            txt = _counted(run, api.sam_video, seg, word, m, offline=offline)
        except FileNotFoundError as e:
            if offline:     # long videos probe by default since D-NIGHT3: a cache filled before has no windows
                raise FileNotFoundError(f"{e} (a probe window: a run made without --probe-window replays with "
                                        "--no-probe-window)") from e
            raise
        if any(tracks.parse_boxes(txt).values()):
            return True
    return False


def word_ladder(run, clip, n, words, offline, probe=None):
    """Try SAM with each word in turn; stop at the first that tracks anything. Returns (word|None, text, tried).
    `clip` may be a zoom tile; then frames/boxes are in tile coordinates.
    probe: windows (_probe_windows) a word must find something in before the whole clip is sent; a word that finds
    nothing there is recorded with frames 0 and its windows."""
    tried = []
    for w in words:
        if probe and not _probe(run, clip, w, probe, offline):
            tried.append(dict(word=w, frames=0, probe=[list(x) for x in probe]))
            continue
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


def _steady(p, j, k=2, ratio=2.0):
    """False when box j of path p [(frame, box)] has over `ratio` x the median area of its k neighbours each side: a
    mask that bled into the water for a frame or two (11/4 s001 m8:1: the audit crop and queue thumbnail showed open
    water beside the nautilus; 32 of 230 cr9 tracks were shown to Spark at such a moment). Steady growth is kept."""
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
    nb = sorted(area(p[i][1]) for i in range(max(0, j - k), min(len(p), j + k + 1)) if i != j)
    return len(nb) < 2 or area(p[j][1]) <= ratio * nb[len(nb) // 2]


AUDIT_WORKERS = 3      # audit sheets prepared and sent at once (each holds its ~40 frames: ~0.3 GB at 1080p)


def audit(run, clip, frames, trk, label, context, offline, per_sheet=12, start=0, target=None, frame_wh=None, only=None, tag=""):
    """Show Spark three crops per track (early, largest box, late) in sheets of 12; returns {track: verdict}.
    frame_wh=(W, H) (opt-in, clean tracks): the "largest box" moment skips boxes touching the frame edge when the
    track has any other (11/3 TF_52: a fish leaving the frame had its largest box half cut off at the edge).
    Each sheet is saved as audit_<label>_<n>.jpg and each track's three crops as thumbs/T<k>_trio.jpg, so a person
    sees what Spark saw.
    only: optional test on a track id (only those tracks); tag: sheet file prefix (audit_<tag><label>_<n>.jpg), so
    tracks audited on their own sheets (--crowd-peak tile tracks) leave every other sheet as it was."""
    # camo tracks (--camo) are left out: still crops cannot show a camouflaged animal; camo_look decided them
    paths = {t: p for t, p in _paths(frames).items() if trk[t]["label"] == label and not trk[t]["source"].startswith("camo")
             and (only is None or only(t))}
    best, trios, thumb = {}, {}, {}
    for t, p in paths.items():
        area = lambda j: (p[j][1][2] - p[j][1][0]) * (p[j][1][3] - p[j][1][1])
        if frame_wh:
            W, H = frame_wh
            inner = [j for j, (_, b) in enumerate(p) if b[0] > 1 and b[1] > 1 and b[2] < W - 1 and b[3] < H - 1]
            i = max(inner or range(len(p)), key=area)
        else:
            i = max(range(len(p)), key=area)
        best[t] = (None, p[i][0], p[i][1])
        # the queue thumbnail a person sees skips a bled box; Spark's sheet keeps its moment (11/4 cr10: moving it
        # re-drew 32 tracks' sheets and Spark's answers on the other tracks of those sheets shifted, s003 3 -> 2)
        ti = i if _steady(p, i) else max([j for j in range(len(p)) if _steady(p, j)] or [i], key=area)
        thumb[t] = (p[ti][0], p[ti][1])
        trios[t] = [(p[j][0], _ibox(p[j][1])) for j in _three_idx(len(p), i, max(1, len(p) // 3))]
    ids = sorted(best, key=lambda t: best[t][1])
    names = {t: f"T{start + i + 1}" for i, t in enumerate(ids)}
    os.makedirs(run.path("thumbs"), exist_ok=True)
    def one(i):
        chunk = ids[i:i + per_sheet]
        imgs = video.frames(clip, {f for t in chunk for f, _ in trios[t]} | {thumb[t][0] for t in chunk})   # one sheet's frames at a time
        groups = []
        for t in chunk:
            f, b = thumb[t]
            crop = render.crop(imgs[f], b, pad=0.25, min_side=96)
            open(run.path("thumbs", f"{names[t]}.jpg"), "wb").write(video.jpg(crop, max_w=320))
            groups.append(motion.trio(imgs, trios[t], names[t], half=_half(trios[t])))
            open(run.path("thumbs", f"{names[t]}_trio.jpg"), "wb").write(video.jpg(groups[-1], max_w=900))
        del imgs
        sheet = motion.layout(groups)
        open(run.path(f"audit_{tag}{api_safe(label)}_{i // per_sheet + 1}.jpg"), "wb").write(sheet)
        reply = _counted(run, api.spark, AUDIT_PROMPT.format(label=label, target=target or label, context=context), [sheet], offline=offline, check=api.parse_json_list)
        return api.parse_json_list(reply)

    # sheets are independent (own frames, own track names, own Spark call): AUDIT_WORKERS at a time, each decoding its
    # frames while another waits on Spark. Same sheets, same prompts, answers read in sheet order (11/21 LONG1_cr9 S1,
    # cache only: 18 sheets and every thumbnail byte-identical, 74 s -> see out/speed.md)
    out = {}
    ex = cf.ThreadPoolExecutor(AUDIT_WORKERS)
    try:
        for got in ex.map(one, range(0, len(ids), per_sheet)):
            for v in got:
                out[v["track"]] = v
    finally:    # a sheet that raised (cache miss offline, budget stop) leaves the sheets not yet started unsent
        ex.shutdown(wait=True, cancel_futures=True)
    return {t: dict(out.get(names[t], {}), name=names[t], frame=best[t][1], box=best[t][2]) for t in ids}


# Tracks per shadow / confirm sheet. 11/21: ~226 dark tracks of a 2-min TNC rockfish clip on one 46,992 x 1,228 sheet
# made Spark refuse it ("image decode limit exceeded") and the run died with no result. The largest shadow sheet that
# went through held 32 tracks (LONG1_cr9 S1, 6,640 px tall), so up to this many the sheet is exactly as before and a
# longer list goes on more sheets of this size (confirm rows are half as tall, so the same count is well inside).
SHADOW_PER_SHEET = 32
CONFIRM_PER_SHEET = 32


def _split_sheets(fn, per, run, clip, frames, ts, offline, sheet_no):
    """fn's answers for ts cut into sheets of `per`: the first keeps sheet_no, later ones are '<sheet_no>_<k>'."""
    out = {}
    for k in range(0, len(ts), per):
        out.update(fn(run, clip, frames, ts[k:k + per], offline, sheet_no=sheet_no if k == 0 else f"{sheet_no}_{k // per + 1}"))
    return out


def confirm_motion(run, clip, frames, ts, offline, sheet_no=1):
    """_confirm_sheet on sheets of at most CONFIRM_PER_SHEET tracks. Returns {track: reply dict}."""
    if len(ts) > CONFIRM_PER_SHEET:
        return _split_sheets(_confirm_sheet, CONFIRM_PER_SHEET, run, clip, frames, ts, offline, sheet_no)
    return _confirm_sheet(run, clip, frames, ts, offline, sheet_no=sheet_no)


def _confirm_sheet(run, clip, frames, ts, offline, sheet_no=1):
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
    open(run.path(f"confirm_{sheet_no}.jpg"), "wb").write(sheet)
    want = set(names.values())

    def every_tile(text):     # a reply that skips a tile is not cached (it would silently drop that track forever)
        got_ = {str(v.get("tile", "")).upper() for v in api.parse_json_list(text) if isinstance(v, dict)}
        if not want <= got_:
            raise ValueError(f"confirm reply misses {sorted(want - got_)}")
        return True
    reply = _counted(run, api.spark, CONFIRM_PROMPT, [sheet], offline=offline, check=every_tile)
    got = {str(v.get("tile", "")).upper(): v for v in api.parse_json_list(reply) if isinstance(v, dict)}
    return {t: got.get(names[t], {}) for t in ts}


def dark_tracks(clip, frames, ts, W, H):
    """Tracks (of `ts`) whose boxes are darker than the seabed around them with no highlight inside (SHADOW_DARK,
    SHADOW_BRIGHT), measured at the first eighth, middle and last eighth of the path, median of the three."""
    import cv2
    import numpy as np
    paths = _paths(frames)
    at = {t: [paths[t][j] for j in sorted({min(len(paths[t]) - 1, len(paths[t]) // 8), len(paths[t]) // 2,
                                             max(0, len(paths[t]) - 1 - len(paths[t]) // 8)})] for t in ts}
    # 11/21: a frame at a time (read in order, every box on it measured, then dropped) instead of holding every frame
    # and its L channel: LONG1_cr9 S1 went from 0.7 GB to over 4 GB here. Same numbers per box.
    on = {}
    for t in ts:
        for j, (f, b) in enumerate(at[t]):
            on.setdefault(f, []).append((t, j, b))
    got = {}
    for f, img in video.iter_frames(clip, on):
        L = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)[:, :, 0].astype(np.float32)
        for t, j, b in on[f]:
            got[t, j] = _dark_at(L, b, W, H)
    out = []
    for t in ts:
        dl, hi = [], []
        for j in range(len(at[t])):
            v = got.get((t, j))
            if v:
                dl.append(v[0])
                hi.append(v[1])
        if dl and np.median(dl) <= SHADOW_DARK and np.median(hi) <= SHADOW_BRIGHT:
            out.append(t)
    return out


def _dark_at(L, b, W, H):
    """(inner median - ring median, inner 95th percentile - ring median) of box b on one frame's L channel, or None
    when the box or its ring is too small."""
    import numpy as np
    x0, y0, x1, y1 = (int(round(v)) for v in b)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    w, h = x1 - x0, y1 - y0
    if w < 5 or h < 5:
        return None
    inner = L[y0 + h // 5:y1 - h // 5, x0 + w // 5:x1 - w // 5]
    X0, Y0, X1, Y1 = max(0, x0 - w // 2), max(0, y0 - h // 2), min(W, x1 + w // 2), min(H, y1 + h // 2)
    m = np.ones((Y1 - Y0, X1 - X0), bool)
    m[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = False
    ring = L[Y0:Y1, X0:X1][m]
    if inner.size < 4 or ring.size < 4:
        return None
    r = float(np.median(ring))
    return float(np.median(inner)) - r, float(np.percentile(inner, 95)) - r


def shadow_pairs(frames, dark, counted):
    """{dark track: (companion, spread, dist)} for dark tracks that move rigidly with a counted, not dark fish above them
    of about their size (SHADOW_PAIR_*), over at least 2 shared frames: the fish and its shadow on the seabed."""
    import numpy as np
    paths = {t: dict(p) for t, p in _paths(frames).items()}

    def c(b):
        return np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])

    def size(b):
        return max(b[2] - b[0], b[3] - b[1], 1)
    out = {}
    for d in dark:
        p = paths.get(d, {})
        best = None
        for f_ in counted:
            if f_ == d or f_ in dark:
                continue
            q = paths.get(f_, {})
            com = sorted(set(p) & set(q))
            if len(com) < 2:
                continue
            s = float(np.mean([size(p[f]) for f in com]))
            off = np.array([c(q[f]) - c(p[f]) for f in com])
            spread = float(np.linalg.norm(off.std(0))) / s
            dist = float(np.linalg.norm(off.mean(0))) / s
            ratio = float(np.mean([size(q[f]) / size(p[f]) for f in com]))
            if (spread <= SHADOW_PAIR_SPREAD and dist <= SHADOW_PAIR_DIST and off.mean(0)[1] / s <= -SHADOW_PAIR_ABOVE
                    and SHADOW_PAIR_RATIO[0] <= ratio <= SHADOW_PAIR_RATIO[1]) and (best is None or spread < best[1]):
                best = (f_, round(spread, 3), round(dist, 2))
        if best:
            out[d] = best
    return out


def shadow_look(run, clip, frames, ts, offline, sheet_no=1):
    """_shadow_sheet on sheets of at most SHADOW_PER_SHEET tracks. Returns {track: reply dict}."""
    if len(ts) > SHADOW_PER_SHEET:
        return _split_sheets(_shadow_sheet, SHADOW_PER_SHEET, run, clip, frames, ts, offline, sheet_no)
    return _shadow_sheet(run, clip, frames, ts, offline, sheet_no=sheet_no)


def _shadow_sheet(run, clip, frames, ts, offline, sheet_no=1):
    """Ask, with a wide view, whether each dark track is an animal or a fish's shadow / bare seabed (SHADOW_PROMPT).
    Saved as shadow_<sheet_no>.jpg. Returns {track: reply dict}."""
    paths = _paths(frames)
    groups, names, trios = [], {}, {}
    for t in ts:
        p = paths[t]
        L = len(p)
        idx = [min(L - 1, L // 8), L // 2, max(0, L - 1 - L // 8)]
        trios[t] = [(p[j][0], _ibox(p[j][1])) for j in idx]
    imgs = video.frames(clip, {f for t in ts for f, _ in trios[t]})
    for i, t in enumerate(ts):
        names[t] = f"S{i + 1}"
        # close view (the audit's zoom) over a wide one: 11/3 cr2 luderick 20190618_3, a faint far fish in open water
        # was a few pixels in the wide view alone, Spark said "empty blue water" and a real fish was taken out
        wide = max(96, int(2.5 * max(max(b[2] - b[0], b[3] - b[1]) for _, b in trios[t])))
        groups.append(np.vstack([motion.trio(imgs, trios[t], names[t], half=_half(trios[t]), words=("first", "middle", "last")),
                                 motion.trio(imgs, trios[t], "", half=wide, words=("wide", "wide", "wide"))]))
    del imgs
    sheet = motion.layout(groups)
    open(run.path(f"shadow_{sheet_no}.jpg"), "wb").write(sheet)
    want = set(names.values())

    def every_tile(text):
        got_ = {str(v.get("tile", "")).upper() for v in api.parse_json_list(text) if isinstance(v, dict)}
        if not want <= got_:
            raise ValueError(f"shadow reply misses {sorted(want - got_)}")
        return True
    reply = _counted(run, api.spark, SHADOW_PROMPT, [sheet], offline=offline, check=every_tile)
    got = {str(v.get("tile", "")).upper(): v for v in api.parse_json_list(reply) if isinstance(v, dict)}
    return {t: got.get(names[t], {}) for t in ts}


def crowd_tiles(W, H, cols=3, rows=2, pad=0.12):
    """Overlapping tiles covering the whole frame (x, y, w, h), even sizes. 11/3 IMAS TF_52 (a school of seabream):
    the small far fish in the upper water were missed by the full-frame pass, and the scout-picked zoom covers at
    most two cells. Neighbours overlap by 2*pad of a tile so a fish on a seam is whole in at least one tile."""
    ev = lambda v: int(v) // 2 * 2
    w, h = W / cols, H / rows
    out = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = max(0, (c - pad) * w), max(0, (r - pad) * h)
            x1, y1 = min(W, (c + 1 + pad) * w), min(H, (r + 1 + pad) * h)
            out.append((f"r{r}c{c}", (ev(x0), ev(y0), ev(x1 - x0), ev(y1 - y0))))
    return out


REFILL_WINDOW = 100     # frames per refill call (20 s at 5 fps; SAM bills at least SAM_MIN_FRAMES=50 per call)
REFILL_OVERLAP = 2      # frames shared by consecutive windows, so merge() drops the repeat and stitch() joins the pieces


def _refill_capped(run, name, s, max_usd):
    _capped(run, "track", f"16-id limit: {name} not re-sent from frame {s}: would pass the per-video cap ${max_usd:.2f}")


def _refill_chain_ahead(run, job, s, n, offline, ahead, window, overlap, cap, max_usd):
    """refill_saturated's chain for one pass with up to `ahead` windows in flight (opt-in, --refill-ahead).
    The chain goes window by window: the next starts `window - overlap` frames on unless this one ran out of ids at r
    (then at r). That is known only when the answer is back, so the serial chain waits for every call (LONG1_cr9:
    141 calls, all one after another). Here the windows on the no-run-out grid (s, s+98, s+196, ...) are sent at
    once; the chain still walks its own path and uses an answer only for the window it would have sent itself (same
    start, same cut, so the same cache entry), and a window off its path (after a run-out) is paid for and dropped.
    So the sources returned are the serial chain's (11/21: 6 LONG1_cr9 segments, 43 rounds instead of 141, 20
    wasted 100-frame calls, ~$0.40, t4_sim.py). Under max_usd a window is sent only while the cap would hold with
    every call still in flight paid for (the serial chain has none in flight, so there it is the same check)."""
    name, label, prompt, path, box = job
    step = window - overlap
    live_cap = max_usd is not None and not offline
    out, pending, held = [], {}, {}     # held: future -> what it may still bill (in run.status once it is done)

    def cut(t):
        e = min(n, t + window)
        seg = run.path(f"seg_{name}+{t}.mp4")
        video.segment(path, seg, t, length=None if e == n else e - t)
        return e, seg

    def call(t):
        e, seg = cut(t)
        return e, _counted(run, api.sam_video, seg, prompt, e - t, offline=offline)

    def price(t):
        e, seg = cut(t)
        return 0.0 if api.sam_cached(seg, prompt) else max(api.SAM_MIN_FRAMES, e - t) * api.SAM_PER_FRAME

    def owed():
        return run.status["billed_usd"] + sum(c for f, c in held.items() if not f.done())

    with cf.ThreadPoolExecutor(ahead) as ex:
        while s is not None and s < n - 2 and len(out) < cap:
            if s not in pending:
                cost = price(s) if live_cap else 0.0
                if live_cap and cost and owed() + cost > max_usd:     # owed: dropped calls still running bill too
                    _refill_capped(run, name, s, max_usd)
                    break
                pending[s] = ex.submit(call, s)
                held[pending[s]] = cost
            for i in range(1, ahead):
                t = s + i * step
                if t >= n - 2 or len(out) + i >= cap:
                    break
                if t in pending:
                    continue
                cost = price(t) if live_cap else 0.0
                if live_cap and owed() + cost > max_usd:
                    break
                pending[t] = ex.submit(call, t)
                held[pending[t]] = cost
            e, raw = pending.pop(s).result()
            txt = tracks.shift_text(raw, s)
            d = tracks.parse_boxes(txt)
            out.append((f"{name}+{s}", label, tracks.from_tile(d, box, 2) if box else d, txt, box))
            r = tracks.saturation_frame(d)
            s = r if r is not None and r > s else (e - overlap if e < n else None)
            for t in [t for t in pending if s is None or t < s or (t - s) % step]:
                pending.pop(t).cancel()     # off the chain's path: dropped (a call already sent still finishes)
        for f in pending.values():
            f.cancel()
    return out


def refill_saturated(run, jobs, results, n, offline, max_segments=4, window=REFILL_WINDOW, overlap=REFILL_OVERLAP,
                     max_usd=None, ahead=1):
    """SAM 3.1 gives one call at most 16 object ids for the whole clip (tracks.SAM_MAX_OBJECTS). When a prompt/tile
    pass has used them all at frame s, nothing that arrives later is ever boxed (11/3 TF_52: the large seabream over
    the pale sand at the end, in tile r1c1 whose 16 ids were gone by frame 22). From s the video is sent again in
    windows of at most `window` frames, each a new call with fresh ids: a window that runs out at frame r is sent again
    from r, one that does not (or runs out on its first frame: more than 16 in view, a re-send gains nothing) is
    followed by the next window, `overlap` frames back. A short clip is one window, so this is the old chain there.
    Windows keep a long segment (LONG1: 2,658 frames, out of ids at frame 78) from re-sending everything left on
    every call. At most `max_segments` calls per window's worth of frames.
    max_usd: a window that is not cached and would take the run past the per-video cap is not sent, and that pass
    stops there (cached windows are free and always used, so a replay is unchanged).
    ahead: opt-in (--refill-ahead N): up to N windows of a chain in flight at once (_refill_chain_ahead); same
    sources as the serial chain, sooner, for the calls it sends past a run-out. 1 (default): one at a time.
    Returns extra sources (name "<pass>+<start>", frames renumbered to the clip) to merge after all others."""
    out_res = {r[0]: r for r in results}

    def chain(job):
        name, label, prompt, path, box = job
        s = tracks.saturation_frame(tracks.parse_boxes(out_res[name][3]))
        out = []
        cap = max_segments * -(-(n - s) // (window - overlap)) if s is not None else 0
        if ahead > 1:
            return _refill_chain_ahead(run, job, s, n, offline, ahead, window, overlap, cap, max_usd)
        while s is not None and s < n - 2 and len(out) < cap:
            e = min(n, s + window)
            seg = run.path(f"seg_{name}+{s}.mp4")
            video.segment(path, seg, s, length=None if e == n else e - s)
            if (max_usd is not None and not offline and not api.sam_cached(seg, prompt)
                    and run.status["billed_usd"] + max(api.SAM_MIN_FRAMES, e - s) * api.SAM_PER_FRAME > max_usd):
                _refill_capped(run, name, s, max_usd)
                break
            txt = tracks.shift_text(_counted(run, api.sam_video, seg, prompt, e - s, offline=offline), s)
            d = tracks.parse_boxes(txt)
            out.append((f"{name}+{s}", label, tracks.from_tile(d, box, 2) if box else d, txt, box))
            r = tracks.saturation_frame(d)
            s = r if r is not None and r > s else (e - overlap if e < n else None)
        return out

    todo = [j for j in jobs if j[0] in out_res]
    with cf.ThreadPoolExecutor(4) as ex:
        extra = [x for xs in ex.map(chain, todo) for x in xs]
    run.stage("track", "16-id limit: " + (", ".join(f"{e[0]} ({len({d['id'] for ds in e[2].values() for d in ds})} ids)" for e in extra)
                                          or "no pass ran out of ids"))
    return extra


def _sam_cost(path, prompt, n_frames):
    """A whole-clip SAM call's worst case: 0 when it is in the cache."""
    return 0.0 if api.sam_cached(path, prompt) else max(api.SAM_MIN_FRAMES, n_frames) * api.SAM_PER_FRAME


def ladder_estimate(path, words, n_frames, probe=None):
    """Worst-case $ of word_ladder(path, words): every word on the whole clip (cached calls free); with probe windows
    (R9) at most every word on its windows plus one whole-clip call, never more than without them.
    ponytail: a window is counted as paid even when cached (looking it up means cutting it first); what was really
    paid is in the ledger, which the next segment's share does not depend on."""
    whole = [_sam_cost(path, w, n_frames) for w in words]
    if not probe or not whole:
        return sum(whole)
    return min(sum(whole), len(words) * _window_cost(probe) + max(whole))


def _window_cost(windows):
    """$ of one word on every probe window."""
    return sum(max(api.SAM_MIN_FRAMES, m) for _, m in windows) * api.SAM_PER_FRAME


def first_estimate(jobs, others, clip, n_frames, probes=None):
    """Worst-case $ of the first pass's SAM calls: each prompt / tile job as a whole-clip call and each discovery
    ladder as ladder_estimate (probes: its windows, aligned with others). Calls already in the cache are free and do
    not count: a rerun of a 600-s segment whose calls were all cached stopped at the default $1 cap before
    ("estimate $2.13 > per-video cap $1.00", LONG1 S2, 11/21c), with nothing to pay."""
    probes = probes or [None] * len(others)
    return (sum(_sam_cost(j[3], j[2], n_frames) for j in jobs)
            + sum(ladder_estimate(clip, ws, n_frames, p) for (_, ws), p in zip(others, probes)))


def first_pass_trim(jobs, others, clip, n_frames, max_usd, required, probes=None):
    """What of the first pass fits under max_usd: -> (est of what is sent, [(item, what)] left unsent).
    Items are left out, last first, until the estimate fits: the discovery ladders (d<i>), then the zoom / crowd tiles,
    then the scout's words (last: without them a crab or shrimp is counted under "fish"). The --prompts jobs
    (`required`) are never left out: when they alone pass max_usd, BudgetExceeded (the run stops before paying, as
    every first pass did before D-NIGHT3). A cached item costs nothing and is never left out. Deterministic: the
    same inputs and cache give the same list. Before, any overshoot stopped the run: a long video with discovery
    stopped at its first segment's estimate."""
    probes = probes or [None] * len(others)
    lad = [ladder_estimate(clip, ws, n_frames, p) for (_, ws), p in zip(others, probes)]
    job = {j[0]: _sam_cost(j[3], j[2], n_frames) for j in jobs}
    est = sum(lad) + sum(job.values())
    order = ([(f"d{i}", lad[i], f"discovered '{o.get('what')}' ({', '.join(ws)})")
              for i, (o, ws) in reversed(list(enumerate(others))) if ws]
             + [(j[0], job[j[0]], f"tile {j[0]}") for j in reversed(jobs) if j[4] is not None]
             + [(j[0], job[j[0]], f"scout word '{j[2]}'") for j in reversed(jobs) if j[4] is None and j[2] not in required])
    out = []
    for item, cost, what in order:
        if est <= max_usd + 1e-9:
            break
        if cost > 0:
            est -= cost
            out.append((item, what))
    if est > max_usd + 1e-9:
        raise api.BudgetExceeded(f"estimate ${est:.2f} for the --prompts words alone > per-video cap ${max_usd:.2f}")
    return est, out


def _left_unsent(run):
    """Items the live run in this folder left unsent at the cap (result["capped"] item): an offline replay of it
    leaves them out too. Any other cache miss raises, as it always did."""
    try:
        with open(run.path("result.json")) as f:
            res = json.load(f)
        return {c["item"] for c in res.get("capped", []) if isinstance(c, dict) and c.get("item")}
    except (OSError, ValueError, AttributeError, TypeError):
        return set()


def mark_error(d, e):
    """Write a run's failure into <d>/status.json: stage "error", error "<Type>: <message>", the time, and a log line;
    the rest of the status (log, calls, billed) is kept. Before (round 3), only the web screen did this: a CLI or batch
    run that raised left its last stage ("audit", "segments"), so a crashed run looked like one still going. A status
    already marked (an inner run_pipeline) is left as it is; this never raises (the original error is what matters)."""
    p = os.path.join(d, "status.json")
    try:
        try:
            with open(p) as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            st = None
        if not isinstance(st, dict):
            st = dict(id=os.path.basename(d), log=[])
        if st.get("stage") == "error":
            return
        msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        st.update(stage="error", error=msg[:1000], failed=time.time())
        st.setdefault("log", []).append(f"{time.strftime('%H:%M:%S')} stopped: {msg[:300]}")
        os.makedirs(d, exist_ok=True)
        with open(p + ".err.tmp", "w") as fh:
            json.dump(st, fh)
        os.replace(p + ".err.tmp", p)
    except OSError:
        pass


def run_pipeline(src, rid=None, *a, **kw):
    """_run_pipeline (below: every option), and on any exception the run's status.json says "error" (mark_error)."""
    rid = rid or time.strftime("%m%d-%H%M%S")
    try:
        return _run_pipeline(src, rid, *a, **kw)
    except BaseException as e:
        mark_error(os.path.join(RUNS, rid), e)
        raise


def _run_pipeline(src, rid=None, offline=False, do_scout=True, do_audit=True, do_zoom=False, prompts=None, max_usd=1.0,
                 do_discover=False, do_motion=None, lowlight="auto", site=None, crowd=False, clean=True, refill=True, camo=False,
                 misslook=False, crowd_look=True, box_window=None, probe_window=None, skip_people=False, refill_ahead=1,
                 crowd_peak=None, _peak=None, _run=None, haze="off"):
    """haze: opt-in "auto" / "on" (video.is_hazy, video.clahe_frame): a clip that is not dark but washed out (median
    L p95-p5 below video.HAZE_WIDTH) is analysed after CLAHE on L alone; the original is kept as clip_original.mp4 and
    the numbers go into result["video"]["lowlight"]["haze"]. A dark clip's brightening already includes CLAHE.
    "off" (default): nothing changes.
    crowd_peak: opt-in half width in frames (CROWD_PEAK). After the crowd check, every row it marks a lower bound has
    the frames within crowd_peak of its peak frame sent as the 3x2 crowd tiles (peak_windows, peak_tiles), and the
    run is made again in the same folder with those tile tracks merged last, so they are audited, peak-checked and
    counted like any other track (every earlier call is a cache hit the second time). It also asks the crowd check
    about requested words that counted nothing (empty_rows), so a 0 can be marked a lower bound and tiled too.
    result["crowd_peak"] keeps the windows and the first pass's crowd check. None (default): nothing changes.
    skip_people: opt-in (_is_people): a discovery naming people or a boat and no animal is not searched for, and a
    sign whose suspected animal is one is not either. False (default): every discovery is searched, as before.
    probe_window: opt-in (PROBE_WINDOW): a discovered word is tried on +-probe_window frames around the frames Spark
    named before the whole clip (discovery ladder, zoom tiles, closer_look cells; clips of PROBE_MIN_FRAMES or more;
    not signs or reversed back-fills). None (default): straight to the whole clip.
    box_window: opt-in (BOX_WINDOW): a motion box prompt on a clip longer than 2 * box_window + 1 frames sends SAM
    only the frames within box_window of its spot (motion_look). None (default): the whole clip, as before.
    crowd_look: crowd_check (on by default, needs audits): marks a MaxN a lower bound when Muse Spark, unprimed,
    counts clearly more animals in the peak frame. Changes no count.
    misslook: opt-in miss_look (Spark points at animals without a box on a few frames -> SAM box prompts).
    camo: opt-in camo_look (needs audits): movers no still frame shows, tracked from a SAM box when SAM follows the
    moving spot; their verdict comes from that look, not the audit. Off by default, so earlier evaluations replay unchanged.
    refill (refill_saturated): a SAM call that used all 16 of its object ids is run again from the frame it
    ran out, so animals arriving later get ids. Extra passes merge last (lowest priority), so every existing track keeps
    its number. On by default since 11/3 (refill=False reproduces the evaluations made before that).
    refill_ahead: opt-in (--refill-ahead N): those re-sends go up to N windows at a time (same result, sooner, and a
    few calls paid for and dropped where a window runs out of ids). 1 (default): one after another, as before.
    clean: track hygiene (11/3 TF_52): tracks.repair_ids() gives back the ids SAM shuffled for a frame (boxes that
    hopped between fish, a fish's id on its shadow), tracks.split_jumps() cuts IDs SAM reused for another object, and the
    audit's "largest box" moment skips boxes cut by the frame edge. On by default since 11/3 (clean=False: the old runs).
    crowd: opt-in "crowded scene" pass (crowd_tiles): every overlapping 3x2 tile, upscaled 2x, gets SAM "fish";
    tile duplicates merge as zoom tiles do. Off by default, so earlier evaluations replay unchanged.
    site: opt-in site memory (fishcount/sitememory.py, docs/site_memory.md): words a reviewer gave to earlier
    videos of this site are added as SAM ladders; with site=None nothing below changes.
    do_motion: run the motion residual (default: only when audits run, since unaudited motion tracks would be
    counted unchecked). The paper's no-audit discovery baseline sets it explicitly.
    lowlight: "auto" brightens only a dark clip (video.is_dark), "on" always, "off" never; the original is kept as
    clip_original.mp4 and the decision with the brightness numbers goes into result["video"]["lowlight"]."""
    args = dict(locals())
    do_motion = (do_discover and do_audit) if do_motion is None else do_motion
    rid = rid or time.strftime("%m%d-%H%M%S")
    run = _run or Run(rid)
    unsent_before = _left_unsent(run) if offline else set()     # read before this run writes its own result
    clip = run.path("clip.mp4")
    # 11/3: identical clip copies of finished runs are hard links to each other (disk full); writing into one would
    # rewrite them all, so a run starts from fresh files.
    for f in ("clip.mp4", "clip_rev.mp4"):
        if os.path.lexists(run.path(f)):
            os.unlink(run.path(f))
    run.stage("ingest", f"re-encoding {os.path.basename(src)} to 5 fps")
    src_warn = []       # video.source_warnings: cut short, damaged, unknown length (round 3); [] for an intact file
    if src.endswith(".mp4") and video.info(src)["fps"] == 5.0:
        shutil.copy(src, clip)      # already analysis-ready (keeps the cache key stable)
    else:
        src_warn = (video.ingest(src, clip) or {}).get("source_warnings") or []
    for w in src_warn:
        run.stage("ingest", f"WARNING: {w}")
    light = video.light_stats(clip)
    light.update(mode=lowlight, brightened=lowlight == "on" or (lowlight == "auto" and video.is_dark(light)))
    if light["brightened"]:
        os.replace(clip, run.path("clip_original.mp4"))
        video.brighten(run.path("clip_original.mp4"), clip)
        run.stage("ingest", f"dark clip (median L {light['median_l']}, mean {light['mean_l']}): brightened with gamma 0.5 + CLAHE")
    elif haze != "off":
        hz = video.contrast_stats(clip)
        hz.update(mode=haze, applied=haze == "on" or (haze == "auto" and video.is_hazy(hz)))
        light["haze"] = hz
        if hz["applied"]:
            os.replace(clip, run.path("clip_original.mp4"))
            video.brighten(run.path("clip_original.mp4"), clip, frame_fn=video.clahe_frame)
            run.stage("ingest", f"washed-out clip (L p95-p5 {hz['l_width']}): CLAHE on L")
    inf = video.info(clip)
    inf["lowlight"] = light
    if src_warn:        # only then, so an intact clip's result is byte for byte what it was
        inf["source_warnings"] = src_warn
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
            # 11/1 s003: 'shell' found nothing but Spark's own name 'nautilus' tracked, so its name goes first, as its
            # head noun: a long name was skipped entirely before (11/2 long-video segment 2: "chambered nautilus
            # clustered on bait" never tried "nautilus", and all six tracks went to the queue)
            # only a known animal noun goes first; any other fallback word ("white bacterial mat" -> "mat") goes after
            # Spark's own search words, so a junk word that happens to track cannot block them (11/2 pre-freeze review)
            # every known animal noun of the name goes first, head noun first (11/3 s003 rehearsal take 1: "chambered
            # nautilus cephalopod" tried only cephalopod, shell, snail, never "nautilus", and counted 1 of 3)
            h = short_name(o.get("what", ""))
            name = animal_nouns(o.get("what", ""))
            tail = [] if h in _GROUP_OF or not h else [h]
            words = []
            for w in name + o.get("search_words", []) + tail:
                w = w.strip().lower()
                if w and w not in used and w not in words:
                    words.append(w)
            words = words[:3]
            if words and len(others) < 3:
                # --skip-people: kept with no words, so the name still reaches the audit context and the motion
                # sheet as before (their Spark prompts, cache keys and verdicts unchanged) but SAM is never asked
                others.append((o, [] if skip_people and _is_people(o) else words))
        run.stage("discover", "Spark also sees: " + (", ".join(f"{o['what']} -> try {w}" if w else f"{o['what']} -> not searched (--skip-people)"
                                                         for o, w in others) or "nothing else"))
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
    if crowd:
        for name, box in crowd_tiles(inf["width"], inf["height"]):
            tp = run.path(f"tile_crowd-{name}.mp4")
            video.crop_tile(clip, tp, box, scale=2)
            jobs.append((f"crowd-{name}", plist[-1][0], "fish", tp, box))
    probes = [_probe_windows(o.get("frames"), inf["n_frames"], probe_window) if probe_window else None for o, _ in others]
    if _peak is not None and hasattr(run, "first_unsent"):
        # --crowd-peak second pass: what the first pass sent is cached now, so what it left out would fit; it stays
        # out, so the second pass sees the inputs the first had and capped stays true
        est, unsent = first_estimate(jobs, others, clip, inf["n_frames"], probes), run.first_unsent
    elif offline:
        est = first_estimate(jobs, others, clip, inf["n_frames"], probes)
        unsent = [(x, "left unsent by the live run") for x in [j[0] for j in jobs] + [f"d{i}" for i in range(len(others))]
                  if x in unsent_before]
    else:
        est, unsent = first_pass_trim(jobs, others, clip, inf["n_frames"], max_usd, set(prompts or ["fish"]), probes)
    run.first_unsent = unsent
    for item, what in unsent:
        _capped(run, "first_pass", f"first pass: {what} not sent: would pass the per-video cap ${max_usd:.2f}", item=item)
    skip = {x for x, _ in unsent}
    jobs = [j for j in jobs if j[0] not in skip]
    run.stage("track", f"SAM 3.1 tracking {len(jobs)} prompt(s)/tile(s) in parallel: {[(j[2], j[0]) for j in jobs]} (est ${est:.2f} for the calls not cached)")

    def one(job):
        name, label, prompt, path, box = job
        txt = _counted(run, api.sam_video, path, prompt, video.info(path)["n_frames"], offline=offline)
        d = tracks.parse_boxes(txt)
        return name, label, (tracks.from_tile(d, box, 2) if box else d), txt, box

    with cf.ThreadPoolExecutor(4) as ex:
        ladders = [None if f"d{i}" in skip else ex.submit(word_ladder, run, clip, inf["n_frames"], words, offline, probes[i])
                   for i, (o, words) in enumerate(others)]
        results = list(ex.map(one, jobs))
        for i, ((o, _), fu) in enumerate(zip(others, ladders)):
            if fu is None:      # left unsent at the cap: named (audit context, motion sheet) but never searched
                found.append(dict(what=o["what"], why=o.get("why_notable"), word=None, tried=[], maxn_full=0,
                                  expected=o.get("approx_max_count"), not_sent=True))
                continue
            word, txt, tried = fu.result()
            found.append(dict(what=o["what"], why=o.get("why_notable"), word=word, tried=tried,
                              maxn_full=tracks.max_per_frame(tracks.parse_boxes(txt)), expected=o.get("approx_max_count")))
            run.stage("discover", f"{o['what']}: " + ", ".join(f"'{t['word']}' {t['frames']} frames" for t in tried))
            if word:
                results.append((f"d{i}", word, tracks.parse_boxes(txt), txt, None))
    if _peak is None:   # what the first pass's SAM calls cost (the --crowd-peak second pass finds them cached)
        run.status["first_pass_sam_usd"] = run.status["billed_usd"] - run.status.get("spark_usd", 0.0)
    if refill:
        results += refill_saturated(run, jobs, results, inf["n_frames"], offline, max_usd=max_usd, ahead=refill_ahead)
    signs = [sg for sg in disc.get("signs", []) if not (skip_people and isinstance(sg, dict)
                                                        and _is_people(dict(what=sg.get("possible_animal"))))]
    recovered = recover(run, clip, inf, others, found, signs, results, max_usd, offline,
                        probe_window=probe_window) if do_discover else []
    moved = []
    if do_motion:
        try:
            moved = motion_look(run, clip, inf, results, max_usd, offline, names=[f["what"] for f in found], box_window=box_window)
            # second look (11/4 s001: the first sheet's 8 spots were all pieces of the 4 nautiluses it then tracked,
            # so a 5th that moved only in frames 35-40 ranked 20th and was never shown; with those tracks known it
            # ranks 7th). Only when the first look added a track: otherwise the candidates would be the same.
            if any(e.get("source") for e in moved):
                moved += motion_look(run, clip, inf, results, max_usd, offline, names=[f["what"] for f in found], rnd=2,
                                     box_window=box_window)
        except MOTION_ERRORS as e:
            _skip_stage(run, "motion", f"motion look skipped: {type(e).__name__}: {str(e)[:160]}", e)
        recovered += moved
    camo_verdicts = {}
    if camo and do_audit:
        try:
            got_log, camo_verdicts = camo_look(run, clip, inf, results, max_usd, offline, names=[f["what"] for f in found])
            recovered += got_log
        except MOTION_ERRORS as e:
            _skip_stage(run, "camo", f"camouflage look skipped: {type(e).__name__}: {str(e)[:160]}", e)
    if misslook:
        try:
            recovered += miss_look(run, clip, inf, results, max_usd, offline, labels=[lab for lab, _ in plist],
                                   names=[f["what"] for f in found])
        except MOTION_ERRORS as e:
            _skip_stage(run, "miss", f"missed-animal look skipped: {type(e).__name__}: {str(e)[:160]}", e)
    site_entries = []
    if site:      # after recovery and the motion look, so their inputs and cache keys are exactly those of a run without site
        site_entries, site_results = site_look(run, clip, inf, site, {q for _, q in plist} | {f["word"] for f in found if f["word"]},
                                               max_usd, offline)
        results[0:0] = site_results       # a remembered specific kind wins overlaps, like the scout's words
    if _peak:     # --crowd-peak second pass: last, so every input and cache key above is that of the first pass
        results += peak_tiles(run, clip, inf, _peak["windows"], plist[-1][0], max_usd, offline)
    raw = {name: (txt, tile) for name, _, _, txt, tile in results}   # tile=None: full-frame text (masks drawable)
    # clean: SAM 3.1 sometimes hands a frame's boxes the wrong ids (tracks.repair_ids); ids only, boxes and counts stay
    sources = [(name, label, tracks.repair_ids(d) if clean else d) for name, label, d, _, _ in results]
    frames, trk = tracks.merge(sources, apart=("peak+",))
    n0 = len(trk)
    if clean:
        frames, trk = tracks.split_jumps(frames, trk)
        run.stage("track", f"{n0} raw tracks -> {len(trk)} after cutting reused IDs")
    trk = tracks.stitch(frames, trk, apart=("camo", "peak+"))
    run.stage("track", f"{n0} raw tracks -> {len(trk)} after re-joining broken IDs")

    verdicts = {}
    if do_audit:
        context = (json.dumps(sc.get("objects", []))[:600] + " " + json.dumps([f["what"] for f in found])).strip() or "none"
        # a discovered word is only SAM's handle ("eel"); ask about the animal Spark named ("hagfish")
        asked = {f["word"]: f["what"] for f in found if f["word"]}
        site_src = {e["source"] for e in site_entries if e.get("word")}
        # labels only site memory produced are audited last, so every other label keeps its track numbers and cached sheets
        site_only = lambda l: bool(site_src) and all(t["source"] in site_src for t in trk.values() if t["label"] == l)
        asked.update({e["word"]: e["label"] for e in site_entries if e.get("word")})
        # --crowd-peak tile tracks go on their own sheets after every other track (11/21 LONG1_cr9 S5/S6: mixed into
        # the 'fish' sheets they renumbered the first-pass tracks, the sheets were asked again and Spark's answers on
        # first-pass tracks moved: two saddled seabream became "unidentified", a flatfish row vanished)
        is_peak = lambda t: trk[t]["source"].startswith("peak+")
        own = (None,) if not any(is_peak(t) for t in trk) else (lambda t: not is_peak(t), is_peak)
        for only in own:
            for label in sorted({v["label"] for t, v in trk.items() if only is None or only(t)}, key=lambda l: (site_only(l), l)):
                run.stage("audit", f"Muse Spark checks every '{label}' track crop" + (" (crowd-peak tiles)" if only is is_peak else ""))
                verdicts.update(audit(run, clip, frames, trk, label, context, offline, start=len(verdicts), target=asked.get(label),
                                      frame_wh=(inf["width"], inf["height"]) if clean else None,
                                      only=only, tag="peak_" if only is is_peak else ""))
        if camo_verdicts:
            verdicts.update(camo_verdicts_for(run, clip, frames, trk, camo_verdicts, inf["n_frames"]))
        n_flag = sum(1 for v in verdicts.values() if needs_review(v))
        run.stage("audit", f"{n_flag} of {len(verdicts)} tracks need a human look")

    labels = auto_labels(trk, verdicts)
    maybe = []      # motion tracks with a mid-confidence audit yes (COUNT_MIDCONF_MOTION)
    rename = []     # discovered tracks with a mid-confidence "it is <a discovered animal>" (RELABEL_MIDCONF_DISCOVERED)
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
        if (RELABEL_MIDCONF_DISCOVERED and trk[t]["source"].startswith("d") and v.get("is_target") is False
                and 0.5 <= _conf(v) < 0.7 and norm_label(v.get("species") or "") in seen):
            rename.append(t)
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
            # 11/2 s001: a third motion nautilus had audit 0.55 ("blurry pale shell") and waited in the queue. A
            # mid-confidence (0.5-0.7) yes whose species is in a group the discovery step had named gets the unprimed
            # second look too, on its own sheet (confirm_2) so the first sheet's cached answers stay as they were.
            if (COUNT_MIDCONF_MOTION and v.get("is_target") is not False and 0.5 <= _conf(v) < 0.7
                    and name_group(v.get("species")) and name_group(v.get("species")) in {name_group(f["what"]) for f in found}):
                maybe.append(t)
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
                # the second look sees no names, so a different animal group from it (s004 v16: audit "caridean
                # shrimp", second look "fish") puts the name in doubt but not the animal: the track still counts under
                # the audit's name and also waits in the queue, where a person can rename it
                elif name_disagreement(verdicts[t].get("species") or labels[t], c.get("name")):
                    verdicts[t]["name_disagrees"] = name_disagreement(verdicts[t].get("species") or labels[t], c.get("name"))
            run.stage("audit", f"second look at {len(sure)} motion or renamed track(s) before they count: "
                      + ", ".join(f"{verdicts[t]['name']} {'yes' if labels[t] else 'no'} ({said.get(t, {}).get('reason', 'no answer')})" for t in sure))
        if maybe:
            said = confirm_motion(run, clip, frames, maybe, offline, sheet_no=2)
            for t in maybe:
                c = said.get(t, {})
                verdicts[t]["confirm"] = c
                # counted only on a confident second-look yes that names no other animal group; it stays in the queue
                # (audit < 0.7), so a person still sees it
                if (c.get("is_animal") is True and _conf(c) >= 0.7
                        and not name_disagreement(verdicts[t].get("species"), c.get("name"))):
                    labels[t] = verdicts[t]["species"].lower()
                    verdicts[t]["midconf_counted"] = True
            run.stage("audit", f"second look at {len(maybe)} mid-confidence motion track(s): "
                      + ", ".join(f"{verdicts[t]['name']} {'counted' if labels.get(t) else 'not counted'} ({said.get(t, {}).get('reason', 'no answer')})" for t in maybe))
        if rename:
            said = confirm_motion(run, clip, frames, rename, offline, sheet_no=3)
            for t in rename:
                c = said.get(t, {})
                verdicts[t]["confirm"] = c
                if (c.get("is_animal") is True and _conf(c) >= 0.7
                        and not name_disagreement(verdicts[t].get("species"), c.get("name"))):
                    labels[t] = verdicts[t]["species"].lower()
                    verdicts[t]["relabelled"] = f"{trk[t]['label']} -> {labels[t]}"
                    verdicts[t]["midconf_renamed"] = True
            run.stage("audit", f"second look at {len(rename)} mid-confidence renamed discovery track(s): "
                      + ", ".join(f"{verdicts[t]['name']} {labels.get(t) or 'kept'} ({said.get(t, {}).get('reason', 'no answer')})" for t in rename))
    if do_audit and clean:
        for f in os.listdir(run.path()):
            if f.startswith("shadow_") and f.endswith(".jpg"):
                os.remove(run.path(f))
        counted = [t for t in verdicts if labels.get(t) and not trk[t]["source"].startswith("camo")]
        dark = dark_tracks(clip, frames, counted, inf["width"], inf["height"]) if counted else []
        if dark:
            # --crowd-peak tile tracks on their own sheet (shadow_2), so the first-pass sheet and its answer stay
            said = {}
            for ts, no in (([t for t in dark if not trk[t]["source"].startswith("peak+")], 1),
                           ([t for t in dark if trk[t]["source"].startswith("peak+")], 2)):
                if ts:
                    said.update(shadow_look(run, clip, frames, ts, offline, sheet_no=no))
            pairs = shadow_pairs(frames, dark, counted)
            for t in dark:
                c = said.get(t, {})
                # only an answer of "shadow" takes a track out: "water"/"sand" from this look does not overrule the
                # audit's close-up yes (the luderick fish above)
                if c.get("is_animal") is False and str(c.get("what", "")).lower() == "shadow" and _conf(c) >= 0.7:
                    verdicts[t]["shadow"] = c
                    labels[t] = None        # needs_review keeps it in the queue, where a person can restore it
                elif t in pairs:            # a counted fish above moves rigidly with it: that fish's shadow (T50)
                    comp, spread, dist = pairs[t]
                    verdicts[t]["shadow"] = {"what": "shadow", "pair": comp, "spread": spread, "dist": dist,
                                             "reason": f"moves with {verdicts.get(comp, {}).get('name', comp)} above it"}
                    labels[t] = None
            run.stage("audit", f"{len(dark)} counted track(s) darker than the seabed around them; Muse Spark, wide view: "
                      + ", ".join(f"{verdicts[t]['name']} {'shadow' if verdicts[t].get('shadow') else 'animal'} "
                                  f"({verdicts[t].get('shadow', {}).get('reason') or said.get(t, {}).get('reason', 'no answer')})"
                                  for t in dark))
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
    for c in checks:
        for q in c.get("queue", []):
            if q["track"] in verdicts:
                verdicts[q["track"]]["peak_doubt"] = f"peak frame {c['frame']}, asked '{c['label']}': {q['said']}"
    m = tracks.metrics(frames, trk, inf["n_frames"], inf["fps"], labels)
    for name, mm in m.items():
        mm["peak_checked"] = any(c["label"] == name and c["frame"] == mm["maxn_frame"] for c in checks)
    crowd = []
    if do_audit and crowd_look:
        try:
            crowd = crowd_check(run, clip, m, inf["fps"], offline,
                                extra=empty_rows(m, plist, frames, trk, inf["n_frames"]) if crowd_peak is not None else ())
        except FileNotFoundError as e:      # an offline replay of a run made before the crowd check
            run.stage("verify", f"crowd check skipped: {str(e)[:120]}")
    if crowd_peak is not None and _peak is None:
        win = peak_windows(crowd, inf["n_frames"], crowd_peak)
        if win:
            run.stage("verify", f"crowd peak: lower bound(s) at frame(s) {sorted({c['frame'] for c in crowd if c.get('lower_bound')})}; "
                      f"3x2 tiles on frames {', '.join(f'{s}-{e - 1}' for s, e in win)}, then the run again with them")
            return run_pipeline(**dict(args, rid=rid, _peak=dict(windows=win, first=crowd), _run=run))
    live = {}       # frames a track still holds after verify_peaks/drop_nested removed boxes (trk keeps the pre-removal list)
    for f, ks in frames.items():
        for k in ks:
            live.setdefault(k["track"], []).append(f)
    result = dict(id=rid, source=os.path.basename(src), video=inf, prompts=plist, jobs=[dict(name=j[0], label=j[1], prompt=j[2], tile=j[4]) for j in jobs], scout=sc,
                  tracks={t: dict(v, n=len(fs), first=min(fs, default=None), last=max(fs, default=None), frames=None) for t, v in trk.items() for fs in [live.get(t, [])]},
                  verdicts=verdicts, auto_labels=labels, metrics=m, group_metrics=group_metrics(m, inf["fps"]),
                  discovered=found, signs=disc.get("signs", []), recovered=recovered, peak_checks=checks, duplicates=dups,
                  crowd_checks=crowd, frames={str(f): [dict(track=k["track"], box=[round(x, 1) for x in k["box"]]) for k in ks] for f, ks in frames.items()})
    if site:
        result["site"] = dict(name=site, entries=site_entries)
    if _peak:
        result["crowd_peak"] = dict(half=crowd_peak, windows=_peak["windows"], first_pass=_peak["first"])
    if run.capped:      # only when a stage was skipped at the cap, so other results keep their exact bytes
        result["capped"] = run.capped
    run.save("result.json", result)
    run.stage("render", "drawing evidence frames")
    for name, mm in m.items():
        if mm["maxn_frame"] is not None:
            render.evidence(clip, raw, result, mm["maxn_frame"], run.path(f"evidence_{api_safe(name)}.jpg"), name)
    run.stage("render", "drawing the annotated video")
    render.annotate(clip, raw, result, run.path("annotated.mp4"))
    gone = drop_temp(run.dir)
    if gone:
        run.stage("render", f"removed {len(gone)} working video(s) sent to SAM (FISH_KEEP_TEMP=1 keeps them)")
    run.status["done"] = time.time()
    run.stage("done", f"finished in {run.status['done'] - run.status['started']:.0f}s; live calls {run.status['live_calls']}, cached {run.status['cached_calls']}, billed ${run.status['billed_usd']:.3f}")
    return result


def site_look(run, clip, inf, site, skip, max_usd, offline):
    """Site memory (opt-in, docs/site_memory.md): words a reviewer gave to earlier videos of this site, each a SAM word
    ladder [noun, alt]. Runs after discovery and the second look: words discovery already tracked (`skip`) are not
    repeated, entries that would pass the per-video cap are dropped (least confirmed first), and an uncached word in a
    free replay is recorded as not tried, never an error. Returns (entries, results to merge first)."""
    from fishcount import sitememory
    entries = sitememory.plan(site, skip_words=skip)
    per_word = max(api.SAM_MIN_FRAMES, inf["n_frames"]) * api.SAM_PER_FRAME
    while entries and not offline and run.status["billed_usd"] + sum(len(e["words"]) for e in entries) * per_word > max_usd:
        e = entries.pop()
        _capped(run, "recover", f"site memory '{e['label']}' skipped: would pass the per-video cap ${max_usd:.2f}")
    if not entries:
        return [], []
    run.stage("recover", "site memory: " + ", ".join(f"{e['label']} -> try {e['words']}" for e in entries))

    def one(e):
        try:
            return word_ladder(run, clip, inf["n_frames"], e["words"], offline) + (None,)
        except MOTION_ERRORS as ex:
            return None, "", [], f"{type(ex).__name__}: {str(ex)[:120]}"

    with cf.ThreadPoolExecutor(3) as ex:
        outs = list(ex.map(one, entries))
    results = []
    for i, (e, (word, txt, tried, err)) in enumerate(zip(entries, outs)):
        d = tracks.parse_boxes(txt) if txt else {}
        e.update(source=f"k{i}", word=word, tried=tried, frames=len(d), maxn_full=tracks.max_per_frame(d) if d else 0)
        if err:
            e["error"] = err + (" (free replay only reuses saved answers; allow paid calls to try this word)" if offline else "")
        run.stage("recover", f"site memory '{e['label']}': " + (", ".join(f"'{t['word']}' {t['frames']} frames" for t in tried) or e.get("error", "not tried")))
        if word:
            results.append((f"k{i}", word, d, txt, None))
    return entries, results


def recover(run, clip, inf, others, found, signs, results, max_usd, offline, max_tiles=3, probe_window=None):
    """Second look for discovered animals (11/1 s003: full frame 'nautilus' tracked 1 of 3; a zoomed crop tracked
    all 3, and a reversed pass back-filled the frames before SAM first recognised it).
      backfill: the word that worked, run again on the reversed clip;
      zoom:     Spark expected more than SAM found -> crop the cells Spark named and run the ladder there;
      sign:     an indirect sign (sand puff, shadow) -> crop that cell and try the words for the suspected animal.
    Appends (name, label, dets, text, tile) to `results`; returns a log for the UI."""
    n, W, H = inf["n_frames"], inf["width"], inf["height"]
    jobs, log = [], []
    for i, ((o, words), f) in enumerate(zip(others, found)):
        if not words or f.get("not_sent"):       # --skip-people / left unsent at the cap
            continue
        if f["word"]:
            jobs.append(dict(kind="backfill", name=f"d{i}rev", what=o["what"], words=[f["word"]], cell=None))
        if (f["maxn_full"] or 0) < int(o.get("approx_max_count") or 1):
            ladder = ([f["word"]] if f["word"] else []) + [w for w in words if w != f["word"]]
            for cell in [c for c in o.get("cells", []) if c in CELLS][:2]:
                jobs.append(dict(kind="zoom", name=f"d{i}z-{cell}", what=o["what"], words=ladder[:2], ladder=ladder[:3], cell=cell,
                                 spark_frames=o.get("frames")))
    for j, sg in enumerate(signs):
        guess = (sg.get("possible_animal") or "").lower()
        if sg.get("region") not in CELLS or "unknown" in guess:
            continue
        match = next((f for f in found if f["word"] and (f["word"] in guess or guess in f["what"].lower())), None)
        words = [match["word"]] if match else [w for w in guess.split()[-1:] if w.isalpha()]
        if words:
            jobs.append(dict(kind="sign", name=f"s{j}-{sg['region']}", what=sg.get("sign", ""), words=words, cell=sg["region"],
                             spark_frames=[sg.get("frame")]))
    seen, todo = set(), []
    for jb in jobs:     # one tile per (block, first word); backfills always kept, tiles capped
        key = (jb["cell"] and block_box(jb["cell"], W, H), jb["words"][0])
        if key in seen or (jb["cell"] and sum(1 for t in todo if t["cell"]) >= max_tiles):
            continue
        seen.add(key)
        todo.append(jb)
    if not todo:
        return log
    # R9: a zoom ladder with probe windows is priced as word_ladder will run it (ladder_estimate, never more than before)
    whole = max(api.SAM_MIN_FRAMES, n) * api.SAM_PER_FRAME
    est = 0.0
    for jb in todo:
        k = len(jb["words"])
        pw = _probe_windows(jb.get("spark_frames"), n, probe_window) if probe_window and jb["kind"] == "zoom" else []
        est += min(k * whole, k * _window_cost(pw) + whole) if pw else k * whole
    if run.status["billed_usd"] + est > max_usd and not offline:
        _capped(run, "recover", f"skipped second look: est ${est:.2f} would pass the per-video cap ${max_usd:.2f}")
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
        m = video.info(jb["path"])["n_frames"]
        # not a sign: Spark's one frame is where the sand moved, the animal may show later (11/21 DH7: sign at frame 0,
        # SAM's crab from frame 28 - a window would have dropped it)
        probe = _probe_windows(jb.get("spark_frames"), m, probe_window) if probe_window and jb["kind"] == "zoom" else None
        word, txt, tried = word_ladder(run, jb["path"], m, jb["words"], offline, probe)
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
        log += closer_look(run, clip, inf, closer, results, max_usd, offline, probe_window=probe_window)
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


# Coarse animal groups for comparing two names of one track. Only clear group differences count as a disagreement
# (a "fish" against a "shrimp"); a name outside this list never does.
NAME_GROUPS = {
    "fish": ("fish", "eel", "hagfish", "shark", "ray", "seabream", "bream", "luderick", "grouper", "snapper", "wrasse",
             "goby", "blenny", "cod", "rockfish", "flatfish", "flounder", "skate", "lamprey", "perch", "mullet",
             # 11/9 outside data (IMR, Exeter, FinPrint): Spark named these and they fell out of the fish total and the
             # peak check's same-group rule (G2 haddock 2, BE10 "pollack / saithe" 5, FinPrint jack/trevally/fusilier).
             # Any other "...fish" or "...shark" word is a fish too (_group_of_word), unless listed under another group.
             "haddock", "pollack", "pollock", "saithe", "whiting", "hake", "lingcod", "rockling",
             "plaice", "halibut", "turbot", "brill", "mackerel", "herring", "sprat", "sardine",
             "anchovy", "tuna", "bonito", "jack", "trevally", "fusilier", "gurnard", "sculpin", "greenling", "bass",
             "seabass", "sweetlip", "tang", "chromis", "puffer", "barracuda", "salmon", "trout",
             "dory", "moray", "conger", "stingray", "manta", "seahorse", "dragonet", "weever", "wobbegong", "mola",
             "flathead", "remora", "cobia", "sweeper", "morwong", "drummer", "leatherjacket", "eelpout",
             "hammerhead", "sandeel", "megrim", "tarpon", "snook", "porgy"),
    "crustacean": ("shrimp", "prawn", "crab", "lobster", "krill", "amphipod", "isopod", "crustacean", "crayfish", "crawfish",
                   "caridean", "copepod", "barnacle", "squat", "nephrop", "langoustine"),   # norm_label: nephrops -> nephrop
    "cephalopod": ("nautilus", "octopus", "octopi", "squid", "cuttlefish", "inkfish", "cephalopod"),
    "gastropod": ("snail", "whelk", "slug", "nudibranch", "gastropod", "limpet"),
    "echinoderm": ("starfish", "star", "seastar", "urchin", "cucumber", "brittlestar", "echinoderm", "crinoid"),
    "worm": ("worm", "polychaete", "tubeworm", "annelid"),
    "cnidarian": ("anemone", "jellyfish", "jelly", "coral", "hydroid", "cnidarian"),
}
_GROUP_OF = {w: g for g, ws in NAME_GROUPS.items() for w in ws}


def _group_of_word(w):
    """The group of one normalised word: the lists above, else any longer "...fish" / "...shark" word is a fish
    ("lionfish", "catshark"); "shellfish" is not one animal group and "nonfish" is not a fish. Jellyfish, starfish,
    cuttlefish, inkfish, crayfish and crawfish are listed under their own groups, so they never reach the suffix rule."""
    if not w:
        return None
    if w in _GROUP_OF:
        return _GROUP_OF[w]
    if len(w) > 5 and w.endswith(("fish", "shark")) and w != "shellfish" and not w.startswith("non"):
        return "fish"
    return None


_PLACE = ("on", "at", "in", "near", "by", "under", "over", "with", "from", "behind", "inside", "beside", "among")


def _name_words(name):
    """The normalised words of a discovery name before its first place preposition."""
    ws = re.sub(r"[^a-z ]", " ", (name or "").lower()).split()
    for i, w in enumerate(ws):
        if w in _PLACE:
            ws = ws[:i]
            break
    return [norm_label(w) for w in ws]


def animal_nouns(name):
    """Every known animal word (NAME_GROUPS) of a discovery name before a place preposition, from the end, so the
    head noun comes first: "chambered nautilus cephalopod" -> [cephalopod, nautilus], "crab on a starfish" -> [crab]."""
    out = []
    for w in reversed(_name_words(name)):
        if w in _GROUP_OF and w not in out:
            out.append(w)
    return out


def short_name(name):
    """The animal noun of a discovery name, for SAM: words before a place preposition, then from the end the first
    known animal word (NAME_GROUPS), else the last word that is not a participle ("clustered", "swimming") or vague.
    "chambered nautilus clustered on bait" -> nautilus, "small red crab on seabed" -> crab."""
    cand = _name_words(name)
    for w in reversed(cand):
        if w in _GROUP_OF:
            return w
    for w in reversed(cand):
        if w and not w.endswith(("ed", "ing")) and len(w) > 2:
            return w
    return None


# Opt-in (--skip-people): a discovery that names people or a boat and no animal is not searched for. 11/21 night,
# LONG1_cr9 S1 (the camera on deck before it went in): "human on boat deck" -> 'person' on the whole segment and on
# it reversed (5,316 billed frames, $1.06) plus 10 audits and 3 duplicate checks, all for rows "human" (MaxN 3) and
# "person (unidentified)" (1) in a fish census. Off by default: a survey that counts divers or boats keeps them.
PEOPLE_WORDS = {"person", "persons", "people", "human", "humans", "man", "men", "woman", "women", "diver", "divers",
                "snorkeler", "swimmer", "fisherman", "fishermen", "crew", "hand", "hands", "arm", "leg", "foot", "feet",
                "boat", "vessel", "ship", "deck", "hull", "kayak"}


def _is_people(o):
    """True when a Spark discovery (others[i]) names a person or a boat in its name or search words and no animal."""
    words = _name_words(o.get("what") or "")
    for w in o.get("search_words") or []:
        if isinstance(w, str):
            words += [norm_label(x) for x in re.sub(r"[^a-z ]", " ", w.lower()).split()]
    if any(_group_of_word(w) for w in words):
        return False
    return any(w in PEOPLE_WORDS or w.rstrip("s") in PEOPLE_WORDS for w in words if w)


# a negated phrase, up to the next comma or bracket or a word that turns to what it is: "blurry water no fish",
# "not a cod, other fish" -> "other fish", "not a cod but a haddock" -> "but a haddock" (11/10 review: these were None);
# "no-" in a hyphenated word is not a negation ("no-name fish") unless an animal word follows ("no-fish zone", see
# name_group); "non" only its own word: "elongate non-flatfish fish" is a fish (outreach Exeter G1, a flatfish track's
# peak check)
# re.ASCII: \b as in JavaScript (demo/static_review.js), so a letter like "é" next to "no" splits them the same way
_NEGATED = re.compile(r"\bnon-?[a-z]*|\b(?:not\b|no\b(?!-))"
                      r"(?:(?!\b(?:but|only|rather|instead|however|though|although|except|yet|just)\b)[^,;.()/])*",
                      re.ASCII)


def name_group(name):
    """The coarse group of a name, by its head noun and then any of its words ("caridean shrimp" -> crustacean);
    None when no word is known. A negated phrase names no animal: "blurry water no fish" is None, not fish
    (runs/demo_TF52d,g-j and cr_s004: such peak-check answers were queued as another animal of the group)."""
    name = re.sub(r"\bno-([a-z]+)", lambda m: "no " + m[1] if _group_of_word(norm_label(m[1])) else m[0],
                  (name or "").lower(), flags=re.ASCII)
    name = _NEGATED.sub(" ", name)
    g = _group_of_word(_head(name))
    if g:
        return g
    for w in re.sub(r"[^a-z ]", " ", (name or "").lower()).split():
        g = _group_of_word(norm_label(w))
        if g:
            return g
    return None


# words that make a "not a <name>" answer a part, a duplicate or not an animal, even when an animal word is in it
# ("sediment between crab legs", "tail of another fish", "second box on the same fish"): such a box leaves the peak
_NOT_ANOTHER = {"leg", "tail", "fin", "head", "claw", "antenna", "shell", "part", "body", "same", "second", "sediment",
                "sand", "rock", "bait", "shadow", "reflection", "mesh", "trap", "debris", "carcass", "between"}
# Before a place word: remains as the last noun leave the peak ("fish skeleton", "shrimp moult"); a plant leaves only
# when no animal is named with it ("seaweed near fish", "algae on crab"). "clear striped fish over seagrass"
# (runs/eval_fish_20190618_9), "fish next to seagrass", "fish and seaweed", "kelp and small fish", "algae urchin" stay
# (11/10 review: the plant rule fired on "fish next to seagrass" / "fish amongst kelp" / "fish and seaweed").
# Not "egg" or "burrow": "crab with eggs", "crab in burrow" are the animal (11/10 develop review).
# For the plant, "with" and "past" join instead of placing: "kelp with fish", "seagrass with a fish in it", "seaweed
# drifting past fish" say the animal is in the box with the plant and stay; "seaweed near fish" / "on" / "next to" put
# the animal beside the box and leave. Remains are the last noun of a phrase that "of" / "with" / "past" end: "skeleton
# of fish", "moult of a fish", "pile of fish skeleton", "kelp with fish skeleton", "fish remains" leave; "school of
# fish" stays. "remains" is the noun only at the end or before "of": "the fish remains still" / "fish remains in place"
# are the verb and stay (as on 22ea128, which had no "remains" rule; 11/10 third review).
_PLANT = {"kelp", "seagrass", "seaweed", "weed", "alga", "algae"}
_REMAINS = {"moult", "molt", "skeleton"}
_JOIN = ("with", "past")
_AROUND = _PLACE + ("above", "below", "beneath", "across", "through", "around", "against", "amid", "along",
                    "alongside", "past", "next", "to", "amongst", "amidst", "within", "atop", "underneath", "beyond",
                    "into", "onto", "upon", "toward", "towards")


def same_group_answer(said, group):
    """True when a peak-check answer names another animal of `group` ("other fish" under a fish label), not a part,
    a duplicate or a non-animal that merely mentions an animal word (11/2 pre-freeze review: "sediment between crab
    legs" was kept under "crab"; 11/10: "blurry water no fish" was kept under "fish", see name_group)."""
    raw = re.sub(r"[^a-z ]", " ", (said or "").lower()).split()
    words = [norm_label(w) for w in raw]
    if set(words) & _NOT_ANOTHER:
        return False
    def upto(stops):
        return next((i for i, w in enumerate(raw) if w in stops), len(raw))
    lead, end = words[:upto(_AROUND)], upto(set(_AROUND) - set(_JOIN))
    if set(lead) & _PLANT and not any(_group_of_word(w) for w in words[:end]):
        return False
    # Remains: each "with" / "past" phrase in turn, each "of" part read from its last word back; remains there that no
    # animal word follows leave ("fish skeleton", "skeleton of fish"). The first phrase that names an animal is what
    # the box is, so the phrases after it are only beside it: "fish with skeleton" stays, "kelp with fish skeleton" not.
    start = 0
    for stop in [i for i in range(end) if raw[i] in _JOIN] + [end]:
        animal = named = False
        for i in reversed(range(start, stop)):
            if raw[i] == "of":
                animal = False
            elif not animal:
                if words[i] in _REMAINS or (raw[i] == "remains" and (i + 1 == len(raw) or raw[i + 1] == "of")):
                    return False
                animal = bool(_group_of_word(words[i]))
                named = named or animal
        if named:
            break
        start = stop + 1
    return name_group(said) == group


CROWD_WORDS = {"fish": "fish (any kind, including sharks and eels)", "crustacean": "crabs, shrimp or other crustaceans",
               "cnidarian": "corals or sea anemones", "cephalopod": "nautiluses, octopuses or squid",
               "gastropod": "snails or slugs", "echinoderm": "sea stars, urchins or sea cucumbers", "worm": "worms"}
CROWD_PROMPT = """The first image is one frame of underwater survey video. The next four images are its four quarters (top-left, top-right, bottom-left, bottom-right), enlarged, so that small animals are easier to see; they show the same animals again, so count each animal once.

Count the {what} in this frame. Count only what you would bet is a separate animal; include animals that are partly hidden, at the edge, small or far away. If they are packed so tightly that you cannot count each one, give your best estimate.

Reply with JSON only: {{"total": <integer>, "estimated": <true if you estimated instead of counting each one>, "reason": "<one short sentence>"}}"""
CROWD_MIN_EXTRA, CROWD_RATIO = 3, 1.5     # fixed 11/4 before any crowd_check reply was seen


def _crowd_reply(text):
    j = api.parse_json(text)
    if not isinstance(j, dict) or not isinstance(j.get("total"), int) or j["total"] < 0:
        raise ValueError("expected {total: int}")
    return j


def crowd_count(img, what, offline, run=None):
    """Muse Spark's unprimed count of `what` in one frame (BGR), shown whole and as four 2x quarters."""
    h, w = img.shape[:2]
    quarters = [img[y:y + h // 2, x:x + w // 2] for y in (0, h // 2) for x in (0, w // 2)]
    pics = [video.jpg(img, max_w=1280)] + [video.jpg(cv2.resize(q, (w // 2 * 2, h // 2 * 2)), max_w=1280) for q in quarters]
    args = (api.spark, CROWD_PROMPT.format(what=what), pics)
    kw = dict(offline=offline, check=_crowd_reply)
    return _crowd_reply(_counted(run, *args, **kw) if run else args[0](*args[1:], **kw))


def crowd_rows(m, fps):
    """One row per counted animal group (any number of labels) plus each counted label outside the groups:
    (row name, labels, maxn, peak frame, words for the question)."""
    out = []
    for g, gg in group_metrics(m, fps, min_labels=1).items():
        if gg["maxn"]:
            out.append((g, gg["labels"], gg["maxn"], gg["maxn_frame"], CROWD_WORDS.get(g, g)))
    for name, mm in m.items():
        if not name_group(name) and mm["maxn"]:
            out.append((name, [name], mm["maxn"], mm["maxn_frame"], short_name(name) or name))
    return out


def empty_rows(m, plist, frames, trk, n):
    """--crowd-peak only: each requested word whose animal group counted nothing gets a crowd_check row too, MaxN 0,
    asked at the frame where most boxes of that word were before the audit (or the middle frame when SAM found none).
    Without it a clip whose boxes were all turned down, or never made, says 0 and nothing asks again; crowd_rows keeps
    only rows with a MaxN. Spark's count marks the 0 a lower bound at CROWD_MIN_EXTRA or more, as for any row."""
    counted = {name_group(x) or x for x, mm in m.items() if mm["maxn"]}
    out = []
    for lab, _ in plist:
        g = name_group(lab) or lab
        if g in counted or any(r[0] == g for r in out):
            continue
        per = {}
        for f, ks in frames.items():
            for k in ks:
                if trk.get(k["track"], {}).get("label") == lab:
                    per[int(f)] = per.get(int(f), 0) + 1
        f = min(per, key=lambda x: (-per[x], x)) if per else n // 2
        out.append((g, [], 0, f, CROWD_WORDS.get(g, short_name(lab) or lab)))
    return out


# Opt-in (--crowd-peak): the crowd tiles (crowd_tiles, 3x2, 2x) only around a peak frame the crowd check marked a lower
# bound. 11/21 night: LONG1 S1, S5, S6 peaks are lower bounds (MaxN 14 / 10 / 8 against Spark 22 / 19 / 28); --crowd on
# a 600-s segment sends six whole-segment tiles ($3.19), a window of 51 frames costs 6 x 51 frames ($0.06).
CROWD_PEAK = 25         # frames on each side of the peak frame (51 frames = 10 s at 5 fps)
CROWD_PEAK_MAX = 3      # windows per clip


def peak_windows(checks, n, half):
    """[(start, end)] frame ranges around every lower-bound row's frame, overlapping ones joined, at most CROWD_PEAK_MAX.
    The whole clip when a window would be half of it or more (a 12-s clip: the tiles are then --crowd's own calls)."""
    fs = sorted({c["frame"] for c in checks if c.get("lower_bound")})
    if not fs:
        return []
    if 2 * (2 * half + 1) >= n:
        return [(0, n)]
    out = []
    for f in fs:
        s, e = max(0, f - half), min(n, f + half + 1)
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out[:CROWD_PEAK_MAX]


def peak_tiles(run, clip, inf, windows, label, max_usd, offline):
    """SAM 'fish' on the crowd tiles of each window (a clip of its own, video.segment), frames renumbered to the clip.
    Each tile of each window is a fresh call with its own 16 ids. Returns sources (name "peak+<start>-<tile>") to
    merge after every other source, so every earlier track keeps its number."""
    jobs = []
    for s, e in windows:
        src = clip
        if e - s < inf["n_frames"]:
            src = run.path(f"peak+{s}.mp4")
            video.segment(clip, src, s, length=e - s)
        for name, box in crowd_tiles(inf["width"], inf["height"]):
            tp = run.path(f"tile_peak+{s}-{name}.mp4")
            video.crop_tile(src, tp, box, scale=2)
            jobs.append((f"peak+{s}-{name}", label, "fish", tp, box, s, e - s))
    todo = []
    for j in jobs:
        if (not offline and not api.sam_cached(j[3], j[2])
                and run.status["billed_usd"] + max(api.SAM_MIN_FRAMES, j[6]) * api.SAM_PER_FRAME > max_usd):
            _capped(run, "track", f"crowd peak: {j[0]} not sent: would pass the per-video cap ${max_usd:.2f}")
            continue
        todo.append(j)

    def one(j):
        name, label, prompt, path, box, s, m = j
        txt = tracks.shift_text(_counted(run, api.sam_video, path, prompt, m, offline=offline), s)
        return name, label, tracks.from_tile(tracks.parse_boxes(txt), box, 2), txt, box

    with cf.ThreadPoolExecutor(4) as ex:
        out = list(ex.map(one, todo))
    run.stage("track", "crowd peak tiles: " + ", ".join(
        f"{o[0]} {len({d['id'] for ds in o[2].values() for d in ds})} ids" for o in out))
    return out


def crowd_check(run, clip, m, fps, offline, extra=()):
    """extra: more rows in crowd_rows' form (empty_rows, --crowd-peak only).
    GPT review 11/4, Table 3e: in crowded peak frames MaxN is a lower bound (DH3 crustaceans 4 against two
    counters' 15, DH8 fish 16 against 44, s004 hagfish 1 against 20), and nothing in the output said so. SAM 3.1 gives
    one call 16 object ids and answers only some words, so the tracks cannot be made to see every animal; instead the
    count is checked. Muse Spark, unprimed (no boxes, no number), counts the row's animals in its peak frame, given
    the frame and its four enlarged quarters, with the instruction the two human counters had. A row is marked a
    lower bound when Spark's total is at least CROWD_MIN_EXTRA more than MaxN and at least CROWD_RATIO times it; the
    review screen then shows MaxN as ">= n" with a "count this frame" card, and the export carries the flag. Spark's
    number is never used as the count: Table 1c shows its own counts run high."""
    rows = crowd_rows(m, fps) + list(extra)
    if not rows:
        return []
    imgs = video.frames(clip, {r[3] for r in rows})
    out = []
    for name, labels, maxn, f, what in rows:
        img = imgs.get(f)
        if img is None:
            continue
        try:
            j = crowd_count(img, what, offline, run)
        except (ValueError, FileNotFoundError) as e:
            out.append(dict(row=name, labels=labels, frame=f, maxn=maxn, total=None, lower_bound=False, error=str(e)[:120]))
            continue
        tot = j["total"]
        lb = tot >= maxn + CROWD_MIN_EXTRA and tot >= CROWD_RATIO * maxn
        out.append(dict(row=name, labels=labels, frame=f, maxn=maxn, total=tot, estimated=bool(j.get("estimated")),
                        reason=j.get("reason", ""), lower_bound=lb))
        if not maxn:        # an empty_rows row: nothing was counted, Spark was asked anyway
            out[-1]["empty"] = True
    run.stage("verify", "crowd check (Muse Spark counts each row's peak frame, unprimed): " + ", ".join(
        f"{c['row']} MaxN {c['maxn']} / Spark {c['total']}{' -> lower bound' if c['lower_bound'] else ''}" for c in out))
    return out


def group_metrics(m, fps, min_labels=2):
    """Same-frame totals per coarse animal group (NAME_GROUPS) over the per-label metrics `m`: one track has one
    label, so the per-frame counts of the labels in a group add up ("caridean shrimp" 12 + "shrimp (unidentified)" 3
    peaking in one frame is 15 crustaceans). Only groups covering `min_labels` or more labels are returned (a group
    of one label is that label's row). Labels outside NAME_GROUPS are left out. The per-label rows are unchanged."""
    groups = {}
    for name in m:
        g = name_group(name)
        if g:
            groups.setdefault(g, []).append(name)
    out = {}
    for g, names in sorted(groups.items()):
        if len(names) < min_labels:
            continue
        n = max(len(m[x]["curve"]) for x in names)
        c = [sum(m[x]["curve"][i] for x in names if i < len(m[x]["curve"])) for i in range(n)]
        top = max(c) if c else 0
        firsts = [m[x]["first_frame"] for x in names if m[x]["first_frame"] is not None]
        first = min(firsts) if firsts else None
        out[g] = dict(labels=sorted(names), maxn=top, maxn_frame=c.index(top) if top else None,
                      maxn_time=round(c.index(top) / fps, 2) if top else None, first_frame=first,
                      first_time=round(first / fps, 2) if first is not None else None,
                      tracks=sum(m[x]["tracks"] for x in names), curve=c)
    return out


def name_disagreement(audit_name, second_name):
    """'<audit> vs <second look>' when both names fall in known, different groups; else None."""
    a, b = name_group(audit_name), name_group(second_name)
    if a and b and a != b:
        return f"{audit_name} vs {second_name}"
    return None


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
    elif len(w) > 5 and w.endswith("uses") and w[-5] not in "aeiou":
        # octopuses -> octopus, nautiluses -> nautilus, walruses -> walrus; houses, causes, blouses fall through to
        # the plain rule (house). ponytail: "excuses"/"abuses" still lose the e (excus) - no animal name, no list
        w = w[:-2]
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


def _miss_box(v, s, W, H, min_side=8):
    """Spark's missed-animal box in frame pixels (its picture scaled by `s`), clamped to the frame; None when it is
    malformed or less than `min_side` px wide or tall inside the frame. The size is checked after clamping: a 45 px box
    with 5 px inside the frame used to pass and reach SAM as a sliver (11/10 develop review)."""
    try:
        b = [float(x) / s for x in v["box"]][:4]
    except (KeyError, TypeError, ValueError):
        return None
    if len(b) < 4:
        return None
    b = [max(0, min(W, b[0])), max(0, min(H, b[1])), max(0, min(W, b[2])), max(0, min(H, b[3]))]
    if b[2] - b[0] < min_side or b[3] - b[1] < min_side:
        return None
    return b


def _miss_label(lab, labels):
    """A missed animal's label: in a one-label request, a name of the same known group takes the request's label
    ("luderick" or "bream" in a fish request is a fish). Two names outside every group are not the same group."""
    if len(labels) == 1 and lab not in [norm_label(l) for l in labels]:
        g = name_group(lab)
        if g and g == name_group(labels[0]):
            return norm_label(labels[0])
    return lab


# Opt-in (--box-window): a box prompt on a long clip goes to SAM with only the frames around the spot's frame.
# 11/21 night (LONG1_cr9, 6 segments of 2,658 frames): 28 box prompts were $14.88, 57% of the SAM bill, and the
# boxes they left counted toward no MaxN (all 6 segments, every label, unchanged with them removed). 92% of their
# boxes lay over 100 frames from the spot: the same still object (seabed, a crab, a snail; the audit rejected them)
# all segment long, or SAM's id 1 moved to other fish, already tracked by the "fish" pass.
BOX_WINDOW = 100        # frames on each side of the spot's frame (201 frames = 40 s at 5 fps)
BOX_STILL = 0.5         # a windowed track whose centre stays within this many box sizes counts as sitting still


def _box_clip(run, clip, frame, n, half, tag):
    """(path, first frame, frames) of the clip a box prompt at `frame` goes to: the whole clip, or with `half` the
    frames [frame - half, frame + half] cut out as a clip of their own (video.segment). A window as long as the clip
    is the clip itself, so short clips keep their exact SAM call (and cache key)."""
    if half is None:
        return clip, 0, n
    s, e = max(0, frame - half), min(n, frame + half + 1)
    if e - s >= n:
        return clip, 0, n
    seg = run.path(f"box_{tag}+{s}.mp4")
    video.segment(clip, seg, s, length=e - s)
    return seg, s, e - s


def _sits_still(d, still=BOX_STILL):
    """True when every box in `d` keeps its centre within `still` box sizes of the first one (a resting animal, a
    rock, a crab that has not moved)."""
    fs = sorted(f for f, ds in d.items() if ds)
    if len(fs) < 2:
        return False
    b0 = d[fs[0]][0]["box"]
    size = max(b0[2] - b0[0], b0[3] - b0[1], 1)
    cx, cy = (b0[0] + b0[2]) / 2, (b0[1] + b0[3]) / 2
    return all(math.hypot((x["box"][0] + x["box"][2]) / 2 - cx, (x["box"][1] + x["box"][3]) / 2 - cy) <= still * size
               for f in fs for x in d[f])


def _followed(box, frame, mine, windowed):
    """Name of an earlier box call whose track already has this spot, or None. In its frame (motion_look's rule);
    with windowed calls also a track that sat still in its window and has this box at its frame nearest to `frame`
    (11/21 night LONG1_cr9: the whole-clip calls skipped 13 spots as already followed; on 100-frame windows the
    frame rule alone still skips 2 of them, with the nearest frame of a still track 11, and none of the 28 spots the
    whole-clip calls sent is skipped)."""
    for name, d in mine:
        if any(tracks.overlap(box, k["box"]) >= 0.3 for k in d.get(frame, [])):
            return name
        if windowed and _sits_still(d):
            g = min((f for f, ds in d.items() if ds), key=lambda f: abs(f - frame))
            if any(tracks.overlap(box, k["box"]) >= 0.3 for k in d[g]):
                return name
    return None


def motion_look(run, clip, inf, results, max_usd, offline, k=8, max_boxes=5, min_conf=0.6, names=(), rnd=1, box_window=None):
    """Look where pixels moved but nothing was boxed (fishcount/motion.py): up to `k` spots go to Spark on one
    sheet; up to `max_boxes` it calls animals go to SAM as box prompts, no word. Appends ("m<i>", label, dets,
    text, None) to `results`; returns log entries for the UI. Spark's verdict and the chosen boxes are cached per
    clip (cache/motion_<sha>_<ver>.json), so a free replay does not depend on re-deriving the same sheet bytes.
    box_window: opt-in half width in frames (BOX_WINDOW): each box prompt sees only the frames around its spot
    (_box_clip); None = the whole clip, as before."""
    n, W, H = inf["n_frames"], inf["width"], inf["height"]
    known = {}
    for _, _, d, _, _ in results:            # +-3 frames: a box SAM lost for a frame still covers its animal
        for f, ds in d.items():
            for g in range(max(0, f - 3), min(n, f + 4)):
                known.setdefault(g, []).extend(list(det["box"]) for det in ds)
    # keyed by what decides the spots (clip, boxes already found, prompt), so a free replay of the same run finds
    # it and a run with other prompts does not reuse it
    kb = json.dumps(sorted((f, sorted([round(v) for v in b] for b in bs)) for f, bs in known.items()))
    # rnd 2 = the look again after the first look's boxes (the first look's key is unchanged, so its cache still hits)
    key = hashlib.sha256((api.file_sha(clip) + kb + MOTION_PROMPT + MOTION_VERSION + ("" if rnd == 1 else f"r{rnd}")).encode()).hexdigest()[:24]
    cpath = os.path.join(api.CACHE, f"motion_{key}.json")
    sheet_jpg = run.path("motion_sheet.jpg" if rnd == 1 else f"motion_sheet{rnd}.jpg")
    scan = "Movement outside every box" + ("" if rnd == 1 else " (second look, after the first boxes)")
    per_box = min(n, 2 * box_window + 1) if box_window is not None else n
    est = 0.04 + max_boxes * max(api.SAM_MIN_FRAMES, per_box) * api.SAM_PER_FRAME
    if run.status["billed_usd"] + est > max_usd and not offline:
        _capped(run, "motion", f"skipped motion look: est ${est:.2f} would pass the per-video cap ${max_usd:.2f}")
        return []
    if os.path.exists(cpath):
        mc = json.load(open(cpath))
        if mc.get("sheet"):
            shutil.copy(os.path.join(api.CACHE, mc["sheet"]), sheet_jpg)
        run.stage("motion", f"motion look (saved): {mc['n_candidates']} moving spots outside every box, Spark saw {len(mc['said'])}")
    elif offline:
        run.stage("motion", "motion look not cached for this clip: skipped in the free replay")
        return [] if rnd > 1 else [dict(kind="motion-scan", what=scan, tried=[], word=None, note="not cached")]
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
    log = [dict(kind="motion-scan", what=scan, tried=[], word=None, candidates=mc["n_candidates"],
                shown=len(mc["said"]), animals=sum(1 for v in mc["said"] if v.get("is_animal") is True),
                said=[dict(tile=v["tile"], is_animal=v.get("is_animal"), what=v.get("what"), confidence=v.get("confidence")) for v in mc["said"]])]
    if rnd > 1:
        log[0]["round"] = rnd
    if not chosen:
        run.stage("motion", "Spark: none of the moving spots is an animal")
        return log
    run.stage("motion", "SAM 3.1 tracks from a box, no word: " + ", ".join(f"{c['tile']} {c['what']} (frame {c['frame']})" for c in chosen))

    def one(c):
        path, s, m = _box_clip(run, clip, c["frame"], n, box_window, f"r{rnd}{c['tile']}")
        prompt = motion.box_prompt(c["frame"] - s, c["box"], W, H)
        txt = _counted(run, api.sam_video, path, prompt, m, offline=offline)
        return c, (tracks.shift_text(txt, s) if s else txt)

    # one at a time: SAM tracks a box both ways through the clip, so a later spot may be the animal an earlier box
    # already followed (11/2 s004: M4 at frame 34 and M7 at frame 50 were one red shrimp) -> skip, no second call
    windowed = box_window is not None and 2 * box_window + 1 < n
    prior, mine, calls = list(results), [], 0
    if windowed:    # a second look's spot may be a still animal a first-look window ended before: it is known
        mine = [(src, d) for src, _, d, _, _ in results if re.fullmatch(r"m\d+", src)]
    for i, c in enumerate(chosen):
        entry = dict(kind="motion", tile=c["tile"], what=c.get("what") or c["label"], cell=None, frame=c["frame"], box=c["box"],
                     tried=[dict(word="box", frames=None)], word=None, **({"round": rnd} if rnd > 1 else {}))
        if calls >= max_boxes:      # failed calls count too: the estimate above covers max_boxes
            break
        # the sheet box can sit on half a large slow animal (11/4 s001 m8): SAM gets the whole animal's box
        wb = motion.whole_box(clip, c["frame"], c["box"], W, H, n)
        if wb != list(c["box"]):
            entry.update(box=wb, sheet_box=c["box"])
            c = dict(c, box=wb)
        same = _followed(c["box"], c["frame"], mine, windowed)
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
            src = f"m{i}" if rnd == 1 else f"m{(rnd - 1) * 8 + i}"     # round 1 uses m0..m6 (max_boxes + 2)
            results.append((src, label, d, txt, None))
            entry["source"] = src
        log.append(entry)
        run.stage("motion", f"{c['tile']} box -> '{label}' tracked in {k_frames} of {n} frames"
                  + (f" (frames {max(0, c['frame'] - box_window)}-{min(n - 1, c['frame'] + box_window)} sent)" if windowed else "")
                  + (f" ({clash} frames already tracked removed" + (f", joined '{took}')" if took else ")") if clash else ""))
    return log


def camo_verdicts_for(run, clip, frames, trk, by_source, n):
    """The verdict camo_look gave each camo source, for its tracks (named K1, K2, ... in track order), with the queue
    thumbnails a person needs: thumbs/K<k>.jpg (the middle crop) and thumbs/K<k>_trio.jpg (still crops over the
    "what moved" crops, what Spark saw)."""
    paths = _paths(frames)
    ts = sorted((t for t in trk if trk[t]["source"] in by_source and t in paths), key=lambda t: paths[t][0][0])
    os.makedirs(run.path("thumbs"), exist_ok=True)
    out = {}
    for j, t in enumerate(ts):
        p = paths[t]
        mid = len(p) // 2
        tr = [(p[i][0], _ibox(p[i][1])) for i in _three_idx(len(p), mid, max(1, len(p) // 3))]
        name = f"K{j + 1}"
        imgs = video.frames(clip, motion.frames_for(tr, n))
        open(run.path("thumbs", f"{name}.jpg"), "wb").write(video.jpg(render.crop(imgs[p[mid][0]], p[mid][1], pad=0.25, min_side=96), max_w=320))
        open(run.path("thumbs", f"{name}_trio.jpg"), "wb").write(video.jpg(motion.camo_group(imgs, tr, name, n), max_w=900))
        out[t] = dict(by_source[trk[t]["source"]], name=name, frame=p[mid][0], box=p[mid][1])
    return out


# 11/3 recall (대표님: "재현율 98~99%"): of the 20 human boxes the luderick runs miss (dev 14, holdout 6), none is
# recovered by filling gaps between a track's boxes, a contrast-stretched copy, the camo look or the crowd tiles: SAM
# never boxed those fish at all. 9 of them are one faint fish far back in murky water (20190710_4 frames 52-61); shown
# that frame with the found boxes drawn, Spark named it ("distant faint fish", 0.45) and SAM, given its box, tracked
# it in 32 frames (4 more human boxes matched). Opt-in (--misslook): earlier evaluations stay as they were.
MISS_PROMPT = """Underwater survey video frame, {w}x{h} pixels. Every animal already found has a green rectangle. Look carefully, including faint, hazy or distant animals far back in murky water, small ones, and ones partly hidden by seagrass, rock or the frame edge.
Return ONLY a JSON list of animals that have NO green rectangle: [{{"box":[x1,y1,x2,y2],"name":"one plain everyday English noun (fish, shrimp, crab, eel, octopus, ray)","what":"<=6 words","confidence":0.0-1.0}}] in pixel coordinates of this image. Return [] if every animal has a rectangle."""
MISS_FRAMES = 6         # frames shown per clip, evenly spaced (the busiest frame among them)
MISS_MAX_BOXES = 4      # SAM box prompts per clip
MISS_MAX_OVERLAP = 0.3   # a box-prompt track on existing tracks in this share of its frames is one we have
MISS_MIN_CONF = 0.4     # the faint 20190710_4 fish came at 0.45; the audit then judges the track like any other


def _miss_reply(text):
    v = api.parse_json_list(text)
    if not isinstance(v, list):
        raise ValueError("miss look: not a JSON list")
    return True


def miss_look(run, clip, inf, results, max_usd, offline, labels=(), names=(), k=MISS_FRAMES, max_boxes=MISS_MAX_BOXES,
              min_conf=MISS_MIN_CONF):
    """Opt-in (--misslook): show Spark `k` frames with every box found so far drawn, ask for animals with no box,
    and give up to `max_boxes` of them to SAM as box prompts (most confident first). Appends ("x<i>", label, dets,
    text, None) to `results`: ordinary tracks for the audit. Returns log entries for the UI."""
    import cv2
    n, W, H = inf["n_frames"], inf["width"], inf["height"]
    known = {}
    for _, _, d, _, _ in results:
        for f, ds in d.items():
            known.setdefault(f, []).extend(list(det["box"]) for det in ds)
    est = k * 0.005 + max_boxes * max(api.SAM_MIN_FRAMES, n) * api.SAM_PER_FRAME
    if run.status["billed_usd"] + est > max_usd and not offline:
        _capped(run, "miss", f"skipped the missed-animal look: est ${est:.2f} would pass the per-video cap ${max_usd:.2f}")
        return []
    step = n / k
    show = sorted({min(n - 1, int(step * (i + 0.5))) for i in range(k)})
    imgs = video.frames(clip, set(show))
    s = min(1.0, 960 / W)
    w2, h2 = int(W * s), int(H * s)
    props = []
    for f in show:
        im = imgs[f].copy()
        for b in known.get(f, []):
            x0, y0, x1, y1 = (int(round(v)) for v in b)
            cv2.rectangle(im, (x0, y0), (x1, y1), (0, 255, 0), max(2, int(3 / s)))
        jpg = video.jpg(cv2.resize(im, (w2, h2)))
        try:
            reply = _counted(run, api.spark, MISS_PROMPT.format(w=w2, h=h2), [jpg], offline=offline, check=_miss_reply)
        except MOTION_ERRORS as e:
            run.stage("miss", f"frame {f}: missed-animal look failed ({type(e).__name__})")
            continue
        for v in api.parse_json_list(reply):
            b = _miss_box(v, s, W, H)
            if b is None:
                continue
            if any(tracks.overlap(b, kb) >= 0.3 for kb in known.get(f, [])):
                continue        # Spark pointed at an animal that has a box after all
            lab = _named(v, list(labels) + list(names))
            if not lab:
                continue
            lab = _miss_label(lab, labels)
            props.append(dict(frame=f, box=[int(round(x)) for x in b], label=lab, what=v.get("what"), confidence=_conf(v)))
    del imgs
    log = [dict(kind="miss-scan", what="Animals without a box", tried=[], word=None, frames=show, proposed=len(props),
                said=[dict(p) for p in props])]
    chosen = sorted((p for p in props if p["confidence"] >= min_conf), key=lambda p: -p["confidence"])
    if not chosen:
        run.stage("miss", f"Muse Spark looked at {len(show)} frames with every box drawn: no animal without a box")
        return log
    run.stage("miss", f"Muse Spark looked at {len(show)} frames with every box drawn: " + ", ".join(
        f"{p['what'] or p['label']} (frame {p['frame']}, {p['confidence']:.2f})" for p in chosen))
    prior, mine, calls = list(results), [], 0
    for i, c in enumerate(chosen):
        entry = dict(kind="miss", tile=f"X{i + 1}", what=c["what"] or c["label"], cell=None, frame=c["frame"], box=c["box"],
                     tried=[dict(word="box", frames=None)], word=None)
        if calls >= max_boxes:
            break
        same = next((t for t, d in mine if any(tracks.overlap(c["box"], kk["box"]) >= 0.3 for kk in d.get(c["frame"], []))), None)
        if same:
            entry.update(note=f"already followed by {same}")
            log.append(entry)
            continue
        calls += 1
        try:
            txt = _counted(run, api.sam_video, clip, motion.box_prompt(c["frame"], c["box"], W, H), n, offline=offline)
        except MOTION_ERRORS as e:
            entry["note"] = f"{type(e).__name__}: {str(e)[:120]}"
            log.append(entry)
            run.stage("miss", f"X{i + 1}: SAM box prompt failed ({entry['note']})")
            continue
        d0 = tracks.parse_boxes(txt)
        d, took, clash = _absorb(d0, prior)
        label = took or c["label"]
        k_frames = sum(1 for ds in d.values() if ds)
        entry.update(word=label if k_frames else None, frames=k_frames, raw_frames=sum(1 for ds in d0.values() if ds),
                     overlapped=clash, absorbed_into=took)
        entry["tried"] = [dict(word="box", frames=k_frames)]
        mine.append((f"X{i + 1}", d0))
        raw_n = entry["raw_frames"]
        if raw_n and clash / raw_n >= MISS_MAX_OVERLAP:
            # mostly on a track we already have: the same animal, Spark's box a little off it (11/3 20190709_4: 31 of
            # 66 frames on the counted fish, the rest added a second box and MaxN 2 -> 4) -> not a new animal
            entry.update(note=f"same animal as an existing track ({clash} of {raw_n} frames)", word=None)
            log.append(entry)
            run.stage("miss", f"X{i + 1}: {clash} of {raw_n} frames on an existing track, the same animal: dropped")
            continue
        if k_frames:
            results.append((f"x{i}", label, d, txt, None))
            entry["source"] = f"x{i}"
        log.append(entry)
        run.stage("miss", f"X{i + 1} box -> '{label}' tracked in {k_frames} of {n} frames"
                  + (f" ({clash} frames already tracked removed)" if clash else ""))
    return log


def camo_look(run, clip, inf, results, max_usd, offline, k=8, max_boxes=5, min_conf=0.6, names=()):
    """Opt-in (--camo): movers that no still frame shows (motion.camo_candidates). Up to `k` spots go to Spark on one
    sheet with a "what moved" row under each still crop; up to `max_boxes` it calls animals go to SAM as box prompts.
    A box track is kept only when motion.follows() says SAM followed the moving spot (and moved itself): that is the
    second look for these tracks, because the audit's still crops cannot show a camouflaged animal (run_pipeline
    leaves "camo" tracks out of the audit). Appends ("camo<i>", label, dets, text, None) to `results`; returns
    (log entries, {source: verdict}). Spark's verdicts are cached like motion_look's."""
    n, W, H = inf["n_frames"], inf["width"], inf["height"]
    known = {}
    for _, _, d, _, _ in results:
        for f, ds in d.items():
            for g in range(max(0, f - 3), min(n, f + 4)):
                known.setdefault(g, []).extend(list(det["box"]) for det in ds)
    kb = json.dumps(sorted((f, sorted([round(v) for v in b] for b in bs)) for f, bs in known.items()))
    key = hashlib.sha256((api.file_sha(clip) + kb + CAMO_PROMPT + CAMO_VERSION).encode()).hexdigest()[:24]
    cpath = os.path.join(api.CACHE, f"camo_{key}.json")
    est = 0.04 + max_boxes * max(api.SAM_MIN_FRAMES, n) * api.SAM_PER_FRAME
    if run.status["billed_usd"] + est > max_usd and not offline:
        _capped(run, "camo", f"skipped camouflage look: est ${est:.2f} would pass the per-video cap ${max_usd:.2f}")
        return [], {}
    if os.path.exists(cpath):
        mc = json.load(open(cpath))
        if mc.get("sheet"):
            shutil.copy(os.path.join(api.CACHE, mc["sheet"]), run.path("camo_sheet.jpg"))
        run.stage("camo", f"camouflage look (saved): {mc['n_candidates']} moving spots, Spark saw {len(mc['said'])}")
    elif offline:
        run.stage("camo", "camouflage look not cached for this clip: skipped in the free replay")
        return [dict(kind="motion-scan", camo=True, what="Movers no still frame shows", tried=[], word=None, note="not cached")], {}
    else:
        run.stage("camo", "looking for movers no still frame shows (frame-to-frame change, no model)")
        cands = motion.camo_candidates(clip, known)
        picks = motion.camo_pick(cands, known, W, H, k=k)
        said, meta, sheet_name = {}, [], None
        if picks:
            jpg, meta = motion.camo_sheet(clip, picks, W, H, n)
            sheet_name = f"camo_{key}.jpg"
            open(os.path.join(api.CACHE, sheet_name), "wb").write(jpg)
            open(run.path("camo_sheet.jpg"), "wb").write(jpg)
            run.stage("camo", f"{len(cands)} moving spots; Muse Spark looks at the {len(picks)} that travel farthest and straightest")

            def any_tile(text):
                got_ = api.parse_json(text)
                if not any(isinstance(v, dict) and str(v.get("tile", "")).startswith("K") for v in (got_ if isinstance(got_, list) else [got_])):
                    raise ValueError("camo reply names no tile")
            reply = _counted(run, api.spark, CAMO_PROMPT, [jpg], offline=offline, check=any_tile)
            got = api.parse_json(reply)
            for v in (got if isinstance(got, list) else [got]):
                if isinstance(v, dict):
                    said[str(v.get("tile"))] = v
        mc = dict(n_candidates=len(cands), sheet=sheet_name,
                  said=[dict(said.get(f"K{i}", {}), tile=f"K{i}", frame=t, box=b, path=picks[i - 1]["path"]) for i, t, b in meta])
        with open(cpath + ".tmp", "w") as fh:
            json.dump(mc, fh)
        os.replace(cpath + ".tmp", cpath)
    chosen = []
    for v in sorted(mc["said"], key=lambda v: -_conf(v)):
        lab = _named(v, names)
        if v.get("is_animal") is not True or _conf(v) < min_conf or not lab:
            continue
        if any(abs(v["frame"] - c["frame"]) <= 5 and tracks.overlap(v["box"], c["box"]) >= 0.3 for c in chosen):
            continue
        chosen.append(dict(v, label=lab))
    log = [dict(kind="motion-scan", camo=True, what="Movers no still frame shows", tried=[], word=None, candidates=mc["n_candidates"],
                shown=len(mc["said"]), animals=sum(1 for v in mc["said"] if v.get("is_animal") is True),
                said=[dict(tile=v["tile"], is_animal=v.get("is_animal"), what=v.get("what"), confidence=v.get("confidence")) for v in mc["said"]])]
    if not chosen:
        run.stage("camo", "Spark: none of the moving spots is an animal")
        return log, {}
    run.stage("camo", "SAM 3.1 tracks from a box, no word: " + ", ".join(f"{c['tile']} {c.get('what')} (frame {c['frame']})" for c in chosen))
    prior, mine, calls, verdicts = list(results), [], 0, {}
    for i, c in enumerate(chosen):
        entry = dict(kind="motion", camo=True, tile=c["tile"], what=c.get("what") or c["label"], cell=None, frame=c["frame"], box=c["box"],
                     tried=[dict(word="box", frames=None)], word=None)
        if calls >= max_boxes:
            break
        same = next((t for t, d in mine if any(tracks.overlap(c["box"], q["box"]) >= 0.3 for q in d.get(c["frame"], []))), None)
        if same:
            entry.update(note=f"already followed by {same}")
            log.append(entry)
            continue
        calls += 1
        try:
            txt = _counted(run, api.sam_video, clip, motion.box_prompt(c["frame"], c["box"], W, H), n, offline=offline)
        except MOTION_ERRORS as e:
            entry["note"] = f"{type(e).__name__}: {str(e)[:120]}"
            log.append(entry)
            run.stage("camo", f"{c['tile']}: SAM box prompt failed ({entry['note']})")
            continue
        d0 = tracks.parse_boxes(txt)
        mine.append((c["tile"], d0))
        ok, hits, shared, moved = motion.follows(d0, c["path"])
        entry["follows"] = dict(ok=ok, hits=hits, shared=shared, moved_px=moved)
        if not ok:
            entry["note"] = f"SAM did not follow the moving spot ({hits} of {shared} frames, moved {moved} px)"
            log.append(entry)
            run.stage("camo", f"{c['tile']}: {entry['note']}, not kept")
            continue
        d, took, clash = _absorb(d0, prior)
        k_frames = sum(1 for ds in d.values() if ds)
        entry.update(word=(took or c["label"]) if k_frames else None, frames=k_frames, max_per_frame=tracks.max_per_frame(d),
                     raw_frames=sum(1 for ds in d0.values() if ds), overlapped=clash, absorbed_into=took)
        entry["tried"] = [dict(word="box", frames=k_frames)]
        if k_frames:     # frames already tracked were removed by _absorb, as in motion_look
            src = f"camo{i}"
            results.append((src, took or c["label"], d, txt, None))
            entry["source"] = src
            verdicts[src] = dict(is_target=True, species=None, confidence=_conf(c), camo=dict(tile=c["tile"], what=c.get("what"),
                                 hits=hits, shared=shared, moved_px=moved),
                                 reason=f"moves like an animal ({c.get('what')}); SAM followed the moving spot in {hits} of {shared} frames")
        log.append(entry)
        run.stage("camo", f"{c['tile']} box -> '{c['label']}' tracked in {k_frames} of {n} frames, follows the moving spot in {hits} of {shared}"
                  + (f" ({clash} frames already tracked removed, joined '{took}')" if clash else ""))
    return log, verdicts


def closer_look(run, clip, inf, jobs, results, max_usd, offline, probe_window=None):
    """A block found nothing: crop just the cell Spark named at 3x and try every word, keeping the one tracked in
    the most frames (11/2 s002: 'crab' fired 5 frames on the nautilus' shell edge, 'shrimp' 12 frames on the real
    crustacean; stopping at the first hit would keep the wrong one). Then the same word on the reversed cell
    back-fills the frames before SAM recognised it (s002: 12 -> 58 of 60 frames, one track)."""
    n, W, H = inf["n_frames"], inf["width"], inf["height"]
    jobs = jobs[:2]
    est = sum(len(jb["words"]) + 1 for jb in jobs) * max(api.SAM_MIN_FRAMES, n) * api.SAM_PER_FRAME
    if run.status["billed_usd"] + est > max_usd and not offline:
        _capped(run, "recover", f"skipped closer look: est ${est:.2f} would pass the per-video cap ${max_usd:.2f}")
        return []
    run.stage("recover", "closer look, one cell at 3x: " + ", ".join(f"{jb['what']} in {jb['cell']} {jb['words']}" for jb in jobs))

    def one(jb):
        box = cell_tile(jb["cell"], W, H)
        path = run.path(f"tile_{jb['name']}.mp4")
        video.crop_tile(clip, path, box, scale=CELL_SCALE)
        tried, best = [], (0, None, "")
        probe = _probe_windows(jb.get("spark_frames"), n, probe_window) if probe_window else None
        for w in jb["words"]:
            try:
                if probe and not _probe(run, path, w, probe, offline):
                    tried.append(dict(word=w, frames=0, probe=[list(x) for x in probe]))
                    continue
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
    # a camo track (--camo) is not shown: its still crops look like rock or empty water (11/3 TF_52: the second rock
    # fish was removed as "empty water"); camo_look's "what moved" sheet and SAM following the moving spot decided it
    lab = lambda t: None if trk[t]["source"].startswith("camo") else labels.get(t, trk[t]["label"])
    for _ in range(rounds):
        m = tracks.metrics(frames, trk, n, fps, labels)
        # peak frames still come from every counted track, camo included (so a camo box can set the peak frame)
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
            # "not a <name>" but the same coarse group as the word asked ("other fish" under a fish label): the box is
            # what was asked for, so it stays and the track goes to the queue for its species (it used to leave the count
            # silently, paper 7.1). Another group or no animal (a nautilus track's box on "sea anemone" tentacles, a
            # pipe) is removed from this label's peak as before: in s002 that track is a nautilus again by frame 6,
            # and queuing it would have put a clear nautilus at "0-1 until checked" (tested 11/2, fixes branch).
            wg = name_group(word) or name_group(name)
            same_g = [(k, v) for k, v in bad if wg and same_group_answer(v.get("what_it_is"), wg)]
            bad = [(k, v) for k, v in bad if (k, v) not in same_g]
            drop = {k["track"] for k, _ in bad}
            for g in range(max(0, f - window), f + window + 1):
                if g in frames:
                    frames[g] = [k for k in frames[g] if k["track"] not in drop]
            log.append(dict(label=name, frame=f, checked=len(ks), kept=len(ks) - len(bad),
                            rejected=[dict(track=k["track"], box=[round(x) for x in k["box"]], said=v.get("what_it_is")) for k, v in bad],
                            kept_same_group=[dict(track=k["track"], said=v.get("what_it_is")) for k, v in same_g],
                            queue=[dict(track=k["track"], said=v.get("what_it_is")) for k, v in same_g]))
            run.stage("verify", f"{name}: Spark checks all {len(ks)} boxes in peak frame {f} (with the track just before and after), rejects {len(bad)}"
                      + (": " + "; ".join(sorted({v.get('what_it_is', '?') for _, v in bad})) if bad else ""))
    return log


def same_animal_pairs(run, clip, frames, trk, labels, dec, offline, contain=0.8, contain_cross=0.6):
    """Every nested pair in the clip (two counted detections, one mask >= `contain` inside the other) goes to Spark
    once, shown in the frame where it nests most, as "same animal or two?". For a duplicate the smaller-mask track
    is removed from each frame where it nests inside the other.
    Pairs of the same SAM word go on sheets pairs_<n>.jpg; pairs of two different words (one animal found as "shrimp"
    and renamed "small red crab", or a motion box on a word track) go on separate sheets pairsx_<n>.jpg, so adding
    the cross-word check leaves every same-word sheet, and its cached answer, unchanged (11/2 review: duplicates
    were only checked within one word). Mutates `frames`; returns [dict(outer, inner, frame, containment, same, said,
    cross)].
    Two different words on one animal rarely give one mask inside the other: each word's mask covers a different
    part or extent of the body, so cross-word pairs are sent to Spark from `contain_cross` (0.6) instead of 0.8. Spark
    still decides; the lower bar only lets more cross-word candidates be asked (11/2: none were found at 0.8)."""
    lab = lambda t: labels.get(t, trk[t]["label"])
    best, cross = {}, {}   # (outer, inner) -> (containment, frame, outer mask, inner mask)
    for f, ks in frames.items():
        ms = [maskdedupe.det_mask(dec, k["track"].split(":")[0], f, k["box"]) for k in ks]
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                a, b = ks[i]["track"], ks[j]["track"]
                if a == b or not (lab(a) and lab(b)) or tracks.overlap(ks[i]["box"], ks[j]["box"]) <= 0:
                    continue
                c = maskdedupe.containment(ms[i], ms[j])
                same_word = trk[a]["label"] == trk[b]["label"]
                if c is None or c < (contain if same_word else contain_cross):
                    continue
                into = best if same_word else cross
                o, n_ = (i, j) if ms[i][0].sum() >= ms[j][0].sum() else (j, i)
                key = (ks[o]["track"], ks[n_]["track"])
                if key[::-1] in into:   # sizes swap between frames: keep one orientation per pair
                    key, o, n_ = key[::-1], n_, o
                if key not in into or c > into[key][0]:
                    into[key] = (c, f, ms[o], ms[n_])
    out = []
    # a pair with a --crowd-peak tile track goes on its own sheets (pairsp_/pairsxp_), so every first-pass pair keeps
    # its tile number, sheet and cached answer
    pk = lambda k: any(trk[t]["source"].startswith("peak+") for t in k)
    for found, prefix, mine in ((best, "pairs", False), (cross, "pairsx", False), (best, "pairsp", True), (cross, "pairsxp", True)):
        pairs = sorted((k for k in found if pk(k) == mine), key=lambda k: found[k][1])
        if not pairs:
            continue
        imgs = video.frames(clip, {found[k][1] for k in pairs})
        tiles = [video.label(render.square(pair_tile(imgs[found[k][1]], found[k][2], found[k][3]), 256), f"P{i + 1}") for i, k in enumerate(pairs)]
        said = {}
        for i in range(0, len(tiles), 16):
            sheet = video.jpg(video.grid(tiles[i:i + 16], 4, 256), q=85)
            open(run.path(f"{prefix}_{i // 16 + 1}.jpg"), "wb").write(sheet)
            reply = _counted(run, api.spark, PAIR_PROMPT, [sheet], offline=offline, check=api.parse_json_list)
            for v in api.parse_json_list(reply):
                said[v.get("tile")] = v
        for i, (o, in_) in enumerate(pairs):
            v = said.get(f"P{i + 1}", {})
            same = v.get("same_animal") is True
            out.append(dict(outer=o, inner=in_, frame=found[(o, in_)][1], containment=round(found[(o, in_)][0], 2),
                            same=same, said=v.get("what"), cross=found is cross))
            if same:
                drop_nested(frames, dec, o, in_, contain if found is best else contain_cross)
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
    if v.get("peak_doubt") or v.get("name_disagrees"):   # a later look named another animal: a person decides the name
        return True
    if v.get("shadow"):         # taken out as a fish's shadow (shadow_look): a person can put it back
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
    ap.add_argument("--no-clean", action="store_true", help="keep SAM IDs reused for another object (before 11/3)")
    ap.add_argument("--crowd", action="store_true", help="crowded scene: SAM 'fish' on every overlapping 3x2 tile (2x)")
    ap.add_argument("--camo", action="store_true", help="also look for movers no still frame shows (frame-to-frame change -> "
                    "Spark sees still and 'what moved' crops -> SAM box; kept when SAM follows the moving spot)")
    ap.add_argument("--misslook", action="store_true", help="Spark points at animals with no box on a few frames -> SAM box prompts")
    ap.add_argument("--crowd-peak", type=int, nargs="?", const=CROWD_PEAK, metavar="FRAMES",
                    help=f"crowded peaks: the 3x2 crowd tiles only within FRAMES (default {CROWD_PEAK}) of a peak frame the "
                         "crowd check marks a lower bound, then the run again with those tracks (not with --crowd)")
    ap.add_argument("--box-window", type=int, nargs="?", const=BOX_WINDOW, metavar="FRAMES",
                    help=f"long clips: a motion box prompt sends SAM only the frames within FRAMES (default {BOX_WINDOW}) of its spot")
    ap.add_argument("--probe-window", type=int, nargs="?", const=PROBE_WINDOW, metavar="FRAMES",
                    help=f"clips of {PROBE_MIN_FRAMES}+ frames: a discovered word is tried on FRAMES (default {PROBE_WINDOW}) around "
                         "every frame Spark named before the whole clip (long videos: on by default, --no-probe-window)")
    ap.add_argument("--no-probe-window", action="store_true",
                    help="long videos: every discovered word goes straight to the whole segment (needed to replay "
                         "offline a long video whose cache was filled without --probe-window)")
    ap.add_argument("--skip-people", action="store_true",
                    help="a discovery that names people or a boat and no animal (camera still on deck) is not searched for")
    ap.add_argument("--no-crowd-look", action="store_true", help="skip the unprimed peak-frame count that marks a MaxN a lower bound")
    ap.add_argument("--no-refill", action="store_true", help="do not re-run a SAM pass that used up its 16 object ids (before 11/3)")
    ap.add_argument("--refill-ahead", type=int, default=1, metavar="N",
                    help="send up to N of those re-run windows at once (same result, sooner; a few calls past a window "
                         "that runs out of ids are paid for and dropped: LONG1 about $0.40 an hour at N=4)")
    ap.add_argument("--discover", action="store_true", help="Spark names what was not asked for; SAM word ladder")
    ap.add_argument("--prompts", nargs="*")
    ap.add_argument("--site", help="site memory: add words reviewers gave to earlier videos of this site (docs/site_memory.md)")
    ap.add_argument("--max-usd", type=float, help="short video: its cap (default $1). Long video: a ceiling on each "
                    "segment's share of the video cap (--max-usd-video)")
    ap.add_argument("--lowlight", choices=("auto", "on", "off"), default="auto", help="brighten dark clips (auto: by the brightness test)")
    ap.add_argument("--haze", choices=("auto", "on", "off"), default="off",
                    help="washed-out clips: CLAHE on L before the analysis (auto: when L p95-p5 is below video.HAZE_WIDTH)")
    ap.add_argument("--segment", type=float, help="split into segments of at most this many seconds and merge "
                    "(automatic at 600 s, the SAM 3.1 per-file limit, for longer videos)")
    ap.add_argument("--skip-empty", action="store_true", help="long videos: stretches where the picture does not change from "
                    "the last analysed frame are not sent; their boxes are carried (fishcount/screen.py). Uses --max-usd-video, not --max-usd")
    ap.add_argument("--max-usd-video", type=float,
                    help="cap for the whole video: long videos default $6 an hour (at least $1), with --skip-empty $4 an "
                         "hour; a short video uses it when --max-usd is not given. Each segment gets an equal share, at "
                         "least the first pass of the --prompts words; what a segment leaves out is listed in capped")
    ap.add_argument("--probe-every", type=float, help="with --skip-empty: seconds between probes of a skipped stretch (default 600)")
    ap.add_argument("--segment-workers", type=int, default=1, metavar="N",
                    help="long videos: run N segments at once (same result, sooner; two fit a 4 GB memory cap, each "
                         "more needs ~1.2 GB; not with --skip-empty)")
    ap.add_argument("--resume", action="store_true",
                    help="long videos: segments an earlier run with this --id finished (same clip, options and code) "
                         "are not run again (after a crash, only the rest runs; not with --skip-empty)")
    ap.add_argument("--no-upload-ahead", action="store_true",
                    help="long videos: do not cut and upload the next segment while one runs (the default saves its "
                         "first SAM call the ~360 MB upload; same result either way)")
    a = ap.parse_args()
    if a.resume and a.skip_empty:
        ap.error("--resume is not used with --skip-empty")
    if not a.skip_empty and a.probe_every is not None:
        ap.error("--probe-every needs --skip-empty")
    if a.probe_window is not None and a.no_probe_window:
        ap.error("--probe-window and --no-probe-window together")
    if a.id and re.search(r"__[SP]\d+$", a.id):
        ap.error("--id may not end in __S<n> or __P<n>: those name a long video's segments and probes")
    if a.crowd_peak is not None and (a.crowd or a.crowd_peak < 1 or a.no_audit or a.no_crowd_look):
        ap.error("--crowd-peak needs a number >= 1, the audit and the crowd check, and not --crowd (which tiles the whole clip)")
    if a.segment_workers < 1 or (a.segment_workers > 1 and a.skip_empty):
        ap.error("--segment-workers needs a number >= 1, and only 1 with --skip-empty (its video cap is paid segment by segment)")
    a.id = a.id or time.strftime("%m%d-%H%M%S")   # named here so the run folder can be printed at the end
    from fishcount import longvideo, provenance
    run_dir = os.path.join(RUNS, a.id)
    probe = video.encoder_probe()        # would this machine re-encode to the bytes the cache was filled with?
    enc_warn = api.encoder_check(probe, write=not a.offline)
    if enc_warn:
        print(f"WARNING: {enc_warn}", file=sys.stderr)
    provenance.start(run_dir, sys.argv, a.video, probe=probe, encoder_warning=enc_warn)   # <run>/provenance.json
    try:     # from here an error closes provenance.json with it (video.info, a cap below the first pass)
        src_info = video.info(a.video)
        long_path = longvideo.needs_split(src_info, a.segment, a.skip_empty)
        # K2: long videos probe discovered words by default; the options a run really used go into provenance and status
        probe_window = a.probe_window if a.probe_window is not None or a.no_probe_window or not long_path else PROBE_WINDOW
        short_floor = 0.0 if long_path else longvideo.first_pass_floor(round(src_info["n_frames"] / src_info["fps"] * 5), a.prompts)
        short_cap, raised = longvideo.short_cap(a.max_usd, a.max_usd_video, short_floor, a.offline)
        if raised:
            print(raised, file=sys.stderr)
        effective = dict(probe_window=probe_window, max_usd=a.max_usd if long_path else short_cap, max_usd_video=a.max_usd_video)
        provenance.effective(run_dir, effective)
        if not long_path and not a.offline:     # a warning only: cached calls are free (a long video warns in run_long)
            warn = api.budget_warning(short_floor)
            if warn:
                print(f"WARNING: {warn}", file=sys.stderr)
        if long_path:
            r = longvideo.run_long(a.video, a.id, min(a.segment or longvideo.MAX_SEGMENT_S, longvideo.MAX_SEGMENT_S),
                                   offline=a.offline, do_scout=not (a.no_scout or a.discover), do_audit=not a.no_audit, do_zoom=a.zoom,
                                   prompts=a.prompts, max_usd=a.max_usd, do_discover=a.discover, lowlight=a.lowlight, site=a.site,
                                   crowd=a.crowd, clean=not a.no_clean, refill=not a.no_refill, camo=a.camo,
                                   misslook=a.misslook, crowd_look=not a.no_crowd_look, box_window=a.box_window,
                                   probe_window=probe_window, skip_people=a.skip_people, refill_ahead=a.refill_ahead, skip_empty=a.skip_empty, max_usd_video=a.max_usd_video, probe_every_s=a.probe_every,
                                   segment_workers=a.segment_workers, crowd_peak=a.crowd_peak, haze=a.haze, resume=a.resume,
                                   upload_ahead=not a.no_upload_ahead)
        else:
            r = run_pipeline(a.video, a.id, a.offline, not (a.no_scout or a.discover), not a.no_audit, a.zoom, a.prompts, short_cap, a.discover,
                             lowlight=a.lowlight, site=a.site, crowd=a.crowd, clean=not a.no_clean, refill=not a.no_refill,
                             camo=a.camo, misslook=a.misslook, crowd_look=not a.no_crowd_look, box_window=a.box_window,
                             probe_window=probe_window, skip_people=a.skip_people, refill_ahead=a.refill_ahead,
                             crowd_peak=a.crowd_peak, haze=a.haze)
    except BaseException as e:
        provenance.finish(run_dir, error=f"{type(e).__name__}: {e}")
        raise
    provenance.finish(run_dir)
    print(json.dumps({k: {x: y for x, y in v.items() if x != "curve"} for k, v in r["metrics"].items()}, indent=1))
    print(f"run folder: {os.path.relpath(run_dir)}/", file=sys.stderr)
