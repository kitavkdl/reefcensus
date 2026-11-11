# reefcensus — details

The parts of the [main README](../README.md) that a first read can skip: how each step works, the export and
annotation tools added after the evaluation, and the measured results in full. Every number here is also in the
[paper](paper/paper.md), which has the protocols and the evidence for each claim.

## How it works, step by step

What runs after discovery and the word ladder (main README, *How it works*):

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
  frames from one box. A motion track counts only when a second Spark look (other moments, no label, no earlier
  names) still sees an animal: after a confident audit (≥ 0.7), or after a mid-confidence one (0.5–0.7) for an animal
  group the discovery step had named, if that second look is itself confident (≥ 0.7) and names no other group, and
  then it also stays in the queue; otherwise it waits in the human queue. The same second look gates
  a discovered track that the audit renamed to another animal the discovery step had named.
- All API calls are cached by content hash and metered against a budget (`FISH_BUDGET`, default $1). A Spark reply
  that is not valid JSON is never cached and is asked once more.
- SAM masks are decoded by a small C port of `meta_sam_parser`'s one_bit codec (`fishcount/_maskdec.c`, built with
  `cc` on first use; ~1 ms a mask instead of ~1 s). Without a C compiler it falls back to `meta_sam_parser`.
  `python3 spikes/maskcheck.py` checks it against the reference on every cached SAM output.

## Long videos

One SAM 3.1 call takes a file of up to 10 minutes. A longer video is cut automatically into equal,
back-to-back segments of at most 600 s (`--segment S` for shorter ones), each segment is run as a normal clip, and the
segments are merged into one ordinary run, so the review screen, queue and CSV work on it unchanged. MaxN and first
arrival are per-frame numbers, so the merge is exact for them: MaxN is the largest segment MaxN, first arrival is the
segment start plus the time inside it, and no frame is counted twice. A name is merged only when it is identical in
both segments; names sharing a head noun are listed for the reviewer to rename (`fishcount/longvideo.py`,
measurements in `report/long_video.md`).

`--skip-empty` (opt-in, added after the evaluation, no paper number uses it): every 5 fps frame is read at 480x270
($0) and compared with the last frame the models saw, after matching brightness; a blob of 12 px or more that stands
out from the rest of the frame is a change, and so is a quarter of the frame differing (camera knocked, an animal
filling the view; murk spreading over the whole frame is sent too, which costs money, not a miss). The quarter rule is
there because when the whole frame changes no cell stands out from the rest, so the blob rule alone would never move
the reference on: on a 53-minute NOAA SEFSC GoPro drop (Gulf of Mexico station T60233160_A, its three files joined
at 5 fps) the camera is still sinking for the first ~160 s; with the rule 38% of the frames are sent, without it the
reference stays a sinking-camera frame, every sea-bed frame differs from it everywhere, and only the head (1.9%) is
sent. Stretches with no change are not sent and get the last analysed frame's boxes (marked carried, listed in
`result["skipped"]`). A sent stretch starts 10 s before a change and ends after 10 s without one; close stretches
join, each lasts at least 60 s, the first 60 s always go. A 10 s probe goes every 10 minutes of skipped footage, and if its counted boxes do not pair
with the carried ones the stretch before it is sent once, up to the probe, whose own run is kept. Each run gets what
is left of the whole-video cap (`--max-usd-video`, default $4 an hour; the per-segment `--max-usd` is not used); at
the first run a cap or `FISH_BUDGET` stops, nothing from there to the end is analysed or carried (animals there count
0) and that span is `result["unsent"]`. Stages a run skipped at the cap are listed in `result["capped"]`, by any run
with or without `--skip-empty` (`fishcount/screen.py`, `fishcount/longvideo.py`).

## The review screen

The review screen plays the annotated clip (blue = asked for, orange = found without being asked) over a per-species
count strip on the same timeline, shows each MaxN as a tally with its evidence frame, the second-look log, and a queue
of low-confidence tracks to confirm, rename or remove (counts and the CSV are recomputed from your edits). Until the queue
is checked, a count that depends on it is shown as a range, from confident answers only to every queued track answered "Yes".
New runs replay saved API answers for free unless "Allow paid API calls" is ticked (capped at $2 a run).

## Free replays on another machine

