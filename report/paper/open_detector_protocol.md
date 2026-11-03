# Open-vocabulary detector baseline (protocol, fixed before the detector is run)

Written 2026-11-03 before any detector output was seen. Results go into the paper as they come out.
No query, threshold or code change after seeing them; a bug found afterwards is reported, not fixed in these numbers.

## Question
Reviewers asked whether an off-the-shelf open-vocabulary detector, given a broad word, already does what discovery
does. The word ladder of the paper is SAM 3.1 with basic-level nouns; "animal" gives SAM 0 frames (§ What the
segmenter responds to). An open-vocabulary detector is the obvious alternative that needs no VLM.

## Setup (`report/paper/scripts/open_detector.py`, $0, CPU)
- Detector: OWLv2, `google/owlv2-base-patch16-ensemble` (Hugging Face transformers 5.22.1, torch 2.15 CPU), default
  processor (pads to a square, 960 px). One pass per frame with 17 queries: "animal" + the 16 fixed words of
  `fixed_vocab.py` (fish, shark, ray, eel, crab, shrimp, lobster, octopus, squid, snail, shell, starfish, jellyfish,
  sea urchin, sea cucumber, worm).
- Clips: the 15 discovery clips (DH1–DH11 held-out, s001–s004 development), every frame of the 5 fps clip that each
  final run tracked (`runs/vswap_<clip>/clip.mp4`, the offline replay of the final run; s001 is the brightened clip).
- Score threshold: **0.2 primary**; 0.1 and 0.3 reported as sensitivity. Boxes ≥ 0.05 are stored.
- No tracking, no VLM: the detector is per frame, as it would be used without the rest of the pipeline.

## Measures (fixed now)
1. **Pipeline discoveries found**: counted (not queued) non-fish pipeline tracks for which some detector box (any
   query) has IoU ≥ 0.3 with the track's box in ≥ 3 frames — the overlap rule of `fixed_vocab.py`. Also reported:
   how many of these overlaps carry a word of the track's coarse group ("right word"), and how many come only from
   "animal".
2. **Loose boxes**: non-fish-query boxes that overlap no pipeline track box in their frame (IoU < 0.3) — what a person
   would have to check if the detector were the discovery step. Reported per clip; whether they are animals is not
   judged here (it would need a label-free crop judgement like metric 3; if one is made later it is reported as an
   addition, with the crops chosen by a fixed rule: the 3 highest-scoring loose boxes per clip).
3. **Frames with an "animal" box**, per clip.
4. **CPU time per frame** (6-core server shared with other jobs; reported as measured, `DET_THREADS=2`).

## Limits stated in advance
One detector, base size, CPU; no fine-tuning. Grounding DINO is not run (one detector keeps memory inside the cap
next to the hour-long run). Measure 1 uses the pipeline's own tracks as the reference, so it measures agreement with
what the pipeline counted, not recall against the person's lists; misses of the pipeline that the detector finds
appear only in measure 2.
