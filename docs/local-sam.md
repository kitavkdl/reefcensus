# Local SAM 3.1 (`FISH_SAM=local`)

SAM 3.1 can run on your own NVIDIA GPU instead of the Meta API. Only the SAM calls move: the pipeline, its caps and
its Spark calls are the same, and the output has the API's text format, so everything after SAM reads it as before.
Unset, nothing changes (the API, its cache keys and its command-line defaults).

## What leaves the machine
- **The video does not.** With `FISH_SAM=local`, or `FISH_PRIVATE=1` whatever `FISH_SAM` says, the code refuses
  every request that would carry a clip (an upload to `/files`, a SAM call to `/responses`, any request body with an
  `input_video`) before it is sent, and the long-video "upload ahead" never starts. A misspelt `FISH_SAM` blocks too.
- **Spark still gets pictures**: six whole frames on a 640-px sheet for scouting and discovery, crops and zoom sheets
  for the checks. Only use the local mode for footage whose owner allows those pictures to go to the Meta API.
- So `FISH_PRIVATE=1` means **the video file is not uploaded**, not "nothing leaves": Spark's frames and crops do.
  With SAM on the API it stops at the first SAM call.
- **Keep the Meta key in the repo's `.env` only**, beside `FISH_SAM=local` and `FISH_PRIVATE=1`: do not
  `export META_API_KEY` in the shell of a private machine, and do not create `~/.config/meta-api/key` there (the code
  reads that file when no key is set). A checkout without that `.env` then has no key and sends nothing; with the
  key file it would run in API mode, which uploads clips. The key file is not ignored in local mode instead, because
  the risky case is a checkout where `FISH_SAM` is not set at all.

## Setup (Linux or WSL2 with an NVIDIA driver; `nvidia-smi` must work)
Two virtual environments, because sam3 needs `numpy<2` and the pipeline pins `numpy==2.5.4` (cache bytes):

```bash
python3 -m venv ~/venv-main && ~/venv-main/bin/pip install -r requirements.txt
python3 -m venv ~/uvtool && ~/uvtool/bin/pip install uv && UV=~/uvtool/bin/uv
$UV python install 3.12 && $UV venv -p 3.12 ~/venv-sam
$UV pip install --python ~/venv-sam/bin/python torch torchvision --index-url https://download.pytorch.org/whl/cu126
$UV pip install --python ~/venv-sam/bin/python \
  "git+https://github.com/facebookresearch/sam3.git@31cb7e624e4fe95301b1be1d4e809111593d2e45" meta-sam-parser==0.1.0 \
  einops pycocotools psutil "opencv-python-headless<4.12" scipy pillow
~/venv-sam/bin/python -c "import torch, torchvision, sam3.model_builder; print(torch.__version__, torch.cuda.is_available())"
```

- **Python 3.12 for venv-sam.** sam3 needs `numpy<2`, which has no wheels for newer Pythons (3.14 fails to build);
  uv fetches a 3.12 without touching the system Python.
- **Match the CUDA build to the driver.** `nvidia-smi` prints the driver's CUDA version; pick the torch index at or
  below it (driver 560 = CUDA 12.6 → `cu126`; a `cu128` build sees no GPU there). Install torchvision from the same
  index: the PyPI one pulls in another torch and then has no `nms`.
