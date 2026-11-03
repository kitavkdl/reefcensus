"""Site memory: a reviewer's rename teaches the next video from the same site.

Added after the evaluation (not used in any paper number). Off unless a site name is given (`--site NAME` on the CLI,
a "Site" field in the web form). Design, review and demo: docs/site_memory.md.

  runs/_site_memory/<site>.json   {"site": ..., "records": [{run, track, label, noun, alt, t}]}   (FISH_SITE_DIR overrides the folder)

A record is written only when a person, in a run that was started with a site, confirms or renames a queued track
(web/server.py review action). Removing a track, "Undo" or a label ending in "(unidentified)" teach nothing; Undo and
removal also delete the record they replace. `noun` is the plain noun SAM is asked for (head noun of the label), `alt`
is the word that actually tracked that animal in the earlier run when it was not a request word (earlier example:
reviewer name "hagfish" gave SAM 0 frames, the word "eel" gave 24).
  python3 fishcount/sitememory.py list SITE | forget SITE WORD
"""
import fcntl, json, os, re, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api

DIR = os.environ.get("FISH_SITE_DIR") or os.path.join(api.ROOT, "runs", "_site_memory")
MAX_ENTRIES = 3             # remembered animals one run adds (each costs 1-2 SAM calls, see docs/site_memory.md)
SITE_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,40}")
LABEL_RE = re.compile(r"[a-z][a-z -]{0,40}")
_lock = threading.Lock()


class _locked:
    """One writer at a time across threads and processes (the web server and the CLI): flock on <folder>/.lock."""
    def __enter__(self):
        _lock.acquire()
        os.makedirs(DIR, exist_ok=True)
        self.f = open(os.path.join(DIR, ".lock"), "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)

    def __exit__(self, *a):
        self.f.close()
        _lock.release()


def canon(run, track):
    """A segment run `<id>__S2` of a long video and the merged run `<id>` are one video: key both as the merged run's
    ids, so the same animal reviewed in either place is one record."""
    m = re.fullmatch(r"(.+)__S(\d+)", run)
    return (m.group(1), f"S{m.group(2)}:{track}") if m else (run, track)


def norm_site(name):
    """Lowercased site name safe to use as a file name, or ValueError."""
    s = (name or "").strip().lower()
    if not SITE_RE.fullmatch(s):
        raise ValueError("site name: 1-41 letters, digits, . _ - (starting with a letter or digit)")
    return s


def _path(site):
    return os.path.join(DIR, norm_site(site) + ".json")


def load(site):
    try:
        with open(_path(site)) as f:
            d = json.load(f)
        return d if isinstance(d.get("records"), list) else dict(site=norm_site(site), records=[])
    except (OSError, ValueError):
        return dict(site=norm_site(site), records=[])


def _save(site, d):
    os.makedirs(DIR, exist_ok=True)
    p = _path(site)
    with open(p + ".tmp", "w") as f:
        json.dump(d, f, indent=1)
    os.replace(p + ".tmp", p)


def noun_for(label):
    """The plain noun SAM is asked for, from a reviewer's label; None when the label teaches nothing."""
    from fishcount import pipeline          # lazy: pipeline imports this module's users
    l = (label or "").strip().lower()
    if not LABEL_RE.fullmatch(l) or l.endswith("unidentified)"):
        return None
    n = pipeline.short_name(l)
    return n if n and LABEL_RE.fullmatch(n) else None


def forget_track(site, run, track):
    run, track = canon(run, track)
    with _locked():
        d = load(site)
        keep = [r for r in d["records"] if not (r["run"] == run and r["track"] == track)]
        if len(keep) != len(d["records"]):
            d["records"] = keep
            _save(site, d)


def record(site, run, track, label, alt=None):
    """A person confirmed or renamed `track` of `run` as `label`. Replaces that track's earlier record. Returns the
    noun remembered, or None (the label teaches nothing; the track's old record is dropped)."""
    noun = noun_for(label)
    run, track = canon(run, track)
    with _locked():
        d = load(site)
        d["records"] = [r for r in d["records"] if not (r["run"] == run and r["track"] == track)]
        if noun:
            alt = alt if alt and LABEL_RE.fullmatch(alt) and alt != noun else None
            d["records"].append(dict(run=run, track=track, label=label.strip().lower(), noun=noun, alt=alt, t=time.time()))
        _save(site, d)
    return noun


def plan(site, skip_words=(), max_entries=MAX_ENTRIES):
    """Remembered animals for a new run, confirmed in the most videos first (ties: most recent). Each entry is a SAM word ladder
    [noun, alt]; words the run already uses (`skip_words`) or an earlier entry has are dropped."""
    by = {}
    for r in load(site)["records"]:
        e = by.setdefault(r["noun"], dict(noun=r["noun"], n=0, t=0, label=r["label"], alts=[], runs=[]))
        if r["t"] >= e["t"]:
            e["t"], e["label"] = r["t"], r["label"]
        if r.get("alt") and r["alt"] not in e["alts"]:
            e["alts"].append(r["alt"])
        if r["run"] not in e["runs"]:
            e["runs"].append(r["run"])
            e["n"] += 1         # confirmed in n different videos: one run with many tracks does not outvote the others
    out, seen = [], set(skip_words)
    for e in sorted(by.values(), key=lambda e: (-e["n"], -e["t"], e["noun"])):
        words = [w for w in [e["noun"]] + e["alts"][:1] if w not in seen]
        if not words:
            continue
        seen.update(words)
        out.append(dict(noun=e["noun"], label=e["label"], words=words, n=e["n"], runs=e["runs"]))
        if len(out) >= max_entries:
            break
    return out


def source_word(result, track):
    """The SAM word that tracked `track` in `result`, when it is not one of the request words and the track was not a
    word-less motion box; else None."""
    t = result.get("tracks", {}).get(track)
    if not t or re.sub(r"^S\d+:", "", t["source"]).startswith("m"):
        return None
    asked = {p[1] for p in result.get("prompts", []) if len(p) > 1}
    w = (t.get("label") or "").strip().lower()
    return w if w and w not in asked else None


def forget_word(site, word):
    with _locked():
        d = load(site)
        keep = [r for r in d["records"] if word not in (r["noun"], r.get("alt"), r["label"])]
        d["records"] = keep
        _save(site, d)
        return len(keep)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "list":
        for e in plan(sys.argv[2], max_entries=99):
            print(f"{e['label']!r}: SAM words {e['words']}, confirmed in {e['n']} video(s): {', '.join(e['runs'])}")
    elif len(sys.argv) == 4 and sys.argv[1] == "forget":
        print(f"{forget_word(sys.argv[2], sys.argv[3].lower())} records left")
    else:
        sys.exit(__doc__)
