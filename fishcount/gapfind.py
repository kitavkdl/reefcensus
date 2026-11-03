"""Find boxes missing from an existing annotation, and fix them with one tap per track.

Added after the evaluation (not used in any paper table). It re-reads finished runs, so it calls no model and costs $0.

Why: on the luderick held-out set, 40 pipeline boxes scored as false positives were judged with labels hidden and none
was "not a fish" (paper §6.2). Old annotation sets made for one purpose (here, training a single-species detector) leave
fish unboxed, and a count scored against them is penalised for being right. This tool turns that check into a workflow:

  1. sheet  - for each counted pipeline track that has boxes matching no human box (IoU < 0.3) on annotated frames,
              cut up to three crops of those boxes, draw the existing human boxes in grey, shuffle the tracks (optionally
              with control tracks that do match), and write one self-contained HTML page a person answers on a phone:
                O  a fish (or the target animal) that has no grey box     -> its boxes are added
                D  the same fish as a grey box (already annotated)        -> nothing added
                P  a box on part of a fish                                -> listed for a person to redraw
                X  not a fish (plant, rock, shadow, water)                -> nothing added
                ?  cannot tell                                            -> listed as unresolved
              The page shows no label, no queue status and no score; it exports the answers as JSON.
  2. apply  - answers + key + original annotations -> corrected annotation files in the same format (added boxes carry
              the label "<label> (added: gapfind)"), plus a summary of MaxN on the annotated frames before and after.

A track is judged as a whole: one answer applies to all of its unmatched boxes. The sheet shows the first, middle and
last of them so a track that switched to another object is visible (answer ? or X then).

  python3 -m fishcount.gapfind sheet --manifest CLIPS/manifest.json --runs RUNS --prefix cr3_ --out DIR [--controls 3]
  python3 -m fishcount.gapfind sheet --run RUNS/x --gt gt.json --video clip.mp4 --out DIR
  python3 -m fishcount.gapfind apply --key DIR/key.json --answers answers.json --out FIXED_DIR

Annotation format (as the luderick clips): {"frames": {"<frame>": [[x, y, w, h, label], ...]}, "n_frames": N}; frame
indices are those of the clip the run was made on.
"""
import argparse, base64, html, json, os, random, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IOU_MATCH = 0.3       # same rule as the evaluation (evaluate_pipeline, report/paper/scripts/fp_sheet.py)
ADDED = " (added: gapfind)"
CODES = {"O": "fish, no grey box", "D": "already boxed (grey)", "P": "part of a fish", "X": "not a fish", "?": "can't tell"}


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def load_gt(path):
    """{frame: [(x0, y0, x1, y1, label)]} from an [x, y, w, h, label] annotation file."""
    d = json.load(open(path))
    return {int(f): [(x, y, x + w, y + h, (r[0] if r else "")) for x, y, w, h, *r in v] for f, v in d["frames"].items()}


def counted(result):
    """{track: label} for the tracks the run counts (the same rule fp_sheet and the evaluation use)."""
    out = {}
    for t, v in result.get("tracks", {}).items():
        lab = result.get("auto_labels", {}).get(t, v.get("label"))
        if lab:
            out[t] = lab
    for t, lab in result.get("auto_labels", {}).items():
        if lab and t not in out:
            out[t] = lab
    return out


def match_frame(gt_boxes, run_boxes, thr=IOU_MATCH):
    """Greedy one-to-one matching in human-box order (as fp_sheet). Returns the set of matched run-box indices."""
    used = set()
    for a in gt_boxes:
        best = max(((iou(a, k["box"]), j) for j, k in enumerate(run_boxes) if j not in used), default=(0, None))
        if best[0] >= thr:
            used.add(best[1])
    return used


def find_gaps(result, gt, queued=frozenset()):
    """Per counted track: its unmatched and matched boxes on annotated frames.

    Returns {track: dict(label, queued, unmatched=[(frame, box)], matched=n, raises=n)}; `raises` counts annotated
    frames where the run has more counted boxes than the annotation and this track is unmatched there (frames that
    could change MaxN)."""
    lab = counted(result)
    out = {}
    for f, gb in sorted(gt.items()):
        ks = [k for k in result.get("frames", {}).get(str(f), []) if k["track"] in lab]
        used = match_frame(gb, ks)
        more = len(ks) > len(gb)
        for j, k in enumerate(ks):
            t = k["track"]
            e = out.setdefault(t, dict(label=lab[t], queued=t in queued, unmatched=[], matched=0, raises=0))
            if j in used:
                e["matched"] += 1
            else:
                e["unmatched"].append((f, [float(v) for v in k["box"]]))
                e["raises"] += more
    return out


