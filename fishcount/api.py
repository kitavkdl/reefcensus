"""Meta Model API clients (SAM 3.1 video, Muse Spark chat) with a disk cache and a spend ledger.
Every paid call runs inside `reserve(est)`, which refuses to exceed FISH_BUDGET (default $1) for the lifetime of the
ledger file; the check and the hold are atomic across threads and processes, so parallel calls cannot overshoot it. The API key comes from META_API_KEY (environment or a .env file in the repo root,
see .env.example) or else ~/.config/meta-api/key, and is never printed."""
import base64, hashlib, json, os, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import _pylib  # noqa: F401  optional vendored package folder (see _pylib.py)
import requests

BASE = "https://api.meta.ai/v1"
KEYFILE = os.path.expanduser("~/.config/meta-api/key")


def _load_dotenv(path=os.path.join(ROOT, ".env")):
    """KEY=VALUE lines from .env, without overriding variables already set in the environment."""
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()
CACHE = os.environ.get("FISH_CACHE_DIR") or os.path.join(ROOT, "cache")   # FISH_CACHE_DIR=<empty dir>: a fresh, uncached run
# one spend ledger whatever the cache; FISH_LEDGER points a git worktree (its own ROOT) at the main checkout's ledger,
# so a branch's spend is not split into a second copy that FISH_BUDGET never sees
LEDGER = os.environ.get("FISH_LEDGER") or os.path.join(ROOT, "cache", "ledger.jsonl")
SAM_PER_FRAME = 0.20 / 1000
SAM_MIN_FRAMES = 50
SPARK_IN, SPARK_OUT = 1.25e-6, 4.25e-6
PRICES = {"muse-wonder-1.0": (4.0e-6, 20.0e-6)}   # $/token (in, out); everything else is priced as Spark
SPARK_MODEL = os.environ.get("FISH_SPARK_MODEL", "muse-spark-1.3")


class BudgetExceeded(RuntimeError):
    pass


def _key():
    k = os.environ.get("META_API_KEY", "").strip()
    if not k and os.path.exists(KEYFILE):
        k = open(KEYFILE).read().strip()
    if not k:
        raise RuntimeError("no Meta API key: set META_API_KEY (see .env.example), or use --offline / the demo runs")
    return k


def spent():
    if not os.path.exists(LEDGER):
        return 0.0
    return sum(json.loads(l)["usd"] for l in open(LEDGER) if l.strip())


_resv_lock = threading.Lock()


def _resv_path():
    return LEDGER + ".resv"


def _live_reservations(lines):
    """Reservations whose process is still alive (a crashed run must not hold budget forever)."""
    out = []
    for l in lines:
        try:
            d = json.loads(l)
            os.kill(d["pid"], 0)
            out.append(d)
        except (ValueError, KeyError, ProcessLookupError):
            continue
        except PermissionError:
            out.append(d)
    return out


class _Reservation:
    """Hard spend cap. Check-and-reserve happens under one lock (threads: a mutex; processes sharing the ledger: an
    flock on ledger.jsonl.resv), so parallel calls cannot all pass the same check: each one's estimate is held until
    the call has been written to the ledger (or failed). Estimates are upper bounds of one call (SAM: billed frames
    are the clip's; Spark: $0.02 against a largest logged call of $0.015)."""

    def __init__(self, est):
        self.est, self.id = est, f"{os.getpid()}-{threading.get_ident()}-{time.time_ns()}"

    def _edit(self, fn):
        import fcntl
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with _resv_lock, open(_resv_path(), "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            res = _live_reservations(fh.read().splitlines())
            res = fn(res)
            fh.seek(0)
            fh.truncate()
            fh.write("".join(json.dumps(r) + "\n" for r in res))

    def __enter__(self):
        budget = float(os.environ.get("FISH_BUDGET", "1.0"))

        def take(res):
            held = sum(r["usd"] for r in res)
            if spent() + held + self.est > budget:
                raise BudgetExceeded(f"would spend ${spent() + held + self.est:.3f} > budget ${budget:.2f}"
                                     f"{f' (${held:.3f} held by calls in flight)' if held else ''} (set FISH_BUDGET)")
            return res + [dict(id=self.id, pid=os.getpid(), usd=self.est)]
        self._edit(take)
        return self

    def __exit__(self, *exc):
        self._edit(lambda res: [r for r in res if r["id"] != self.id])
        return False


def reserve(est):
    """`with reserve(est): <paid call, then _log>` holds `est` against FISH_BUDGET until the call is logged."""
    return _Reservation(est)


def _guard(est):
    """Check only (kept for the paper's repeat scripts, which call it before a single serial call)."""
    with _Reservation(est):
        pass


_tl = threading.local()     # per-thread spend, so parallel calls don't bill each other


def thread_spent():
    return getattr(_tl, "usd", 0.0)


def _log(kind, usd, note):
    _tl.usd = thread_spent() + usd
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps({"t": time.time(), "kind": kind, "usd": usd, "note": note}) + "\n")


