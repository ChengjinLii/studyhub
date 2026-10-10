#!/usr/bin/env bash
# Regression tests for the render tooling. Each test names the review finding it covers.
# Usage: bash tests/test_tooling.sh     (needs Chrome, node, python3 + numpy, ffmpeg; ~30 s)
set -u
cd "$(dirname "$0")/.."
T=.work/tests
rm -rf "$T"; mkdir -p "$T"
PASS=0; FAIL=0
ok() { echo "PASS  $1"; PASS=$((PASS + 1)); }
ko() { echo "FAIL  $1"; FAIL=$((FAIL + 1)); }

# Codex review 2026-10-09, P1 (build.sh START): a clip whose --from is not a whole frame must use the renderer's
# frame boundaries: --from 0.02 --to 0.62 -> frames 1..18 (round(0.6)=1, round(18.6)=19), so 18 frames and 0.6 s of audio.
if bash render/build.sh --from 0.02 --to 0.62 --blur 2 --scale 0.25 --workers 2 --out "$T/clip.mp4" > "$T/build.log" 2>&1; then
  n=$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 "$T/clip.mp4")
  d=$(ffprobe -v error -select_streams a:0 -show_entries stream=duration -of csv=p=0 "$T/clip.mp4")
  if [ "$n" = 18 ] && python3 -c "import sys; sys.exit(0 if abs(float('$d') - 0.6) < 0.03 else 1)"; then
    ok "build.sh: fractional --from renders frames 1-18 (18 frames, audio ${d} s)"
  else
    ko "build.sh: expected 18 frames and ~0.6 s audio, got $n frames and ${d} s"
  fi
else
  ko "build.sh: fractional --from failed (see $T/build.log)"
fi

# Codex review 2026-10-09, P1 (render.mjs still names): two still times that map to the same file name must be rejected,
# not silently overwrite each other.
if node render/render.mjs --times 1.201,1.204 --out "$T/stills" > "$T/stills.log" 2>&1; then
  ko "render.mjs: still times 1.201 and 1.204 both wrote t_01.20.png"
elif grep -q "same file name" "$T/stills.log"; then
  ok "render.mjs: colliding still names are rejected"
else
  ko "render.mjs: failed for another reason (see $T/stills.log)"
fi

# Codex review 2026-10-09, P2 (qc.sh filtergraph escaping): QC must work on a file name with a comma.
ffmpeg -v error -y -f lavfi -i testsrc=size=320x240:rate=30 -f lavfi -i sine=frequency=440:sample_rate=48000 -t 1 \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -ac 2 "$T/cut,final.mp4"
if bash render/qc.sh "$T/cut,final.mp4" "$T/qc" > "$T/qc.log" 2>&1 && [ "$(wc -l < "$T/qc/luma.csv" | tr -d ' ')" -ge 30 ]; then
  ok "qc.sh: file name with a comma is measured (luma for every frame)"
else
  ko "qc.sh: file name with a comma failed (see $T/qc.log)"
fi

echo "passed $PASS, failed $FAIL"
[ "$FAIL" = 0 ]
