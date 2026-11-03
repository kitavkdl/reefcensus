"""Other-VLM comparison by shadow replay (protocol: report/paper/vlm_swap_protocol.md).

Each clip's final pipeline run is replayed from the cache (Spark's answers drive every step; the run is offline, so SAM and Spark are never called live).
Every Spark call is also sent, unchanged (same prompt, same images, same max_tokens and effort, same reply check),
to a second model, and both replies are written to report/paper/data/vlm_swap/calls_<model>.jsonl.
The second model's spend is logged in the ledger under its own name but kept out of the run's per-video cap.

  FISH_BUDGET=<ledger+cap> memcap --max 2G -- python3 report/paper/scripts/vlm_swap.py [--clips DH1 DH2 ...] [--model muse-wonder-1.0]
"""
import argparse, json, os, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from fishcount import api, pipeline  # noqa: E402

FLAGS = dict(do_scout=False, do_audit=True, do_zoom=True, prompts=["fish"], do_discover=True)
CLIPS = {f"DH{n}": f"spikes/DH/clips/DH{n}.mp4" for n in range(1, 6)}
CLIPS.update({f"DH{n}": f"spikes/DHB/clips/DH{n}.mp4" for n in range(6, 12)})
CLIPS.update({"s001": "spikes/L1/clips/nautilus_s001_0_12.mp4", "s002": "spikes/L1/clips/nautilus_0_12.mp4",
              "s003": "spikes/L1/clips/nautilus_s003_0_12.mp4", "s004": "spikes/L1/clips/nautilus_s004_0_12.mp4"})
KINDS = {name: getattr(pipeline, name).split("{")[0][:60] for name in
         ("SCOUT_PROMPT", "DISCOVER_PROMPT", "AUDIT_PROMPT", "VERIFY_PROMPT", "PAIR_PROMPT", "MOTION_PROMPT", "CONFIRM_PROMPT")}

_orig = api.spark
_lock = threading.Lock()


def kind_of(prompt):
    for name, head in KINDS.items():
        if prompt.startswith(head):
            return name.replace("_PROMPT", "").lower()
    return "other"


def make_shadow(model, clip, out, dry=False):
    def shadow(prompt, images=(), **kw):
        kw.pop("offline", None)
        text = _orig(prompt, images, offline=True, **kw)        # Spark: cache only; a miss means the replay diverged
        rec = {"clip": clip, "kind": kind_of(prompt), "prompt": prompt, "spark": text}
        before = api.thread_spent()
        t0 = time.time()
        try:
            rec["other"] = _orig(prompt, images, model=model, offline=dry, **kw)
        except Exception as e:                                    # unreadable twice, HTTP error: recorded, not retried
            rec["other"], rec["error"] = None, f"{type(e).__name__}: {e}"[:400]
        rec["seconds"] = round(time.time() - t0, 2)
        rec["usd"] = round(api.thread_spent() - before, 6)
        api._tl.usd = before                                      # keep the second model out of the run's cap
        with _lock, open(out, "a") as f:
            f.write(json.dumps(rec) + "\n")
        return text
    return shadow


def motion_shadow(model, clip, out, dry):
    """The motion look is saved apart from the Spark cache (cache/motion_<key>.json + .jpg), so the replay does not
    call Spark for it; send the saved sheet with MOTION_PROMPT to the second model and record Spark's saved answer."""
    import glob, hashlib
    sheet = f"runs/vswap_{clip}/motion_sheet.jpg"
    if not os.path.exists(sheet):
        return
    h = hashlib.sha256(open(sheet, "rb").read()).hexdigest()
    for j in glob.glob(os.path.join(api.CACHE, "motion_*.json")):
        mc = json.load(open(j))
        sj = os.path.join(api.CACHE, mc.get("sheet") or "-")
        if os.path.exists(sj) and hashlib.sha256(open(sj, "rb").read()).hexdigest() == h:
            break
    else:
        return
    rec = {"clip": clip, "kind": "motion", "prompt": pipeline.MOTION_PROMPT, "spark": json.dumps(mc["said"])}
    t0 = time.time()
    try:
        rec["other"] = _orig(pipeline.MOTION_PROMPT, [open(sheet, "rb").read()], model=model, offline=dry,
                             check=pipeline._motion_reply)
    except Exception as e:
        rec["other"], rec["error"] = None, f"{type(e).__name__}: {e}"[:400]
    rec["seconds"] = round(time.time() - t0, 2)
    with _lock, open(out, "a") as f:
        f.write(json.dumps(rec) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", nargs="*", default=list(CLIPS))
    ap.add_argument("--model", default="muse-wonder-1.0")
    ap.add_argument("--dry", action="store_true", help="second model from cache only (counts the calls, $0)")
    a = ap.parse_args()
    os.makedirs("report/paper/data/vlm_swap", exist_ok=True)
    out = f"report/paper/data/vlm_swap/calls_{a.model}{'_dry' if a.dry else ''}.jsonl"
    for clip in a.clips:
        api.spark = make_shadow(a.model, clip, out, a.dry)
        try:
            r = pipeline.run_pipeline(CLIPS[clip], f"vswap_{clip}", True, max_usd=1.0, lowlight="auto", **FLAGS)
            print(clip, "done", r["metrics"].keys() if isinstance(r, dict) and "metrics" in r else "", flush=True)
        except Exception as e:
            print(clip, "FAILED", type(e).__name__, str(e)[:300], flush=True)
        finally:
            api.spark = _orig
        motion_shadow(a.model, clip, out, a.dry)
    print("ledger total", round(api.spent(), 4))


if __name__ == "__main__":
    main()
