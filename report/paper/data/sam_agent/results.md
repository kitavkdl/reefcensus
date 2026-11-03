# SAM 3 Agent-style loop — results (protocol `../../sam_agent_protocol.md`, `2011ab9`, run 2026-11-03)

Propose (each final run's own discovery reply) -> SAM 3.1 text prompt, full frame, forward -> Spark sees the boxes ->
keep / revise / drop, at most 3 SAM rounds per thing. 15 discovery clips, one run, no change after seeing results.
Script total **$0.41** (SAM 56 calls, 41 already cached; Spark 29 calls). Per clip: `<clip>.json`, sheets
`<clip>_round<k>.jpg`, `summary.json` (`--score`).

## Measure 1 — taxa reached (blind grading)
Fresh grader (Claude Sonnet subagent, read-only) on `blind_names.md` (pipeline counted non-fish labels vs the loop's
kept things, A/B order random per clip), unblinded with `blind_key.json` and tallied per method.

| | pipeline (counted) | agent loop (kept) |
|---|---|---|
| Held-out DH1–DH11, strict (5 taxa) | **4 of 5** | 3 of 5 |
| same, lenient (4) | 4 of 4 | 3 of 4 |
| Development s001–s004 (7 taxa) | **7 of 7** (Table 3)* | 5 of 7 |
| Entries supported by no reference list | 1 (DH7 crab) | 1 (DH7 crab) |

\* The blind sheet's pipeline list for s004 lacked "hagfish": the shared helper `counted_nonfish` (from
`open_detector.py`) drops labels whose coarse group is fish, and "hagfish" maps to fish. The pipeline counts hagfish 1
(Table 2, `runs/vswap_s004/result.json`), so 7 of 7 stands; the grader's raw tally for that list was 6 of 7.

What the loop missed and why (from `<clip>.json`):
- **DH3 spider crab**: 'crab', 'spider', 'crayfish' all 0 frames on the full frame (the pipeline reaches it with
  "crab" in a 3× cell). All four DH3 things ended with 0 frames after 3 tries each.
- **s002 small red crab**: 'crab', 'lobster', 'bug' all 0 (pipeline: "shrimp" in a 3× cell, renamed by A1).
- **s003 nautilus**: 'shell', 'snail', 'octopus' all 0 — Spark's revisions never tried "nautilus", which tracks 33
  frames forward on this clip in the pipeline (the word ladder tries the discovery reply's listed words in order).
- s001: the loop keeps 'shell' (9 frames, 1 nautilus); the pipeline counts 4 through motion box prompts.

## Measure 2 — agreement with the pipeline
Pipeline counted non-fish tracks overlapped by a kept-phrase box (IoU ≥ 0.3 in ≥ 3 frames): **18 of 45** (held-out
6 of 15, development 12 of 30). Kept phrases overlapping no pipeline track: **0** (nothing to judge).

## Measure 3 — rounds
25 things proposed; 16 were revised at least once; **2 kept after a revision** (DH2 sea anemone as 'coral' on the
third try, DH11 amphipod as 'bug' on the third try); 2 dropped (DH2 worm, DH8 shark); 10 ended with three 0-frame tries.

## Measure 4 — cost
$0.41 in all ($0.32 held-out, $0.09 development); most first-round phrases were already cached from the final runs.

## Reading
Visual feedback alone did not replace the pipeline's other routes: every miss is an animal the pipeline reaches by
zooming into a cell, by the reversed or listed word, or by a box prompt from motion. Revisions rarely helped (2 of 16)
and once moved away from the word that works ('octopus' instead of 'nautilus'). It counted nothing that is not an
animal, as the pipeline does not.
