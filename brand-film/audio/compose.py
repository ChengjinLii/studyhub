#!/usr/bin/env python3
"""Procedural score and sound design for the StudyHub brand film.

Everything is synthesised here from sine waves and seeded noise (no samples, no third-party audio),
so the track is original and licence-free. All hit times come from src/cues.json, the same file the
picture reads, so sound and picture stay in sync.

Usage: python3 audio/compose.py --out out/audio [--from 0 --to 30]
Writes music.wav, sfx.wav, mix.wav (48 kHz, stereo, 24-bit PCM, peak-normalised to -3 dBFS, not loudness-mastered)
and cue_report.json (every scheduled sound with its time). Loudness mastering happens at mux time (ffmpeg loudnorm).
Requires: Python 3.9+, numpy.
"""
import argparse
import json
import math
import os
import wave

import numpy as np

SR = 48000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUES = json.load(open(os.path.join(ROOT, 'src', 'cues.json'), encoding='utf-8'))
DUR = CUES['duration']
N = int(round(DUR * SR))
BEAT = CUES['beat']
BAR0 = CUES['barOffset']
RNG = np.random.default_rng(20251101)
REPORT = []


def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def tt(dur):
    return np.arange(int(dur * SR)) / SR


def env_ad(n, a, d_tau, sr=SR):
    t = np.arange(n) / sr
    e = np.exp(-t / max(d_tau, 1e-4))
    if a > 0:
        e *= np.clip(t / a, 0, 1)
    return e


def fade_tail(x, ms=6):
    k = min(len(x), int(ms / 1000 * SR))
    if k > 0:
        x[-k:] *= np.linspace(1, 0, k)
    return x


class Bus:
    def __init__(self, name):
        self.name = name
        self.L = np.zeros(N + SR * 3)
        self.R = np.zeros(N + SR * 3)

    def add(self, t0, sig, gain=1.0, pan=0.0, label=None):
        if t0 < -1 or t0 > DUR:
            return
        i0 = int(round(t0 * SR))
        sig = np.asarray(sig, dtype=np.float64) * gain
        if i0 < 0:
            sig = sig[-i0:]
            i0 = 0
        n = min(len(sig), len(self.L) - i0)
        if n <= 0:
            return
        # Equal-power pan.
        a = (pan + 1) * math.pi / 4
        self.L[i0:i0 + n] += sig[:n] * math.cos(a)
        self.R[i0:i0 + n] += sig[:n] * math.sin(a)
        if label:
            REPORT.append({'t': round(t0, 4), 'bus': self.name, 'sound': label})

    def stereo(self):
        return np.stack([self.L[:N], self.R[:N]], axis=1)


# ---------------------------------------------------------------- filters
def onepole_lp(x, fc):
    """One-pole low-pass, vectorised via an exponential-smoothing FFT kernel approximation for static fc."""
    a = math.exp(-2 * math.pi * fc / SR)
    n = len(x)
    k = int(min(n, max(64, 6 / (1 - a + 1e-9))))
    kern = (1 - a) * a ** np.arange(k)
    return fftconv(x, kern)[:n]


def fftconv(x, h):
    n = len(x) + len(h) - 1
    nf = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, nf) * np.fft.rfft(h, nf), nf)[:n]


def bandpass_fft(x, lo, hi):
    n = len(x)
    nf = 1 << (n - 1).bit_length()
    X = np.fft.rfft(x, nf)
    f = np.fft.rfftfreq(nf, 1 / SR)
    m = 1 / (1 + (lo / np.maximum(f, 1)) ** 4) / (1 + (f / hi) ** 4)
    return np.fft.irfft(X * m, nf)[:n]


def sweep_noise(dur, f0, f1, q=1.2, seed=0, curve=1.0):
    """Noise through a band-pass whose centre glides f0 -> f1 (done in short FFT blocks with overlap-add)."""
    n = int(dur * SR)
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(n + 4096)
    out = np.zeros(n + 4096)
    hop = 512
    win = np.hanning(hop * 2)
    for i in range(0, n, hop):
        u = (i / max(1, n - 1)) ** curve
        fc = f0 * (f1 / f0) ** u
        seg = noise[i:i + hop * 2] * win
        if len(seg) < hop * 2:
            break
        X = np.fft.rfft(seg)
        f = np.fft.rfftfreq(hop * 2, 1 / SR)
        bw = fc / q
        m = np.exp(-0.5 * ((f - fc) / bw) ** 2)
        out[i:i + hop * 2] += np.fft.irfft(X * m, hop * 2)
    return out[:n] / (np.max(np.abs(out[:n])) + 1e-9)


