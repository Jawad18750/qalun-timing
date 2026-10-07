#!/usr/bin/env python3
"""What does the gap-filler score on words we already know are right?

A confidence number is meaningless without a baseline. This runs the exact
fill procedure over spans whose words the matcher already placed confidently,
so the score distribution for "correct" is known, and a threshold for accepting
a filled gap can be set from measurement rather than taste.
"""
import json, os, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, "/root/qrtt"); os.chdir("/root/qrtt")
os.environ.setdefault("NEMO_CKPT", "/root/qrtt/phase3_full.nemo")
import numpy as np, librosa, statistics as st
from nemo_adapter import NeMoASR
from src.phase3_alignment.ctc_align import (_load_vocab, _build_char_to_id,
                                            _tokenize_word, _forced_align_chunk)
SR, PAD = 16000, 0.10
vocab = _load_vocab("/root/qrtt/data/onnx/tokens.txt")
c2i = _build_char_to_id(vocab)
asr = NeMoASR.get_instance()

def score_span(audio, t0, t1, words):
    a = audio[max(0, int((t0 - PAD) * SR)):int((t1 + PAD) * SR)]
    if a.size < SR // 8:
        return None
    _, _, lp = asr.transcribe(a, SR)
    if lp is None:
        return None
    lp = lp[0] if lp.ndim == 3 else lp
    tok = []
    for w in words:
        tok += _tokenize_word(w, vocab, c2i)
    if not tok or lp.shape[0] < len(tok):
        return None
    _, sc = _forced_align_chunk(lp, tok)
    return float(np.exp(np.mean(sc))), (t1 - t0) / max(1, len(words))

path = Path(sys.argv[1]); surah = int(path.stem)
d = json.loads(path.read_text(encoding="utf-8"))
audio, _ = librosa.load(f"/var/www/quran-audio/audio/{d['reciter']}/{surah:03d}.mp3",
                        sr=SR, mono=True)
good = [s for s in d["segments"]
        if s.get("ref_from") and not s.get("filled_gap")
        and (s.get("words") or []) and (s.get("confidence") or 0) >= 0.9]
print(f"  scoring {min(len(good), 25)} known-good segments from {path.name} "
      f"(of {len(good)} at confidence >= 0.9)", flush=True)
rows = []
for s in good[:25]:
    ws = [w for w in s["words"] if w.get("start") is not None]
    if not ws:
        continue
    base = s["time_from"]
    r = score_span(audio, base + ws[0]["start"], base + ws[-1]["end"],
                   [w["word"] for w in ws])
    if r:
        rows.append(r)
        print(f"    conf={r[0]:.3f}  {r[1]:.2f}s/word  ({len(ws)}w)", flush=True)
if rows:
    cs = sorted(r[0] for r in rows)
    sw = sorted(r[1] for r in rows)
    print(f"\n  KNOWN-GOOD confidence: median {st.median(cs):.3f}  "
          f"min {cs[0]:.3f}  p10 {cs[max(0,len(cs)//10)]:.3f}  max {cs[-1]:.3f}")
    print(f"  KNOWN-GOOD sec/word  : median {st.median(sw):.2f}  max {sw[-1]:.2f}")
