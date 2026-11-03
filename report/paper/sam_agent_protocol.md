# SAM 3 Agent-style loop as a discovery baseline (protocol, fixed before any paid call)

Written 2026-11-03 before any loop output was seen. Results go into the paper as they come out, poor or not.
No prompt, threshold or code change after seeing them; a bug found afterwards is reported, not fixed in these numbers.

## Question
SAM 3's paper describes "SAM 3 Agent": an MLLM proposes noun phrases, calls SAM 3, looks at the returned masks and
revises the phrase (Carion et al., 2026, §6). Our related-work section calls our loop an application of that known
pattern. Does the plain pattern — propose, segment, look, revise — already find what our discovery pipeline finds,
without the word ladder, zoom passes, reversed passes, motion residual and audits?

## Design (`report/paper/scripts/sam_agent.py`)
- Clips: the 15 discovery clips (DH1–DH11 held-out, s001–s004 development), the 5 fps clip each final run tracked
  (`runs/vswap_<clip>/clip.mp4`; s001 is the brightened clip).
- Round 1 proposals: the final run's own discovery reply (`runs/vswap_<clip>/discover.json`, already paid): up to 4
  things, each starting with its first search word — the same start as the pipeline, so the comparison is about
  what happens after the first look.
- Each round: SAM 3.1 (text prompt, full frame, forward only) on every open phrase. Then **one** Spark 1.3 call per clip
  sees (a) the same 6-frame contact sheet as discovery and (b) a result sheet: per phrase one row of the three frames
  with the most boxes (at least 5 frames apart), boxes drawn, or "found nothing". Spark answers per phrase
  keep / revise (with one new plain noun) / drop. Revised phrases go to the next round; earlier tries of the same
  thing are listed in the prompt. **At most 3 SAM rounds per thing.** Same settings as the pipeline (effort low,
  max_tokens 6000, reply check with one retry).
- Output per clip: the kept phrases, each with SAM's frames, tracks and MaxN (largest box count in one frame).
  No audit, no queue — this is the baseline, not a variant of our pipeline.

## Measures (fixed now)
1. **Taxa reached** (as metric 1 of the held-out protocols, but "kept" in place of "counted"): reference taxa
   (committed lists `discovery_heldout*/reference_*.md`; s001–s004 Table 2's lists) with a kept phrase of the right
   coarse group. Graded **blind** by a fresh grader that sees, per clip, the reference lists and two unlabelled lists
   in random order: the pipeline's counted non-fish labels and the loop's kept phrases. Held-out and development
   reported apart.
2. **Agreement with the pipeline**: pipeline counted non-fish tracks overlapped by some kept-phrase box (IoU ≥ 0.3 in
   ≥ 3 frames — the overlap rule of `fixed_vocab.py`), and kept phrases whose boxes overlap no pipeline track in any
   frame ("loose"). Loose phrases are not judged here; if a label-free person judgement is made later it is reported
   as an addition, with crops chosen by rule (the frame with most boxes, up to 3 boxes per phrase).
3. **Rounds and calls**: phrases revised, kept after a revision, dropped; SAM and Spark calls per clip.
4. **Cost**: total and per clip (SAM calls already in the cache cost nothing and are counted as cached).

## Budget and stop rule
Estimated maximum $2.4 (≤ 12 SAM calls × $0.012 + 2 Spark calls per clip). The script keeps its own running total
from its own calls (thread spend, independent of the hour-long run sharing the ledger) and stops before a call that
would take it past **$3.00**; a stop is reported with the clips finished. A dry pass (no live call) runs first to
check that the round-1 SAM calls are cached and the sheets render.

## Limits stated in advance
Text prompts only, forward only, full frame: the published SAM 3 Agent's exact prompts and tool set are not
reproduced; this is the pattern, with our models. Round 1 is shared with the pipeline by design.
