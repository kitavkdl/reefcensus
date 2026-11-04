# Fixed-vocabulary baseline on the BRIGHTENED s001 clip (like-for-like)

The earlier baseline (`../fixed_vocab/`) ran the 16 fixed words on the dark original of s001 (`runs/L1_s001_v16/clip.mp4`),
while the pipeline counts on the brightened copy. This reruns the same words on the same brightened frames the
pipeline used.

- Clip: `runs/mg2_s001/clip.mp4` (the pipeline's auto-brightened clip: gamma 0.5 + CLAHE 2.0; md5 21d38d576f0c7338a33daf3a504af27b,
  identical to `runs/lowlight_s001_gamma_clahe/clip.mp4`); 60 frames, 5 fps, 1920x1080.
- Command (from repo root, code commit `96a1a8c`): `FISH_BUDGET=<ledger+3> python3 report/paper/scripts/fixed_vocab_brightened.py`
- Words: the same 16 as `fixed_vocab.py` + 'nautilus' (17 SAM passes, full frame, no zoom, no reversed pass).
- Cost: 14 live SAM calls x 60 frames x $0.0002 = **$0.168** (billed numbers logged by the run); 3 words ('fish', 'shell',
  'nautilus') were already cached for this clip (cost 0).
- Scoring: as in `fixed_vocab.py` (a word track "matches" when IoU >= 0.3 on >= 3 frames with a track the final
  run counted); reference = the 5 counted nautilus tracks of `runs/mg2_s001/result.json` (MaxN 4).

## Result
- **16 of 17 words: 0 frames.** Including 'nautilus' (0 frames), 'snail' and 'octopus' (on the dark original 'octopus' tracked a
  spot for 57 frames; on the brightened clip it tracks nothing).
- **'shell': 1 track, 9 frames (frames 51-59 of 60), MaxN 1**, and that track matches one of the four counted nautiluses
  (pipeline track d0:1, same box on frame 51). So the list reaches one of the four animals, for 9 of 60 frames, under
  the name "shell"; the other three nautiluses get no track from any of the 17 words.
- Dark original (earlier baseline): 16 of 17 words 0 frames; 'octopus' 57 frames matching no counted animal; 'shell' 0.
- Pipeline on the same brightened clip: 4 nautiluses, tracked 58-60 of 60 frames each (motion box prompts, no word).
