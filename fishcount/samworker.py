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
import inspect, json, os, re, sys, time, uuid

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
    is kept, bit-packed: a whole 3,000-frame call's full masks would not fit in memory. A negative prob is sam3's
    mark for an object it removes on that frame (-1e4, still with its mask): dropped, as the API shows no negative
    conf in 118,835 cached records (11/23)."""
    import numpy as np
    out = []
    for oid, p, m in zip(ids, probs, masks):
        ys, xs = np.nonzero(m.any(axis=1))[0], np.nonzero(m.any(axis=0))[0]
        if not len(ys) or p < 0:
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
                meta_sam_parser=md.version("meta-sam-parser"), batch=_batch())


def _batch():
    """FISH_SAM_BATCH, checked. It changes a word call's output bytes (1, 2 and 4 differ on the same clip), so
    version() reports it and it is part of the cache key (api.local_tag)."""
    raw = os.environ.get("FISH_SAM_BATCH", "1")
    if not (raw.isascii() and raw.isdigit()) or int(raw) < 1:
        raise RuntimeError(f"FISH_SAM_BATCH={raw!r}: give a whole number of frames, 1 or more")
    return int(raw)


def build():
    from sam3.model_builder import build_sam3_multiplex_video_predictor
    ckpt = _ckpt()
    if ckpt not in _SEEN or _SEEN[ckpt] != _stat(ckpt):      # the cache key names the file version() hashed
        raise RuntimeError(f"checkpoint {ckpt} is not the file version() hashed: restart the worker")
    # FA3 kernels are for Hopper GPUs; an RTX 4060 Ti uses the default attention (checked in step 0 of the plan)
    p = build_sam3_multiplex_video_predictor(checkpoint_path=ckpt, max_num_objects=MAX_IDS, use_fa3=False)
    # sam3's builder runs the detector and the mask postprocess on 16 frames at once (sized for an 80 GB GPU): on 8 GB
    # that asks for ~21 GB, which WSL spills to system RAM (minutes a frame) and then runs out. The batch is how many
    # frames go through together; a word call's bytes still differ with it (step 0), hence _batch() in the cache key.
    batch = _batch()
    if not all(hasattr(p.model, a) for a in ("batched_grounding_batch_size", "postprocess_batch_size")):
        raise RuntimeError("this sam3 has no batched_grounding_batch_size / postprocess_batch_size: "
                           "install the sam3 commit in docs/local-sam.md")
    p.model.batched_grounding_batch_size = p.model.postprocess_batch_size = batch
    return p


def _start_session(predictor, clip, offload):
    """The session start_session would open. sam3's start_session (31cb7e6) hands init_state an
    offload_state_to_cpu that the multiplex model's init_state does not take, so it always fails; this calls
    init_state and registers the session as start_session does (sam3_base_predictor.py), on private names."""
    model, states = getattr(predictor, "model", None), getattr(predictor, "_all_inference_states", None)
    try:
        params = inspect.signature(model.init_state).parameters
    except (AttributeError, TypeError, ValueError):
        params = {}
    if not isinstance(states, dict) or not {"resource_path", "offload_video_to_cpu"} <= params.keys():
        raise RuntimeError("this sam3 has no model.init_state(resource_path, offload_video_to_cpu) and "
                           "_all_inference_states to open a session with: install the sam3 commit in docs/local-sam.md")
    kw = dict(resource_path=clip, offload_video_to_cpu=offload)
    if "async_loading_frames" in params and hasattr(predictor, "async_loading_frames"):
        kw["async_loading_frames"] = predictor.async_loading_frames
    state = model.init_state(**kw)
    sess, now = str(uuid.uuid4()), time.time()
    states[sess] = dict(state=state, session_id=sess, start_time=now, last_use_time=now)
    return sess


def _open_frames(predictor, sess):
    """Give every frame an (empty) cached output, so a box prompt's tracked masks are kept. sam3 31cb7e6 builds a
    tracked frame's output on that frame's cached detections (_build_sam2_output) and returns nothing when there are
    none, which in a box-only session is every frame but the prompt's: tracking ran, the masks were dropped."""
    state = predictor._all_inference_states[sess]["state"]
    cache, n = state.get("cached_frame_outputs"), state.get("num_frames")
    if not isinstance(cache, dict) or not isinstance(n, int):
        raise RuntimeError("this sam3 session has no cached_frame_outputs / num_frames: "
                           "install the sam3 commit in docs/local-sam.md")
    for i in range(n):
        cache.setdefault(i, {})


def track(predictor, clip, prompt, encode):
    """One API-equivalent SAM call on the clip -> output text."""
    kind = parse_prompt(prompt)
    offload = os.environ.get("FISH_SAM_OFFLOAD", "") == "1"     # frames in RAM instead of VRAM (step 0 decides)
    sess = _start_session(predictor, clip, offload)
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
            _open_frames(predictor, sess)
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
