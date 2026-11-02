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
- **Counting, luderick (6 clips, 319 frames boxed by people):** recall 97.4% (the same as SAM alone: the checks throw away no real fish), precision 79.2% (a lower bound, see 4.1), MaxN within ±1 of the human count on all 6 clips and exact on 4 (SAM alone: 2); 9 of 27 tracks sent to a person. A rule with no model call, dropping tracks shorter than 4 frames, gives exactly the same numbers, so on this one-species task the checks match a well-chosen heuristic rather than beat it. The 97.4% counts the queued tracks as accepted; if a reviewer rejected all of them, recall would be 84.2%.
- **Held out (24 luderick clips never used in development, frozen code, one run, protocol committed first):** recall 98.9%, MaxN exact on 20 of 24 with the queue accepted (SAM alone and the length rule: 19); with the queue rejected every clip is within ±1 (recall 95.6%). Same estuary as the development clips.
- **Finding what was not asked for (4 nautilus clips, request "fish"):** Spark named all 7 non-fish taxa a person could see and all 7 reached the final count, with no label outside the person's list except two low-confidence "fish (unidentified)" tracks waiting in the queue (s002). SAM asked for "fish" alone found 0 of 7. Spark's naming plus SAM, with no checks, already finds 7 of 7 (with the motion look); the checks give the right names (hagfish, not SAM's "eel"), remove duplicate shrimp and a false "shrimp" on the trap net, and cost one nautilus in s001 (queued). The hardest one (nautiluses at night behind a wire trap) was found only by the motion look.
- **Cost:** a 12 s clip costs about $0.02 (counting only) to $0.27 (discovery) in API calls; all answers are cached by content, so a rerun is free.

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
   │         counted only if the audit is confident AND a second Spark look (other moments, no label) agrees
   │         (the same second look also gates a track the audit renamed to another discovered animal)
   │
   ├─► merge + re-join broken track IDs
   ├─► Spark audit: 3 crops per track (early / middle / late) → species, is it the target, confidence
   │         confident "not the target" → removed; unsure → counted as "(unidentified)" and queued for a person
   │         (motion tracks: counted only if confident and the second look agrees)
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
| Spark sometimes breaks JSON when asked for JSON only | twice during development (for example `{ polo":1 }:`); bad replies are no longer stored, so the rate is not known | a reply that fails its shape check is not cached and is asked once more |
| Spark's judgement depends on what else is on the sheet | the same pair of masks (s004, frame 27) was "same animal" on one sheet and "different" on another | decisions that set a count are made on small sheets with three crops; doubtful ones go to a person |
| The audit takes up a name it is offered | s003: a motion box that had drifted onto the trap's net legs was audited as "large striped shrimp", 0.75 — a name the discovery step had guessed (wrongly) and the audit prompt listed as context. Shown other moments with no label and no names, Spark said "trap mesh, not animal" | a motion track counts only after that second, unprimed look agrees |
| Spark answers from the words it is offered | s001: the motion prompt's example nouns left out nautilus, so a spot Spark described as "striped nautilus shell" got the name "snail" | a name the discovery step already gave wins when Spark's own description uses it |

## 4. Evaluation
### 4.1 Counting against human boxes (luderick)
Six luderick clips with human bounding boxes (Ditria et al. 2021), 319 annotated frames, a match at IoU ≥ 0.3. MaxN
is taken over the annotated frames only, for both columns.

| clip | annotated frames | SAM "fish" alone: recall / precision / MaxN true→counted | reefcensus: recall / precision / MaxN true→counted | tracks sent to a person |
|---|---|---|---|---|
| 20190618_9 | 44 | 98% / 72% / 9→10 | 98% / 72% / 9→10 | 4 of 14 |
| 20190709_14 | 126 | 100% / 72% / 2→2 | 100% / 72% / 2→2 | 1 of 3 |
| 20190618_3 | 58 | 100% / 98% / 2→3 | 100% / 100% / 2→2 | 1 of 3 |
| 20190710_4 | 40 | 82% / 100% / 2→1 | 82% / 100% / 2→1 | 0 of 1 |
| 20190709_13 | 40 | 100% / 100% / 2→2 | 100% / 100% / 2→2 | 0 of 3 |
| 20190709_4 | 11 | 100% / 71% / 2→3 | 100% / 77% / 2→2 | 3 of 3 |
| **all** | **319** | **97.4% / 78.7%**, MaxN off by 1 on 4 of 6 | **97.4% / 79.2%**, MaxN off by 1 on 2 of 6 | **9 of 27** |

- **The checks fix SAM's over-counts without losing fish.** On 20190618_3 and 20190709_4, SAM alone counts 3 where
  people counted 2; the audit brings both to 2 by rejecting a 2- and a 3-frame track. Recall stays at SAM's 97.4%.
  Dropping every track shorter than 4 frames does exactly the same (3 frames fixes one clip, 5 or more lose fish), so
  the checks' value on this task is matching the best threshold without tuning one (see the paper, Table 1).
- **They did lose fish at first.** With one crop per track (its largest box), the audit called a faint fish behind
  seagrass "only seagrass and water" and a 36-frame track left the count; the peak check did the same to another
  faint fish in frame 35 of 20190618_9. Recall fell to 95.9%. Three crops of the same track (early / middle / late,
  and for the peak check the same track just before and after) brought it back to 97.4%.
- **Layout matters, not only content.** A later version moved "this frame" to the first crop when a track starts in
  that frame (so no crop repeats). The same faint fish in frame 35, whose track starts there, was again called
  "seagrass, no fish" and recall dropped to 96.3%. Keeping the judged frame in the middle and repeating it restored
  97.4%. Every prompt or sheet change is now rerun against this clip and against nautilus clip s004's peak frame.
- **The two MaxN misses left.** 20190618_9 (9→10): in the frame that sets the count, two real fish (one cut by the
  left edge) have no human box. 20190710_4 (2→1): a dark fish in murky seagrass that SAM never finds, so no check
  can add it.
- **Precision is a lower bound.** Of 12 tracks scored as false positives in an earlier run, 6 were checked by eye and
  all 6 were real luderick the annotators had not boxed.

### 4.2 Finding what was not asked for (nautilus)
Four nautilus BRUV clips (Barord et al. 2014), 12 s each, request = "fish" only. Before looking at any pipeline
output, every non-fish animal in four frames per clip (frames 0, 20, 40, 59) was listed by eye at taxon level. This is
a non-expert list: 7 taxa over the four clips.

| clip | animals a person listed (not fish) | reefcensus final count (MaxN) | how it was found |
|---|---|---|---|
| s001 (night, wire trap) | nautilus: 1 inside the trap, 3+ outside | **nautilus 2** | no word, zoom or 3x cell tracked anything; motion look → Spark "nautilus" → SAM box prompts (56 and 60 of 60 frames), audit 0.95 / 0.9, second look yes. A third motion track (audit 0.55) waits for a person |
| s002 | nautilus 1; red crustaceans 2 (by the rope, by the bait) | nautilus 1; **small red crab 1** | Spark: "small red crab on seabed". The word "shrimp" tracked it in a 3x cell; the audit said "small red crab, not shrimp" (0.7), which matches the discovery name, so the track is relabelled; the unprimed second look agrees ("small red crab with legs shifts"). The crustacean at the bait is held as "fish (unidentified)" for a person |
| s003 | nautilus 3–4 | nautilus 3 | word "nautilus" + zoom tiles. Spark also proposed a "large striped shrimp" that is not there: no word tracked it, and the motion box later audited under that name was rejected by the second look (figure below) |
| s004 | nautilus 1; shrimp 10+; one grey eel-like animal (hagfish) | nautilus 1; caridean shrimp 12 (+3 unidentified; 15 together in frame 54); hagfish 1 | "hagfish" 0 frames → "eel" 24 frames, labelled hagfish. Two shrimp at the bottom edge only through motion boxes (tracked in 55 and 30 frames) |

| measure | result |
|---|---|
| Spark names it | 7 of 7 taxa |
| reaches the final count | **7 of 7** taxa |
| false animal counted | **0** |
| SAM "fish" alone | 0 of 7 (in s002 it boxed the two crustaceans as low-confidence "fish") |

Counts of individuals cannot be scored here: four frames per clip are not enough for a person to count 10+ shrimp.
In s001 the taxon is counted but the number (2) is below what a person sees (4+).

![Motion sheet, s004](figures/motion_s004.jpg)
*Motion look, s004: each group is one moving spot that no box covered, shown early / middle / late. Spark calls the
shrimp animals and the sediment puffs not; the shrimp then go to SAM as box prompts.*

![Audit sheet, s003](figures/audit_s003_mesh.jpg)
![Second look, s003](figures/confirm_s003.jpg)
*s003. Top, right group (T6): a motion box that drifted onto the trap's net legs; the audit, whose prompt listed the
discovery step's guess "large striped shrimp", passed it at 0.75. Bottom: the same track at other moments, no label,
no names: "looks like trap mesh, not animal". It is not counted.*

## 5. Limits
- **Small samples.** Discovery: 4 clips, 7 taxa, non-expert ground truth. Counting: 6 clips of one species in
  shallow seagrass. Neither says how the pipeline does on long deployments or crowded schools.
- **Precision is a lower bound.** Six of twelve "false-positive" luderick tracks were checked by eye and all six were
  real fish the annotators left unboxed.
- **The human queue is part of the result.** About a third of the luderick tracks (9 of 27) go to a person. The counts are what a
  reviewer confirms, not a finished census.
- **Night footage behind a wire trap (s001) is the weakest case.** No word, zoom or 3x cell tracks a nautilus there;
  only the motion look does. It counts 2 of the 4+ a person sees: the nautilus inside the trap is never tracked, and
  Spark's audit is unsure about the blurriest one, which waits for a person.
- **Duplicates are found only when masks nest.** Nested pairs are checked within a tracker word and, since the final version, across words too (none on the four clips). Two tracks of one animal that never nest are not caught. In s002 a second red crustacean is held as "fish (unidentified)" for a person; it shares 42 frames with the counted crab without overlapping, so it is a different animal.
- **The second look checks "animal or not", not the name.** In s004 it called both counted motion shrimp "fish" (0.6, 0.65) though the audit named them caridean shrimp; they count as shrimp because the audit's species is used.
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
- Ditria, E.M. et al. (2021) luderick-seagrass dataset, CC BY 4.0, PANGAEA doi:10.1594/PANGAEA.926930
- "Curated underwater video highlights of marine protected areas (IMAS, UWA & collaborators)", Australian Ocean Data
  Network record on data.gov.au (dataset b75639f4-c6d8-4a52-b633-988d6ba8a247). The record lists no authors and
  "License: Not Specified"; used only for a vocabulary probe and one figure, licence to be confirmed with the custodian
- Barord, G.J. et al. (2014) Comparative population assessments of Nautilus sp., PLOS ONE 9(6): e100799, S1–S4, CC BY 4.0
