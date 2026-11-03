# Muse Wonder in Spark's place — results (protocol `../../vlm_swap_protocol.md`, run 2026-11-03)

Shadow replay of the 15 discovery clips' final runs; 101 questions, each answered by both models on the same sheet.
Attempt 1 (`attempt1_calls_*.jsonl`) lost 26 Wonder calls to HTTP 503 `service_overloaded` and 16 (all s004) to the
shared ledger budget while the LONG1 run was spending; attempt 2 retried 503s (transport errors, not replies) and
finished all 101, 0 unreadable. Scorer `scripts/vlm_swap_score.py` → `summary.json`.

## Measure 1 — discovery names (blind grading)
A fresh grader (Claude Sonnet subagent, read-only) graded `blind_names.md` against the committed reference lists
without the key; unblinded afterwards with `blind_key.json`.

| | Spark 1.3 | Wonder 1.0 |
|---|---|---|
| Held-out DH1–DH11 named-only recall, strict (crab and shrimp/lobster separate) | **5/5** | 4/5 (DH3 crab: "squat lobster" only) |
| same, lenient (one crustacean group) | 5/5 | 5/5 |
| Development s001–s004 recall (7 taxa as Table 3) | 7/7 | 7/7 |
| Names with no support in any reference list, 15 clips (lenient) | **5** | 12 |
| of which not animals | 0 | 4 (bait carcass, bacterial mat ×2, seaweed) |

Spark's unsupported names: DH5 shrimp, DH6 giant clam, DH7 crab, DH10 worm, s003 large striped shrimp. Note: DH7
"crab" is unsupported by the four-frame reference lists but the pipeline's counted DH7 crab was judged "animal — crab"
from its label-free crop (metric 3). Wonder's: DH2 bait carcass, DH4 seal, DH5 jellyfish and shrimp, DH6 coral and
seaweed, DH7 sea turtle, DH8 coral and seaweed, DH9 bacterial mat, DH10 bacterial mat and worm (+ DH11 "mussels or
clams", "anemone or hydroid" under the strict reading, supported only by the agreement-only list).

## Measure 2 — same tiles, same verdict? (boolean field per tile; confidence thresholds not re-applied)
| kind | agree | Wonder no / Spark yes | Wonder yes / Spark no |
|---|---|---|---|
| audit (A1) | 106/121 | 14 | 1 |
| verify (peak check) | 71/77 | 4 | 2 |
| confirm (motion track) | 12/15 | 2 | 1 |
| motion look | 88/111 | 17 | 6 |
| pair (same animal) | 11/12 | 1 | 0 |

## Measure 3 — rows a person judged "animal" (7 rows, all judged animals)
Wonder would have rejected tiles on 3 of 7: DH3 spider crab (audit T3, T6, T7, T8 and verify D1, D2 — the person:
"animal, certain"), DH2 crab (3 audit tiles), DH2 sea anemone (the same 3 audit tiles; DH2's audit call covers both
names). 0 rejections on DH1 crab, DH5 cusk-eel, DH7 crab, DH11 amphipod. Tile level only; the run is not recomputed.

## Measure 4 — cost and time
Wonder $2.33 for 101 calls by reply usage, **$0.023 per call** (Spark's ledger mean ≈ $0.0042, about 5.5×);
4.7 s mean, 61.6 s max per call (Spark's times were not logged per call).

## Reading
On the same questions the larger model is more conservative: it says "no" to tiles Spark kept, including true
animals a person confirmed (DH3 spider crab), names more things that are not there (12 vs 5 unsupported, 4 of them
non-animals), and costs about 5.5× more. Nothing here argues for swapping Spark out.
