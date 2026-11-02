# Spark-alone counting baseline — protocol (written and committed before any call)

Written 2026-11-02 ~09:50 UTC, for the second independent review's missing baseline 6(c): "can the VLM count on its
own, with no segmenter?"

- **Clips and frames**: the 6 development luderick clips (319 annotated frames) and the 24 held-out clips (445
  annotated frames), i.e. every annotated frame of both manifests. Nothing chosen by looking.
- **Call**: one Muse Spark call per annotated frame, the frame alone (resized to 1280 px wide, JPEG q85), same model
  and reasoning effort ("low") as the pipeline's audits. Prompt, fixed before any call:
  `PROMPT` in `report/paper/scripts/spark_count.py` (count every individual fish visible, partly visible or faint
  included; JSON `{"count": <integer>}` only). An unreadable reply gets the pipeline's one retry; if it fails again
  the frame is reported as missing, not re-asked.
- **Metric**: Spark MaxN = the largest per-frame count over a clip's annotated frames; compared with the human MaxN
  (all boxes, luderick and bream) as in Tables 1 and 1c: MaxN exact, within ±1, Σ|err|. Secondary: mean absolute
  per-frame count error against the number of human boxes (a lower-bound reference, since annotators omit some fish).
  No boxes are asked for, so there is no recall or precision.
- **One run, reported whatever it shows.** No prompt or resolution change after seeing results.
- **Cost**: estimated from one measured call before the run; the run proceeds only under the hackathon's per-task
  pre-approval ($3), otherwise the development clips alone are run and the held-out clips are reported as not run.
