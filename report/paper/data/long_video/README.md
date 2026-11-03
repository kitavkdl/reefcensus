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
