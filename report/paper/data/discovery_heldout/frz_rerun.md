# DH1–DH5 — re-run of previously seen data on the final frozen code (`cbaf59b`)

Labelled as a re-run of previously seen data (protocol amendment 2 of `discovery_heldout2_protocol.md`): these five
clips were scored on the earlier code, so this run is not held out. Ids `DH<n>_frz`; summary
`runs_summary_frz.json` (same scorer functions, run directory switched to `_frz`). Cost $0.035 (most answers cached).

| clip | reference (unchanged) | Spark named | counted (non-queued) | in MaxN, queued (non-fish) | queue |
|---|---|---|---|---|--:|
| DH1 | crab-like | crab | crab 1 | — | 1 |
| DH2 | crab-like [anemone-like] | sea anemone, crab, eel | crab 1; sea anemone 1 | coral (unidentified) 1 (0.4); crab (unidentified) 1 (0.45) | 5 |
| DH3 | crab-like; shrimp/lobster-like [radial] | spider crab, sunflower sea star, squat lobster shrimp | spider crab 3 | crab (unidentified) 1 (0.6) | 6 |
| DH4 | none | — | none | — | 0 |
| DH5 | none | small shrimp | fish (unidentified) 8, pink cusk-eel 1 (fish) | — | 14 |

Protocol metrics are the same as the first run: discovery recall 3/4 counted (the squat-lobster-like animal stays out
of the count; Spark names it), named-only recall 4/4, false discoveries 0 among counted rows (the counted rows are the
same as in the judged first run). New with the final code: three non-fish rows that are in the MaxN but queued
(a second look named another animal group or was unsure); they were not judged with labels hidden and are reported
apart, as amendment 2 requires.
