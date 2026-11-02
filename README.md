# reefcensus — count what you asked for, find what you didn't

Say what to count; get per-species MaxN and time of first arrival **with an evidence frame behind every number**,
and a short queue of uncertain tracks for a human to confirm. Built during the Meta AI hackathon (Oct 26 – Nov 4, 2026).

Technical report with every measurement and what it changed in the design: [report/README.md](report/README.md).

- **SAM 3.1** (Meta Model API) tracks generic categories ("fish", "shark") through the video — no training.
- **Muse Spark** looks at a contact sheet and proposes what to track and where faint animals hide (zoom tiles),
  then audits every track crop (species, is-it-really-a-fish, confidence). Low-confidence tracks go to a human.
- **Discovery** (`--discover`): SAM only sees what you name: asked for "animal", it found nothing on 29 of the 39 clips we tested, including a seagrass clip where "fish" finds 10.
  So Spark looks for living things the request did *not* ask about (and indirect signs such as sediment puffs),
  names each with plain nouns, and SAM tries them in turn (word ladder) until one tracks.
- **Closer look**: when Spark names a small animal and a 2x2-cell zoom still finds nothing, the one cell Spark pointed
  at is blown up 3x, every word is tried and the one tracked longest wins (the first hit can be a false one), then
  that word on the reversed cell back-fills the start. Nautilus clip s002: a ~40 px red crustacean, 0 -> 60/60 frames.
- **One animal, two boxes**: separate passes (whole frame, reversed clip, zoom tiles) can box the same shrimp twice
  (body only and body with legs). Masks find the candidates (one mask lying >=80% inside another); Spark is shown both
  outlines and decides "same animal or two?" — masks alone can't, because SAM sometimes draws one mask over two
  animals and a zoom tile then finds the rear one on its own. Duplicates are removed before MaxN is taken.
- **Motion look** (no word at all): a BRUV camera sits still, so pixels that differ from the clip's median frame and
  keep changing are "look here" hints (`fishcount/motion.py`, no model). Spots outside every box go to Spark as one
  sheet, each shown early / middle / late at the same zoom — an animal keeps its shape, a sediment cloud spreads. The
  ones Spark calls animals go to SAM 3.1 as a **box prompt with no word**, and SAM tracks the animal both ways through
  the clip. Nautilus clip s004: a shrimp at the bottom edge that no word, tile or reversed pass ever tracked, 55/60
  frames from one box. A motion track counts only when the audit is confident and a second Spark look (other moments,
  no label, no earlier names) still sees an animal; otherwise it waits in the human queue. The same second look gates
  a discovered track that the audit renamed to another animal the discovery step had named.
- All API calls are cached by content hash and metered against a budget (`FISH_BUDGET`, default $1). A Spark reply
  that is not valid JSON is never cached and is asked once more.
- SAM masks are decoded by a small C port of `meta_sam_parser`'s one_bit codec (`fishcount/_maskdec.c`, built with
  `cc` on first use; ~1 ms a mask instead of ~1 s). Without a C compiler it falls back to `meta_sam_parser`.
  `python3 spikes/maskcheck.py` checks it against the reference on every cached SAM output.

## Try it

**No key needed to look:** `pip install -r requirements.txt && python3 web/server.py`, then open
http://127.0.0.1:8793. Four finished nautilus runs (`demo/runs`, copied into `runs/` on first start) play with
their evidence frames, motion sheets and human queue. Nothing is called.

**To run new clips with your own key:** `cp .env.example .env` and set `META_API_KEY` (or export it). `FISH_BUDGET`
is a hard cap on total spend; a 12 s discovery run cost $0.02–0.40 on our nine clips.

```
python3 fishcount/pipeline.py <video> [--discover] [--zoom] [--offline] [--no-scout] [--no-audit] [--segment S]
python3 fishcount/evaluate.py            # raw SAM 'fish': recall/precision/MaxN error vs. luderick ground truth
python3 fishcount/evaluate_pipeline.py   # the same next to the full pipeline (runs eval3_<clip>)
python3 web/server.py                    # review screen on http://127.0.0.1:8793
```

