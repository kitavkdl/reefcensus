# Held-out discovery evaluation — protocol (written and committed before any run on these clips)

Written 2026-11-02 (ET), after the development discovery set (four nautilus clips, seven non-fish taxa, 7/7 counted,
0 false) was judged too small and too close to development to support the claim.

- **Clips** (`data/discovery_heldout/clips.json`: URL, sha256, citation, licence): five Wikimedia Commons copies of
  PLOS ONE supplementary videos — DH1–DH3 Anderson & Bell 2014 (e110710, S4/S1/S3, Saanich Inlet 95 m, CC BY 4.0),
  DH4 Anderson & Bell 2016 (e0149107 S2, Strait of Georgia, CC BY 4.0), DH5 Zintzen et al. 2012 (e48522, New Zealand
  BRUV, CC BY 2.5). Rule: every clip a literature/Commons search returned that (a) states a reuse licence, (b) comes
  from a baited or fixed seabed camera, (c) is at least 12 s, (d) has source text naming a non-fish animal (DH1–DH4),
  plus one fish-only BRUV (DH5) to measure false discoveries; none used anywhere in development (excludes Barord 2014
  S1–S4, the IMAS clips and the luderick archive). Chosen from source pages, not by running anything on them.
  Rule (d) favours clips where non-fish animals are present; this measures finding them, not how often they occur.
  DH1–DH4 use carcasses as bait (taphonomy studies); DH5 has species captions burned into the picture.
- **Window**: the 12 s centred on each file's midpoint (whole file if shorter), 5 fps, same ingest as the
  development clips (`report/paper/scripts/prep_discovery_heldout.py`). Fixed by rule, not by looking.
- **Reference list (before the run)**: for each clip a 4-frame sheet (frames 0, 20, 40, 59). Two people write,
  independently and before any pipeline output exists, which non-fish animal shapes they can see — at a coarse
  group level only (e.g. "crab-like", "shrimp-like", "octopus", "sea star", "snail/shell", "eel-like"):
  (1) Jiyul Ahn (non-expert), asked only "apart from fish, what animal shapes do you see?";
  (2) Claude, same question, written to a file before the run (`data/discovery_heldout/reference_claude.md`,
  committed with this protocol; Jiyul Ahn's list is committed in a second commit, still before the run).
  A group is in the reference list if either person lists it; agreement between the two is reported.
  Mobile animals are the primary list; sessile ones (anemones, corals, sponges) and "unsure" entries are reported
  separately, not in the primary recall.
- **Code**: frozen at the commit that adds this file. Command per clip:
  `FISH_BUDGET=<ledger+3> python3 fishcount/pipeline.py spikes/DH/clips/DH<n>.mp4 --id DH<n>_eval --no-scout --prompts fish --discover --zoom`.
- **Metrics** (fixed now):
  1. Discovery recall = reference taxa that end in a counted (non-queued) row of the right coarse group / reference taxa.
  2. Named-only recall = reference taxa that Spark names at the discovery step (counted or not).
  3. False discoveries = counted non-fish rows whose evidence frame shows no animal. Judged by Jiyul Ahn from the
     evidence crop alone, without being shown the label ("is this an animal: yes / no").
  4. Queue size and cost per clip.
  MaxN accuracy is not measured (four frames cannot count shrimp).
- **One run, reported whatever it shows.** No prompt, threshold or code change after seeing these results; a bug
  found here is reported, not fixed in these numbers. Results go into the paper (§6.3, limitations) and README
  even if they are poor.
