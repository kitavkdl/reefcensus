# reefcensus: counting what was asked for and finding what was not, with SAM 3.1 and Muse Spark

Technical report, Meta AI hackathon (Oct 26 – Nov 4, 2026). Every number below was measured on this code; the
command that produces it is under **Reproduce**. Where a number rests on a small sample, it says so.

## Summary
Baited underwater video (BRUV) is scored by hand: someone watches every hour and writes down, per species, the most
individuals seen in one frame (MaxN). reefcensus takes a request such as "fish" and returns per-species MaxN, the
time of first arrival, an evidence frame behind every number, and a short queue of tracks a person should confirm.

Two Meta models do different halves of the work. **SAM 3.1** tracks pixel masks through the clip, but only for what
it is told: asked for "animal" it finds nothing. **Muse Spark** can look at frames and say what is there, but cannot
track. reefcensus puts them in a loop: Spark names what it sees (including animals nobody asked about), turns the
names into words SAM understands, and then checks SAM's work: every track, the frame that sets each MaxN, and whether
two overlapping masks are one animal. Where no word works, a still camera's own motion marks the spot, Spark decides
whether it is an animal, and SAM tracks it from a box with no word at all.

Results (details in **Evaluation**):
- **Counting, luderick (6 clips, 319 frames boxed by people):** RESULT_LUDERICK
- **Finding what was not asked for (4 nautilus clips, request "fish"):** RESULT_DISCOVERY
- **Cost:** a 12 s clip costs about $0.02–0.25 in API calls; all answers are cached by content, so a rerun is free.

![SAM "animal" vs SAM "fish" vs reefcensus on the same frame](figures/compare3.jpg)
*Same deep-sea frame (IMAS TF_52). Left: SAM 3.1 asked for "animal", 0 detections. Middle: asked for "fish".
Right: reefcensus.*

## 1. Problem
A BRUV drops a camera next to a bait bag on the seabed. The standard abundance measure is MaxN: per species, the
largest number of individuals visible in any single frame, a conservative count that never double-counts an animal
that leaves and returns. Getting it means watching the footage. At MBARI, "these 90 hours of video can take anywhere
from 180 to 400 hours to annotate" (MBARI expedition log, Gulf of California 2015, Leg 2, Log 8, 3 March 2015).

Two things make automation hard. First, the species list is open: a survey aimed at fish also films shrimp,
nautiluses and hagfish, and those are often the interesting part. A detector trained on a fixed list cannot report
what is not on it. Second, a count is only useful if a scientist can check it, so every number needs evidence and
the doubtful cases need to be pointed out, not hidden.

## 2. Method
```
video ──► SAM 3.1 "fish" (whole frame, reversed clip, optional 2x2 zoom tiles)
   │
   ├─► Spark: "what else lives here?" ──► plain nouns ──► SAM word ladder ("hagfish" 0 → "eel" 24 frames)
   │         └─ nothing tracks → zoom tile, then the one cell Spark named at 3x, every word, longest wins
   │
   ├─► motion: pixels that keep changing outside every box (no model) ──► Spark, 3 crops per spot:
   │         animal or sediment? ──► animals → SAM box prompt, no word
   │
   ├─► merge + re-join broken track IDs
   ├─► Spark audit: 3 crops per track (early / middle / late) → species, is it the target, confidence
   │         confidence < 0.7 → human queue, not counted
   ├─► Spark "same animal?": one mask inside another → both outlines shown → duplicate removed
   ├─► Spark peak check: every box in the frame that sets MaxN, with the same track before and after
   └─► MaxN, first arrival, evidence frame per species; review screen; CSV
```
All Spark checks look at **three moments** of the same object at the same zoom. One crop of a sediment cloud can look
like a dark fish; across three crops the cloud spreads and changes shape while an animal keeps its shape. The same
three-crop view stopped the audit from discarding a faint fish behind seagrass (section 4.1).

## 3. What we measured about the models
These are the behaviours the design is built around. Each was found by trial during the hackathon.