# ---------------------------------------------------------------- instruments
def kick(gain=1.0):
    """Tight pop kick: short sub body plus a 2-6 kHz beater click so it still reads on phone speakers."""
    t = tt(0.32)
    f = 52 + 120 * np.exp(-t / 0.03)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t / 0.11)
    x += 0.45 * np.sin(ph * 2) * np.exp(-t / 0.025)
    click = bandpass_fft(RNG.standard_normal(len(t)), 2000, 6500) * np.exp(-t / 0.004) * 0.9
    return fade_tail(np.tanh(1.4 * (x + click)) * gain)


def clap():
    t = tt(0.32)
    n = RNG.standard_normal(len(t))
    e = np.zeros(len(t))
    for off in (0.0, 0.011, 0.022, 0.031):
        e += np.where(t >= off, np.exp(-(t - off) / 0.009), 0)
    e += np.where(t >= 0.031, np.exp(-(t - 0.031) / 0.09), 0) * 0.7
    x = bandpass_fft(n, 900, 5200) * e
    body = np.sin(2 * np.pi * 210 * t) * np.exp(-t / 0.04) * 0.3
    return fade_tail((x / (np.max(np.abs(x)) + 1e-9) + body) * 0.8)


def hat(open_=False):
    d = 0.22 if open_ else 0.045
    t = tt(d + 0.02)
    n = RNG.standard_normal(len(t))
    x = bandpass_fft(n, 7000, 16000) * np.exp(-t / (d / 3))
    return fade_tail(x / (np.max(np.abs(x)) + 1e-9) * 0.55)


def shaker():
    t = tt(0.07)
    n = RNG.standard_normal(len(t))
    e = np.clip(t / 0.012, 0, 1) * np.exp(-t / 0.02)
    x = bandpass_fft(n, 4500, 11000) * e
    return fade_tail(x / (np.max(np.abs(x)) + 1e-9) * 0.35)


def bass(m, dur):
    t = tt(dur + 0.05)
    f = mtof(m)
    x = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)
    e = np.clip(t / 0.004, 0, 1) * np.exp(-t / max(0.12, dur * 0.7))
    e *= np.clip((dur + 0.05 - t) / 0.04, 0, 1)
    return fade_tail(np.tanh(1.4 * x * e) * 0.8)


def ep(m, dur):
    """FM electric piano: carrier + 1:1 modulator with decaying index, plus a soft 14:1 tine."""
    t = tt(dur + 0.35)
    f = mtof(m)
    idx = 1.6 * np.exp(-t / 0.09) + 0.25
    x = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * t))
    x += 0.08 * np.sin(2 * np.pi * f * 14 * t) * np.exp(-t / 0.015)
    e = np.clip(t / 0.003, 0, 1) * np.exp(-t / 0.5)
    rel = np.clip((dur + 0.35 - t) / 0.35, 0, 1)
    return fade_tail(x * e * rel * 0.45)


def marimba(m, dur=0.6):
    t = tt(dur)
    f = mtof(m)
    x = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.28)
    x += 0.35 * np.sin(2 * np.pi * f * 3.98 * t) * np.exp(-t / 0.06)
    x += 0.10 * np.sin(2 * np.pi * f * 9.9 * t) * np.exp(-t / 0.018)
    x *= np.clip(t / 0.0015, 0, 1)
    return fade_tail(x * 0.6)


def glock(m, dur=1.2, bright=1.0):
    t = tt(dur)
    f = mtof(m)
    x = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.55)
    x += 0.45 * bright * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t / 0.22)
    x += 0.25 * bright * np.sin(2 * np.pi * f * 5.40 * t) * np.exp(-t / 0.09)
    x += 0.12 * bright * np.sin(2 * np.pi * f * 8.93 * t) * np.exp(-t / 0.04)
    x *= np.clip(t / 0.001, 0, 1)
    return fade_tail(x * 0.42)