**Tests (no network, no key, $0):** `python3 -m unittest discover -s tests -v` runs 28 tests, including an exact
offline replay of the s004 demo run and the long-video merge.

**Long videos.** One SAM 3.1 call takes a file of up to 10 minutes. A longer video is cut automatically into equal,
back-to-back segments of at most 600 s (`--segment S` for shorter ones), each segment is run as a normal clip, and the
segments are merged into one ordinary run, so the review screen, queue and CSV work on it unchanged. MaxN and first
arrival are per-frame numbers, so the merge is exact for them: MaxN is the largest segment MaxN, first arrival is the
segment start plus the time inside it, and no frame is counted twice. A name is merged only when it is identical in
both segments; names sharing a head noun are listed for the reviewer to rename (`fishcount/longvideo.py`,
measurements in `report/long_video.md`).

The review screen plays the annotated clip (blue = asked for, orange = found without being asked) over a per-species
count strip on the same timeline, shows each MaxN as a tally with its evidence frame, the second-look log, and a queue
of low-confidence tracks to confirm, rename or remove (counts and the CSV are recomputed from your edits). Until the queue
is checked, a count that depends on it is shown as a range, from confident answers only to everything counted.
New runs replay saved API answers for free unless "Allow paid API calls" is ticked (capped at $2 a run). A free replay needs answers cached by the current code (`cache/`, included: every SAM and Spark reply our runs used, so all saved runs replay for $0).

