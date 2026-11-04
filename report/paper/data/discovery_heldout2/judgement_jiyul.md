# Pipeline crop judgement (metric 3) — Jiyul Ahn (label-free, from `crops_sheet.jpg` only; labels not seen)

Question per crop: "is this an animal: yes / no" (coarse group if clear). Jiyul Ahn's answer: "#1 a crab; #2 a bug/worm?
or a crustacean."

| Crop | Judgement | (row, added after the judgement) |
|---|---|---|
| 1 | animal — crab | DH7 'crab', counted, MaxN 3, conf 0.95 |
| 2 | animal — bug/worm or crustacean | DH11 'scavenging amphipod crustacean', counted, MaxN 1, conf 0.95 |

No "in MaxN, queued" non-fish row exists in DH6–DH11, so there is no separate judgement for that category.

## Addendum 2026-11-04: the "in MaxN, queued" row of the re-run `DH7_cr3`
The re-run with the new defaults (`DH7_cr3`) has one such row, "crab (unidentified)" MaxN 1, from two tracks Spark
called crab at 0.6 (T3, frame 22; T13, frame 58). Both were shown to Jiyul Ahn as label-free crops (box only,
`#1`/`#2`). Answer: "#1 a fish, #2 looks like a crab." Both are animals, so no false discovery; the name of #1 differs
(crop sheet kept outside the repo: ops `sessions/meta-hackathon/build/dh7crop/`).
