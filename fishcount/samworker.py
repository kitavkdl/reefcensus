"""Local SAM 3.1 worker (D-LOCALSAM, docs/local-sam.md): runs SAM 3.1 on this machine's GPU and answers in the exact
text format of the Meta API's SAM 3.1 (`api.sam_video` caches and reads it the same way).

Run only by api._LocalWorker, as `<venv-sam>/bin/python -I fishcount/samworker.py`: its own virtualenv (torch, sam3,
meta-sam-parser 0.1.0), never the pipeline's, whose numpy / opencv versions are pinned for the cache bytes. -I keeps
fishcount/ off sys.path, so this file imports nothing from the package (video.py and friends would shadow libraries).
Protocol, one JSON object a line: {"id", "cmd": "version"} -> torch / CUDA / GPU / sam3 commit / checkpoint sha256;
{"id", "cmd": "track", "clip", "prompt"} -> {"id", "ok": true, "text"} or {"id", "ok": false, "error"}. Anything a
library prints goes to stderr (the pipeline keeps it in <cache>/sam_local.log), so stdout carries only replies.

The output is the API's (fixed from 1,053 cached API answers, design-v2 3-2): one line per frame that has objects,
`<{f}f>{id}<|box;x1=;y1=;x2=;y2=;w=W;h=H;c=conf|><|mask;x=0;y=0;c=conf;data={h},{w},!{one_bit}|>,...` in id order,
integer pixel boxes with x2 / y2 the last pixel, the mask cut to its box. The box is the mask's own bounds (as
sam3's masks_to_boxes); the API's box is the same for 95.4% of its records (2,183 of 2,289 sampled, 11/23) and up
to a pixel or so wider for the rest; frames without objects have no line and
nothing found is "". A word prompt numbers its tracks from 0 in order of first appearance and keeps at most 16 ids
over the whole call (the API's limit, tracks.py and saturation read it so); a box prompt `<{f}f>1<|box;...|>,2<|box..`
keeps its ids and is tracked both ways from frame f, as the API does. conf is one number per track (94% of the API's
tracks have one): here the mean of SAM's per-frame probability, so it may not mean what the API's does; nothing
in the pipeline gates on it but evaluate.py's cut."""
import json, os, re, sys

MAX_IDS = 16
HEAD = re.compile(r"<(\d+)f>")
BOX = re.compile(r"(\d+)<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")


def parse_prompt(prompt):
    """-> ("text", word) or ("box", frame, [(id, x1, y1, x2, y2)], W, H)."""
    h = HEAD.match(prompt)
    if not h:
        return "text", prompt
    boxes = BOX.findall(prompt[h.end():])
    if not boxes:
        raise ValueError(f"box prompt without a box: {prompt!r}")
    W, H = int(boxes[0][5]), int(boxes[0][6])
    return "box", int(h.group(1)), [tuple(int(v) for v in b[:5]) for b in boxes], W, H


def box_points(x1, y1, x2, y2, W, H):
    """A pixel box (x2 / y2 its last pixel) as SAM's two corner points (labels 2 = top left, 3 = bottom right),
    relative 0-1: the bottom right corner is the far edge of the last pixel."""
    return [[x1 / W, y1 / H], [min(1.0, (x2 + 1) / W), min(1.0, (y2 + 1) / H)]]


def crops(ids, probs, masks):
    """One frame's predictor output (obj ids, probabilities, (n, H, W) bool masks) -> [(id, (x1, y1, x2, y2) with
    the last pixel, h, w, packed bits of the mask cut to that box, prob)]; an empty mask is dropped. Only the cut
    is kept, bit-packed: a whole 3,000-frame call's full masks would not fit in memory."""
    import numpy as np
    out = []
    for oid, p, m in zip(ids, probs, masks):
        ys, xs = np.nonzero(m.any(axis=1))[0], np.nonzero(m.any(axis=0))[0]
        if not len(ys):
            continue
        y1, y2, x1, x2 = int(ys[0]), int(ys[-1]), int(xs[0]), int(xs[-1])
        cut = m[y1:y2 + 1, x1:x2 + 1]
        out.append((int(oid), (x1, y1, x2, y2), y2 - y1 + 1, x2 - x1 + 1, np.packbits(cut).tobytes(), float(p)))
    return out


