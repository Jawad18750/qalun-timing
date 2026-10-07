#!/usr/bin/env python3
"""Does a filled word land where the audio actually says it?

Earlier gates were confounded. Span width and whole-string similarity both
punish a WIDE span rather than a WRONG fill, and a gap's span is often wide
because the bracketing words' timings are loose, not because the words are
missing. The 78:14:4 case scored badly on both while being correct: expected
`ماء`, heard `المعصرات ماء ثجاجا` -- the word is right there.

Two measures that ask the real question:
  containment -- how much of the expected text appears anywhere in what the
                 model heard over that span
  offset      -- distance between where we placed the word and where the ASR
                 independently timed its own matching word
A fill that is real should score high on containment and small on offset.
"""
import json, os, sys, warnings, difflib
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, "/root/qrtt"); os.chdir("/root/qrtt")
os.environ.setdefault("NEMO_CKPT", "/root/qrtt/phase3_full.nemo")
import librosa
from nemo_adapter import NeMoASR
from src.phase3_alignment.ctc_align import _strip_diacritics

SR, PAD = 16000, 0.10
asr = NeMoASR.get_instance()
norm = lambda s: _strip_diacritics(s or "").replace(" ", "")


def containment(exp, heard):
    """Share of the expected string found as a contiguous run inside `heard`."""
    e, h = norm(exp), norm(heard)
    if not e:
        return 0.0
    m = difflib.SequenceMatcher(None, e, h).find_longest_match(0, len(e), 0, len(h))
    return m.size / len(e)


path = Path(sys.argv[1]); surah = int(path.stem)
d = json.loads(path.read_text(encoding="utf-8"))
audio, _ = librosa.load(f"/var/www/quran-audio/audio/{d['reciter']}/{surah:03d}.mp3",
                        sr=SR, mono=True)

def report(tag, segs, limit):
    print(f"\n  {tag}:", flush=True)
    for s in segs[:limit]:
        ws = [w for w in (s.get("words") or []) if w.get("start") is not None]
        if not ws:
            continue
        b = s["time_from"]
        t0, t1 = b + ws[0]["start"], b + ws[-1]["end"]
        a = audio[max(0, int((t0-PAD)*SR)):int((t1+PAD)*SR)]
        if a.size < SR//8:
            continue
        txt, aw, _ = asr.transcribe(a, SR)
        offs = []
        for w in ws:
            best, bs = None, 0.0
            for x in aw:                       # ASR's own timing for that word
                r = difflib.SequenceMatcher(None, norm(w["word"]), norm(x["word"])).ratio()
                if r > bs:
                    bs, best = r, x
            if best and bs >= 0.6:
                ours = (b + w["start"]) - (t0 - PAD)
                offs.append(abs(ours - best["start"]))
        c = containment(" ".join(w["word"] for w in ws), txt)
        o = f"{sum(offs)/len(offs):.2f}s" if offs else "n/a"
        print(f"    containment={c:.3f}  mean_offset={o:>6}  ({len(ws)}w)  "
              f"exp={' '.join(w['word'] for w in ws)[:26]}", flush=True)

good = [s for s in d["segments"] if s.get("ref_from") and not s.get("filled_gap")
        and (s.get("confidence") or 0) >= 0.9 and (s.get("words") or [])]
report("KNOWN-GOOD", good, 14)
report("FILLED GAPS", [s for s in d["segments"] if s.get("filled_gap")], 10)