A free replay needs answers cached by the current code (`cache/`, included: every SAM and Spark reply our runs used). The cache is keyed by the exact bytes sent, so the code pins what changes those bytes between machines (x264 thread count, OpenCV IPP path, and on AVX-512 CPUs x264's AVX2 code, since its AVX-512 code encodes some clips to other bytes); moved from a 6-core SSE4.2 CPU to a 12-core AVX-512 one, the demo runs, all tests and 14 of the 15 discovery re-runs replay for $0 (the 15th, DH11, asks SAM a word the final word ladder adds; `report/paper/scripts/compare_tags.py` lists what moved). The brightened night clip (s001) comes out slightly different on the two CPUs, so its answers are cached for both; on a third CPU its re-run may call the API (about $0.20).

## Standard MaxN export (GlobalArchive layout)
Added after the evaluation (not used in any paper number). Next to the plain CSV, the review screen offers
"Download in GlobalArchive layout"; the same table comes from `python3 fishcount/maxn_export.py <run id> [--opcode CODE] [-o out.csv]`
or `GET /api/runs/<id>/export_globalarchive.csv?opcode=CODE`. It re-lays-out the same reviewed numbers as the plain CSV (human
renames and removals apply), one row per label with MaxN > 0, no group rows:

`OpCode, Family, Genus, Species, MaxN, Frame, Time_mins` then our own columns `spark_common_name, maxn_confirmed, origin,
taxonomy_status, source_file, run_id, human_edits, maxn_lower_bound` (filled when the crowd check marks the count as a lower bound).

**Family, Genus and Species are left for a person**: Muse Spark gives common names, not verified taxonomy, so the name is in `spark_common_name` (a reviewer's rename too) and `taxonomy_status` says it is unverified; a
person adds the taxonomy. `OpCode` defaults to the video's file name (we know no deployment code; pass `--opcode`).
`Frame` is the 0-based frame of our 5 fps analysis copy, not the original video's frame number; `Time_mins` is that frame's time.
Times are on the 5 fps analysis copy (0.2 s steps), and the peak check's ±1 s removal window can move a first arrival
later when it rejects an early box (s002's nautilus: 0 s → 1.2 s; paper, *Wrong rejections in the peak check*).

Sources for the columns (checked 11/3): the GlobalArchive generic-data manual, count file = required `Sample, Family,
Genus, Species, Count` plus any user columns (<https://globalarchivemanual.github.io/generic-datatables>); the CheckEM
workflow, whose MaxN table is `campaignid, sample, family, genus, species, maxn`, keeps rows with maxn > 0, and whose
raw EventMeasure points carry `frame`, `time`, `period`, `family`, `genus`, `species`, `number`
(<https://globalarchivemanual.github.io/CheckEM/articles/r-workflows/check-fish.html>); the NOAA BRUVS data dictionary's
`OpCode`, `Frame`, `Time_min`, `MaxN` definitions (<https://www.fisheries.noaa.gov/inport/item/50417>); MaxN and the
annotation protocol: Langlois et al. (2020), *Methods in Ecology and Evolution* 11(11), doi:10.1111/2041-210X.13470.
Column order and names follow these documents; check the first upload against your own template (`OpCode` vs `Sample`
is the likeliest rename).

## Fix an old annotation: find the boxes it left out (`gapfind`)
Added after the evaluation (not used in any paper number); it re-reads finished runs, so it calls no model and costs $0.
Old annotation sets made for another purpose leave animals unboxed, and a count scored against them is penalised for
being right: on our 24 held-out luderick clips, 40 "false positive" boxes drawn at random were judged with labels hidden
and **none was "not a fish"** (paper §6.2). `gapfind` turns that check into a workflow:

```
python3 -m fishcount.gapfind sheet --manifest <your clips manifest.json> --runs runs --prefix <tag>_ --out sheet_dir [--controls 3]
python3 -m fishcount.gapfind apply --key sheet_dir/key.json --answers answers.json --out fixed_annotations/
```

`sheet` collects every counted track with boxes that match no annotation box (IoU < 0.3) on annotated frames and writes
one phone-friendly HTML page: per track, three crops (first, middle, last) with our box in yellow and the existing boxes
in grey, no labels or scores. One tap per track: **O** an unboxed fish, **D** already boxed, **P** part of a fish,
**X** not a fish, **?** can't tell. "Copy answers" gives JSON with the time from first to last tap. `apply` writes
corrected annotation files in the same `[x, y, w, h, label]` format (added boxes labelled `<label> (added: gapfind)`),
lists P and ? tracks for a person, and reports MaxN before and after. On the held-out set the 153 unmatched boxes come
from 20 tracks, so 153 per-box judgements become 20 taps; in the 40-box sample no track mixed "fish" with "not a fish".
**Measured once (11/3):** the author answered the 20 tracks plus 3 controls on a phone in 9 min 39 s; all 3 controls
"already boxed", 15 tracks unboxed fish (145 boxes added), 1 already boxed, 1 part, 3 unsure, 0 not a fish. The
corrected annotation's MaxN is within ±1 of the author's hand count (21 of 24 blind) on all 24 clips (summed error 6, against 16
for the original boxes). The judge is consistent: 15 tracks were judged twice (first as single boxes in the precision
sheet, then as tracks), and all 11 called fish the first time were called fish again, with no answer turning into "not
a fish"; two of the four first-time "unsure" tracks became fish when seen as a track. Sheet, key, answers and
corrected files: `report/paper/data/heldout/gapfind/`.

## Site memory (added after the evaluation; not used in any paper number)
Off unless you pass `--site NAME` (or fill "Site" in the new-run form). When a reviewer confirms or renames a queued row in a
run started with a site, the label is saved to `runs/_site_memory/<site>.json`. The next video run with the same site name
also asks SAM for those words (up to 3 remembered animals, each a 1-2 word ladder such as `hagfish`, then the word that
tracked it last time, e.g. `eel`), after discovery and the second look, so a correction carries over. Each word costs one SAM call
(`max(50, frames) x $0.0002`: $0.012 for a 12 s clip, $0.60 for a 10 min segment); entries that would pass `--max-usd` are
dropped. Rows that came from a remembered word say so on the review screen. Design, an independent review and a $0.02 demo
(one word that tracked an animal Spark never named, one that found nothing): [docs/site_memory.md](../docs/site_memory.md).
`python3 fishcount/sitememory.py list SITE` and `forget SITE WORD` show and remove what is remembered.

## Finding what you didn't ask for (measured)
Four nautilus BRUV clips (12 s each), request = "fish" only. Before looking at any output, every animal the request did
not name in four frames per clip was listed by eye at taxon level (not an expert's list): 7 taxa, among them a hagfish
(a jawless fish, but not what SAM's "fish" finds).

| | result |
|---|---|
| Spark names it | 7 of 7 |
| counted at the end | 7 of 7 (s001's nautiluses at night behind a wire trap only through the motion look; the final code brightens that dark clip and counts 4 and queues a fainter 5th for a person) |
| something wrong counted | 0 (Spark once proposed a shrimp that isn't there; no word found it, and the motion box that drifted onto the trap mesh was rejected by a second look) |
| SAM "fish" alone | 0 of 7 — it only sees what it is told |
| motion look, added | s001: the nautiluses no word found (night, wire trap; 4 once the clip is brightened, 2 before). s004: 2 shrimp at the bottom edge, outside every box. 0 counted wrongly: a sediment cloud that looked like a fish in one crop is rejected once Spark sees three, and a motion track counts only when the audit is confident and a second Spark look at other moments still sees an animal |

**Five new videos, held out (measured).** Clips from three other studies (deep carcass cameras in British Columbia,
a fish-only BRUV in New Zealand; CC BY), never used in development, run once under a protocol committed first; the
current code gives the same results (paper Table 3b). Before the run the author and, separately, an AI assistant (Claude) marked the non-fish animals they could see: 4 animals over
the five clips, none in two of them.

| | result |
|---|---|
| Spark names it | 4 of 4 |
| counted at the end | 3 of 4 (crabs in DH1, DH2, DH3); the 4th, a squat lobster no word could track, was followed by a motion box in all 60 frames and sent to a person to confirm |
| something wrong counted | 0 (every counted crop judged an animal with its label hidden; nothing non-fish counted on the two clips without one) |
| cost | $1.06 for all five |

**Six more new videos, held out (measured).** Six PLOS ONE videos (two fish-only shark cameras, a
cold-seep time-lapse, two sediment-profile time-lapses, a 2186 m vent), run once under a second protocol committed
first; the current code gives the same results (paper Table 3c). Before the run the author and a second person who had never seen the
project's output marked, separately, the non-fish animals in four frames per clip: one animal over the six clips (a
bug/worm-like animal at the vent).

| | result |
|---|---|
| counted at the end | 1 of 1 (an amphipod, DH11) |
| something wrong counted | 0 (both counted non-fish crops judged animals with labels hidden; nothing non-fish on the two shark clips) |
| outside the reference | DH7: 3 crabs counted in a cold-seep time-lapse where both people marked nothing; the crabs appear in none of the four frames they saw. Judged "a crab" with the label hidden; the source paper names lithodid crabs. Not scored either way |
| SAM with 16 fixed words | finds the amphipod as "worm", but also calls the DH7 crab "starfish" |
| cost | $0.86 for all six (fixed-word baseline $1.00) |

## How well it counts (measured)
Six luderick clips with human boxes (Ditria et al. 2021; remote underwater video in seagrass, the source mentions no bait), 319 annotated frames. The boxes were drawn to train a luderick detector, not to count MaxN, so they leave some fish unboxed; a box matches a human box when they overlap by at least 30% of their combined area (IoU >= 0.3). MaxN over the annotated
frames only, for both columns. Final code, run `cr7` (`fishcount/evaluate_pipeline.py --tag cr7`); the later runs `cr8`–`cr11` give the same scores.

| clip | annotated frames | SAM "fish" alone: recall / precision / MaxN true→counted | full pipeline: recall / precision / MaxN true→counted | tracks sent to a human |
|---|---|---|---|---|
| 20190618_9 | 44 | 98% / 72% / 9→10 | 98% / 72% / 9→10 | 6 of 15 |
| 20190709_14 | 126 | 100% / 72% / 2→2 | 100% / 72% / 2→2 | 0 of 3 |
| 20190618_3 | 58 | 100% / 98% / 2→3 | 100% / 100% / 2→2 | 1 of 3 |
| 20190710_4 | 40 | 82% / 100% / 2→1 | 82% / 100% / 2→1 | 0 of 1 |
| 20190709_13 | 40 | 100% / 100% / 2→2 | 100% / 100% / 2→2 | 0 of 3 |
| 20190709_4 | 11 | 100% / 71% / 2→3 | 100% / 77% / 2→2 | 2 of 3 |
| **all** | 319 | **97.4% / 78.7%**, MaxN off by 1 on 4 of 6 | **97.4% / 79.2%**, MaxN off by 1 on 2 of 6 | 9 of 28 |

- Recall equals SAM alone: the checks no longer throw away real fish. They did at first (95.9%): Spark judged each
  track from one crop, and a faint fish behind seagrass was "only seagrass and water", so a 36-frame track left the
  count. Showing three crops of the same track (early, middle, late; for the peak check, just before and after)
  fixed it, the same way it lets Spark tell a sediment cloud from an animal below.
- Doubtful tracks go to a person, and clearing the queue is quick: the author answered the 9 queued tracks of four clips on a phone in 121 s (about 13 s a track); all 6
  accepted tracks overlap the human boxes and the 3 left unsure match none (a timestamp overlay, open water, a very
  faint shape), so no track the reference lacks was accepted (`report/paper/data/qtime/`).
- Held out: the 24 annotated clips development never used, run once under a protocol committed before the run
  (`report/paper/heldout_protocol.md`). The protocol run: recall 98.9%, MaxN exact on 20 of 24 with the queue accepted
  (SAM alone 19, the length rule 19); with the queue rejected, recall 95.6% and exact on 21. The current code, re-run
  after these clips were scored, gives the same counts with the queue accepted; rejecting the queue puts every clip
  within ±1 at 89.3% recall.
- **Against a hand count of the videos, the pipeline comes closer than the reference boxes.** The author (not a marine biologist) counted MaxN by hand on all 24
  held-out videos (21 blind, shuffled under neutral names): the pipeline is exact on 18 and within ±1 on all 24, summed
  error 6 (over every frame of the clip, the hand count's own scope: exact 17, summed error 7); the human reference boxes are exact on 16, within ±1 on 22, summed error 16. On the worst clip (20190709_17)
  the hand count is 8, the pipeline 7 and the boxes 2 (paper Table 1d, Figure 3). This does not assume the queue is
  accepted unseen: answering the 17 queued tracks from judgements a person had already recorded gives the same MaxN
  on all 24 clips, while rejecting them all falls back to the boxes' summed error of 16.
- **A second, independent counter gives the same order.** A friend of the author who had never seen the project's output counted the
  same 24 videos blind (shuffled, neutral names, key fixed first): the two counters agree within one fish on all 24.
  Against that count the pipeline is exact on 22 clips and within ±1 on all 24, summed error 2; the reference boxes exact
  on 18, summed error 14
  (paper Table 1e, `report/paper/scripts/recount2_score.py`).
- **A third held-out set from another ocean.** Eight 12-s windows cut by rule from NOAA Gulf of Mexico reef-fish survey
  videos, hand-counted and committed before the run: the four clips without fish are 0 with no false fish (two of them
  the hand count first entered as 2 and 4 fish, then judged drifting particles); N1 is exact. Small faint fish over a
  hazy floor are where it counts low (N3 10 of 12); on N7 the tiled re-run (`--crowd`) finds 3 of 9 and the crowd check
  marks that MaxN a lower bound, so the clip goes to a person (paper Table 1f, `report/paper/scripts/score_noaa_heldout.py`).
- Of the two MaxN misses left, 20190618_9 (9→10) is two real fish the annotators did not box in that frame (one cut
  by the left edge); 20190710_4 (2→1) is a dark fish in murky seagrass that SAM never finds.
- **Most "false positives" are unboxed fish.** On the held-out set, 40 of the 153 boxes scored as false were drawn at
  random and judged with labels hidden, mixed with 10 matched controls (all 10 called fish): 29 fish, 2 part of a fish,
  9 unsure, **0 not a fish**. Corrected precision is 93.7% with the unsure boxes counted as wrong (95% interval
  89.6–97.0%, resampling the 15 tracks the boxes come from), against 77.2% scored on the boxes. `gapfind` (above) does this check for a whole annotation set.
