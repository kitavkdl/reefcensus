# reefcensus — count what you asked for, find what you didn't

Say what to count; get per-species MaxN and time of first arrival **with an evidence frame behind every number**,
and a short queue of uncertain tracks for a human to confirm. Built during the Meta AI hackathon (Oct 26 – Nov 4, 2026).

- **SAM 3.1** (Meta Model API) tracks generic categories ("fish", "shark") through the video — no training.
- **Muse Spark** looks at a contact sheet and proposes what to track and where faint animals hide (zoom tiles),
  then audits every track crop (species, is-it-really-a-fish, confidence). Low-confidence tracks go to a human.
- **Discovery** (`--discover`): SAM finds nothing for a vague word like "animal" — it only sees what you name.
  So Spark looks for living things the request did *not* ask about (and indirect signs such as sediment puffs),
  names each with plain nouns, and SAM tries them in turn (word ladder) until one tracks.
- All API calls are cached by content hash and metered against a budget (`FISH_BUDGET`, default $1).

```
pip install -r requirements.txt     # Meta API key in ~/.config/meta-api/key
python3 fishcount/pipeline.py <video> [--discover] [--zoom] [--offline] [--no-scout] [--no-audit]
python3 fishcount/evaluate.py            # recall/precision/MaxN error vs. luderick ground truth
python3 web/server.py                    # review screen on http://127.0.0.1:8793
```

The review screen plays the annotated clip (blue = asked for, orange = found without being asked) over a per-species
count strip on the same timeline, shows each MaxN as a tally with its evidence frame, the second-look log, and a queue
of low-confidence tracks to confirm, rename or remove (counts and the CSV are recomputed from your edits).
New runs replay saved API answers for free unless "Allow paid API calls" is ticked (capped at $2 a run).

## Data credits
- Ditria, E.M. et al. (2021) luderick-seagrass dataset, CC BY 4.0 — github.com/globalwetlands/luderick-seagrass
- Monk, J., Barrett, N., Langlois, T. (2024) Curated underwater video highlights of marine protected areas,
  IMAS, University of Tasmania, CC BY 4.0
- Barord, G.J. et al. (2014) Comparative population assessments of Nautilus sp., PLOS ONE 9(6): e100799,
  supplementary videos S1–S4, CC BY 4.0 (via Wikimedia Commons)

## License
MIT (code). Videos and datasets keep their own licenses above.
