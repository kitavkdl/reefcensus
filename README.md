# reefcensus — count what you asked for, find what you didn't

Say what to count; get per-species MaxN and time of first arrival **with an evidence frame behind every number**,
and a short queue of uncertain tracks for a human to confirm. Built during the Meta AI hackathon (Oct 26 – Nov 4, 2026).

- **SAM 3.1** (Meta Model API) tracks generic categories ("fish", "shark") through the video — no training.
- **Muse Spark** looks at a contact sheet and proposes what to track and where faint animals hide (zoom tiles),
  then audits every track crop (species, is-it-really-a-fish, confidence). Low-confidence tracks go to a human.
- **Discovery** (`--discover`): SAM finds nothing for a vague word like "animal" — it only sees what you name.
  So Spark looks for living things the request did *not* ask about (and indirect signs such as sediment puffs),
  names each with plain nouns, and SAM tries them in turn (word ladder) until one tracks.
- **Closer look**: when Spark names a small animal and a 2x2-cell zoom still finds nothing, the one cell Spark pointed
  at is blown up 3x, every word is tried and the one tracked longest wins (the first hit can be a false one), then
  that word on the reversed cell back-fills the start. Nautilus clip s002: a ~40 px red crustacean, 0 -> 60/60 frames.
- **One animal, two boxes**: separate passes (whole frame, reversed clip, zoom tiles) can box the same shrimp twice
  (body only and body with legs). Masks find the candidates (one mask lying >=80% inside another); Spark is shown both
  outlines and decides "same animal or two?" — masks alone can't, because SAM sometimes draws one mask over two
  animals and a zoom tile then finds the rear one on its own. Duplicates are removed before MaxN is taken.
- All API calls are cached by content hash and metered against a budget (`FISH_BUDGET`, default $1).
- SAM masks are decoded by a small C port of `meta_sam_parser`'s one_bit codec (`fishcount/_maskdec.c`, built with
  `cc` on first use; ~1 ms a mask instead of ~1 s). Without a C compiler it falls back to `meta_sam_parser`.
  `python3 spikes/maskcheck.py` checks it against the reference on every cached SAM output.

```
pip install -r requirements.txt     # Meta API key in ~/.config/meta-api/key
python3 fishcount/pipeline.py <video> [--discover] [--zoom] [--offline] [--no-scout] [--no-audit]
python3 fishcount/evaluate.py            # raw SAM 'fish': recall/precision/MaxN error vs. luderick ground truth
python3 fishcount/evaluate_pipeline.py   # the same next to the full pipeline (runs eval_<clip>)
python3 web/server.py                    # review screen on http://127.0.0.1:8793
```

The review screen plays the annotated clip (blue = asked for, orange = found without being asked) over a per-species
count strip on the same timeline, shows each MaxN as a tally with its evidence frame, the second-look log, and a queue
of low-confidence tracks to confirm, rename or remove (counts and the CSV are recomputed from your edits).
New runs replay saved API answers for free unless "Allow paid API calls" is ticked (capped at $2 a run).

## How well it counts (measured)
Six luderick clips with human boxes (Ditria et al. 2021), 319 annotated frames, IoU >= 0.3. MaxN over the annotated
frames only, for both columns. Measured 11/2 (`fishcount/evaluate_pipeline.py`).

| clip | annotated frames | SAM "fish" alone: recall / precision / MaxN true→counted | full pipeline: recall / precision / MaxN true→counted | tracks sent to a human |
|---|---|---|---|---|
| 20190618_9 | 44 | 98% / 72% / 9→10 | 94% / 72% / 9→8 | 6 of 14 |
| 20190709_14 | 126 | 100% / 72% / 2→2 | 100% / 72% / 2→2 | 1 of 3 |
| 20190618_3 | 58 | 100% / 98% / 2→3 | 100% / 98% / 2→3 | 2 of 3 |
| 20190710_4 | 40 | 82% / 100% / 2→1 | 82% / 100% / 2→1 | 0 of 1 |
| 20190709_13 | 40 | 100% / 100% / 2→2 | 100% / 100% / 2→2 | 1 of 3 |
| 20190709_4 | 11 | 100% / 71% / 2→3 | 100% / 77% / 2→2 | 3 of 3 |
| **all** | 319 | **97.4% / 78.7%**, MaxN off by 1 on 4 of 6 | **95.9% / 79.3%**, MaxN off by 1 on 3 of 6 | 13 of 27 |

- Precision is a floor: one crop from each of 6 "false-positive" tracks (of 12) was looked at, and all 6 are real
  luderick that the annotators left unboxed or boxed elsewhere.
- MaxN is never more than 1 off on these clips, in either direction. The pipeline does not replace the reviewer:
  about half the tracks go to the human queue, and the counts are what a reviewer confirms, not a final census.

## Data credits
- Ditria, E.M. et al. (2021) luderick-seagrass dataset, CC BY 4.0 — github.com/globalwetlands/luderick-seagrass
- Monk, J., Barrett, N., Langlois, T. (2024) Curated underwater video highlights of marine protected areas,
  IMAS, University of Tasmania, CC BY 4.0
- Barord, G.J. et al. (2014) Comparative population assessments of Nautilus sp., PLOS ONE 9(6): e100799,
  supplementary videos S1–S4, CC BY 4.0 (via Wikimedia Commons)

## License
MIT (code). Videos and datasets keep their own licenses above.
