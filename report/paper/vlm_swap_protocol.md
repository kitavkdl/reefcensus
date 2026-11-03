# Other-VLM comparison: Muse Wonder in Spark's place (protocol, fixed before any paid call)

Written 2026-11-03 before any Wonder reply was seen. Results go into the paper as they come out, poor or not.
No prompt, threshold or code change after seeing them.

## Why this model
The Meta Model API lists (GET /v1/models, 2026-11-03): muse-wonder-1.0, sam-3.1, muse-spark-1.1/1.2/1.3 (+ contributor),
muse-voice-transcribe-1.0, muse-image-1.0. **No Llama vision model is offered**, so the only other image-reading model
on the same API is Muse Wonder (Meta's top model; image input; $4.00 / $20.00 per 1M input / output tokens against
Spark's $1.25 / $4.25). The question is whether the larger, dearer model would change what the pipeline concludes.

## Design: shadow replay (`report/paper/scripts/vlm_swap.py`)
- Clips: the 15 discovery clips — held-out DH1–DH11 (primary) and development s001–s004 (reported apart).
- Each clip's final run is replayed **offline** with the current code (`--no-scout --prompts fish --discover --zoom`,
  low-light auto). Spark's cached answers drive every step; SAM is never called. A dry pass found every call cached:
  101 questions (audit 30, verify 29, discover 15, motion 14, confirm 9, pair 4).
- Every question is also sent, unchanged (same text, same images, same max_tokens 6000, reasoning effort "low", same
  reply check with one retry), to `muse-wonder-1.0`. Both replies, seconds and cost go to
  `report/paper/data/vlm_swap/calls_muse-wonder-1.0.jsonl`.
- What this does not measure: Wonder's own end-to-end run (its discovery names are not tracked by SAM, and later
  questions are the ones Spark's choices led to). It is a same-question comparison.

## Measures (fixed now)
1. **Named-only recall** (metric 2 of the held-out protocols) on DH1–DH11: reference taxa (primary lists already
   committed: `discovery_heldout*/reference_*.md`) named in the discovery reply. Both models' lists are graded again
   **blind** by a fresh grader that sees the reference lists and two unlabelled name lists per clip (order random), with
   the coarse-group rule of those protocols. s001–s004 against Table 2's person lists, reported apart.
2. **Agreement per question kind**: share of tiles on which Wonder's verdict, read by the pipeline's own parsing of
   that kind of reply, equals Spark's. Unreadable replies are counted as their own row, not as disagreement.
3. **Rows a person already judged**: for counted non-fish rows judged in metric 3 ("is this an animal", label-free),
   the number Wonder's verify / audit verdict would have dropped (judged animal) or kept (judged not an animal).
   Tile-level only; the run is not recomputed.
4. **Cost and time**: total and per-call cost, mean and maximum seconds per call, for each model (Spark's from its
   cached usage).

## Budget and stop rule
Pilot on DH1 first (6 questions) to measure Wonder's cost per call; if 101 calls extrapolate to ≤ $3 the rest runs at
once under `FISH_BUDGET=<ledger + 3>`; otherwise it stops and the owner is asked. A budget stop mid-run is reported
as such, with the clips finished.
