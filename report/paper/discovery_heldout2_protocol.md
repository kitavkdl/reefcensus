# Second held-out discovery set (DH6–DH13) — protocol (written and committed before any clip is downloaded or run)

Written 2026-11-02 (ET). Why: the first held-out set (DH1–DH5, `discovery_heldout_protocol.md`) found 4/4 reference
animals with 0 false discoveries, but it is five clips from three studies, four of them carcass-bait videos from one
research group. This set asks the same question on more, different footage, and adds the question the second review
raised: **outside the development clips, is Spark's naming step needed, or would SAM 3.1 with a fixed list of animal
words find the same animals?** Same rules as the first set wherever possible; differences are marked *new*.

## Selection (fixed before searching)
- **Where**: Wikimedia Commons, File namespace, video files, searched through the Commons API (text results only —
  titles, descriptions, licence fields; no thumbnails opened while selecting). Queries, in this order:
  1. `baited remote underwater video`  2. `baited camera`  3. `BRUV`  4. `lander camera seafloor`
  5. `deep-sea camera bait`  6. `benthic time-lapse camera`  7. `underwater video fish pone` (PLOS ONE supplements)
  8. `seafloor video invertebrate`
  Candidates are taken in query order, then API result order. PLOS ONE supplementary videos found on PLOS directly
  (journals.plos.org) are allowed only if the same file is also on Commons or the article states CC BY.
- **Eligible** when all hold, judged from the file page and the source article text only:
  (a) licence CC BY (any version) or CC0 / public domain — not CC BY-SA, not NC/ND, not "fair use";
  (b) real underwater footage from a camera that does not travel during the shot: baited/unbaited fixed camera,
      lander, tripod, cabled observatory or drop camera resting on/near the bottom (*new*: wording widened from
      "baited or fixed seabed camera"; towed cameras, ROV/AUV transects, diver-held footage are excluded);
  (c) at least 12 s long;
  (d) source publication / uploader series **not used anywhere so far**: excludes Barord et al. 2014 (e100799,
      development nautilus clips and the demo clip), the luderick archive (development and 24 held-out clips),
      Anderson & Bell 2014 (e110710) and 2016 (e0149107), Zintzen et al. 2012 (e48522), and the withdrawn IMAS clips.
      *New*: the whole publication is excluded, not just the files already used (other files of the same study share
      site, camera and bait);
  (e) no burned-in text that names the animals on screen (species captions would leak the answer to Spark);
      *new* — DH5 had such captions.
  (f) at most **2 clips per publication** (*new*, for spread).
- **How many**: 8 clips — the first **6** eligible whose file description or source article names at least one
  non-fish animal (crab, shrimp, lobster, octopus, squid, sea star, urchin, sea cucumber, snail, worm, jellyfish …)
  and the first **2** eligible whose text names fish only (to measure false discoveries). If the queries run out
  before 6 + 2, the set is smaller and that is reported; no further queries are added after seeing results.
  As in DH1–DH5, the non-fish rule favours clips where such animals are present: this measures *finding* them, not
  how often they occur.
- Every candidate looked at is logged in `data/discovery_heldout2/candidates.md` with the reason it was taken or
  skipped, before any clip is downloaded.

## Clips
- IDs DH6–DH13 in selection order. Window, ingest and sheet exactly as DH1–DH5: the 12 s centred on the file's
  midpoint (whole file if shorter), 5 fps, width ≤ 1920, no audio, a 4-frame sheet (frames 0, 20, 40, 59) per clip
  (`report/paper/scripts/prep_discovery_heldout2.py`, same code path as `prep_discovery_heldout.py`). The window is
  fixed by rule, not by looking: if the midpoint window shows no non-fish animal, that clip stays as it is.
- `data/discovery_heldout2/clips.json`: URL, sha256, citation, licence, author, duration, window start.

## Reference lists (before any pipeline or baseline call)
- From the clean 4-frame sheets only (no labels, no boxes), the same question as before — "apart from fish, what
  animal shapes do you see?" — coarse groups only ("crab-like", "shrimp-like", "octopus", "sea star", "snail/shell",
  "eel-like", …), with rough counts. Bait (carcasses, wrapped meat, bait bags) is not an animal to find.