def spread(items, k=3):
    """First, middle and last (k evenly spaced) of a list."""
    if len(items) <= k:
        return list(items)
    return [items[round(i * (len(items) - 1) / (k - 1))] for i in range(k)]


def maxn(gt):
    return max((len(v) for v in gt.values()), default=0)


# ---------------------------------------------------------------- sheet

def _crop(img, box, gt_boxes, cell=320):
    import cv2
    im = img.copy(); H, W = im.shape[:2]
    for g in gt_boxes:
        cv2.rectangle(im, (int(g[0]), int(g[1])), (int(g[2]), int(g[3])), (170, 170, 170), 2)
    x0, y0, x1, y1 = map(int, box)
    cv2.rectangle(im, (x0, y0), (x1, y1), (0, 230, 255), 3)
    s = max(x1 - x0, y1 - y0, 120)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    X0, Y0, X1, Y1 = int(max(0, cx - s)), int(max(0, cy - s)), int(min(W, cx + s)), int(min(H, cy + s))
    cr = im[Y0:Y1, X0:X1]
    k = cell / max(cr.shape[:2])
    return cv2.resize(cr, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)


def collect(clips, controls=0, seed=0):
    """clips: [(clip_id, result, gt, video_path)]. Returns the shuffled card list (with crop requests)."""
    from fishcount import pipeline
    cards, ctrl_pool = [], []
    for cid, res, gt, vid in clips:
        q = frozenset(t for t, v in res.get("verdicts", {}).items() if pipeline.needs_review(v))
        for t, e in find_gaps(res, gt, q).items():
            base = dict(clip=cid, track=t, label=e["label"], queued=e["queued"], video=vid,
                        n_unmatched=len(e["unmatched"]), n_matched=e["matched"], raises=e["raises"])
            if e["unmatched"]:
                cards.append(dict(base, kind="gap", boxes=e["unmatched"], show=spread(e["unmatched"])))
            elif controls:
                fb = [(f, [float(v) for v in k["box"]]) for f in sorted(gt) for k in res["frames"].get(str(f), [])
                      if k["track"] == t]
                ctrl_pool.append(dict(base, kind="control", boxes=[], show=spread(fb)))
    rng = random.Random(seed)
    cards += rng.sample(ctrl_pool, min(controls, len(ctrl_pool)))
    rng.shuffle(cards)
    for i, c in enumerate(cards, 1):
        c["n"] = i
    return cards


