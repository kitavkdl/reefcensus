# meta-fish — MaxN review accelerator for underwater survey video

Say what to count; get per-species MaxN and time of first arrival **with an evidence frame behind every number**,
and a short queue of uncertain tracks for a human to confirm. Built during the Meta AI hackathon (Oct 26 – Nov 4, 2026).

- **SAM 3.1** (Meta Model API) tracks generic categories ("fish", "shark") through the video — no training.
- **Muse Spark** looks at a contact sheet and proposes what to track and where faint animals hide (zoom tiles),
  then audits every track crop (species, is-it-really-a-fish, confidence). Low-confidence tracks go to a human.
- All API calls are cached by content hash and metered against a budget (`FISH_BUDGET`, default $1).

```
python3 fishcount/pipeline.py <video> [--zoom] [--offline] [--no-scout] [--no-audit]
python3 fishcount/evaluate.py            # recall/precision/MaxN error vs. luderick ground truth
```

## Data credits
- Ditria, E.M. et al. (2021) luderick-seagrass dataset, CC BY 4.0 — github.com/globalwetlands/luderick-seagrass
- Monk, J., Barrett, N., Langlois, T. (2024) Curated underwater video highlights of marine protected areas,
  IMAS, University of Tasmania, CC BY 4.0