| finding | evidence | what we did |
|---|---|---|
| SAM 3.1 returns nothing for a broad word | "animal" on three IMAS deep-sea clips: 0 detections on all three; "fish": 13–16 per frame | Spark proposes basic-level nouns (fish, shrimp, eel, nautilus) |
| SAM 3.1 returns nothing for a descriptive name | "pink seabream" on the same clips: 0 | species comes from the Spark audit, SAM gets the plain noun |
| A name SAM does not know can fail where a near word works | s004: "hagfish" 0 frames, "eel" 24 frames | word ladder, Spark's own name kept for the label |
| Word tracking starts only once the object is clear and runs forward | animals clear only late in a clip were missed before that point | the clip is also run reversed and the two are joined |
| A **box prompt with no word** tracks both ways from its frame | s004 bottom-edge shrimp: no word, tile or reversed pass ever tracked it; one box → 57 of 60 frames in the first test, 55 of 60 in the pipeline | motion look → Spark → box prompt |
| A box touching the frame edge is rejected | `y2 = 1080` on a 1080-high clip: HTTP 400 "lies outside the frame" | boxes clamped to H−2 |
| Spark sometimes breaks JSON when asked for JSON only | 2 of 124 cached replies (for example `{ polo":1 }:`) | a reply that fails its shape check is not cached and is asked once more |
| Spark's judgement depends on what else is on the sheet | the same pair of masks (s004, frame 27) was "same animal" on one sheet and "different" on another | decisions that set a count are made on small sheets with three crops; doubtful ones go to a person |
| Spark answers from the words it is offered | s001: the motion prompt's example nouns left out nautilus, so a spot Spark described as "striped nautilus shell" got the name "snail" | a name the discovery step already gave wins when Spark's own description uses it |

## 4. Evaluation
### 4.1 Counting against human boxes (luderick)
Six luderick clips with human bounding boxes (Ditria et al. 2021), 319 annotated frames, a match at IoU ≥ 0.3. MaxN
is taken over the annotated frames only, for both columns.

TABLE_LUDERICK

NOTES_LUDERICK

### 4.2 Finding what was not asked for (nautilus)
Four nautilus BRUV clips (Barord et al. 2014), 12 s each, request = "fish" only. Before looking at any pipeline
output, every non-fish animal in four frames per clip (frames 0, 20, 40, 59) was listed by eye at taxon level. This is
a non-expert list: 7 taxa over the four clips.

TABLE_DISCOVERY

![Motion sheet, s004](figures/motion_s004.jpg)
*Motion look, s004: each group is one moving spot that no box covered, shown early / middle / late. Spark calls the
shrimp animals and the sediment puffs not; the shrimp then go to SAM as box prompts.*

## 5. Limits
- **Small samples.** Discovery: 4 clips, 7 taxa, non-expert ground truth. Counting: 6 clips of one species in
  shallow seagrass. Neither says how the pipeline does on long deployments or crowded schools.
- **Precision is a lower bound.** Six of twelve "false-positive" luderick tracks were checked by eye and all six were
  real fish the annotators left unboxed.
- **The human queue is part of the result.** About a quarter of the tracks go to a person. The counts are what a
  reviewer confirms, not a finished census.
- **Night footage behind a wire trap (s001) is the weakest case.** No word, zoom or 3x cell tracks a nautilus there;
  only the motion look does, and Spark's audit is unsure about the blurriest one.
- **Spark is not deterministic.** The same input on a different sheet can get a different answer (section 3). Cached
  answers make a run reproducible; a fresh run can differ by a track.

## 6. Reproduce
```
pip install -r requirements.txt
export META_API_KEY=...            # or .env; not needed for cached replays
export FISH_BUDGET=1.0             # hard cap on total spend (USD)
python3 fishcount/evaluate.py                          # SAM "fish" alone vs. luderick boxes
python3 fishcount/evaluate_pipeline.py --run --tag t1  # full pipeline vs. the same boxes (runs t1_<clip>)
python3 fishcount/pipeline.py <clip> --no-scout --prompts fish --discover --zoom   # discovery run
python3 web/server.py                                  # review screen, http://127.0.0.1:8793
```

## Data
- Ditria, E.M. et al. (2021) luderick-seagrass dataset, CC BY 4.0
- Monk, J., Barrett, N., Langlois, T. (2024) Curated underwater video highlights of marine protected areas, IMAS,
  University of Tasmania, CC BY 4.0
- Barord, G.J. et al. (2014) Comparative population assessments of Nautilus sp., PLOS ONE 9(6): e100799, S1–S4, CC BY 4.0
