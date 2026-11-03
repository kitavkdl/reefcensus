# One long real deployment (≈ 53 min) — pre-run record

Written 2026-11-03 (UTC), **before any paid call** on this video. Purpose: replace the paper's extrapolation ("an
hour-long deployment has not been run; estimated about $30 and 7.5 h sequentially") by one measured run. The project
owner approved running one real long video and collecting the numbers.

## Source
- **What**: a baited remote underwater video (BRUV) deployment, one GoPro camera ("A"), station folder `T60233001_A`,
  three consecutive GoPro chapter files from the same continuous recording: `GOPR1512.MP4`, `GP011512.MP4`,
  `GP021512.MP4`. A fourth chapter of the same recording (`GP031512.MP4`, 17.7 min) and a 5-s start-up file
  (`GOPR1511.MP4`) exist in the folder; they are **not** used (the first three chapters were chosen in advance so the run
  is about 53 min and fits the budget; nothing was looked at to decide this beyond a 240p preview of the four chapters
  to confirm that this is a real seafloor deployment).
- **Where**: NOAA Open Data Dissemination (NODD) bucket of the NOAA Fisheries Southeast Fisheries Science Center
  (SEFSC), Google Cloud Storage `gs://nmfs_odp_sefsc/PEMD/VIDEO_DATA/GOM_REEF_FISH/Jack_Videos/sefis video/T60233001_A/`
  (public HTTP: `https://storage.googleapis.com/nmfs_odp_sefsc/PEMD/VIDEO_DATA/GOM_REEF_FISH/Jack_Videos/sefis%20video/T60233001_A/<file>`).
  The bucket carries the labels `dg_data_confidentiality: public`, `dg_data_source: public` (NOAA), and SEFSC is listed
  as a NODD data source at https://www.noaa.gov/nodd/datasets. Object upload date 2024-08-24.
- **Authors / title**: NOAA Fisheries, Southeast Fisheries Science Center, reef fish video survey (the folder has no
  title; SEFSC describes the same kind of data as its SEAMAP / SEFIS baited-video reef fish surveys, see
  https://github.com/SEFSC/SEAMAPD21). Station ID `T60233001`; position, depth and date are not stated in the folder.
- **Licence**: US federal government work of NOAA (public domain, 17 U.S.C. § 105), published through NOAA's open-data
  programme; NOAA requests attribution ("NOAA Fisheries Southeast Fisheries Science Center"). **Caveat for the record**:
  the files carry no per-file licence text; the basis for reuse is the public-domain status of NOAA data and the NODD
  publication, not a Creative Commons statement. If the owner wants a stricter standard than this, drop this run.
- **Not one of the clips already used**: not luderick (Ditria 2021), nautilus S1–S4, IMAS, DH1–DH11; none of the
  SEFSC videos has been used in this project (the SEAMAPD21 pages were only read for the licence/provenance question).

## Video
| file | size | duration | stream |
|---|---|---|---|
| GOPR1512.MP4 | 4,001,918,677 B | 1063.08 s | H.264 High, 1920×1080, 29.97 fps, 30 Mbit/s, GoPro |
| GP011512.MP4 | 4,001,919,900 B | 1063.06 s | same |
| GP021512.MP4 | 4,001,972,162 B | 1063.06 s | same |

Total 3189.2 s = **53.2 min** (45–75 min asked for). The first ≈ 5 s of the first chapter show the boat deck (the camera
is switched on before it is lowered); the rest is a static camera on a sandy, green-water seabed with sporadic fish.
SHA-256 of the three originals: see `sha256.txt` in this folder.

## Preparation (no model calls)
The originals (4 GB each; the disk cannot hold all three plus the run) were downloaded one by one, converted with the
same ffmpeg line as the pipeline's own ingest (`fps=5,scale='min(1920,iw)':-2`, libx264 veryfast, crf 20, no audio), the
original deleted, and the three 5 fps parts joined by stream copy into `data_long/sefsc1/sefsc1_5fps.mp4` (git-ignored,
not committed). The pipeline then re-encodes this file once more at 5 fps as it does for every input (frame timing
unchanged; one extra generation of h264 at crf 20). Script: `prep_sefsc1.sh` in this folder.

## Run (planned, exactly)
```
cd ~/meta-fish
FISH_BUDGET=<ledger total + 40> setsid nohup python3 fishcount/pipeline.py data_long/sefsc1/sefsc1_5fps.mp4 \
  --id LONG1 --no-scout --prompts fish --discover --zoom --max-usd 8 > report/paper/data/long_video/run.log 2>&1 &
```
- Settings identical to the held-out discovery evaluation (`--no-scout --prompts fish --discover --zoom`; audits on,
  low-light auto), frozen code at commit `78649bb`. The video is cut automatically into equal back-to-back segments
  of ≤ 600 s (expected: 6 segments of about 532 s each, 2,660 frames).
- `--max-usd 8` is per segment. `FISH_BUDGET` = total ledger at launch + $40 (the guard compares the whole ledger, which
  another agent may also add a few small calls to). Hard ceiling for this run: $40; if a segment would pass it the run is
  stopped and reported, the budget is not raised.
- Prediction written before the run (from `report/long_video.md`: about $0.0018 per frame, 18,000 frames/h): ≈ $27 for
  16,000 frames (53 min at 5 fps) and ≈ 6.7 h sequential. One run, reported whatever it shows; no code change on this
  video.
- **Disk housekeeping (not a code change)**: the pipeline leaves large intermediates in every segment's run folder (the
  reversed clip `clip_rev.mp4` and the zoom-tile videos `tile_*.mp4`, hundreds of MB each at this resolution), and the
  disk has about 13 GB free. A small detached script (`janitor_long1.sh` in this folder) deletes only those files, and
  the segment cut `seg<k>.mp4`, from a segment folder after its `status.json` says `done`, and deletes the 2.5 GB source
  proxy after segment 1 is done (the run keeps its own `full_5fps.mp4` until the end). Counts, tracks, evidence frames,
  `clip.mp4` and `annotated.mp4` are untouched. Everything deleted can be regenerated from the cache (replay) at no cost.
