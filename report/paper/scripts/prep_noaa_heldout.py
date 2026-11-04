"""Third held-out set (NOAA reef-fish survey, N1-N8): select stations and cut the 600.0-612.0 s window, exactly as
report/paper/noaa_heldout_protocol.md fixes it. Writes report/paper/data/noaa_heldout/clips.json (station, file, URL,
size, window, sha256 of each cut clip, the git HEAD at cutting time) and skips.log.

  python3 report/paper/scripts/prep_noaa_heldout.py --list-only   # names and sizes only, no video opened
  python3 report/paper/scripts/prep_noaa_heldout.py [--out DIR]    # cut the clips (freezes fishcount/ per protocol)

Two copies per clip in DIR (default data_noaa/, not committed): N<k>.mp4 (pipeline input: 12 s, H.264, width <= 1920,
no audio) and N<k>_full.mp4 (the same 12 s at the original frame rate, for the hand count; lightly compressed).
Each chosen chapter (about 4 GB) is downloaded with curl (the bundled ffmpeg cannot read HTTPS), cut, and deleted;
about 5 min per station."""
import argparse, hashlib, json, os, random, subprocess, sys, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
BUCKET = "nmfs_odp_sefsc"
PREFIX = "PEMD/VIDEO_DATA/GOM_REEF_FISH/Jack_Videos/sefis video/"
EXCLUDE = "T60233001_A"          # the 53-min run (Table 3d)
SEED, N, MIN_BYTES, T0, DUR = 1105, 8, 10 ** 9, 600.0, 12.0
OUT_DATA = os.path.join(ROOT, "report", "paper", "data", "noaa_heldout")


def ffmpeg():
    """The pipeline's own ffmpeg (imageio-ffmpeg, or the vendored folder via FISH_PYLIB)."""
    sys.path.insert(0, ROOT)
    from fishcount.video import FFMPEG
    return FFMPEG


def gcs_list(prefix, delimiter="/"):
    """All prefixes (folders) and objects under prefix, following pages."""
    prefixes, items, token = [], [], None
    while True:
        q = {"prefix": prefix, "delimiter": delimiter, "maxResults": 1000}
        if token:
            q["pageToken"] = token
        url = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o?" + urllib.parse.urlencode(q)
        d = json.load(urllib.request.urlopen(url, timeout=60))
        prefixes += d.get("prefixes", []); items += d.get("items", [])
        token = d.get("nextPageToken")
        if not token:
            return prefixes, items


def media_url(name):
    return f"https://storage.googleapis.com/{BUCKET}/" + urllib.parse.quote(name)


def duration(url):
    r = subprocess.run([ffmpeg(), "-hide_banner", "-nostdin", "-i", url], capture_output=True, text=True, timeout=300)
    for line in r.stderr.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            h, m, s = line.split(",")[0].split()[1].split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return None


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "data_noaa"))
    a = ap.parse_args()
    stations, _ = gcs_list(PREFIX)
    stations = sorted(s[len(PREFIX):].rstrip("/") for s in stations)
    stations = [s for s in stations if s != EXCLUDE]
    random.Random(SEED).shuffle(stations)
    print(f"{len(stations)} stations after removing {EXCLUDE}; shuffled with random.Random({SEED})")
    head = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if not a.list_only and subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--", "fishcount"],
                                          capture_output=True, text=True).stdout:
        sys.exit("fishcount/ has uncommitted changes; commit first so the frozen code is a commit")
    picked, skips = [], []
    for st in stations:
        if len(picked) == N:
            break
        _, items = gcs_list(PREFIX + st + "/")
        gopr = [i for i in items if os.path.basename(i["name"]).upper().startswith("GOPR")
                and i["name"].upper().endswith(".MP4") and int(i["size"]) >= MIN_BYTES]
        if not gopr:
            skips.append((st, "no GOPR*.MP4 chapter of at least 1 GB")); continue
        f = max(gopr, key=lambda i: int(i["size"]))
        rec = dict(station=st, file=os.path.basename(f["name"]), url=media_url(f["name"]), size=int(f["size"]),
                   window=[T0, T0 + DUR])
        if not a.list_only:
            os.makedirs(a.out, exist_ok=True)
            local = os.path.join(a.out, "_chapter.MP4")
            subprocess.run(["curl", "-sS", "--fail", "-o", local, rec["url"]], check=True, timeout=3600)
            dur = duration(local)
            if dur is None or dur < T0 + DUR:
                os.remove(local)
                skips.append((st, f"chapter {rec['file']} duration {dur} s < {T0 + DUR} s or unreadable")); continue
            rec["chapter_seconds"] = dur
            k = len(picked) + 1
            pipe, full = os.path.join(a.out, f"N{k}.mp4"), os.path.join(a.out, f"N{k}_full.mp4")
            base = [ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-ss", str(T0), "-i", local,
                    "-t", str(DUR), "-an"]
            subprocess.run(base + ["-vf", "scale='min(1920,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
                                   "-crf", "18", "-pix_fmt", "yuv420p", pipe], check=True, timeout=900)
            subprocess.run(base + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", full],
                           check=True, timeout=900)
            os.remove(local)
            rec.update(id=f"N{k}", sha256_pipeline=sha256(pipe), sha256_handcount=sha256(full))
        picked.append(rec)
        print(f"N{len(picked)}  {st}  {rec['file']}  {rec['size'] / 1e9:.2f} GB")
    for st, why in skips:
        print(f"skip {st}: {why}")
    if a.list_only:
        print("--list-only: nothing cut, nothing written"); return
    os.makedirs(OUT_DATA, exist_ok=True)
    json.dump(dict(protocol="report/paper/noaa_heldout_protocol.md", code_head=head, seed=SEED, clips=picked),
              open(os.path.join(OUT_DATA, "clips.json"), "w"), indent=1)
    with open(os.path.join(OUT_DATA, "skips.log"), "w") as fh:
        fh.writelines(f"{st}\t{why}\n" for st, why in skips)
    # hand-count sheet (protocol: shuffled with random.Random(1106), neutral names clip_a ..., key fixed before counting)
    ids = [c["id"] for c in picked]
    random.Random(1106).shuffle(ids)
    key = {f"clip_{chr(97 + i)}": cid for i, cid in enumerate(ids)}
    hk = os.path.join(OUT_DATA, "handcount_key.json")
    json.dump(dict(protocol="NOAA held-out hand count: full-rate 12-s clips, no boxes, shuffled with random.Random(1106), "
                            "neutral names; fixed before counting", key=key), open(hk, "w"), indent=1)
    for name, cid in key.items():
        os.link(os.path.join(a.out, f"{cid}_full.mp4"), os.path.join(a.out, f"{name}.mp4"))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import count_sheet_video
    sheet = os.path.join(a.out, "noaa-count-sheet.html")
    open(sheet, "w").write(count_sheet_video.build(key, a.out, ".mp4", "fishcount-noaa"))
    print(f"wrote {OUT_DATA}/clips.json (code {head[:7]}), {hk}; clips and hand-count sheet {sheet} in {a.out}")


if __name__ == "__main__":
    main()