## Finding what you didn't ask for (measured)
Four nautilus BRUV clips (12 s each), request = "fish" only. Before looking at any output, every non-fish animal in
four frames per clip was listed by eye at taxon level (not an expert's list): 7 taxa.

| | result |
|---|---|
| Spark names it | 7 of 7 |
| counted at the end | 7 of 7 (s001's nautiluses at night behind a wire trap only through the motion look; the final code brightens that dark clip and counts 4 of at least 4, v16 counted 2) |
| something wrong counted | 0 (Spark once proposed a shrimp that isn't there; no word found it, and the motion box that drifted onto the trap mesh was rejected by a second look) |
| SAM "fish" alone | 0 of 7 — it only sees what it is told |
| motion look, added | s001: the nautiluses no word found (night, wire trap; 4 once the clip is brightened, 2 before). s004: 2 shrimp at the bottom edge, outside every box. 0 counted wrongly: a sediment cloud that looked like a fish in one crop is rejected once Spark sees three, and a motion track counts only when the audit is confident and a second Spark look at other moments still sees an animal |

**Five new videos, held out (measured).** Clips from three other studies (deep carcass cameras in British Columbia,
a fish-only BRUV in New Zealand; CC BY), never used in development, run once with frozen code under a protocol
committed first. Before the run the author and, separately, an AI assistant (Claude) marked the non-fish animals they could see: 4 animals over
the five clips, none in two of them.

| | result |
|---|---|
| Spark names it | 4 of 4 |
| counted at the end | 3 of 4 (crabs in DH1, DH2, DH3); the 4th, a squat lobster no word could track, was followed by a motion box in all 60 frames and sent to a person to confirm |
| something wrong counted | 0 (every counted crop judged an animal with its label hidden; nothing non-fish counted on the two clips without one) |
| cost | $1.06 for all five |

## How well it counts (measured)
Six luderick clips with human boxes (Ditria et al. 2021), 319 annotated frames, IoU >= 0.3. MaxN over the annotated
frames only, for both columns. Measured 11/2 (`fishcount/evaluate_pipeline.py`).

| clip | annotated frames | SAM "fish" alone: recall / precision / MaxN true→counted | full pipeline: recall / precision / MaxN true→counted | tracks sent to a human |
|---|---|---|---|---|
| 20190618_9 | 44 | 98% / 72% / 9→10 | 98% / 72% / 9→10 | 4 of 14 |
| 20190709_14 | 126 | 100% / 72% / 2→2 | 100% / 72% / 2→2 | 1 of 3 |
| 20190618_3 | 58 | 100% / 98% / 2→3 | 100% / 100% / 2→2 | 1 of 3 |
| 20190710_4 | 40 | 82% / 100% / 2→1 | 82% / 100% / 2→1 | 0 of 1 |
| 20190709_13 | 40 | 100% / 100% / 2→2 | 100% / 100% / 2→2 | 0 of 3 |
| 20190709_4 | 11 | 100% / 71% / 2→3 | 100% / 77% / 2→2 | 3 of 3 |
| **all** | 319 | **97.4% / 78.7%**, MaxN off by 1 on 4 of 6 | **97.4% / 79.2%**, MaxN off by 1 on 2 of 6 | 9 of 27 |

- Recall equals SAM alone: the checks no longer throw away real fish. They did at first (95.9%): Spark judged each
  track from one crop, and a faint fish behind seagrass was "only seagrass and water", so a 36-frame track left the
  count. Showing three crops of the same track (early, middle, late; for the peak check, just before and after)
  fixed it, the same way it lets Spark tell a sediment cloud from an animal below.
- A third of the tracks go to the human queue: the counts are what a reviewer confirms, not a final census.
- Honest baseline: dropping every track shorter than 4 frames (no model call) gives exactly the same numbers on these
  clips, so here the checks match a well-chosen heuristic rather than beat it; their own value shows in discovery
  (names, duplicates, the trap net). The 97.4% counts queued tracks as accepted; rejecting them all gives 84.2%.
- Held out: the frozen final code, run once on the 24 annotated clips development never used (protocol committed
  before the run, `report/paper/heldout_protocol.md`): recall 98.9%, MaxN exact on 20 of 24 with the queue accepted
  (SAM alone 19, the length rule 19); rejecting the queue puts every clip within ±1 at 95.6% recall. Same estuary, so
  this tests transfer within one site, not to new habitats.
- Of the two MaxN misses left, 20190618_9 (9→10) is two real fish the annotators did not box in that frame (one cut
  by the left edge); 20190710_4 (2→1) is a dark fish in murky seagrass that SAM never finds. Earlier, 6 of 12
  "false-positive" tracks were checked by eye and all 6 were real luderick the annotators left unboxed, so precision
  is a lower bound.

## Data credits
- Ditria, E.M. et al. (2021) luderick-seagrass dataset, CC BY 4.0 — PANGAEA doi:10.1594/PANGAEA.926930,
  github.com/globalwetlands/luderick-seagrass
- Barord, G.J. et al. (2014) Comparative population assessments of Nautilus sp., PLOS ONE 9(6): e100799,
  supplementary videos S1–S4, CC BY 4.0 (via Wikimedia Commons)
- Held-out discovery clips (Wikimedia Commons copies): Anderson & Bell (2014) PLOS ONE 9(10): e110710, S4/S1/S3,
  CC BY 4.0; Anderson & Bell (2016) PLOS ONE 11(3): e0149107, S2, CC BY 4.0; Zintzen et al. (2012) PLOS ONE 7(10):
  e48522, Video S1, CC BY 2.5
- Held-out discovery clips (via Wikimedia Commons): Anderson, G.S. & Bell, L.S. (2014) PLOS ONE 9(10): e110710,
  videos S4, S1, S3, CC BY 4.0; Anderson & Bell (2016) PLOS ONE 11(3): e0149107, video S2, CC BY 4.0; Zintzen, V. et
  al. (2012) PLOS ONE 7(10): e48522, Video S1, CC BY 2.5 (URLs and hashes in `report/paper/data/discovery_heldout/clips.json`)

## License
MIT (code). Videos and datasets keep their own licenses above.
