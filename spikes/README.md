# spikes/ - development experiments
The experiments of the hackathon (Oct 26 - Nov 4, 2026) that led to the pipeline in `fishcount/`. Not needed to run
reefcensus (`web/server.py`, `fishcount/`). Paths here are referenced by the paper, `web/server.py` and the main
README, so they stay where they are. Untracked scratch output (images, logs, file lists) is git-ignored.

Subfolders (each has `clips/`, `out/` = raw SAM text, `data/` = ignored inputs):
- `A/` spectrogram-as-video (`specvid.py`): audio calls tracked as objects; early idea exploration, not part of reefcensus
- `B/` SDO sun images (sunspot prompts); early idea exploration, not part of reefcensus
- `C/` ice-floe videos; early idea exploration, not part of reefcensus
- `D/` sonar video (`D1_sonar_kenai`); early idea exploration, not part of reefcensus
- `E/` thermal video (`rangezip.py` lists/extracts remote zip members); early idea exploration, not part of reefcensus
- `F/` AI-video object-permanence check (`lifecycle.py`); early idea exploration, not part of reefcensus
- `G/` kitchen contact graph (`contact.py`, `maskcontact.py`, `timeline.py`); early idea exploration, not part of reefcensus
- `DH/` held-out discovery evaluation clips (made by `report/paper/scripts/prep_discovery_heldout.py`, protocol `report/paper/discovery_heldout_protocol.md`)
- `L1/` discovery: Spark names what was not asked, SAM tries the words (`discover.py`); led to `--discover`
- `M/` s004 box prompts (`s004_boxA/B.txt`); exploratory
- `control/` IMAS clip `imas_TF_52` with a "fish" prompt, as a control
Scripts:
- `run.py` run SAM on a spike clip through `fishcount.api` (cache + ledger) and summarise tracks
- `evid.py` evidence sheet: chosen frames with SAM masks and track IDs
- `motion.py`, `motion_sheet.py` motion candidates from pixels alone (no model call) and a contact sheet of them
- `maskcheck.py` checks the C mask decoder against `meta_sam_parser` on every cached SAM output
- `maskdup.py`, `maskpair_img.py`, `pairdry.py` mask-containment and nested-pair checks, replayed offline ($0)
- `make_report.py`, `make_report2.py` HTML reports of the Nov 1 non-camera spikes