def _cache_path(kind, payload):
    h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
    return os.path.join(CACHE, f"{kind}_{h}.json")


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:24]


# ---------------- SAM 3.1 ----------------
def sam_cached(clip_path, prompt):
    """True when sam_video(clip_path, prompt) would be answered from cache (free)."""
    return os.path.exists(_cache_path("sam", {"clip": file_sha(clip_path), "prompt": prompt}))


def sam_video(clip_path, prompt, n_frames, offline=False):
    """Track `prompt` through the clip. Returns the raw output_text (one line per frame with objects).
    Cached by (clip content hash, prompt). offline=True never calls the network (raises if not cached)."""
    payload = {"clip": file_sha(clip_path), "prompt": prompt}
    cp = _cache_path("sam", payload)
    if os.path.exists(cp):
        return json.load(open(cp))["output_text"]
    if offline:
        raise FileNotFoundError(f"not cached: SAM {prompt!r} on {clip_path}")
    est = max(SAM_MIN_FRAMES, n_frames) * SAM_PER_FRAME
    with reserve(est):
        return _sam_live(clip_path, prompt, n_frames, payload, cp)


UPLOAD_REUSE_S = 20 * 3600     # an uploaded clip's file_id is reused this long (the upload expires after 24 h)
UPLOAD_TRIES = 3               # a failed upload (timeout, dropped connection, 5xx) is sent again, up to this many times
# The whole multipart body goes out in one socket sendall() under the *connect* timeout (urllib3 2.x), and since
# Python 3.5 a socket timeout bounds the whole sendall, not each send: with (300, 600) any upload slower than 300 s
# failed every time ("The write operation timed out": cr9 S2/S4, a 396 MB segment at 1.3 MB/s, 11/21). The send is
# now allowed size / UPLOAD_MIN_BPS seconds (396 MB: ~33 min), at least 300 s as before.
UPLOAD_MIN_BPS = 200 * 1024
_uploads, _upload_locks, _uploads_lock = {}, {}, threading.Lock()


def _upload(clip_path, key, fresh=False, sha=None):
    """(file_id of `clip_path` on the API, whether it was reused). 11/21: every SAM call uploaded its clip again,
    though one 600-s segment gets several words on the same ~350 MB file (LONG1_cr9: 3-11 calls per segment clip)
    and this uplink manages 0.5-1.3 MB/s; the same bytes now go up once per process (per clip content,
    UPLOAD_REUSE_S), and threads asking for the same clip wait for that one upload. A failed upload (dropped
    connection, timeout, 5xx) is sent again. Uploading is free; SAM sees the same file either way, so answers and
    cache keys do not change. fresh=True uploads again even when an id is held (the server no longer had it)."""
    sha = sha or file_sha(clip_path)
    with _uploads_lock:
        lock = _upload_locks.setdefault(sha, threading.Lock())
    with lock:
        got = _uploads.get(sha)
        if got and not fresh and time.time() - got[1] < UPLOAD_REUSE_S:
            return got[0], True
        for attempt in range(UPLOAD_TRIES):
            try:
                with open(clip_path, "rb") as fh:
                    r = requests.post(f"{BASE}/files", headers={"Authorization": f"Bearer {key}"},
                                      data={"purpose": "user_data", "expires_after[anchor]": "created_at", "expires_after[seconds]": "86400"},
                                      files={"file": (os.path.basename(clip_path), fh, "video/mp4")},
                                      timeout=(max(300.0, os.path.getsize(clip_path) / UPLOAD_MIN_BPS), 600))
                if r.status_code < 500:
                    r.raise_for_status()
                    break
                err = requests.HTTPError(f"upload HTTP {r.status_code}: {r.text[:200]}")
            except (requests.ConnectionError, requests.Timeout) as e:
                err = e
            if attempt == UPLOAD_TRIES - 1:
                raise err
            time.sleep(5 * 3 ** attempt)
        fid = r.json()["id"]
        _uploads[sha] = (fid, time.time())
        return fid, False