def render_crops(cards, gts):
    """Adds c['crops'] = [jpeg bytes] to each card; reads only the frames it needs, one video at a time."""
    from fishcount import video  # noqa: F401  (sets the cv2 path)
    import cv2
    by_vid = {}
    for c in cards:
        by_vid.setdefault(c["video"], set()).update(f for f, _ in c["show"])
    for vid, idx in by_vid.items():
        fr = video.frames(vid, sorted(idx))
        for c in cards:
            if c["video"] == vid:
                gt = gts[c["clip"]]
                c["crops"] = [cv2.imencode(".jpg", _crop(fr[f], b, gt.get(f, [])), [cv2.IMWRITE_JPEG_QUALITY, 85])[1]
                              .tobytes() for f, b in c["show"] if f in fr]
        del fr


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Missing boxes</title>
<meta name="claude:viewport-fit-sides" content="cover"><style>
:root{--bg:#fff;--fg:#111;--mut:#666;--card:#f3f4f6;--on:#0a7;--line:#ddd}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111;--fg:#eee;--mut:#999;--card:#1d1f23;--line:#333;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#111;--fg:#eee;--mut:#999;--card:#1d1f23;--line:#333;color-scheme:dark}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.4 system-ui,sans-serif}
header{position:sticky;top:env(safe-area-inset-top,0px);background:var(--bg);border-bottom:1px solid var(--line);
padding-block:10px;z-index:2}body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);
z-index:10;background:var(--bg)}header,main{padding-left:max(16px,env(safe-area-inset-left,0px));
padding-right:max(16px,env(safe-area-inset-right,0px))}main{padding-block:12px 80px;max-width:760px;margin:auto}
button:focus-visible{outline:2px solid var(--on);outline-offset:2px}.c{background:var(--card);border-radius:10px;padding:10px;margin:0 0 14px}
.c h2{font-size:15px;margin:0 0 8px}.im{display:flex;gap:6px;overflow-x:auto}.im img{height:150px;border-radius:6px}
.b{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}.b button{flex:1;min-width:52px;padding:12px 0;font-size:16px;
border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}.b button.on{background:var(--on);color:#fff}
p.k{color:var(--mut);font-size:14px;margin:4px 0}textarea{width:100%;height:120px}
#done{width:100%;padding:12px;font-size:16px;margin-top:6px}</style></head><body>
<header><b>Is there an unboxed fish in the yellow box?</b> <span id="prog"></span>
<p class="k">Grey = boxes already in the annotation. One answer per row (up to three moments of one track).<br>
O fish, no grey box &middot; D same fish as a grey box &middot; P part of a fish &middot; X not a fish &middot; ? can't tell</p></header>
<main>__CARDS__<button id="done">Copy answers</button><textarea id="out" readonly aria-label="answers"></textarea></main>
<script>
const SHEET="__SHEET__",N=__N__,K="gapfind:"+SHEET;let A={},T={};try{const s=JSON.parse(localStorage.getItem(K)||"{}");
A=s.a||{};T=s.t||{}}catch(e){}
function draw(){document.querySelectorAll(".c").forEach(c=>{const n=c.dataset.n;c.querySelectorAll("button").forEach(b=>
b.classList.toggle("on",A[n]===b.dataset.a))});document.getElementById("prog").textContent=Object.keys(A).length+" / "+N}
document.querySelectorAll(".b button").forEach(b=>b.onclick=()=>{const n=b.closest(".c").dataset.n;
A[n]=A[n]===b.dataset.a?undefined:b.dataset.a;if(A[n]===undefined)delete A[n];T[n]=Date.now();
try{localStorage.setItem(K,JSON.stringify({a:A,t:T}))}catch(e){}draw()});
document.getElementById("done").onclick=()=>{const ts=Object.values(T);const t=JSON.stringify({sheet:SHEET,answers:A,
seconds_first_to_last:ts.length?Math.round((Math.max(...ts)-Math.min(...ts))/1000):null,n_answered:Object.keys(A).length});const o=document.getElementById("out");
o.value=t;o.select();try{navigator.clipboard.writeText(t).then(()=>{document.getElementById("done").textContent="Copied"},
()=>{})}catch(e){}};draw();
</script></body></html>"""


def write_sheet(cards, out_dir, sheet_id, protocol=""):
    os.makedirs(out_dir, exist_ok=True)
    parts = []
    for c in cards:
        imgs = "".join(f'<img alt="crop" src="data:image/jpeg;base64,{base64.b64encode(j).decode()}">' for j in c["crops"])
        btns = "".join(f'<button data-a="{html.escape(a)}">{html.escape(a)}</button>' for a in CODES)
        parts.append(f'<div class="c" data-n="{c["n"]}"><h2>#{c["n"]}</h2><div class="im">{imgs}</div>'
                     f'<div class="b">{btns}</div></div>')
    page = PAGE.replace("__CARDS__", "".join(parts)).replace("__SHEET__", sheet_id).replace("__N__", str(len(cards)))
    open(os.path.join(out_dir, "sheet.html"), "w").write(page)
    key = dict(sheet=sheet_id, protocol=protocol, codes=CODES, iou_match=IOU_MATCH,
               cards=[{k: v for k, v in c.items() if k not in ("crops",)} for c in cards])
    json.dump(key, open(os.path.join(out_dir, "key.json"), "w"), indent=1)
    return os.path.join(out_dir, "sheet.html")


# ---------------------------------------------------------------- apply

def apply(key, answers, gts):
    """key: key.json dict; answers: {"<n>": code}; gts: {clip: gt (load_gt form)}.
    Returns (fixed {clip: gt}, summary dict). Only gap cards answered O add boxes."""
    fixed = {cid: {f: list(v) for f, v in g.items()} for cid, g in gts.items()}
    s = dict(added_boxes=0, added_tracks=0, by_answer={}, redraw=[], unresolved=[], controls={}, clips={})
    for c in key["cards"]:
        a = answers.get(str(c["n"]))
        tag = (c["kind"], a or "unanswered")
        s["by_answer"]["%s:%s" % tag] = s["by_answer"].get("%s:%s" % tag, 0) + 1
        if c["kind"] == "control":
            s["controls"][str(c["n"])] = a
            continue
        ref = dict(n=c["n"], clip=c["clip"], track=c["track"], frames=[f for f, _ in c["boxes"]])
        if a == "O":
            for f, b in c["boxes"]:
                fixed[c["clip"]].setdefault(f, []).append((b[0], b[1], b[2], b[3], c["label"] + ADDED))
                s["added_boxes"] += 1
            s["added_tracks"] += 1
        elif a == "P":
            s["redraw"].append(ref)
        elif a in ("?", None):
            s["unresolved"].append(ref)
    for cid in gts:
        s["clips"][cid] = dict(maxn_before=maxn(gts[cid]), maxn_after=maxn(fixed[cid]))
    return fixed, s


def dump_gt(gt, n_frames, path):
    fr = {str(f): [[x0, y0, x1 - x0, y1 - y0, lab] for x0, y0, x1, y1, lab in v] for f, v in sorted(gt.items())}
    json.dump(dict(frames=fr, n_frames=n_frames), open(path, "w"))


# ---------------------------------------------------------------- CLI

def _clips_from_args(a):
    if a.manifest:
        root = os.path.dirname(os.path.dirname(os.path.abspath(a.manifest)))
        m = json.load(open(a.manifest))
        out = []
        for cid, c in m["clips"].items():
            rp = os.path.join(a.runs, a.prefix + cid, "result.json")
            if not os.path.exists(rp) or "gt" not in c:
                print("skip", cid, "(no run or no annotation)", file=sys.stderr)
                continue
            out.append((cid, json.load(open(rp)), load_gt(os.path.join(root, c["gt"])), os.path.join(root, c["path"]),
                        os.path.join(root, c["gt"])))
        return out
    cid = os.path.basename(os.path.normpath(a.run))
    return [(cid, json.load(open(os.path.join(a.run, "result.json"))), load_gt(a.gt), a.video, a.gt)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("--manifest"); s.add_argument("--runs", default="runs"); s.add_argument("--prefix", default="")
    s.add_argument("--run"); s.add_argument("--gt"); s.add_argument("--video")
    s.add_argument("--out", required=True); s.add_argument("--controls", type=int, default=0)
    s.add_argument("--seed", type=int, default=0)
    p = sub.add_parser("apply")
    p.add_argument("--key", required=True); p.add_argument("--answers", required=True); p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "sheet":
        if not a.manifest and not (a.run and a.gt and a.video):
            ap.error("sheet needs --manifest, or --run with --gt and --video")
        cl = _clips_from_args(a)
        cards = collect([c[:4] for c in cl], a.controls, a.seed)
        render_crops(cards, {c[0]: c[2] for c in cl})
        gt_paths = {c[0]: c[4] for c in cl}
        for c in cards:
            c["gt_path"] = gt_paths[c["clip"]]
        sid = "%s-%d" % (os.path.basename(os.path.normpath(a.out)), a.seed)
        path = write_sheet(cards, a.out, sid, protocol="gapfind sheet: counted tracks with boxes matching no "
                           "annotation box at IoU>=%.1f on annotated frames; shuffled with seed %d; %d controls" %
                           (IOU_MATCH, a.seed, a.controls))
        gaps = [c for c in cards if c["kind"] == "gap"]
        print("%s: %d tracks to judge (%d unmatched boxes, %d on frames with more run boxes than annotated), "
              "%d controls" % (path, len(gaps), sum(c["n_unmatched"] for c in gaps), sum(c["raises"] for c in gaps),
                               len(cards) - len(gaps)))
    else:
        key = json.load(open(a.key))
        ans = json.load(open(a.answers))
        ans = ans.get("answers", ans)
        paths = {}
        for c in key["cards"]:
            paths[c["clip"]] = c["gt_path"]
        gts = {cid: load_gt(p) for cid, p in paths.items()}
        fixed, summ = apply(key, ans, gts)
        os.makedirs(a.out, exist_ok=True)
        for cid, g in fixed.items():
            n = json.load(open(paths[cid])).get("n_frames")
            dump_gt(g, n, os.path.join(a.out, cid + ".json"))
        json.dump(summ, open(os.path.join(a.out, "summary.json"), "w"), indent=1)
        ch = {c: v for c, v in summ["clips"].items() if v["maxn_before"] != v["maxn_after"]}
        print("added %d boxes from %d tracks; %d to redraw, %d unresolved; MaxN changed on %d clips: %s" %
              (summ["added_boxes"], summ["added_tracks"], len(summ["redraw"]), len(summ["unresolved"]), len(ch),
               ", ".join("%s %d->%d" % (c, v["maxn_before"], v["maxn_after"]) for c, v in sorted(ch.items()))))


if __name__ == "__main__":
    main()