def encode_one(packed, h, w):
    """Packed bits of an h x w mask -> the API's one_bit payload ("!..."), byte for byte (meta-sam-parser 0.1.0's
    encoder; 300 of 300 API masks decoded and encoded again came out identical)."""
    import numpy as np
    from meta_sam_parser._mask_codec import _encode_raster
    bits = np.unpackbits(np.frombuffer(packed, np.uint8))[:h * w]
    return _encode_raster(bits.tobytes(), w, h)


def encode_all(items):
    """[(packed, h, w)] -> payloads, one after another (the worker passes a process pool's starmap instead)."""
    return [encode_one(*it) for it in items]


def _conf(values):
    import numpy as np
    return repr(float(np.float32(sum(values) / len(values))))


def assemble(frames, W, H, encode=encode_all, box_prompt=False):
    """{frame: crops(...)} -> the API's output text (module docstring). encode([(packed, h, w)]) -> payloads."""
    keep, order = {}, []         # predictor id -> output id, in order of first appearance
    for f in sorted(frames):
        for rec in sorted(frames[f], key=lambda r: r[0]):
            oid = rec[0]
            if oid not in keep and (box_prompt or len(keep) < MAX_IDS):
                keep[oid] = oid if box_prompt else len(keep)
    rows = [(f, rec) for f in sorted(frames) for rec in frames[f] if rec[0] in keep]
    probs = {}
    for _, rec in rows:
        probs.setdefault(rec[0], []).append(rec[5])
    conf = {oid: _conf(v) for oid, v in probs.items()}
    payloads = encode([(rec[4], rec[2], rec[3]) for _, rec in rows])
    lines = {}
    for (f, (oid, (x1, y1, x2, y2), h, w, _, _)), data in zip(rows, payloads):
        c = conf[oid]
        lines.setdefault(f, []).append((keep[oid], f"{keep[oid]}<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={W};h={H};c={c}|>"
                                                   f"<|mask;x=0;y=0;c={c};data={h},{w},{data}|>"))
    return "".join(f"<{f}f>" + ",".join(t for _, t in sorted(lines[f])) + "\n" for f in sorted(lines))


# ---------------- the process (venv-sam only) ----------------
def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


_SEEN = {}      # checkpoint path -> _stat when version() hashed it; build() loads only that file


def _stat(path):
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns, st.st_ino


def _ckpt():
    """The checkpoint version() hashes and build() loads: FISH_SAM_CHECKPOINT, else sam3.1 from Hugging Face (sam3's
    own default, when given None, is another checkpoint)."""
    from sam3.model_builder import download_ckpt_from_hf
    return os.environ.get("FISH_SAM_CHECKPOINT") or download_ckpt_from_hf(version="sam3.1")


def version():
    """What the pipeline records as the backend (api.local_tag) and checks before paying anything (preflight).
    The model is not loaded. ponytail: the checkpoint (~3.5 GB) is hashed on every start, a few seconds; keep the
    hash beside it if starts become frequent."""
    import importlib.metadata as md
    import torch
    try:
        commit = json.loads(md.distribution("sam3").read_text("direct_url.json") or "{}").get("vcs_info", {}).get("commit_id")
    except Exception:
        commit = None
    ckpt = _ckpt()
    seen = _stat(ckpt)
    sha = _sha256(ckpt)
    if _stat(ckpt) != seen:
        raise RuntimeError(f"checkpoint {ckpt} changed while it was hashed")
    _SEEN[ckpt] = seen
    cuda = torch.cuda.is_available()
    return dict(torch=torch.__version__, cuda=cuda, gpu=torch.cuda.get_device_name(0) if cuda else None,
                vram_mb=torch.cuda.get_device_properties(0).total_memory // 2 ** 20 if cuda else None,
                sam3=md.version("sam3"), sam3_commit=commit, checkpoint=ckpt, checkpoint_sha256=sha,
                meta_sam_parser=md.version("meta-sam-parser"))