- Ground truth: none. This is a cost / time / robustness measurement and a MaxN-per-taxon list for the reviewer's queue,
  not an accuracy evaluation.

## Attempt 1 crashed (out of memory) — rendering fix, no change to counting
- Launched 2026-11-03 04:16 UTC at `1a50ab7` (= `78649bb` code). Segment 1 finished every model call, the counts and
  the evidence frames (14 live calls, $2.18, `runs/LONG1__S1/result.json`), then the process was killed by the kernel
  OOM killer at 04:49 UTC while drawing the annotated video (python3 at 9.4 GB resident on a 12 GB server; kernel log).
- Cause: `render.annotate()` loaded every frame of the segment into memory at once (`video.frames(clip, range(n))`,
  2,658 frames × ~6 MB at 1080p). Clips of 12–53 s never reached this.
- Fix (commit after `1a50ab7`): stream the frames with one sequential `cv2.VideoCapture`. Drawing only; nothing that
  decides a count changed. Checked: the replayed s004 annotated video is identical frame by frame (60/60 frames,
  mean absolute pixel difference 0) to `demo/runs/mg2_s004/annotated.mp4`; 50 unit tests pass.
- Attempt 2 uses the same command and settings. Segment 1's model answers come from the cache (no new charge); the
  $40 ceiling counts attempt 1's $2.18 (FISH_BUDGET = ledger total + $38). Run under a user systemd unit with
  `MemoryMax=8G` so a repeat would stop only this run.

## Attempt 2 stopped at its 8 GB memory cap — reversal fix, no change to counting
- Attempt 2 (`reef-long1b`, MemoryMax=8G) replayed segment 1 from the cache and was stopped by its own cgroup cap
  (systemd `Result: oom-kill`, peak 8 G; no global OOM, nothing else killed) at "second look: backfill ['person']".
- Cause: `video.reverse()` uses ffmpeg's `reverse` filter, which buffers every decoded frame (2,658 × 1080p yuv420
  ≈ 8.3 GB). Attempt 1 got through this step only by swapping.
- Fix: clips over 900 frames are reversed in 600-frame chunks joined last-first (clips up to 900 frames keep the old
  single command, so every existing run and cache entry is unchanged). Checked on s004 with a forced 20-frame chunk:
  60/60 frames, reversed order, mean absolute difference to the single-command reversal 0.38 (re-encoding noise),
  fps 5.0; unit tests pass. Segment 1's reversed clip now differs byte-wise, so its reversed SAM pass is paid again.
- Attempt 3: same command and settings, run with `memcap --bg` (MemoryMax 8G); ceiling still $40 including attempts 1–2.

## Result (attempt 3, finished 2026-11-03 09:05 UTC = 04:05 ET)
- All six segments done; merged run `runs/LONG1/` (run folders are git-ignored; every model answer is in `cache/`).
- Completed attempt: **$15.082**, 68 live + 11 cached calls, 12,546 s (3.5 h) wall clock, segments run one after another.

| segment | start (s) | frames | wall clock (s) | live / cached calls | billed | MaxN |
|---|---|---|---|---|---|---|
| S1 | 0.0 | 2,658 | 627 | 4 / 11 | $0.544 | fish (unidentified) 5, human 3, person (unidentified) 1 |
| S2 | 531.6 | 2,658 | 3,404 | 17 / 0 | $5.883 | fish (unidentified) 8 |
| S3 | 1063.2 | 2,658 | 2,202 | 14 / 0 | $2.698 | fish (unidentified) 3 |
| S4 | 1594.8 | 2,658 | 2,343 | 11 / 0 | $2.690 | fish (unidentified) 2 |
| S5 | 2126.4 | 2,658 | 1,565 | 11 / 0 | $1.632 | fish (unidentified) 3, jack 1 |
| S6 | 2658.0 | 2,655 | 1,405 | 11 / 0 | $1.636 | fish (unidentified) 5 |

- Merged MaxN: fish (unidentified) 8 @ 546.0 s, human 3 @ 22.6 s, jack 1 @ 2133.4 s, person (unidentified) 1 @ 69.4 s.
- All three attempts on this video: $17.27 (attempts 1–2 $2.183 + attempt 3 $15.082). Per hour of video: about $17
  (attempt 3 alone) or $19.5 (all attempts); the 40-s extrapolation in `report/long_video.md` said about $30 and 7.5 h.
- **The first ~2 minutes are on the boat deck**, not underwater: the human tracks run from 0 to 117.8 s. The "human"
  count (3) is the crew. "person (unidentified)" (track S1:d0rev:4, 3 frames at 69.4–71.0 s, box 1596–1660 × 349–571,
  Spark 0.65 "silhouette behind trap") was checked by eye on its evidence thumbnails: a crew member standing behind
  a trap on deck, i.e. a real person under a second name (name split), not an animal mistaken for a person.
  One "fish" track (S1:p0:0, 10.8–111.0 s, Spark 0.95 "Clear silvery fish in deck trap") is a fish in a trap on deck.
- Audit: 116 tracks, 35 judged not a target by Spark (e.g. "Metal boat structure, no bird"), 81 kept; species words
  from Spark among kept tracks: unknown 71, human 6, flatfish 2, snail 1, jack 1.
- Not done: no ground truth exists for this video, so none of these counts is scored. Deck frames are not shown in
  the paper, figures or demo.

