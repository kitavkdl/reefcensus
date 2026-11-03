#!/bin/bash
# Disk housekeeping for the LONG1 run (see README.md). Deletes only regenerable intermediates of FINISHED segments.
R=$HOME/meta-fish/runs
SRC=$HOME/meta-fish/data_long/sefsc1/sefsc1_5fps.mp4
while true; do
  for s in "$R"/LONG1__S*/; do
    [ -f "$s/status.json" ] || continue
    if grep -q '"stage": "done"' "$s/status.json"; then
      rm -f "$s"/tile_*.mp4 "$s"/clip_rev.mp4
      n=$(basename "$s"); k=${n##*__S}
      rm -f "$R/LONG1/seg$k.mp4"
      [ "$k" = 1 ] && rm -f "$SRC"
    fi
  done
  grep -q '"stage": "done"' "$R/LONG1/status.json" 2>/dev/null && exit 0
  sleep 60
done