def build():
    from sam3.model_builder import build_sam3_multiplex_video_predictor
    ckpt = _ckpt()
    if ckpt not in _SEEN or _SEEN[ckpt] != _stat(ckpt):      # the cache key names the file version() hashed
        raise RuntimeError(f"checkpoint {ckpt} is not the file version() hashed: restart the worker")
    # FA3 kernels are for Hopper GPUs; an RTX 4060 Ti uses the default attention (checked in step 0 of the plan)
    return build_sam3_multiplex_video_predictor(checkpoint_path=ckpt,
                                                max_num_objects=MAX_IDS, use_fa3=False)


def track(predictor, clip, prompt, encode):
    """One API-equivalent SAM call on the clip -> output text."""
    kind = parse_prompt(prompt)
    offload = os.environ.get("FISH_SAM_OFFLOAD", "") == "1"     # frames in RAM instead of VRAM (step 0 decides)
    sess = predictor.handle_request(dict(type="start_session", resource_path=clip, offload_video_to_cpu=offload))["session_id"]
    W = H = None
    try:
        if kind[0] == "text":
            predictor.handle_request(dict(type="add_prompt", session_id=sess, frame_index=0, text=kind[1]))
            req = dict(propagation_direction="forward", start_frame_index=0)
        else:
            _, f, boxes, W, H = kind
            for oid, x1, y1, x2, y2 in boxes:     # one tracked object per box, with the prompt's id (as the API)
                predictor.handle_request(dict(type="add_prompt", session_id=sess, frame_index=f, obj_id=oid,
                                              points=box_points(x1, y1, x2, y2, W, H), point_labels=[2, 3]))
            req = dict(propagation_direction="both", start_frame_index=f)
        frames = {}
        for r in predictor.handle_stream_request(dict(type="propagate_in_video", session_id=sess,
                                                      evict_cached_frame_outputs=True, **req)):
            o = r["outputs"]
            if o is None or r["frame_index"] in frames:     # both ways: the prompt frame comes twice
                continue
            m = o["out_binary_masks"]
            H, W = m.shape[1], m.shape[2]
            frames[r["frame_index"]] = crops(o["out_obj_ids"], o["out_probs"], m)
        # ponytail: masks are encoded after tracking, in a pool; overlap with the GPU if step 0 shows it matters
        return assemble(frames, W, H, encode, kind[0] == "box") if W else ""
    finally:
        predictor.handle_request(dict(type="close_session", session_id=sess))


def main():
    proto = os.fdopen(os.dup(1), "w")       # replies only; fd 1 (print, C libraries) goes to stderr from here
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    # the encoder pool is made before torch is imported, with spawn: no fork of a process that holds CUDA
    import multiprocessing as mp
    pool = mp.get_context("spawn").Pool(int(os.environ.get("FISH_SAM_ENCODERS", "4")))
    encode = lambda items: pool.starmap(encode_one, items, chunksize=8)
    predictor = None
    for line in sys.stdin:
        req, out = None, None
        try:
            req = json.loads(line)
            if req.get("cmd") == "version":
                out = version()
            elif req.get("cmd") == "track":
                predictor = predictor or build()
                out = dict(text=track(predictor, req["clip"], req["prompt"], encode))
            else:
                raise ValueError(f"unknown request {req.get('cmd')!r}")
            out["ok"] = True
        except Exception as e:      # CUDA out of memory included: the worker stays up, the pipeline stops the run
            out = dict(ok=False, error=f"{type(e).__name__}: {e}"[:2000])
            if "torch" in sys.modules:
                sys.modules["torch"].cuda.empty_cache()
        out["id"] = (req or {}).get("id")
        proto.write(json.dumps(out) + "\n")
        proto.flush()
    pool.close()


if __name__ == "__main__":
    main()
