#!/bin/bash
# 11/3: every frozen evaluation once more with clean + refill on (the new defaults), tag "cr". Old runs stay as they were.
# FISH_BUDGET (env) is the hard cap on the whole ledger. Each step skips runs that already have a result.json.
set -u
cd "$(dirname "$0")/../../.."
P=fishcount/pipeline.py
DISC="--no-scout --prompts fish --discover --zoom"
run() { local id=$1; shift; [ -f runs/$id/result.json ] && { echo "skip $id"; return; }; echo "== $id"; python3 $P "$@" --id $id > runs/$id.log 2>&1 || echo "FAILED $id (runs/$id.log)"; }
echo "== luderick development (6)"; python3 fishcount/evaluate_pipeline.py --run --tag cr
echo "== luderick held-out (24)"; python3 fishcount/evaluate_pipeline.py --run --tag cr --manifest manifest_heldout.json
for k in 1 3 4; do run cr_s00$k spikes/L1/clips/nautilus_s00${k}_0_12.mp4 $DISC; done
run cr_s002 spikes/L1/clips/nautilus_0_12.mp4 $DISC
for n in 1 2 3 4 5; do run DH${n}_cr spikes/DH/clips/DH$n.mp4 $DISC; done
for n in 6 7 8 9 10 11; do run DH${n}_cr spikes/DHB/clips/DH$n.mp4 $DISC; done
echo "== done"
