# Site memory (design, 11/3)

Goal: when a reviewer renames or confirms a queued row, the next video from the same site starts with that word, so the
correction carries over. Added after the evaluation; **off unless a site is given** (`--site NAME` / the "Site" field);
no paper number uses it.

## Data
`runs/_site_memory/<site>.json` (inside the git-ignored `runs/`, which the run list skips because it has no status.json; folder overridable with `FISH_SITE_DIR`):
`{"site": "...", "records": [{"run","track","label","noun","alt","t"}]}`. `label` = what the person typed or confirmed,
`noun` = the plain noun SAM is asked for (`pipeline.short_name(label)`, e.g. "red crab" -> "crab"), `alt` = the word that
actually tracked that animal in the earlier run when it was not a request word (in s004 the reviewer name "hagfish" gave SAM
0 frames, "eel" gave 24, so a name alone can waste a call). Module: `fishcount/sitememory.py` (`plan`, `record`, `forget_*`).

## Site identity
Explicit only: `--site NAME` (pipeline CLI), `site` field in `POST /api/run` and a text box in the new-run form. Lowercased,
`[a-z0-9][a-z0-9._-]{0,40}`, so it is safe as a file name. No guessing from the clip name or GPS.

## When words are recorded
Review actions in `server._save_review` are: a string label (button "Yes, <guess>" and "Rename" both send it), `null`
("Not an animal"), `"__undo__"`. A string label is recorded only when (a) the run was started with a site, (b) it differs from the
automatic label (it is a correction, not Spark's own answer confirmed) and (c) it matches `[a-z][a-z -]{0,40}` and is not
"... (unidentified)". One record per run+track, replaced by a new label. `null`, `__undo__`, the automatic label and labels that teach
nothing delete that track's earlier record. The record is written after `review.json`; a failure never loses the review.
A segment run `<id>__S2` and the merged run `<id>` of one long video share record keys.

## How words enter a run
`run_pipeline(..., site=None)`; with a site, a new step `pipeline.site_look` runs **after discovery, the second look and the
motion look** (their inputs and cache keys stay those of a run without site). `sitememory.plan` returns up to `MAX_ENTRIES = 3`
entries, ranked by the number of different videos that confirmed them (not tracks; ties: most recent). Each entry is a SAM word
ladder `[noun, alt]` (existing `word_ladder`: stops at the first word that tracks anything). Words the request or discovery
already tracked are skipped. Entries that would pass `--max-usd` (billed so far + worst case) are dropped, least confirmed first.
In a free replay an uncached word is recorded as not tried, not an error. Results go **first** in the merge order, source names
`k0..` (a remembered specific kind wins overlaps against the catch-all "fish", as scout words do); the label is the word that
tracked, the audit target is the reviewer's label, and labels only site memory produced are audited after all others so the other
labels keep their track numbers and cached sheets. Discovery, `found`, "You asked for" and the request words are untouched; the
step writes one separate key, `result["site"] = {name, entries:[{label, words, tried, word, frames, source}]}` (the words
actually used, so a run can be explained later).

## Cost (from code)
One SAM call = `max(SAM_MIN_FRAMES=50, frames) * $0.0002` -> 12 s clip (60 frames) $0.012; 5 min $0.30; 10 min segment $0.60.
An entry costs 1 call if its first word tracks, 2 if the ladder falls through, so worst case 3 entries = 6 calls = $0.072
at 12 s (0 extra if the memory is empty; a call whose answer is already in `cache/` costs $0). Plus Spark for any new label: 1 audit sheet per 12 tracks (ledger mean $0.004 per
Spark call) and the peak check if the label counts. Entries that would pass `--max-usd` are dropped instead of failing the run. With `--segment`, every segment pays it again.

## UI
Rows whose tracks came from a site word show "From site memory (<site>): <label>, tracked as '<word>', N frames" in the
"Found without being asked" panel (they are not "asked", so they stay orange in the video); the found panel names the site
and lists words tried with frames, including those that tracked nothing. In the queue, a saved rename says "Remembered for
site <site>" (nothing is said when the label teaches nothing).

## Off by default
`site=None` is the default everywhere; no site code runs, `result.json` has no `site` key, and the review action writes
nothing. `longvideo.merge` builds one `site` block from the segments (entries tagged with their segment) so reviews of merged runs are remembered too.

## Review
Independent read by a new sonnet subagent that was given only the goal, this file and the code paths (first draft of this
design). Its points, most severe first, and what was done:

| # | point | decision |
|---|---|---|
| 1 | A wrong remembered word silently lowers counts (site results first in `tracks.merge` take overlapping boxes); "Yes, <guess>" confirms Spark's own low-confidence guess; ranking by tracks lets one video outvote; words not stored per run | **Applied in part.** Record only corrections that differ from the automatic label; rank by videos; `result["site"]` stores the words used; `sitememory.py list/forget`; Undo forgets. **Rejected:** moving site results last in the merge: then a remembered word could never relabel what "fish" already tracks, which is the point. The risk stays (a bad word steals boxes with IoU >= 0.5 and the audit may reject them), noted here. |
| 2 | Free replay: an uncached word raises `FileNotFoundError` and the run fails | **Applied.** `site_look` catches it, records `error`, run continues (test). |
| 3 | Putting site entries into `found`/`discovered` breaks `recover`'s zip, audit `context`, `seen`, motion names, `drawFound` | **Applied.** Own key `site`; `found`/`others`/`context` untouched. |
| 4 | Audit numbering is by label; "site-only last" must be a separate pass | **Applied in part.** Site-only labels sorted last. A site label shared with a motion track's label would share a sheet; request/discovery words are excluded from site words, so only motion labels can collide (rare, noted). |
| 5 | Site SAM spend can make `recover`/`motion_look` skip themselves; estimate ignores it | **Applied.** `site_look` runs after them and checks `billed_usd + worst case` against the cap. Under `--segment` each segment pays again (stated above). |
| 6 | Adding site words to `used` stops discovery trying the head noun | **Applied.** `used` unchanged; discovered words are skipped on the site side instead. |
| 7 | Site results in `results` change the `motion_look` cache key | **Applied.** Site results are added after the motion look. |
| 8 | Long videos: `merge` drops `site`; per-segment plans; segment runs `rid__S1` are reviewable and would be recorded twice | **Applied.** `merge` builds one block with segment-tagged entries; `sitememory.canon` keys segment and merged runs alike. |
| 9 | `_save_review` ordering; per-process lock; stale records after `--id` re-run or deleted run | **Applied** (record after `review.json`, never raises; `flock` across processes). **Rejected, documented:** automatic cleanup of stale records; use `sitememory.py forget SITE WORD`. |
| 10 | `demo/build_static.py` patches `app.js` by string/regex | **Checked, nothing to change:** `review()` and the `/api` strings are untouched; `build_static.py` runs. |
| - | Dependents: positional `run_pipeline` callers; numbers must not move when off; exports have no site column | `site=None` is the last parameter; `test_site_run_with_nothing_usable_gives_the_saved_counts` replays s004 with and without `site` and checks the saved counts and that `result.json` has no `site` key when off. **Rejected:** a site column in the CSV exports (the `origin` column says "found"; the screen shows the badge). |

Process note: `fishcount/sitememory.py` existed as an untracked draft when the review was requested (the subagent saw it);
nothing in `pipeline`, `server`, `longvideo` or the UI used it yet.

## Demo (11/3, real calls; clips nautilus s002/s003/s004, 12 s, 60 frames)
Ledger before $14.075234, `FISH_BUDGET` = $56.075234 (before + 42), `--max-usd 0.6`; total spent by the demo **$0.0181**
(ledger $14.093380 after). Runs are in `runs/` (git-ignored); memory files in `runs/_site_memory/`.

**1. A rename from the review screen's API (`POST /api/runs/site_demo_A/review`).** `site_demo_A` = the s002 clip, run with
`--site nautilus-bait` (free replay of the saved answers). Its queued track `p0:1` (Spark: "reddish stationary shape likely crab",
0.5) was confirmed as "red crab" (what the "Yes, red crab" button sends; a simulated reviewer action, not a verified
identification). Memory: `crab`. Next videos, same site, discovery on, live allowed:

| run | words used | frames tracked for the remembered word | counts before -> after | cost |
|---|---|---|---|---|
| `site_demo_Bs004_before` -> `_after` | request fish + Spark's own + `crab` | 0 | same (caridean shrimp 12, nautilus 1, hagfish 1, shrimp (unidentified) 3; run on the frozen defaults, the current demo run gives 14 + 2) | $0 (the answer for `crab` on this clip was cached from the discovery ladder) |
| `site_demo_Bs003_before` -> `_after` | same | 0 | same (nautilus 3) | $0 |

Result: no effect. SAM finds no "crab" at full frame in these clips (it needed a 3x zoom on s002 itself), so the memory was
used, tried and recorded, and changed nothing. That is the honest result for this word.

**2. A word that does track (staged).** In s004 the reviewer-facing name "hagfish" gave SAM 0 frames and "eel" gave 24
(`mg2_s004`). `site_demo_A2` = s004 with `--site hagfish-site` (free replay). Its track `d2rev:1` is already auto-labelled
"hagfish", so a rename would not be a correction and nothing would be recorded; the entry was therefore **written directly with
`sitememory.record("hagfish-site", "site_demo_A2", "d2rev:1", "hagfish", alt)`**, `alt` = `sitememory.source_word(...)` = `eel`,
the same call the review hook makes. Memory: ladder `[hagfish, eel]`. Then a run with the request word "fish" only, discovery off,
so Spark never names the animal:

| run | words used | frames for the remembered word | counted | cost |
|---|---|---|---|---|
| `site_demo_H_before` (s004, no site) | fish | - | nothing | $0 (cached) |
| `site_demo_H_after` (s004, `--site hagfish-site`) | fish + `hagfish`, `eel` | `hagfish` 0, `eel` 24 | **hagfish 1** (MaxN 1 at 1.4 s, audit confirmed, row marked "From site memory") | $0.0061 live (2 Spark calls; both SAM answers were already cached, uncached they would be 2 x $0.012) |
| `site_demo_H3_before` -> `_after` (s003, a different clip) | fish + `hagfish`, `eel` | 0 and 0 | nothing -> nothing | $0.012 (one new SAM call) |

Limits: the s004 case is the clip the word came from (a mechanism check, not generalisation); on the one other clip tried
the words found nothing and cost $0.012. Nothing here is evidence that site memory improves counts, only that the step works,
costs what the code says, and shows where a row came from.
