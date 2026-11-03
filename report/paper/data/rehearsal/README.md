# Empty-cache rehearsals through the web screen (§7.5)

Four live takes of the screen a viewer uses (`web/server.py`, `POST /api/run` with `{"prompts": ["fish"],
"discover": true, "allow_api": true, "max_usd": 0.6}`; the screen runs with audits on). Before every
take the server was restarted with a new, empty `FISH_CACHE_DIR`, so every model call is fresh (`cached_calls: 0`
in each `status.json`). Each folder holds that take's `status.json` (log lines, calls, cost) and `result.json`.
Purpose: how much a fresh run moves, before choosing the clip for the live scene of the video. Not a scored
evaluation; no code change between takes.

| take | clip | wall clock | live / cached calls | billed | counted (MaxN) | queue / note |
|---|---|---|---|---|---|---|
| `DH11_1103-035902` | DH11 (held-out, Cuvelier et al. 2014) | 115 s | 25 / 0 | $0.257 | pink amphipod-like crustacean 1 | 2 motion boxes (tube openings) |
| `DH11_1103-040128` | DH11 | 121 s | 23 / 0 | $0.249 | none | the amphipod track queued (second look: "Static against seabed") |
| `nautilus_s003_0_12_1103-091310` | s003 (development, Barord et al. 2014) | 156 s | 21 / 0 | $0.212 | chambered nautilus 1 | Spark proposed "cephalopod", "shell", "snail" for "chambered nautilus cephalopod"; "nautilus" never tried; zoom-centre "cephalopod" 40 frames counted |
| `nautilus_s003_0_12_1103-091555` | s003 | 166 s | 19 / 0 | $0.196 | nautilus 3 | "nautilus" 38 frames, reversed 60; same as the demo run `mg2_s003` (3) |

- No take counted a non-animal. The motion box M3 near the trap in s003 ("small dark shrimp" / "small dark fish",
  tracked 60 of 60 frames) went to the queue or was dropped in both takes; a person judged that spot not an animal
  earlier (it does not hold its shape across frames).
- DH11 takes ran at code `9056d80` plus uncommitted site-memory changes (site memory off by default); s003 takes ran
  at `8687166`. Spend: ledger stages "live rehearsal, empty cache" and "live rehearsal s003" in
  `report/paper/scripts/ledger_summary.py`.