- **The extra packages** are imported by sam3 31cb7e6 but not listed in its pyproject.
- **The worker works around three things in sam3 31cb7e6**, on its private names, and stops with an error naming
  this page when a sam3 does not look like that commit, so install the commit above: `start_session` cannot open a
  session on the 3.1 model (it passes `offload_state_to_cpu`), so the worker opens it; a box prompt's tracked masks
  are dropped on every frame without cached detections (all but the prompt's in a box-only call), so the worker gives
  each frame an empty one; the builder batches 16 frames (`FISH_SAM_BATCH` below). sam3 also marks an object it
  removes on a frame with the score -1e4; those records are left out, as the API has none.
- **A box prompt's conf is 1.0** on every frame (sam3 scores an object it was given as certain); the API's is not.
  Nothing in the count reads it; `evaluate.py`'s conf cut-offs do, so compare those by backend.
- **ssh or rsync to the GPU machine hangs after connecting** (key exchange stalls, a copy stops at once): the network
  path may drop large packets without telling the sender. Lower the MTU on that link, or connect through a
  `ProxyCommand` that sets a small TCP maximum segment size (about 1100 bytes worked).

The checkpoint (`facebook/sam3.1`, `sam3.1_multiplex.pt`) is gated: accept the terms on Hugging Face with your own
account and put a read token in `~/.cache/huggingface/token`. Then, in the repo's `.env`:

```
FISH_SAM=local
FISH_PRIVATE=1
FISH_SAM_PYTHON=/home/<you>/venv-sam/bin/python
META_API_KEY=...          # Spark only
```

Run the pipeline with `~/venv-main/bin/python fishcount/pipeline.py ...` as usual. Before anything is paid it starts
the worker and checks it (torch sees CUDA, the GPU, the sam3 commit, the checkpoint and its sha256); a problem stops
the run there.

| Variable | Default | What |
|---|---|---|
| `FISH_SAM` | unset = `api` | `local` runs SAM here; anything else but `api` is refused |
| `FISH_PRIVATE` | unset | any value but `0`: SAM must be local, no clip leaves (Spark's frames and crops still do) |
| `FISH_SAM_PYTHON` | — | the sam venv's python (required for local) |
| `FISH_SAM_CHECKPOINT` | Hugging Face download | a checkpoint file to use instead |
| `FISH_SAM_FPS` | 2 | frames a second the GPU tracks; sets each call's time limit (frames / fps x 3 + 60 s, at least 120 s, +600 s for the model load) |
| `FISH_SAM_ENCODERS` | 4 | processes that encode masks (CPU) |
| `FISH_SAM_OFFLOAD` | unset | `1` keeps the video frames in RAM instead of GPU memory |
| `FISH_SAM_BATCH` | 1 | frames sam3 detects and post-processes together (its own 16 needs ~21 GB); raise it only on a bigger GPU |

## How it behaves
- **One SAM call at a time.** The worker (`fishcount/samworker.py`, run with the sam venv's `python -I`) is one
  process per pipeline process; it and the worker hold `~/.cache/fishcount/sam_local.lock` while the worker lives
  (whatever `FISH_CACHE_DIR` says, and still if the pipeline process is killed): a second process on the same
  machine (another CLI, the web server) stops at once instead of loading a second model into the GPU. On the command line
  `--segment-workers` and `--refill-ahead` default to 1 and refuse more.
- **Money.** Local SAM is free: `--max-usd`, `--max-usd-video`, the `--skip-empty` cap and `FISH_BUDGET` count Spark
  only. Each machine has its own `cache/ledger.jsonl`, so `FISH_BUDGET` on this machine is the only cap on its spend.
- **Failures stop the run.** A worker that dies is started once more and the call sent again; a second death, a time
  limit or an error (e.g. CUDA out of memory) raises `LocalSamError`, which no stage swallows: the run ends with the
  error, `status.json` counts it in `local_failures` (a long video: the segment's), `batch.py`'s `videos.csv` has a
  `local_failures` column, and `--resume` runs that segment again. It is never sent to the API instead.
- **Cache.** A local answer's key adds `backend: sam3.1-local:<checkpoint sha 12>:<sam3 commit 7>`, so it never stands in
  for an API answer or another checkpoint's, and an API answer is not reused by a local run. The same backend goes into
  `--resume` fingerprints and `provenance.json` (`models.sam`, `models.sam_local`). An `--offline` replay of a local
  run needs the same backend name, so it starts the worker (no GPU needed) on the machine that holds the videos.
- `status.json` counts local calls as live calls and in `local_calls`.

## Known differences from the API
- **Box prompts** (`<{f}f>1<|box;...|>`) track that one object both ways from frame f, with the prompt's id, as the API
  does (133 of 135 cached API box answers have one id; the two others had several boxes). Locally a box is given to SAM
  as its two corner points.
- **Word prompts** number tracks from 0 in order of first appearance and keep at most 16 ids per call (the API's limit,
  which `tracks.py` and the 16-id re-runs read).
- A **box** in the output is its mask's bounds. The API's box is the same for 95.4% of its records (2,183 of 2,289
  sampled) and a pixel or so wider for the rest.
- **conf** is one number per track (as 94% of the API's tracks), here SAM's mean per-frame probability; it may not mean
  what the API's does. Only `evaluate.py`'s cut reads it.
- Whether local and API counts agree is measured, not assumed: one SAM call against another, then whole runs, on
  public videos before any private footage.

## Tests on a machine with local SAM
The repo's `.env` sets `FISH_SAM`; run the tests with it empty so they see the API settings they were written for:
`FISH_SAM= FISH_PRIVATE= python3 -m unittest discover -s tests`.
