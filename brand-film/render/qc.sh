#!/usr/bin/env bash
# Technical QC of an exported film: spec, frame count, black/frozen frames, luma jumps (flicker), loudness and true peak.
# Usage: bash render/qc.sh StudyHub_Brand_Film.mp4 [out_dir]
set -euo pipefail
F=${1:?usage: qc.sh file.mp4 [out_dir]}
OUT=${2:-out/qc}
mkdir -p "$OUT"

echo "== container and streams"
ffprobe -v error -show_entries format=format_name,duration,bit_rate -of default=nw=1 "$F"
ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=codec_name,profile,pix_fmt,width,height,r_frame_rate,avg_frame_rate,nb_read_frames,duration,color_primaries -of default=nw=1 "$F"
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,profile,sample_rate,channels,channel_layout,duration,bit_rate -of default=nw=1 "$F"

echo "== black frames (pix_th 0.05, >= 1 frame)"
ffmpeg -hide_banner -nostats -i "$F" -vf "blackdetect=d=0.03:pix_th=0.05:pic_th=0.98" -an -f null - 2>&1 | grep -E "black_start" || echo "none"

echo "== frozen spans (>= 1.5 s, noise 0.0005)"
ffmpeg -hide_banner -nostats -i "$F" -vf "freezedetect=n=0.0005:d=1.5" -an -f null - 2>&1 | grep -E "freeze_(start|duration|end)" || echo "none"

echo "== luma per frame -> $OUT/luma.csv; largest frame-to-frame jumps"
# Read the file as a normal input (a movie= source would need filtergraph escaping for names with , : or quotes).
ffmpeg -hide_banner -nostats -i "$F" -an -vf "signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG" -f null - 2>&1 \
  | sed -n 's/.*lavfi\.signalstats\.YAVG=//p' > "$OUT/luma.csv"
python3 - "$OUT/luma.csv" <<'PY'
import sys
v = [float(x.strip(',')) for x in open(sys.argv[1]).read().split() if x.strip(',')]
jumps = sorted(((abs(v[i] - v[i - 1]), i) for i in range(1, len(v))), reverse=True)[:8]
print(f"frames={len(v)}  min Y={min(v):.1f}  max Y={max(v):.1f}")
for d, i in jumps:
    print(f"  frame {i:4d} (t={i / 30:6.3f} s): dY={d:6.1f}")
PY

echo "== loudness (EBU R128) and true peak"
ffmpeg -hide_banner -nostats -i "$F" -af ebur128=peak=true -f null - 2>&1 | sed -n '/Summary:/,$p' | grep -E "I:|LRA:|Peak:"
echo "== clipped samples"
ffmpeg -hide_banner -nostats -i "$F" -af astats=metadata=0:reset=0 -f null - 2>&1 | grep -E "Overall|Peak level dB|Number of samples|Max level" | head -8 || true

echo "== contact sheet (1 frame per second) -> $OUT/sheet.png"
ffmpeg -v error -y -i "$F" -vf "fps=1,scale=-2:300,tile=10x3:padding=6:margin=6:color=white" -frames:v 1 "$OUT/sheet.png"
echo "done"