def _sam_live(clip_path, prompt, n_frames, payload, cp):
    key = _key()
    fid, reused = _upload(clip_path, key, sha=payload["clip"])
    for attempt in range(2):
        body = {"model": "sam-3.1", "stream": True, "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},
                "input": [{"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": prompt}, {"type": "input_video", "file_id": fid}]}]}
        r = requests.post(f"{BASE}/responses", headers={"Authorization": f"Bearer {key}", "Accept": "text/event-stream"},
                          json=body, stream=True, timeout=(30, 900))
        if 400 <= r.status_code < 500 and reused:
            r.close()       # a reused file_id the server no longer has (expired, deleted): upload once more
            fid, reused = _upload(clip_path, key, fresh=True, sha=payload["clip"])
            continue
        break
    text, usage, status = [], None, "unknown"
    with r:
        if r.status_code >= 300:
            raise RuntimeError(f"SAM HTTP {r.status_code}: {r.text[:300]}")
        for raw in r.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            d = raw[5:].strip()
            if d == "[DONE]":
                break
            try:
                ev = json.loads(d)
            except ValueError:
                continue
            t = ev.get("type")
            if t == "response.output_text.delta":
                text.append(ev.get("delta", ""))
            elif t == "response.completed":
                status, usage = "completed", (ev.get("response") or {}).get("usage")
            elif t in ("response.failed", "response.incomplete", "error"):
                status = t
    billed = (usage or {}).get("video_frames_processed") or max(SAM_MIN_FRAMES, n_frames)
    _log("sam", billed * SAM_PER_FRAME, f"{os.path.basename(clip_path)}:{prompt}")
    if status != "completed":
        raise RuntimeError(f"SAM status {status}")
    out = "".join(text)
    json.dump({"payload": payload, "output_text": out, "usage": usage}, open(cp, "w"))
    return out


# ---------------- Muse Spark ----------------
def img_data_url(jpg_bytes):
    return "data:image/jpeg;base64," + base64.b64encode(jpg_bytes).decode()


def _valid(check, text):
    try:
        check(text)
        return True
    except ValueError:      # json.JSONDecodeError is a ValueError
        return False


def spark(prompt, images=(), max_tokens=6000, effort="low", offline=False, check=None, model=None):
    """One chat call with optional JPEG images (bytes). Returns the reply text. Cached by content.
    `check(text)` raising ValueError marks a bad reply (11/2: Spark twice sent broken JSON, e.g. `{ polo":1 }:`,
    and the cached reply then killed every rerun): a bad reply is never cached, a cached bad one counts as a miss,
    and one more live call is made before giving up."""
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": img_data_url(b)}} for b in images]
    model = model or SPARK_MODEL
    payload = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens}
    if effort:
        payload["reasoning_effort"] = effort
    cp = _cache_path("spark", payload)
    if os.path.exists(cp):
        cj = json.load(open(cp))
        text = cj["text"]
        if check is None or _valid(check, text):
            _tl.last_usage = cj.get("usage") or {}
            return text
    if offline:
        raise FileNotFoundError("not cached: spark call")
    for attempt in range(2 if check else 1):
        with reserve(0.02 if model == SPARK_MODEL else 0.15):     # largest logged: Spark $0.015, Wonder $0.096
            text, u = _spark_live(payload, model)
        if check is None or _valid(check, text):
            tmp = f"{cp}.{os.getpid()}.{threading.get_ident()}.tmp"     # CLI and web server may share cache/
            with open(tmp, "w") as fh:
                json.dump({"text": text, "usage": u}, fh)
            os.replace(tmp, cp)
            _tl.last_usage = u
            return text
    raise ValueError(f"Spark sent an unreadable reply twice: {text[:120]!r}")


def _spark_live(payload, model):
    r = requests.post(f"{BASE}/chat/completions", headers={"Authorization": f"Bearer {_key()}"}, json=payload, timeout=(30, 300))
    if r.status_code >= 300:
        raise RuntimeError(f"Spark HTTP {r.status_code}: {r.text[:300]}")
    j = r.json()
    u = j.get("usage") or {}
    p_in, p_out = PRICES.get(model, (SPARK_IN, SPARK_OUT))
    usd = u.get("prompt_tokens", 0) * p_in + u.get("completion_tokens", 0) * p_out
    _log("spark" if model == SPARK_MODEL else model, usd, f"in={u.get('prompt_tokens')} out={u.get('completion_tokens')}")
    text = j["choices"][0]["message"]["content"] or ""
    if not text.strip():
        raise RuntimeError(f"Spark returned empty text (usage {u}); raise max_tokens or lower effort")
    return text, u


def parse_json_list(text):
    """parse_json for replies that must be a list of objects (audit, verify, pair); raises ValueError otherwise."""
    got = parse_json(text)
    if not (isinstance(got, list) and all(isinstance(v, dict) for v in got)):
        raise ValueError("expected a JSON list of objects")
    return got


def parse_json(text):
    """Pull the first JSON object/array out of a model reply (tolerates ```json fences)."""
    s = text.strip()
    if "```" in s:
        s = s.split("```")[1]
        s = s[4:] if s.startswith("json") else s
    i = min([p for p in (s.find("{"), s.find("[")) if p >= 0], default=-1)
    if i < 0:
        raise ValueError("no JSON in reply")
    return json.JSONDecoder().raw_decode(s[i:])[0]