def pad(ms, dur, att=0.35, rel=0.6, bright=0.5):
    t = tt(dur + rel)
    x = np.zeros(len(t))
    for m in ms:
        f = mtof(m)
        for det in (-0.08, 0.0, 0.07):
            fd = f * 2 ** (det / 12)
            for h in range(1, 7):
                x += (bright ** (h - 1)) / h * np.sin(2 * np.pi * fd * h * t + h * 1.3 + det * 40)
    e = np.clip(t / att, 0, 1) * np.clip((dur + rel - t) / rel, 0, 1)
    return fade_tail(x * e / (len(ms) * 3) * 0.5)


# ---------------------------------------------------------------- sound effects
def pop(m, gain=1.0):
    t = tt(0.16)
    f = mtof(m) * (1 + 1.2 * np.exp(-t / 0.012))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.045)
    x += RNG.standard_normal(len(t)) * np.exp(-t / 0.002) * 0.15
    return fade_tail(x * gain)


def whoosh(dur, f0, f1, seed, gain=1.0, shape='bell', curve=1.0):
    x = sweep_noise(dur, f0, f1, q=1.4, seed=seed, curve=curve)
    t = np.linspace(0, 1, len(x))
    if shape == 'bell':
        e = np.sin(np.pi * t) ** 1.5
    elif shape == 'rise':
        e = t ** 2.2
    else:  # 'fall'
        e = (1 - t) ** 1.5 * np.clip(t / 0.05, 0, 1)
    return fade_tail(x * e * gain)


def impact(gain=1.0, dur=1.2):
    t = tt(dur)
    f = 32 + 70 * np.exp(-t / 0.06)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.35)
    nz = onepole_lp(RNG.standard_normal(len(t)), 900) * np.exp(-t / 0.12) * 1.8
    return fade_tail(np.tanh(1.3 * (x + nz)) * gain)


def blip(f0, f1, dur=0.09, gain=1.0):
    t = tt(dur)
    f = f0 * (f1 / f0) ** (t / dur)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.clip(t / 0.003, 0, 1) * np.exp(-t / (dur / 2.5))
    return fade_tail(x * gain)


def tap(f=1800, gain=1.0, kind='soft'):
    """Three UI touch sounds: 'soft' (field/tab), 'card' (wooden tick on a list card), 'button' (pressed key with body)."""
    t = tt(0.09)
    if kind == 'card':
        x = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.006) + 0.5 * np.sin(2 * np.pi * f * 2.4 * t) * np.exp(-t / 0.003)
        x += RNG.standard_normal(len(t)) * np.exp(-t / 0.001) * 0.25
    elif kind == 'button':
        x = np.sin(2 * np.pi * 180 * t) * np.exp(-t / 0.03) * 0.8
        x += np.sin(2 * np.pi * f * t) * np.exp(-t / 0.01) * 0.6
        x += bandpass_fft(RNG.standard_normal(len(t)), 1500, 7000) * np.exp(-t / 0.003) * 0.5
    else:
        x = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.012)
        x += RNG.standard_normal(len(t)) * np.exp(-t / 0.0015) * 0.4
    return fade_tail(x * gain)


def key(i):
    t = tt(0.05)
    f = 2600 + 300 * ((i * 7) % 5)
    x = RNG.standard_normal(len(t)) * np.exp(-t / 0.004) * 0.6
    x += np.sin(2 * np.pi * f * t) * np.exp(-t / 0.008) * 0.35
    x = bandpass_fft(x, 1200, 9000)
    return fade_tail(x / (np.max(np.abs(x)) + 1e-9) * 0.5)


def woodblock(f=900, gain=1.0):
    t = tt(0.08)
    x = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.018) + 0.4 * np.sin(2 * np.pi * f * 2.7 * t) * np.exp(-t / 0.008)
    return fade_tail(x * gain * 0.6)


def sparkle(seed, n=7, base=84, dur=0.6, gain=1.0):
    rng = np.random.default_rng(seed)
    out = np.zeros(int((dur + 0.6) * SR))
    scale = [0, 2, 4, 7, 9, 12, 14, 16, 19]
    for k in range(n):
        m = base + scale[rng.integers(0, len(scale))]
        g = glock(m, 0.5, bright=0.6) * (0.5 + 0.5 * rng.random())
        i = int((k / n) * dur * SR * (0.8 + 0.4 * rng.random()))
        out[i:i + len(g)] += g[:len(out) - i]
    return fade_tail(out * gain * 0.5)


def tick(gain=1.0, f=3200):
    t = tt(0.025)
    x = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.004) + RNG.standard_normal(len(t)) * np.exp(-t / 0.001) * 0.3
    return fade_tail(x * gain)


