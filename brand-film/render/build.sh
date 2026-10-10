#!/usr/bin/env bash
# Build the StudyHub brand film (or a clip of it): audio -> frames -> H.264/AAC MP4 with two-pass loudness mastering.
#
#   bash render/build.sh                                  # full film -> StudyHub_Brand_Film.mp4
#   bash render/build.sh --from 3 --to 7 --out out/clip.mp4
#   bash render/build.sh --scale 0.5 --blur 1 --out out/preview.mp4   # fast low-res preview
#   bash render/build.sh --layout landscape --out StudyHub_Brand_Film_16x9.mp4   # 1920x1080 cut
#
# Options: --from/--to seconds, --scale (1 = 1080x1920), --blur N sub-frames per frame (motion blur, 180-degree shutter),
#          --workers N Chrome pages, --layout portrait|landscape, --out file, --keep-frames (keep the PNG sequence).
set -euo pipefail
cd "$(dirname "$0")/.."

FROM=0; TO=30; SCALE=1; BLUR=16; WORKERS=6; LAYOUT=portrait; OUT=; KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM=$2; shift 2;;
    --to) TO=$2; shift 2;;
    --scale) SCALE=$2; shift 2;;
    --blur) BLUR=$2; shift 2;;
    --workers) WORKERS=$2; shift 2;;
    --out) OUT=$2; shift 2;;
    --layout) LAYOUT=$2; shift 2;;
    --keep-frames) KEEP=1; shift;;
    *) echo "unknown option $1" >&2; exit 2;;
  esac
done

if [ -z "$OUT" ]; then
  if [ "$LAYOUT" = landscape ]; then OUT=StudyHub_Brand_Film_16x9.mp4; else OUT=StudyHub_Brand_Film.mp4; fi
fi
FPS=30
# Snap --from/--to to whole frames once, with the renderer's rounding (JS Math.round = floor(x + 0.5)), and use the
# same boundaries for frames, sub-frame start index, audio trim and duration (Codex review P1).
F0=$(python3 -c "import math; print(math.floor($FROM * $FPS + 0.5))")
F1=$(python3 -c "import math; print(math.floor($TO * $FPS + 0.5))")
if [ "$F1" -le "$F0" ]; then echo "empty range: --from $FROM --to $TO" >&2; exit 2; fi
FROM=$(python3 -c "print($F0 / $FPS)")
TO=$(python3 -c "print($F1 / $FPS)")
DUR=$(python3 -c "print(($F1 - $F0) / $FPS)")
TAG=$(basename "$OUT" .mp4)
WORK=.work/$TAG
rm -rf "$WORK"; mkdir -p "$WORK"

echo "== audio"
python3 audio/compose.py --out "$WORK/audio" --from "$FROM" --to "$TO"

echo "== frames ($LAYOUT, $FROM-$TO s, scale $SCALE, blur $BLUR)"
node render/render.mjs --from "$FROM" --to "$TO" --scale "$SCALE" --blur "$BLUR" --workers "$WORKERS" --layout "$LAYOUT" --out "$WORK/frames"

echo "== encode"
START=$((F0 * BLUR))
# RGB -> BT.709 limited-range YUV (HD players assume BT.709; swscale's default matrix would be BT.601).
CONV="scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format=yuv420p"
if [ "$BLUR" -gt 1 ]; then
  # Average each group of BLUR sub-frames (tmix), keep one output frame per group, then retime to 30 fps.
  W=$(python3 -c "print(' '.join(['1'] * $BLUR))")
  VF="tmix=frames=$BLUR:weights='$W',select='eq(mod(n\,$BLUR)\,$((BLUR - 1)))',setpts=N/($FPS*TB),$CONV"
  IN_RATE=$((FPS * BLUR))
else
  VF="$CONV"
  IN_RATE=$FPS
fi
ffmpeg -hide_banner -loglevel error -y -framerate "$IN_RATE" -start_number "$START" -i "$WORK/frames/f_%06d.png" \
  -vf "$VF" -r $FPS -c:v libx264 -preset slow -crf 16 -profile:v high -pix_fmt yuv420p -tune animation -x264-params "colorprim=bt709:transfer=bt709:colormatrix=bt709:range=tv" \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv -an "$WORK/video.mp4"

# Two-pass EBU R128 loudness: -14 LUFS integrated. TP target -2 dBTP leaves margin for AAC overshoot, so the file stays <= -1 dBTP.
MEAS=$(ffmpeg -hide_banner -nostats -i "$WORK/audio/mix.wav" -af loudnorm=I=-14:TP=-2:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
mi=$(echo "$MEAS" | python3 -c "import json,sys; print(json.load(sys.stdin)['input_i'])")
mtp=$(echo "$MEAS" | python3 -c "import json,sys; print(json.load(sys.stdin)['input_tp'])")
mlra=$(echo "$MEAS" | python3 -c "import json,sys; print(json.load(sys.stdin)['input_lra'])")
mth=$(echo "$MEAS" | python3 -c "import json,sys; print(json.load(sys.stdin)['input_thresh'])")
moff=$(echo "$MEAS" | python3 -c "import json,sys; print(json.load(sys.stdin)['target_offset'])")
# EBU R128 needs >= 0.4 s; a shorter test clip measures -inf and is muxed without mastering.
AF="loudnorm=I=-14:TP=-2:LRA=11:measured_I=$mi:measured_TP=$mtp:measured_LRA=$mlra:measured_thresh=$mth:offset=$moff:linear=true,aresample=48000"
case "$mi" in -inf|inf|nan) echo "   clip too short for loudness measurement; audio left unmastered"; AF="aresample=48000";; esac
ffmpeg -hide_banner -loglevel error -y -i "$WORK/video.mp4" -i "$WORK/audio/mix.wav" \
  -af "$AF" \
  -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 256k -ar 48000 -ac 2 -t "$DUR" -movflags +faststart "$OUT"

[ "$KEEP" = 1 ] || rm -rf "$WORK/frames"   # the PNG sequence is large (16 sub-frames x 900 frames); audio and logs stay
echo "== done: $OUT"
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels -of compact "$OUT"
