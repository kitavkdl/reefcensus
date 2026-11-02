# Long videos: segment merge and one full-length run (measured 2026-11-02)

## What was run
Barord et al. 2014, S3 (CC BY 4.0), the whole supplementary video: 39.8 s, 199 frames at 5 fps. The four originals are
14, 58, 40 and 14 s long, so nothing from that paper exercises the 600 s split itself. The development clip used
everywhere else is the first 12 s (frames 0–59) of this video. Request "fish", discovery on, zoom on
(`--no-scout --prompts fish --discover --zoom`), both runs uncached, run at the same time.

| run | segments | MaxN counted | first arrival | queued tracks | live calls | billed | wall clock |
|---|---|---|---|---|---|---|---|
| 12 s development clip (frames 0–59, earlier) | 1 | chambered nautilus 3 | 0.0 s | — | — | — | — |
| whole video, one pass | 1 × 199 frames | **chambered nautilus 3** at 4.4 s (peak frame checked, 3 of 3 kept) | 0.0 s | 3 | 14 | $0.351 | 297 s |
| whole video, `--segment 20` | 100 + 99 frames | nautilus 1 at 0.0 s | 0.0 s | 8 | 45 | $0.717 | 489 s |

Spend for both: $1.068 (SAM 3.1 $0.975 = 91%, Muse Spark $0.093).

## What the forced split shows
- **The merge arithmetic is exact** (unit tests: merging a single segment reproduces all four demo runs' MaxN, peak
  frame, first arrival, curve and track counts; two segments lay the curves end to end; first arrival is offset by the
  segment start). The segment-20 run's merged MaxN equals its larger segment's MaxN, as designed.
- **But shorter segments counted fewer nautiluses**, for reasons inside each segment, not at the cut:
  - Segment 1 (0–20 s, which contains the 12 s development clip): SAM's "nautilus" pass held one ID for two animals;
    the zoom track of the second one was judged "shell of same nautilus" by the same-animal check and dropped, and a
    third track was called "striped shrimp" by the audit and "only tentacle, shell body outside box" by the second
    look. MaxN 1. The one-pass run on the whole 40 s got two separate SAM IDs plus a reversed-pass track, all three
    kept at frame 22.
  - Segment 2 (20–40 s): Spark named the animals "chambered nautilus clustered on bait". The pipeline only tries a
    discovered name itself as a SAM word when it has at most two words, so the word list was its other suggestions
    ("shell", "squid", "octopus"), which found nothing on the full frame; the 3× cells and motion boxes did track
    things, but all 6 tracks went to the person queue, so nothing was counted.
- So each segment is an independent discovery run with its own wording and its own SAM IDs; results on a 20 s
  segment can differ from the same frames inside a 40 s run. **Segments are therefore as long as the API allows
  (600 s); short segments are for testing only.** Not done yet: carrying a word that worked in one segment to the
  segments that did not find one (it would have tried "nautilus" in segment 2).

## Scaling to one hour (extrapolated, not run)
- SAM is billed per frame per pass ($0.20 per 1,000 frames) and was 91% of the spend. The one-pass run paid $0.351
  for 199 frames, about $0.0018 per frame, roughly 8 passes over the clip (words, reversed pass, zoom tiles, motion
  boxes). At the same rate, one hour at 5 fps (18,000 frames, six 600 s segments) is **about $30**; the real figure
  moves with how many words, tiles and motion boxes Spark asks for in each segment.
- Wall clock: 297 s for 40 s of video, about 7.5× real time with four SAM calls in parallel. If that holds, an hour
  of video takes about 7.5 hours with segments run one after another; segments are independent and could run in
  parallel, which would bring an hour down to roughly the time of one segment (an estimate, not measured; left as
  future work after the hackathon). No single 600 s SAM call has been made yet.
- Sampling at fewer frames per second would cut both in proportion (MaxN of slow animals at bait may tolerate it); not
  measured.

Runs: `runs/full_s003_once`, `runs/full_s003_seg20` (segments `__S1`, `__S2`); all API answers are in `cache/`, so
both replay for $0.
