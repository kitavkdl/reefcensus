#!/bin/bash
set -e
FF=${FFMPEG:-$HOME/meta-smoke/pylib/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2}   # the ffmpeg shipped with imageio-ffmpeg
D=$HOME/meta-fish/data_long/sefsc1
B="https://storage.googleapis.com/nmfs_odp_sefsc/PEMD/VIDEO_DATA/GOM_REEF_FISH/Jack_Videos/sefis%20video/T60233001_A"
i=0
for f in GOPR1512 GP011512 GP021512; do
  i=$((i+1))
  curl -sS --fail -o $D/orig/$f.MP4 "$B/$f.MP4"
  sha256sum $D/orig/$f.MP4 >> $D/sha256.txt
  $FF -hide_banner -i $D/orig/$f.MP4 2>&1 | grep -E "Duration|Stream #0:0" >> $D/ffprobe.txt || true
  $FF -hide_banner -loglevel error -y -i $D/orig/$f.MP4 -vf "fps=5,scale='min(1920,iw)':-2" -an -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p $D/proxy/part$i.mp4
  rm $D/orig/$f.MP4
  echo "done $f $(date)" >> $D/fetch.log
done
for i in 1 2 3; do echo "file '$D/proxy/part$i.mp4'"; done > $D/proxy/list.txt
$FF -hide_banner -loglevel error -y -f concat -safe 0 -i $D/proxy/list.txt -c copy $D/sefsc1_5fps.mp4
echo "ALL DONE $(date)" >> $D/fetch.log
