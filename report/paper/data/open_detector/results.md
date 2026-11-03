# Open-vocabulary detector baseline — results (protocol: `report/paper/open_detector_protocol.md`)

Run 2026-11-03 (UTC 06:22–09:50), OWLv2 base ensemble, CPU, 17 queries, every frame of the 15 discovery clips
(`runs/vswap_<clip>/clip.mp4`, 900 frames). Scored with `open_detector.py --score` (`summary.json`); the split by
query below uses the same overlap rule (IoU ≥ 0.3 in ≥ 3 frames) and was computed from `detections.json` because the
scorer does not print it (the protocol lists "how many come only from 'animal'" as reported).

| threshold | counted non-fish tracks overlapped (of 45) | only "fish" | a non-fish word | right-group word | only "animal" | clips / frames with an "animal" box | non-fish boxes off every pipeline track |
|---|---|---|---|---|---|---|---|
| 0.1 | 39 | 14 | 24 | 12 | 0 | 5 / 40 | 6,107 of 8,123 |
| **0.2 (primary)** | **39** | **17** | **21** | **11** | **0** | **3 / 30** | **1,716 of 2,903** |
| 0.3 | 37 | 19 | 18 | 10 | 0 | 2 / 22 | 685 of 1,530 |

- Missed at 0.2: DH7 crab × 5 (of 8 counted DH7 tracks), s004 caridean shrimp × 1 (of 19).
- Per clip at 0.2 (counted non-fish / overlapped / right word / loose boxes): DH1 1/1/1/14, DH2 2/2/2/210,
  DH3 3/3/3/351, DH4 0/0/0/92, DH5 0/0/0/266, DH6 0/0/0/34, DH7 8/3/2/43, DH8 0/0/0/8, DH9 0/0/0/0, DH10 0/0/0/0,
  DH11 1/1/0/232, s001 5/5/0/156, s002 2/2/2/92, s003 3/3/1/65, s004 20/19/0/153.
- CPU: 14.9 s per frame on average (840–991 s per 60-frame clip, `DET_THREADS=4`, shared 6-core server).
- Added after the protocol: s004 "hagfish" (d2rev:1), outside measure 1 because its name maps to the fish group,
  overlapped in 29 frames at 0.1 and 0.2, 28 at 0.3.
- Measure 2's loose boxes were not judged (no crop judgement made).
