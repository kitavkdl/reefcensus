#!/bin/bash
# 11/3 evening: frozen evaluations (tag cr2) then LONG1 (LONG1_cr2) on the code with repair_ids + shadow look.
cd "$(dirname "$0")/../../.."
TAG=cr2 bash report/paper/scripts/rerun_cr.sh
echo "== LONG1_cr2"
python3 report/paper/scripts/rerun_long1_cr.py LONG1_cr2
echo "== all done"
