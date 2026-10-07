#!/usr/bin/env python3
"""Are two files the same recitation? And how much bandwidth does each really carry?

Built for swapping a reciter's source without trusting labels (2026-09-29, بلال بن محمود):
durations and titles said "same khatma", and one surah of the new source was a different
take while four others were a different edit. Only the audio can say.

    python3 recording_match.py A.mp3 B.mp3            # probes + bandwidth
    python3 recording_match.py --drift A.mp3 B.mp3    # B's offset against A through the file

Identity: log band-energy spectrogram at 100 frames/s, restricted to 0-4 kHz so a 16 kHz
source competes fairly with a full-band one. A 12-20 s window of A is slid along B and the
score is the mean frame-wise cosine on the best diagonal. Measured: the same recitation
through different codecs scores 0.8-0.98; another take or another recording 0.09-0.30.
One constant offset at every probe means nothing was inserted or cut between them; a step
in `--drift` marks where something was.

Bandwidth: the highest frequency whose long-term level is within 50 dB of the loudest band.
It exposes a relabelled low-bitrate file, and a "new" upload of the same old master.

Runs where numpy and ffmpeg are (on the VPS: /root/nemoenv/bin/python).
"""
import argparse
import subprocess

import numpy as np


def load(path, sr, ss=0.0, t=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", str(ss)] + (["-t", str(t)] if t else []) + \
          ["-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.float32)


def feats(a, hop=80, n=512):
    """8 kHz input -> unit-norm band-energy frames at 100/s."""
    fr = np.lib.stride_tricks.sliding_window_view(a, n)[::hop] * np.hanning(n)
    S = np.log1p(np.abs(np.fft.rfft(fr, axis=1))[:, 4:256].reshape(-1, 63, 4).mean(2))
    S = (S - S.mean(0)) / (S.std(0) + 1e-6)
    return S / (np.linalg.norm(S, axis=1, keepdims=True) + 1e-9)


def match(a_path, b_path, q_start, q_len=20.0, search=30.0):
    """(score, offset): where A[q_start:q_start+q_len] sits in B, relative to q_start."""
    A = feats(load(a_path, 8000, q_start, q_len))
    lo = max(0.0, q_start - search)
    B = feats(load(b_path, 8000, lo, q_len + 2 * search))
    L = len(A)
    acc = np.zeros(max(1, len(B) - L))
    sims = B @ A.T
    for j in range(L):
        acc += sims[j:j + len(acc), j]
    acc /= L
    i = int(acc.argmax())
    return float(acc[i]), lo + i / 100.0 - q_start


def bandwidth(path, ss=5.0, t=60.0):
    a = load(path, 48000, ss, t)
    fr = np.lib.stride_tricks.sliding_window_view(a, 4096)[::2048] * np.hanning(4096)
    P = 10 * np.log10((np.abs(np.fft.rfft(fr, axis=1)) ** 2).mean(0) + 1e-12)
    f = np.fft.rfftfreq(4096, 1 / 48000)
    band = np.convolve(P, np.ones(9) / 9, "same")
    ok = np.where(band > band[f < 4000].max() - 50)[0]
    return f[ok.max()] / 1000.0


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    return float(out or 0)


def probes(a, b):
    da, db = duration(a), duration(b)
    print(f"duration   A {da:.2f}s   B {db:.2f}s   (B-A {db - da:+.2f}s)")
    print(f"bandwidth  A {bandwidth(a):.1f} kHz   B {bandwidth(b):.1f} kHz")
    span = min(da, db)
    for q in sorted({3.0, max(3.0, span * 0.5 - 6), max(3.0, span - 25.0)}):
        if span - q > 4:
            s, off = match(a, b, q, min(12.0, span - q - 0.5), 10.0)
            print(f"  A@{q:8.1f}s  score {s:.2f}  B offset {off:+.2f}s")


def drift(a, b, step, search):
    da = duration(a)
    prev, t = None, 2.0
    while t + 12 <= da:
        s, off = match(a, b, t, 12.0, search)
        note = "" if prev is None else f"  step {off - prev:+.2f}s"
        if s < 0.6:
            note += "  (weak: not the same audio here)"
        print(f"  A@{t:8.1f}s  score {s:.2f}  B offset {off:+7.2f}s{note}")
        prev = off if s >= 0.6 else prev
        t += step


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--drift", action="store_true", help="track B's offset through the file")
    ap.add_argument("--step", type=float, default=60.0, help="seconds between drift probes")
    ap.add_argument("--search", type=float, default=30.0, help="max offset searched, seconds")
    args = ap.parse_args()
    drift(args.a, args.b, args.step, args.search) if args.drift else probes(args.a, args.b)
