# Second held-out discovery set DH6–DH11 — clips, sheets, what happens next

Protocol: `../../discovery_heldout2_protocol.md` (commits b510908, amendment 1543fb7). Selection log: `candidates.md`
(committed before any download, 262b087). Raw files: `spikes/DHB/raw/` (git-ignored; URLs and sha256 in `clips.json`),
clips: `spikes/DHB/clips/DH<n>.mp4` (`report/paper/scripts/prep_discovery_heldout2.py`).

The queries gave **6 eligible clips (4 with a non-fish animal named in the source text, 2 fish-only)**, short of the
6 + 2 quota; per amendment 1 the set is what the queries give.

| ID | Source (all PLOS ONE supplementary video, Wikimedia Commons copy) | Licence | File length | 12 s window from | Size | Text-named animals |
|---|---|---|---|---|---|---|
| DH6 | Werry et al. 2014, e83249 S2 — BRUV, Lord Howe Island | CC BY 4.0 | 37.6 s | 12.8 s | 640×480 | tiger shark (fish-only) |
| DH7 | Niemann et al. 2013, e74894 S1 — stationary seafloor camera, cold seep, time-lapse 2 images/h | CC BY 2.5 | 57.3 s | 22.7 s | 1280×720 | lithodid crabs |
| DH8 | Oliver et al. 2011, e14755 S4 — remote video camera at a cleaning station | CC BY 2.5 | 26.1 s | 7.0 s | 640×480 | thresher sharks (fish-only) |
| DH9 | Sturdivant, Diaz & Cutter 2012, e34539 S4 — Wormcam sediment-profile camera, hourly images | CC BY 2.5 | 31.1 s | 9.6 s | 272×360 | holothurian, worm, goby, juvenile crab, isopod |
| DH10 | same study, S1 — Wormcam, hourly images | CC BY 2.5 | 28.6 s | 8.3 s | 362×480 | blue crab, American eel, worm, mysid shrimp, sea cucumber, fish |
| DH11 | Cuvelier et al. 2014, e96924 S4 — Grotto vent, 2186 m (observatory study) | CC BY 4.0 | 22.5 s | 5.2 s | 426×240 | polynoid polychaete, tubeworms |

The "text-named" column is from the source pages; it is **not** the reference list and is not shown to markers.

## Sheets for the reference lists (label-free)
- `sheet_DH6-11.jpg` — all six clips, one row each, frames 0/20/40/59 (for a second person).
- `sheet_DH6.jpg` … `sheet_DH11.jpg` — the same frames, larger, one clip per sheet (same format as DH1–DH5).
- Question for every marker, nothing else: "apart from fish, what animal shapes do you see?" — coarse groups and a
  rough count, circled or listed per clip. Bait/carcasses are not animals to find. Each list is committed before the run.

## After the reference lists are committed (paid; budget)
1. `FISH_BUDGET=<ledger+2.5> python3 fishcount/pipeline.py spikes/DHB/clips/DH<n>.mp4 --id DH<n>_eval --no-scout --prompts fish --discover --zoom` for n = 6…11
2. `python3 report/paper/scripts/fixed_vocab_heldout2.py --dry` (check), then `FISH_BUDGET=<ledger+1.6> python3 report/paper/scripts/fixed_vocab_heldout2.py`
3. `python3 report/paper/scripts/score_discovery_heldout2.py` → `runs_summary.json`, `crops_sheet.jpg` (metric 3 judge sheet);
   baseline crops in `fixed_vocab/crops_sheet.jpg` (metrics 4–5, key in `fixed_vocab/crops_key.json`, not shown to the judge).
Expected cost ≈ $1.3 (pipeline, DH1–DH5 mean $0.21/clip) + $1.08 (baseline, 90 SAM calls) ≈ $2.4.
