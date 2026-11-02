# Held-out luderick evaluation — protocol (written and committed before any held-out run)

Written 2026-11-02 09:3x UTC, after the second independent review asked for data not used in development.

- **Clips**: every annotated video in our copy of the luderick archive (30 videos, PANGAEA doi:10.1594/PANGAEA.926930)
  that the six development clips did not use: 24 clips, 6–62 frames at 5 fps, 523 boxes on 445 annotated frames,
  MaxN 1–2. Chosen by rule (all remaining), not by looking at them. They are shorter and sparser than the
  development clips (which were the longest and busiest), so this tests transfer to the same site and camera
  set-up, not to new habitats.
- **Preparation**: identical to the development clips (`report/paper/scripts/prep_heldout.py`).
- **Code**: frozen at the commit that adds this file (pipeline unchanged since `3fd3472`, V6). Settings as in the
  luderick evaluation: request "fish", no scout, no discovery, no zoom, audits on.
  Command: `FISH_BUDGET=<ledger+2> python3 fishcount/evaluate_pipeline.py --run --tag held1 --manifest manifest_heldout.json`.
- **Methods compared** (all fixed before the run): SAM 3.1 "fish" alone; merge-and-stitch with the minimum track
  length k = 4 chosen on the development clips; the full pipeline (V6), with the queue accepted and with queued
  rejected tracks removed.
- **Metrics**: as Table 1 (box recall and precision at IoU 0.3 on annotated frames, MaxN exact / within ±1, queue size).
- **One run, reported whatever it shows.** No prompt, threshold or code change after seeing held-out results; if a
  bug is found it is reported, not fixed in these numbers.