# ---------------------------------------------------------------- score
CHORDS = {  # bar index k covers [BAR0 + 2k, BAR0 + 2k + 2)
    -1: 'F', 0: 'G', 1: 'C', 2: 'G', 3: 'Am', 4: 'F', 5: 'C', 6: 'G', 7: 'Am', 8: 'F', 9: 'G', 10: 'C', 11: 'G', 12: 'F', 13: 'C', 14: 'C',
}
ROOT_M = {'C': 36, 'G': 43, 'Am': 45, 'F': 41}
VOICE = {'C': [60, 64, 67], 'G': [59, 62, 67], 'Am': [60, 64, 69], 'F': [60, 65, 69]}
ARP = {'C': [72, 76, 79, 84], 'G': [71, 74, 79, 83], 'Am': [72, 76, 81, 84], 'F': [72, 77, 81, 84]}


def chord_at(t):
    k = math.floor((t - BAR0) / 2)
    if k == 12 and (t - BAR0) - 2 * k >= 1.0:
        return 'G'  # 26-27 s: dominant before the final C
    return CHORDS.get(k, 'C')


def in_any(t, spans):
    return any(a <= t < b for a, b in spans)


def build_music(music, drums):
    m = CUES['music']
    drop = m['drop']
    four_spans = [(drop, 7.5), (8.0, 15.0), (20.0, 25.5)]
    half_spans = [(15.0, 19.0)]
    beats = [round(i * BEAT, 4) for i in range(int(DUR / BEAT) + 1)]
    for b in beats:
        bar_pos = ((b - BAR0) / BEAT) % 4  # 0..3 beat in bar
        # Kick.
        if in_any(b, four_spans) or (in_any(b, half_spans) and bar_pos in (0, 2)) or (19.0 <= b < 19.5):
            drums.add(b, kick(), 0.62, 0, 'kick')
        # Clap on 2 and 4.
        if in_any(b, four_spans) and bar_pos in (1, 3):
            drums.add(b, clap(), 0.45, 0.05, 'clap')
        if in_any(b, half_spans) and bar_pos == 2:
            drums.add(b, clap(), 0.35, 0.05, 'clap')
        # Hats: off-beat 8ths, 16ths in the chorus.
        if 1.0 <= b < 25.5 and not (7.5 <= b < 8.0):
            drums.add(b + BEAT / 2, hat(open_=(bar_pos == 3 and b >= drop)), 0.22 if b < drop else 0.3, 0.25, None)
            if 20.0 <= b < 25.5:
                drums.add(b + BEAT / 4, hat(), 0.14, -0.2, None)
                drums.add(b + 3 * BEAT / 4, hat(), 0.14, -0.2, None)
        # Shaker during the UI section.
        if 8.0 <= b < 15.0:
            for j in range(4):
                drums.add(b + j * BEAT / 4 + 0.008 * (j % 2), shaker(), 0.18, -0.35, None)

    # Snare roll before the data chorus and before S4.
    for (a, z, g0, g1) in [(18.5, 19.95, 0.05, 0.42), (14.5, 14.98, 0.05, 0.22)]:
        n = int((z - a) / (BEAT / 4))
        for i in range(n):
            u = i / max(1, n - 1)
            step = BEAT / 4 if u < 0.6 else BEAT / 8
            tt0 = a + i * BEAT / 4
            drums.add(tt0, clap(), g0 + (g1 - g0) * u, 0.05, None)
            if step < BEAT / 4:
                drums.add(tt0 + BEAT / 8, clap(), (g0 + (g1 - g0) * u) * 0.8, 0.05, None)

    # Bass: 8th-note pump with octave pops on the "and".
    for i in range(int(DUR / (BEAT / 2))):
        t0 = i * BEAT / 2
        if not in_any(t0, [(drop, 7.5), (8.0, 15.0), (20.0, 25.5)]):
            continue
        c = chord_at(t0)
        r = ROOT_M[c]
        off = (i % 2 == 1)
        music.add(t0, bass(r + (12 if off else 0), 0.2), 0.5 if not off else 0.32, 0, None)
    # Sustained bass in the build and the breakdown.
    for k in (7, 8):
        t0 = BAR0 + 2 * k
        music.add(t0, bass(ROOT_M[CHORDS[k]], 1.9), 0.42, 0, None)
    music.add(19.0, bass(ROOT_M['G'], 0.9), 0.42, 0, None)
    music.add(25.5, bass(ROOT_M['F'], 0.5), 0.38, 0, None)
    music.add(26.0, bass(ROOT_M['G'], 0.95), 0.38, 0, None)
    music.add(27.0, bass(ROOT_M['C'] - 12 + 12, 2.6), 0.5, 0, 'final-bass')

    # EP stabs on the off-beats (pop-house bounce), lighter in the UI section.
    for i in range(int(DUR / BEAT)):
        t0 = i * BEAT + BEAT / 2
        if not in_any(t0, [(drop, 7.5), (8.0, 15.0), (20.0, 25.5)]):
            continue
        c = chord_at(t0)
        g = 0.20 if 8.0 <= t0 < 15.0 else 0.27
        for j, mm in enumerate(VOICE[c]):
            music.add(t0 + j * 0.004, ep(mm, 0.16), g, -0.3 + 0.3 * j, None)

    # Pads: build, chorus bed, breakdown and the end.
    for (a, z, cs, g) in [(15.0, 17.0, 'Am', 0.5), (17.0, 19.0, 'F', 0.5), (19.0, 20.0, 'G', 0.45),
                          (21.0, 23.0, 'C', 0.28), (23.0, 25.0, 'G', 0.28), (25.0, 26.0, 'F', 0.45), (26.0, 27.0, 'G', 0.5)]:
        music.add(a, pad(VOICE[cs], z - a, att=0.25, rel=0.4), g, 0, None)
    music.add(27.0, pad([48, 55, 60, 64, 67, 72], 2.6, att=0.02, rel=0.5, bright=0.55), 0.62, 0, 'final-pad')

    # Marimba: intro arpeggio (0-3 s), off-beat plucks (3-15 s), chorus arpeggios (20-25.5 s), final run (27 s).
    for i in range(int(3.0 / (BEAT / 2))):
        t0 = i * BEAT / 2
        c = chord_at(t0)
        mm = ARP[c][i % 4] - 12
        music.add(t0, marimba(mm), 0.55 - 0.1 * (i % 2), -0.25 + 0.5 * (i % 2), None)
    for i in range(int(DUR / (BEAT / 2))):
        t0 = i * BEAT / 2
        c = chord_at(t0)
        if in_any(t0, [(20.0, 25.5)]):
            music.add(t0, marimba(ARP[c][i % 4]), 0.42, -0.3 + 0.6 * ((i // 2) % 2), None)
        elif in_any(t0, [(drop, 7.5), (8.0, 15.0)]) and i % 4 == 3:
            music.add(t0, marimba(ARP[c][(i // 4) % 4]), 0.28, 0.35, None)

    # Glock motif: brand "hello" at the drop and the final sting (G5 C6 E6 G6 / C6 E6 G6 C7).
    for j, mm in enumerate([79, 84, 88, 91]):
        music.add(drop + j * BEAT / 4, glock(mm, 1.0), 0.5, -0.2 + 0.13 * j, 'motif' if j == 0 else None)
    for j, mm in enumerate([84, 88, 91, 96]):
        music.add(27.0 + j * BEAT / 4, glock(mm, 1.6), 0.55, -0.2 + 0.13 * j, 'motif-end' if j == 0 else None)

    # Risers.
    for (a, z, g) in [(2.3, 3.0, 0.35), (14.4, 15.0, 0.25), (18.5, 19.98, 0.42), (26.2, 27.0, 0.38)]:
        music.add(a, whoosh(z - a, 300, 6000, seed=int(a * 10), gain=g, shape='rise', curve=1.4), 1.0, 0, 'riser')


def build_sfx(sfx):
    s1, s2, s3, s4, s5, s6 = (CUES[k] for k in ('s1', 's2', 's3', 's4', 's5', 's6'))
    scale = [72, 74, 76, 79, 81, 84, 86]
    # S1: bubble pops, pitched up the scale; a soft swish under the headline.
    for i, b in enumerate(s1['bubbles']):
        if b['t'] < 0:
            continue  # already on screen at frame 0: no pop (it would be an orphan transient at sample 0)
        sfx.add(b['t'] + 0.02, pop(scale[i % len(scale)] - 12, 0.55), 1.0, -0.3 if b['face'] != 'me' else 0.35, 'bubble-pop')
    sfx.add(s1['headlineIn'] + 0.02, whoosh(0.35, 800, 3000, seed=1, gain=0.18), 1.0, 0, 'headline-swish')
    a, z = s1['implode']
    sfx.add(a - 0.05, whoosh(z - a + 0.05, 2500, 400, seed=2, gain=0.45, shape='rise'), 1.0, 0, 'implode-suck')
    # S2: drop impact, eye blips, wordmark swish, blink, header move, card swishes and snaps.
    sfx.add(s2['wipe'][0], impact(0.75), 1.0, 0, 'drop-impact')
    sfx.add(s2['wipe'][0], pop(60, 0.6), 1.0, 0, 'dot-burst')
    sfx.add(s2['eyesIn'][0] + 0.02, blip(700, 1400, 0.11, 0.22), 1.0, -0.15, 'eye-blip')
    sfx.add(s2['eyesIn'][0] + 0.07, blip(800, 1600, 0.11, 0.22), 1.0, 0.15, 'eye-blip')
    sfx.add(s2['wordmark'], whoosh(0.4, 1200, 5000, seed=3, gain=0.14), 1.0, 0, 'wordmark-swish')
    sfx.add(s2['blink'] + 0.02, blip(1500, 1100, 0.06, 0.12), 1.0, 0, 'blink')
    sfx.add(s2['toHeader'][0], whoosh(0.5, 2500, 700, seed=4, gain=0.2), 1.0, -0.4, 'to-header')
    for i, order in enumerate(s2['cardOrder']):
        t0 = s2['cardsIn'] + order * s2['cardStagger']
        pan = -0.6 if i % 3 == 0 else (0.6 if i % 3 == 2 else 0.0)
        sfx.add(t0 + 0.05, whoosh(0.22, 1500, 5000, seed=10 + i, gain=0.09), 1.0, pan, None)
        if order % 2 == 0:
            sfx.add(t0 + s2['cardFlight'], woodblock(850 + 60 * (order % 4), 0.45), 1.0, pan * 0.6, 'card-snap')
    # S3: UI interactions.
    a, z = s3['toPhone']
    sfx.add(a, whoosh(z - a, 4000, 500, seed=5, gain=0.3), 1.0, 0, 'to-phone')
    sfx.add(z - 0.02, woodblock(620, 0.5), 1.0, 0, 'phone-land')
    for lab in ('label1', 'label2', 'label3'):
        sfx.add(s3[lab], whoosh(0.3, 1000, 4000, seed=int(s3[lab] * 10), gain=0.1), 1.0, 0, 'label-swish')
    sfx.add(s3['tapSearch'], tap(1700, 0.45), 1.0, 0.1, 'tap-soft')
    for i, k in enumerate(s3['typeKeys']):
        sfx.add(k, key(i), 0.5, 0.1, 'key')
    sfx.add(s3['chip'], pop(84, 0.3), 1.0, 0.2, 'chip')
    a, z = s3['reshuffle']
    sfx.add(a, whoosh(z - a, 2000, 6000, seed=6, gain=0.12), 1.0, 0.1, 'reshuffle')
    sfx.add(s3['tapCard'], tap(1100, 0.5, 'card'), 1.0, 0, 'tap-card')
    a, z = s3['cardExpand']
    sfx.add(a, whoosh(z - a, 600, 2500, seed=7, gain=0.16), 1.0, 0, 'card-expand')
    sfx.add(s3['tapGet'], tap(1300, 0.55, 'button'), 1.0, 0, 'tap-button')
    a, z = s3['progress']
    sfx.add(a, blip(1200, 520, z - a, 0.22), 1.0, 0, 'download-glide')
    sfx.add(s3['check'], glock(88, 0.6), 0.35, 0, 'download-chime')
    sfx.add(s3['check'] + 0.09, glock(84, 0.8), 0.35, 0, None)
    sfx.add(s3['tapTab'], tap(1600, 0.4), 1.0, 0.1, 'tap-soft')
    a, z = s3['toUpload']
    sfx.add(a, whoosh(z - a, 1500, 4500, seed=8, gain=0.15), 1.0, 0.3, 'to-upload')
    a, z = s3['noteIn']
    sfx.add(a, whoosh(z - a, 900, 3000, seed=9, gain=0.22), 1.0, -0.5, 'note-in')
    sfx.add(s3['noteLand'], pop(55, 0.45), 1.0, 0, 'note-land')
    for i in range(6):
        sfx.add(s3['titleType'][0] + i * 0.05, key(i + 3), 0.3, 0.1, None)
    sfx.add(s3['tapSubmit'], tap(1500, 0.55, 'button'), 1.0, 0, 'tap-button')
    for j, mm in enumerate([84, 88, 91]):
        sfx.add(s3['toastUpload'] + j * 0.07, glock(mm, 0.7), 0.32, -0.1 + 0.1 * j, 'upload-success' if j == 0 else None)
    a, z = s3['noteLift']
    sfx.add(a, whoosh(z - a, 500, 2500, seed=11, gain=0.2), 1.0, 0, 'note-lift')
    a, z = s3['wipeInk']
    sfx.add(a, whoosh(z - a, 3000, 300, seed=12, gain=0.25, shape='rise'), 1.0, 0, 'wipe-ink')
    # S4: copies (one glock note each, panned by angle), happy boops, pulses.
    sfx.add(s4['lineA'], impact(0.35, 0.8), 1.0, 0, 'build-boom')
    penta = [72, 74, 76, 79, 81]
    for w_i, wv in enumerate(s4['waves']):
        for j in range(wv['count']):
            dep = wv['t'] + j * s4['copyStagger']
            arr = dep + s4['flight']
            ang = (j / wv['count']) * 2 * math.pi + w_i * 0.4
            pan = 0.75 * math.sin(ang)
            mm = penta[(j + w_i * 2) % 5] + 12 * w_i
            if j % (1 if w_i == 0 else 2) == 0:
                sfx.add(dep, glock(mm, 0.7, bright=0.7), 0.16 if w_i else 0.22, pan, 'copy-chime' if j == 0 else None)
            sfx.add(arr + s4['happyDelay'], blip(500 + 80 * ((j * 3) % 7), 900 + 80 * ((j * 3) % 7), 0.07, 0.08), 1.0, pan, None)
    sfx.add(s4['lineB'], whoosh(0.35, 1000, 4000, seed=13, gain=0.1), 1.0, 0, 'line-swish')
    for i, p in enumerate(s4['pulses']):
        sfx.add(p, sparkle(30 + i, n=5, base=84 + 2 * i, dur=0.4, gain=0.35), 1.0, 0, 'pulse-sparkle')
    a, z = s4['wipeSoft']
    sfx.add(a, whoosh(z - a, 300, 3000, seed=14, gain=0.25, shape='rise'), 1.0, 0, 'wipe-soft')
    # S5: impact, counters with ticks that follow the ease-out count, then a ding per row (rising pitch).
    # The data kicker first becomes visible ~3 frames after its cue, so the hit follows the picture.
    sfx.add(s5['kicker'] + 0.1, impact(0.55, 0.9), 1.0, 0, 'data-impact')
    for r_i, row in enumerate(s5['rows']):
        t0 = row['t'] + s5['countDelay']
        sfx.add(row['t'], pop(67 + 2 * r_i, 0.35), 1.0, -0.2, 'row-in')
        nt = s5['countTicks']
        for k in range(1, nt):
            # outCubic inverse: value fraction v -> time fraction u = 1 - (1 - v)^(1/3)
            v = k / nt
            u = 1 - (1 - v) ** (1 / 3)
            sfx.add(t0 + u * s5['count'], tick(0.22, 3000 + 40 * k), 1.0, 0.1, None)
        sfx.add(t0 + s5['count'], glock(84 + 4 * r_i, 0.9), 0.42, 0.1, 'count-ding')
    sfx.add(s5['footnote'], whoosh(0.3, 1500, 4000, seed=15, gain=0.06), 1.0, 0, None)
    a, z = s5['out']
    sfx.add(a, whoosh(z - a, 3500, 600, seed=16, gain=0.25), 1.0, 0, 'data-out')
    # S6: wipe, the signature morph (pitched swoosh), landing impact, text swishes, CTA pop, blink.
    a, z = s6['wipeBlue']
    sfx.add(a + 0.06, whoosh(z - a, 400, 2400, seed=17, gain=0.22), 1.0, 0, 'wipe-blue')
    a, z = s6['morph']
    sfx.add(a, blip(300, 900, z - a, 0.12), 1.0, 0, 'morph-glide')
    sfx.add(a, whoosh(z - a, 600, 5000, seed=18, gain=0.25, shape='rise'), 1.0, 0, 'morph-swoosh')
    sfx.add(s6['land'], impact(0.7, 1.4), 1.0, 0, 'logo-land')
    sfx.add(s6['land'] + 0.05, sparkle(40, n=9, base=91, dur=0.7, gain=0.45), 1.0, 0, 'logo-sparkle')
    sfx.add(s6['wordmark'], whoosh(0.4, 1200, 5000, seed=19, gain=0.1), 1.0, 0, None)
    sfx.add(s6['slogan'], whoosh(0.4, 1000, 4000, seed=20, gain=0.08), 1.0, 0, None)
    sfx.add(s6['cta'] + 0.07, pop(72, 0.45), 1.0, 0, 'cta-pop')
    sfx.add(s6['blink'] + 0.02, blip(1500, 1100, 0.06, 0.12), 1.0, 0, 'blink')


# ---------------------------------------------------------------- mixing
def reverb(x, seconds=1.4, seed=99):
    n = int(seconds * SR)
    rng = np.random.default_rng(seed)
    t = np.arange(n) / SR
    out = []
    for ch in range(2):
        ir = rng.standard_normal(n) * np.exp(-t / (seconds / 5.5))
        ir = onepole_lp(ir, 6000)
        ir[: int(0.012 * SR)] = 0
        ir /= np.sqrt(np.sum(ir ** 2))
        out.append(fftconv(x[:, ch], ir)[: len(x)])
    return np.stack(out, axis=1)


def sidechain(t0s, n, depth=0.35, rel=0.18):
    g = np.ones(n)
    for k in t0s:
        i = int(k * SR)
        if i >= n:
            continue
        m = min(n - i, int(rel * 4 * SR))
        tt_ = np.arange(m) / SR
        g[i:i + m] = np.minimum(g[i:i + m], 1 - depth * np.exp(-tt_ / rel))
    return g


def write_wav(path, x):
    x = np.clip(x, -1, 1)
    pcm = (x * (2 ** 23 - 1)).astype(np.int32)
    b = pcm.astype('<i4').tobytes()
    # Keep the low 3 bytes of each little-endian int32 sample -> 24-bit PCM.
    raw = np.frombuffer(b, dtype=np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(SR)
        w.writeframes(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'out', 'audio'))
    ap.add_argument('--from', dest='t_from', type=float, default=0.0)
    ap.add_argument('--to', dest='t_to', type=float, default=DUR)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    music, drums, sfx = Bus('music'), Bus('drums'), Bus('sfx')
    build_music(music, drums)
    build_sfx(sfx)

    kicks = [r['t'] for r in REPORT if r['sound'] == 'kick']
    duck = sidechain(kicks, N)[:, None]
    mus = music.stereo() * duck + drums.stereo()
    mus = mus + 0.16 * reverb(music.stereo() * duck, 1.6, 7)
    fx = sfx.stereo()
    fx = fx + 0.12 * reverb(fx, 1.1, 8)
    mix = 0.85 * mus + 1.1 * fx
    # Master high-pass (~32 Hz): phone speakers cannot play sub rumble, and it would eat loudness headroom.
    mix = np.stack([bandpass_fft(mix[:, c], 32, 20000) for c in range(2)], axis=1)
    # Gentle bus saturation, then peak-normalise to -3 dBFS (loudness is mastered later).
    mix = np.tanh(mix * 1.2) / 1.2
    t = np.arange(N) / SR
    end_fade = np.clip((DUR - t) / 0.15, 0, 1)[:, None]
    mix *= end_fade
    # 3 ms fade-in: the first bubble pop starts at sample 0 and would otherwise click (landscape review N7).
    k = int(0.003 * SR)
    mix[:k] *= np.linspace(0, 1, k)[:, None]
    peak = np.max(np.abs(mix)) + 1e-9
    gain = 10 ** (-3 / 20) / peak
    i0, i1 = int(a.t_from * SR), int(a.t_to * SR)
    write_wav(os.path.join(a.out, 'mix.wav'), mix[i0:i1] * gain)
    write_wav(os.path.join(a.out, 'music.wav'), (mus * end_fade)[i0:i1] * gain)
    write_wav(os.path.join(a.out, 'sfx.wav'), (fx * end_fade)[i0:i1] * gain)
    REPORT.sort(key=lambda r: r['t'])
    json.dump(REPORT, open(os.path.join(a.out, 'cue_report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'wrote {a.out}/mix.wav [{a.t_from:.2f}, {a.t_to:.2f}) s, {len(REPORT)} labelled events, peak gain {20 * math.log10(gain):+.1f} dB')


if __name__ == '__main__':
    main()
