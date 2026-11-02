"""Fast reader for SAM 3.1 video output: records by regex, one_bit masks through a small C decoder.
meta_sam_parser is pure Python and decodes every mask twice over (parse validates, decode_mask_to_raster
again), ~1 s a mask at our sizes -> 11/1 s003 annotated video took ~2 min. Same results, checked mask by mask
against the reference (spikes/maskcheck.py). Without a C compiler it falls back to the reference decoder."""
import ctypes, hashlib, os, re, subprocess, sys, tempfile
sys.path.insert(0, os.path.expanduser("~/meta-smoke/pylib"))
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "_maskdec.c")
HEADER = re.compile(r"<([0-9]+)f(?:;[^>]*)?>(.*)")
RECORD = re.compile(r",?([0-9]+)((?:<\|[^|]*\|>)+)")
TOKEN = re.compile(r"<\|([A-Za-z][A-Za-z0-9_.-]*)(?:;([^|]*))?\|>")
DATA = re.compile(r"([0-9]+),([0-9]+),([!~][^|]+)")
_lib = None


def _load():
    """Compile _maskdec.c once into __pycache__ (keyed by source hash, atomic rename for parallel workers)."""
    global _lib
    if _lib is None:
        _lib = False
        try:
            tag = hashlib.sha1(open(SRC, "rb").read()).hexdigest()[:12]
            so = os.path.join(HERE, "__pycache__", f"_maskdec-{tag}.so")
            if not os.path.exists(so):
                os.makedirs(os.path.dirname(so), exist_ok=True)
                fd, tmp = tempfile.mkstemp(suffix=".so", dir=os.path.dirname(so))
                os.close(fd)
                subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-o", tmp, SRC], check=True, capture_output=True)
                os.replace(tmp, so)
            lib = ctypes.CDLL(so)
            lib.decode_one_bit.argtypes = [ctypes.c_char_p, ctypes.c_int64, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
            lib.decode_one_bit.restype = ctypes.c_int
            _lib = lib
        except (OSError, subprocess.CalledProcessError):
            pass
    return _lib


def fast():
    return bool(_load())


def decode(payload, width, height):
    """Mask payload -> (height, width) bool array."""
    lib = _load()
    if lib and payload.startswith("!"):
        out = np.empty(width * height, np.uint8)
        b = payload[1:].encode("ascii", "replace")
        if lib.decode_one_bit(b, len(b), width, height, out.ctypes.data) == 0:
            return out.reshape(height, width).astype(bool)
    from meta_sam_parser import decode_mask_to_raster, SegmentationMask   # lossless '~', malformed, or no compiler
    enc = "lossless" if payload.startswith("~") else "one_bit"
    raw = decode_mask_to_raster(SegmentationMask(encoding=enc, payload=payload, width=width, height=height))
    return np.frombuffer(raw, np.uint8).reshape(height, width).astype(bool)


def records(text, frame=None):
    """Yield (frame, (left, top, right, bottom), height, width, payload) per object record, the way
    meta_sam_parser reads them (right/bottom exclusive). frame: only that frame's line."""
    for line in text.splitlines():
        h = HEADER.fullmatch(line.strip())
        if not h or (frame is not None and int(h.group(1)) != frame):
            continue
        for rec in RECORD.finditer(h.group(2)):
            toks = {}
            for t in TOKEN.finditer(rec.group(2)):
                toks.setdefault(t.group(1), dict(kv.split("=", 1) for kv in (t.group(2) or "").split(";") if "=" in kv))
            box, mask = toks.get("box"), toks.get("mask")
            d = DATA.fullmatch((mask or {}).get("data", ""))
            if not box or not d:
                continue
            x1, y1, x2, y2 = (int(box[k]) for k in ("x1", "y1", "x2", "y2"))
            yield int(h.group(1)), (x1, y1, x2 + 1, y2 + 1), int(d.group(1)), int(d.group(2)), d.group(3)


def masks(text, frame=None):
    """{frame: [(box, bool mask)]} for every record (or just `frame`)."""
    out = {}
    for f, box, mh, mw, payload in records(text, frame):
        out.setdefault(f, []).append((box, decode(payload, mw, mh)))
    return out
