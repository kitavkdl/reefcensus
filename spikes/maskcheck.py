"""Check fishcount.maskcodec against meta_sam_parser on every cached SAM output.
  1. records: same (frame, box, mask size, payload) list as the reference parser (its mask decode stubbed out);
  2. masks:   C decode == reference decode_mask_to_raster, pixel for pixel (every --every'th mask; slow side is
              the reference, ~0.5 s a mask).
Usage: python spikes/maskcheck.py [--every K] [--jobs N] [cache/sam_*.json ...]"""
import argparse, concurrent.futures as cf, glob, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import maskcodec
import numpy as np


def reference_records(text):
    import meta_sam_parser._segmentation as seg
    from meta_sam_parser import video_segmentation_format, CompletedOutcome
    keep, seg.decode_mask_to_raster = seg.decode_mask_to_raster, lambda m: b""
    try:
        p = video_segmentation_format().create_parser()
        p.push(text + "\n")
        res = p.finish(CompletedOutcome()).result
    finally:
        seg.decode_mask_to_raster = keep
    return [(r.frame.frame_index, (r.bounds.left, r.bounds.top, r.bounds.right, r.bounds.bottom), r.mask.height, r.mask.width, r.mask.payload)
            for r in res.records if r.kind == "mask" and r.frame is not None]


def check_masks(recs):
    from meta_sam_parser import decode_mask_to_raster, SegmentationMask
    bad = 0
    for f, box, mh, mw, payload in recs:
        ref = np.frombuffer(decode_mask_to_raster(SegmentationMask("one_bit", payload, mw, mh)), np.uint8).reshape(mh, mw).astype(bool)
        bad += not np.array_equal(ref, maskcodec.decode(payload, mw, mh))
    return len(recs), bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    a = ap.parse_args()
    files = a.files or sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "cache", "sam_*.json")))
    print("C decoder:", maskcodec.fast())
    texts = {fn: json.load(open(fn)).get("output_text") or "" for fn in files}
    texts = {fn: t for fn, t in texts.items() if "<|mask" in t}
    rec_bad, todo = 0, []
    for fn, t in texts.items():
        mine, ref = list(maskcodec.records(t)), reference_records(t)
        if mine != ref:
            rec_bad += 1
            print("RECORDS DIFFER", os.path.basename(fn), len(mine), len(ref))
        todo += mine
    print(f"records: {len(texts)} outputs, {len(todo)} masks, {rec_bad} outputs differ")
    todo = todo[::a.every]
    t0 = time.time()
    for i in range(0, len(todo), 2000):     # time the fast path alone
        [maskcodec.decode(p, mw, mh) for _, _, mh, mw, p in todo[i:i + 2000]]
    print(f"fast decode of {len(todo)} masks: {time.time() - t0:.2f}s")
    chunks = [todo[i::a.jobs * 4] for i in range(a.jobs * 4)]
    with cf.ProcessPoolExecutor(a.jobs) as ex:
        res = list(ex.map(check_masks, chunks))
    print(f"masks: {sum(n for n, _ in res)} compared, {sum(b for _, b in res)} differ")