- Markers: (1) Jiyul Ahn (non-expert); (2) *new*: a second person who has not seen any output of this project, if
  one is available before the run; (3) Claude, written to a file before the run. Each list is committed before the
  run. A group is in the reference list if any **human** marker lists it; Claude's list is reported for agreement
  only (*new* — in DH1–DH5 Claude's list counted). If no second person is available before the run, the paper says so.
- Mobile animals are the primary list; sessile ones (anemones, corals, sponges, tube worms) and "unsure" entries are
  reported separately, not in the primary recall.

## Runs (one each, reported whatever they show)
- **Code**: frozen at the commit that adds this file (pipeline, prompts, thresholds). Only the new prep and baseline
  scripts may be added before the run; neither changes the pipeline.
- **Discovery pipeline**, per clip:
  `FISH_BUDGET=<ledger+2.5> python3 fishcount/pipeline.py spikes/DHB/clips/DH<n>.mp4 --id DH<n>_eval --no-scout --prompts fish --discover --zoom`
- **Fixed-vocabulary baseline** (no VLM naming): SAM 3.1 on the full frame with the same 16 basic-level words as
  `report/paper/scripts/fixed_vocab.py` (fish, shark, ray, eel, crab, shrimp, lobster, octopus, squid, snail, shell,
  starfish, jellyfish, sea urchin, sea cucumber, worm), one call per (clip, word); "fish" is reused from the
  pipeline's cache. Script `report/paper/scripts/fixed_vocab_heldout2.py`:
  `FISH_BUDGET=<ledger+1.6> python3 report/paper/scripts/fixed_vocab_heldout2.py`
- **Budget**: pipeline ≈ $0.02–0.40 per clip (DH1–DH5 mean $0.21), baseline 15 paid words × $0.012 = $0.18 per clip;
  expected ≈ $3.1 for 8 clips, hard caps $2.5 (pipeline batch) + $1.6 (baseline batch) through `FISH_BUDGET`.
  A clip that hits the cap is reported as not run.

## Metrics (fixed now)
1. **Discovery recall** = reference taxa (primary list) that end in a counted (non-queued) pipeline row of the right
   coarse group / reference taxa.
2. **Named-only recall** = reference taxa Spark names at the discovery step (counted or not).
3. **False discoveries** = counted non-fish pipeline rows whose evidence crop shows no animal, judged by Jiyul Ahn
   from the crop alone, without the label ("is this an animal: yes / no").
4. **Baseline recall** = reference taxa for which some baseline word has a track that (i) overlaps a counted pipeline
   track of that taxon (IoU ≥ 0.3 in ≥ 3 frames, the rule of `fixed_vocab.py`), or (ii) is judged an animal of that
   coarse group from its label-free crop (one crop per track at its highest-confidence frame; at most the 3 longest
   tracks per clip and word, the rest counted only). Reported also: whether the word was a right one for the group.
5. **Baseline false labels** = non-fish-word tracks whose label-free crop is judged "not an animal", per clip; on the
   two fish-only clips this is the direct comparison with metric 3.
6. Queue size and cost per clip, for both.
   MaxN accuracy is not measured (four frames cannot count shrimp).
- Results go into the paper (§6.3, Table 3b), README and submission form even if they are poor. No prompt, threshold
  or code change after seeing them; a bug found here is reported, not fixed in these numbers.

## Amendment 1 (2026-11-02, after the eight queries' text results, before any clip was downloaded or viewed)
The eight queries returned 47 files; read from titles and descriptions only, **1 non-fish and 3+ fish-only** clips
were eligible (the rest: terrestrial camera traps, animations, pelagic longline cameras, diver-held footage, burned-in
species text, or publications already used — logged in `candidates.md`). The protocol's "set is smaller" clause would
leave 3 clips, too few to answer the question. Amendment, fixed before running them: the same eligibility rules and
the same 6 + 2 quota, with these further Commons API queries appended in this order (text only, as before):
  9. `pone crab video`  10. `pone shrimp video`  11. `octopus camera seafloor`  12. `amphipod bait video`
  13. `hagfish bait video`  14. `sea star time-lapse`  15. `deep sea observatory video`  16. `stationary camera seafloor`
  17. `pone underwater video camera`  18. `cold seep time-lapse`  19. `hydrothermal vent camera fauna`
  20. `pone video invertebrates seabed`
Naming animal groups in queries 9–14 favours clips with non-fish animals; that is the same direction rule (d)
already takes and is disclosed. If these still give fewer than 6 + 2, the set is what they give.
