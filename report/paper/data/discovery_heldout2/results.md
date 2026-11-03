# DH6–DH11 results (frozen code cbaf59b; reference lists 1fb89e4/53d4342; runs 87df5c9; judgements 3897662 + this commit)

Reported as the protocol fixes them, whatever they show. Reference list (primary, human markers): one taxon-in-clip,
DH11 bug/worm-like; DH6–DH10 none.

| Metric | Pipeline (Spark names → SAM tracks → checks) | Fixed-vocabulary baseline (SAM, 16 words) |
|---|---|---|
| 1. Discovery recall | **1/1** (DH11 'scavenging amphipod crustacean', counted; amphipod is in the bug/worm group by the pre-run scoring note) | — |
| 2. Named-only recall | 1/1 | — |
| 3. False discoveries (counted non-fish rows, crop not an animal) | **0/2** (DH7 crab → judged "crab"; DH11 amphipod → judged "bug/worm or crustacean") | — |
| 4. Baseline recall | — | 1/1 (DH11 'worm' track overlaps the counted amphipod track; 'worm' is a right word for the group) |
| 5. Baseline false labels (non-fish-word tracks, crop not an animal) | — | 0 of 6 judged crops (DH7 starfish ×2, crab ×3; DH11 worm ×1); not judged: 9 more DH7 crab-word tracks beyond the 3 longest. On the fish-only clips DH6/DH8 neither method produced a non-fish row: **0 vs 0** |
| 6. Queue / cost | 8 queued tracks (DH6 0, DH7 2, DH8 5, DH9 1, DH10 0, DH11 0); $0.863 ($0.04–0.23 per clip) | $0.996 (83 SAM calls) |

Also reported (not in the protocol metrics):
- **DH7: the pipeline counted crabs (MaxN 3, at 6.8 s / frame 34) that neither human marker listed** on the four-frame
  sheet (frames 0/20/40/59). The label-free judge called the evidence crop "a crab", and the source text names
  lithodid crabs for this video. By protocol these do not enter the recall (not on the reference list) and they are
  not false discoveries (metric 3). The four-frame sheet is the limitation: the pipeline sees all 60 frames.
- Spark named three other things that did not end in a counted row: DH6 'giant clam beside bait', DH10 'pale branching
  worm', DH11 'colonial tube worms'. None is counted, so none is in metric 3.
- Baseline wrong words: on DH7 'starfish' tracks overlap the counted crab track (a crab called starfish), and one
  'shark' track appears on DH7 (judged "fish-like"; no human saw a fish on that sheet). 'shark' on DH6/DH8 is a fish
  word, so it is outside metric 5. Baseline crop 9 (DH8 shark) was "too blurry to tell".
- `--zoom` has no effect with `--no-scout` (as stated in amendment 2).
- Small denominators: one reference taxon. This set mainly tests false discoveries on fish-only and empty clips,
  where the pipeline produced none.
