"""<run>/provenance.json: what made a run, for whoever has to stand behind its numbers later (round 3, 11/21c:
a regulator, a thesis examiner or a monitoring program asks which code, options, models and encoder gave a MaxN,
and status.json / result.json do not say).

One entry per time the run id was started (a --resume or a batch rerun adds one; earlier ones are kept):
  started / finished (UTC ISO times), command (argv as typed), code (git commit, whether tracked files had
  uncommitted changes, branch; None outside a git checkout), models (SAM, Spark, FISH_SPARK_MODEL), encoder (ffmpeg
  binary and version line, the x264 arguments that decide the clip bytes and so the cache keys), machine (CPU model,
  whether it has AVX-512, Python and package versions), environment (FISH_CACHE_DIR, FISH_LEDGER, FISH_BUDGET as
  set), private (on, and what made it so: "env" / "home-marker" / "etc-marker" / "no-home", api.PRIVATE_BY),
  source (path, size, modification time; no hash: hashing hundreds of GB is not free), and when the run ends
  result_sha256 (of result.json) or the error.
Written beside status.json; result.json is not touched, so results stay byte-identical. Never raises: a run is
never stopped by its own record keeping."""
import datetime, hashlib, json, os, platform, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_KEYS = ("FISH_CACHE_DIR", "FISH_LEDGER", "FISH_BUDGET", "FISH_SPARK_MODEL", "FISH_SAM", "FISH_PRIVATE",
            "FISH_SAM_BATCH", "FISH_SAM_OFFLOAD")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20, errors="replace")
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def code():
    """git commit, dirty (tracked files changed), branch of the package's checkout; None outside git."""
    commit = _run(["git", "-C", ROOT, "rev-parse", "HEAD"])
    if not commit:
        return None
    dirty = _run(["git", "-C", ROOT, "status", "--porcelain", "--untracked-files=no"])
    return dict(commit=commit, dirty=bool(dirty) if dirty is not None else None,
                branch=_run(["git", "-C", ROOT, "rev-parse", "--abbrev-ref", "HEAD"]))


def machine():
    cpu, flags = None, []
    try:
        with open("/proc/cpuinfo") as f:
            info = f.read()
        cpu = next((l.split(":", 1)[1].strip() for l in info.splitlines() if l.startswith("model name")), None)
        flags = info.split("\nflags", 2)[1].split("\n", 1)[0].split()
    except (OSError, IndexError):
        pass
    pk = {}
    for name in ("cv2", "numpy", "imageio_ffmpeg", "requests"):
        m = sys.modules.get(name)
        pk[name] = getattr(m, "__version__", None) if m else None
    return dict(cpu=cpu, avx512=("avx512f" in flags) if flags else None, cores=os.cpu_count(),
                python=platform.python_version(), platform=platform.platform(), packages=pk)


def encoder():
    from fishcount import video
    line = _run([video.FFMPEG, "-hide_banner", "-version"])
    return dict(ffmpeg=video.FFMPEG, version=line.splitlines()[0] if line else None, x264_args=list(video.X264_ARGS),
                preset="veryfast", crf=20)


def models():
    """SAM and Spark models; with local SAM (FISH_SAM=local) sam is its backend name (api.local_tag) and sam_local
    what its worker reported: torch, CUDA, GPU, sam3 commit, checkpoint and its sha256."""
    from fishcount import api
    try:
        backend = api.sam_backend()
    except api.LocalSamError as e:      # the run stops at its first SAM call; the entry still says why
        return dict(sam=None, sam_error=str(e), spark=api.SPARK_MODEL)
    if backend == "local":
        return dict(sam=api.local_tag(), sam_local=api.local_preflight(offline=True), spark=api.SPARK_MODEL)
    return dict(sam=api.SAM_MODEL, spark=api.SPARK_MODEL)


def _private():
    from fishcount import api
    return {"on": api.PRIVATE, "by": list(api.PRIVATE_BY)}


def source(path):
    try:
        s = os.stat(path)
        return dict(path=os.path.abspath(path), size=s.st_size,
                    mtime=datetime.datetime.fromtimestamp(s.st_mtime, datetime.timezone.utc).isoformat(timespec="seconds"))
    except OSError:
        return dict(path=path)


def _load(p):
    try:
        with open(p) as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("runs"), list) else dict(runs=[])
    except (OSError, ValueError):
        return dict(runs=[])


def _save(p, d):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, p)


def start(run_dir, argv, src, probe=None, encoder_warning=None):
    """Add this start's entry to <run_dir>/provenance.json. Returns the entry (or None if it could not be written).
    probe: video.encoder_probe()'s sha, kept as encoder.probe; encoder_warning: api.encoder_check's warning, if any."""
    try:
        os.makedirs(run_dir, exist_ok=True)
        p = os.path.join(run_dir, "provenance.json")
        d = _load(p)
        enc = encoder()
        if probe:
            enc["probe"] = probe
        e = dict(started=_now(), command=list(argv), code=code(), models=models(), encoder=enc,
                 machine=machine(), environment={k: os.environ[k] for k in ENV_KEYS if k in os.environ},
                 private=_private(), source=source(src))
        if encoder_warning:
            e["encoder_warning"] = encoder_warning
        d["runs"].append(e)
        _save(p, d)
        return e
    except Exception as ex:     # never stops the run
        print(f"provenance not written: {type(ex).__name__}: {ex}", file=sys.stderr)
        return None


def effective(run_dir, opts):
    """Add to the last entry the options the run really used where the command left a default (probe_window, the
    caps), so a later reader need not know which defaults this code had."""
    try:
        p = os.path.join(run_dir, "provenance.json")
        d = _load(p)
        if d["runs"]:
            d["runs"][-1]["effective"] = opts
            _save(p, d)
    except Exception as ex:     # never stops the run
        print(f"provenance not written: {type(ex).__name__}: {ex}", file=sys.stderr)


def finish(run_dir, error=None):
    """Close the last entry: finished time and result.json's sha256, or the error."""
    try:
        p = os.path.join(run_dir, "provenance.json")
        d = _load(p)
        if not d["runs"]:
            return
        e = d["runs"][-1]
        e["finished"] = _now()
        if error:
            e["error"] = error
        else:
            h = hashlib.sha256()
            with open(os.path.join(run_dir, "result.json"), "rb") as f:
                for b in iter(lambda: f.read(1 << 20), b""):
                    h.update(b)
            e["result_sha256"] = h.hexdigest()
        _save(p, d)
    except Exception as ex:
        print(f"provenance not finished: {type(ex).__name__}: {ex}", file=sys.stderr)
