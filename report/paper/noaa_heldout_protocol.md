# Third held-out set: NOAA reef-fish survey clips (N1–N8) — protocol (written and committed before any clip is cut or seen)

Written 2026-11-04 (ET). Why: the held-out counting results (Tables 1c, 1d) come from one source, the luderick archive
(one estuary, one camera type), and the 53-min NOAA deployment (Table 3d) has no ground truth. This set asks: **on
survey footage from a fisheries agency, at stations never used, does the pipeline's fish MaxN match a hand count?**
It also records any non-fish row counted on these fish-survey clips (false discoveries).

## Selection (fixed before listing any file)
- **Where**: the same public NOAA Open Data Dissemination bucket as the 53-min run,
  `gs://nmfs_odp_sefsc/PEMD/VIDEO_DATA/GOM_REEF_FISH/Jack_Videos/sefis video/` (NOAA Fisheries Southeast Fisheries
  Science Center; US government work, public domain; attribution requested). The station folders are listed through
  the GCS JSON API (names and sizes only; no video opened while selecting).
- **Stations**: the sorted list of station folders, `T60233001_A` (the 53-min run) removed, shuffled with
  `random.Random(1105)`; stations are taken in that order.
- **File and window**: in each station, the first GoPro chapter (`GOPR*.MP4`, the largest file whose name starts with
  `GOPR`; the few-second start-up files are skipped by a 1 GB minimum). The window is **600.0–612.0 s** of that chapter:
  ten minutes after the camera is switched on, past the deck section and the descent (in the 53-min run the deck
  ended at 117.8 s). A station is skipped, and the next one taken, only if it has no such chapter or the chapter is
  shorter than 612 s or the window cannot be decoded; every skip is logged. The window is fixed by rule, not by
  looking: an empty window (no fish) stays in the set and counts as MaxN 0.
- **How many**: the first **8** stations that pass.
- Everything is done by `report/paper/scripts/prep_noaa_heldout.py`, which writes `data/noaa_heldout/clips.json`
  (station, file, URL, size, window, sha256 of the cut clip) and the skip log.

## Clips
- IDs N1–N8 in selection order. Two copies per clip: the pipeline input (12 s, H.264, width ≤ 1920, no audio, the
  pipeline re-encodes to 5 fps as for every other clip) and the hand-count copy (the same 12 s at the original frame
  rate). Clips are not committed (size); `clips.json` makes them reproducible.

## Reference (before any model call on these clips)
- **Hand count**, as Table 1d: Jiyul Ahn counts fish MaxN (the most fish visible at once) from the full-rate 12-s
  clips, no boxes, in a shuffled order (`random.Random(1106)`) under neutral names (`clip_a` …), key fixed before
  counting. Fish too faint to tell from the background are given separately (+n). Any non-fish animal seen is noted.
- The counts are committed (`data/noaa_heldout/handcount.md`) **before** the run. Claude does not look at the clips
  before the run beyond checking that each file decodes (frame count and duration).

## Run (one each, reported whatever it shows)
- **Code**: frozen at the commit that reverts `a912bc8` (the word-ladder change was dropped on 11/4, before any run of
  this set). Only the prep and scoring scripts may be added before the run; neither changes the pipeline.
- **When**: after the demo video is recorded (owner's decision, 11/4).
- **Settings**: the discovery settings of Table 2 and the 53-min run, on the final defaults:
  `python3 fishcount/pipeline.py <clip> --no-scout --prompts fish --discover --zoom --id N<k>_eval`.
- **Budget**: `FISH_BUDGET` = ledger total at start + $4 (expected about $2: 8 clips × $0.22–0.27).

## Scoring (fixed now)
1. **Fish MaxN**: the fish group's MaxN (same-frame total over every label in the fish group of `NAME_GROUPS`; the
   single label's MaxN when only one fish label exists) against the hand count of sure fish: exact, within ±1, Σ|err|.
   Also reported against sure + faint.
2. **Range**: as §4.7, from queue rejected to queue accepted; how many clips' ranges contain the hand count.
3. **False discoveries**: every counted non-fish row, shown to Jiyul Ahn afterwards as a label-free crop
   ("is this an animal?"); a row judged "not an animal" is a false discovery. Non-fish animals the hand count noted
   but the run did not count are reported as misses.
4. Cost and time per clip from the ledger and `status.json`.
- If fewer than 8 clips pass selection, the set is smaller and that is said. No clip is dropped after the run.
