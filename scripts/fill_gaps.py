#!/usr/bin/env python3
"""Fill the small unmatched gaps by forced-aligning the words we know belong there.

The ASR-then-match pipeline leaves holes wherever the transcript drifted from
the reference, but the holes are tiny and well bounded: measured over a full
reciter, 1,224 gaps averaging 2.0 words, and 96%% of them sit between two
correctly matched words. For those we already know the exact audio span AND the
exact canonical text, which is a forced-alignment problem, not a recognition
one -- the matched neighbours act as anchors so the alignment cannot drift.

Each filled gap becomes its own segment marked `filled_gap`, so the work is
auditable and can be dropped again without touching the matched output.

The bracketing words are aligned WITH the missing ones and then discarded. That
matters more than it sounds: aligning a lone word against a span that actually
holds three lets the DP park it anywhere plausible. Measured on 78:14:4, doing
it that way put the word 1.10s from where the ASR independently timed it, while
genuinely matched spans sit within 0.06-0.36s. Anchoring both ends removes that
freedom.

Refuses to guess: a span with no room for the words it is supposed to hold
(a reciter who skipped them, or audio truncated at source) is left alone and
reported, rather than having words smeared across silence.
"""
import difflib
import json
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, "/root/qrtt")
os.chdir("/root/qrtt")
os.environ.setdefault("NEMO_CKPT", "/root/qrtt/phase3_full.nemo")

import numpy as np
import librosa

from nemo_adapter import NeMoASR
from src.phase3_alignment.ctc_align import (
    _load_vocab, _build_char_to_id, _tokenize_word, _forced_align_chunk, BLANK_ID,
    _strip_diacritics,
)

_strip = lambda s: _strip_diacritics(s or "").replace(" ", "")

SR = 16000
FRAME = 0.08
VOCAB_PATH = "/root/qrtt/data/tokens.txt"
AUDIO_ROOT = Path(os.environ.get("RECITERS_ROOT", "/var/www/quran-audio/audio"))
MIN_PER_WORD = float(os.environ.get("MIN_PER_WORD", "0.12"))   # s of audio a word needs
MAX_SPAN = float(os.environ.get("MAX_SPAN", "60.0"))           # refuse huge holes
MAX_OFFSET = float(os.environ.get("MAX_OFFSET", "0.60"))       # vs the ASR's own timing
PAD = 0.10                                                     # spill either side

_QPC = json.loads(Path("/root/qrtt/data/qpc_qalun.json").read_text(encoding="utf-8"))


def canon(surah):
    """Recited words of a surah in order; ornaments hold a slot but are silent."""
    ks = [k for k, v in _QPC.items()
          if int(v["surah"]) == surah and any(c.isalpha() for c in v["text"])]
    ks.sort(key=lambda k: (int(k.split(":")[1]), int(k.split(":")[2])))
    return ks, {k: _QPC[k]["text"] for k in ks}


def fill_file(path, surah, asr, vocab, c2i, verbose=False):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    segs = d.get("segments") or []
    order, text_of = canon(surah)
    if not order:
        return d, {"skipped": "no canon"}

    # absolute end/start time of every matched word we already trust
    at = {}
    for s in segs:
        if not s.get("ref_from"):
            continue
        base = s.get("time_from") or 0.0
        for w in (s.get("words") or []):
            loc = w.get("location")
            if loc and w.get("start") is not None:
                at[loc] = (base + w["start"], base + w["end"])

    idx = {k: i for i, k in enumerate(order)}
    missing = [k for k in order if k not in at]
    if not missing:
        return d, {"missing": 0, "filled": 0, "runs": 0}

    runs, cur = [], [missing[0]]
    for k in missing[1:]:
        if idx[k] == idx[cur[-1]] + 1:
            cur.append(k)
        else:
            runs.append(cur); cur = [k]
    runs.append(cur)

    # Spans are loaded one at a time rather than decoding the whole surah:
    # al-Baqarah is ~3 hours, which is ~700MB as float32, and this box runs the
    # filler alongside a model that already holds most of the free memory.
    apath = str(AUDIO_ROOT / d["reciter"] / f"{surah:03d}.mp3")
    filled = attempted = no_room = unbracketed = bad_offset = 0
    verified = 0
    new_segments = []

    for run in runs:
        i0, i1 = idx[run[0]], idx[run[-1]]
        prev_k = order[i0 - 1] if i0 > 0 else None
        next_k = order[i1 + 1] if i1 + 1 < len(order) else None
        if prev_k not in at or next_k not in at:
            unbracketed += 1
            continue
        # widen to include the anchors themselves; they constrain the fit and
        # are dropped again afterwards
        t0, t1 = at[prev_k][0], at[next_k][1]
        inner = at[next_k][0] - at[prev_k][1]
        if inner < MIN_PER_WORD * len(run) or (t1 - t0) > MAX_SPAN:
            no_room += 1
            continue
        seq = [prev_k] + run + [next_k]

        attempted += 1
        off = max(0.0, t0 - PAD)
        try:
            a, _ = librosa.load(apath, sr=SR, mono=True,
                                offset=off, duration=(t1 + PAD) - off)
        except Exception:
            no_room += 1
            continue
        if a.size < SR // 8:
            no_room += 1
            continue

        heard_text, heard_words, lp = asr.transcribe(a, SR)
        if lp is None:
            continue
        lp = lp[0] if lp.ndim == 3 else lp

        tok, counts = [], []
        for k in seq:
            ids = _tokenize_word(text_of[k], vocab, c2i)
            if not ids:
                counts.append(0); continue
            tok += ids; counts.append(len(ids))
        if not tok or lp.shape[0] < len(tok):
            no_room += 1
            continue

        align, scores = _forced_align_chunk(lp, tok)

        # frame span of each token, in emission order
        frames, ti, prev = [[] for _ in tok], 0, None
        for f, lab in enumerate(align):
            lab = int(lab)
            if lab == BLANK_ID:              # the aligner's blank, not len(vocab):
                prev = lab; continue          # vocab is 1025 long and blank is 1024,
                                              # so guessing it silently counted every
                                              # blank frame as a real token
            if lab != prev and ti < len(tok):
                frames[ti].append(f); ti += 1
            elif ti > 0:
                frames[ti - 1].append(f)
            prev = lab

        base = t0 - PAD
        words, p = [], 0
        for k, n in zip(seq, counts):
            fr = [f for j in range(p, p + n) for f in frames[j]] if n else []
            p += n
            if k not in set(run) or not fr:      # anchors served their purpose
                continue
            st, en = base + min(fr) * FRAME, base + (max(fr) + 1) * FRAME
            words.append({"word": text_of[k], "location": k,
                          "start": round(max(0.0, st - t0 + PAD), 4),
                          "end": round(max(0.0, en - t0 + PAD), 4)})
        if not words:
            continue

        # Verify rather than trust. The CTC path score cannot tell a good fill
        # from a bad one -- measured over segments the matcher placed at >=0.9
        # confidence it ranges 0.003 to 0.997 -- but the ASR's own timing for
        # the same word can: correct placements sit within ~0.06-0.36s of it.
        # A blank-id slip once put every word a whole word early while every
        # other number still looked healthy, so this check is not optional.
        offs = []
        for w in words:
            best, bs = None, 0.0
            for x in heard_words:
                r = difflib.SequenceMatcher(
                    None, _strip(w["word"]), _strip(x["word"])).ratio()
                if r > bs:
                    bs, best = r, x
            if best and bs >= 0.6:
                offs.append(abs((w["start"] - PAD) - best["start"]))
        offset = sum(offs) / len(offs) if offs else None
        if offset is not None and offset > MAX_OFFSET:
            bad_offset += 1
            continue
        conf = float(np.exp(np.mean(scores))) if len(scores) else 0.0
        new_segments.append({
            "ref_from": run[0], "ref_to": run[-1],
            "time_from": round(t0 - PAD, 4), "time_to": round(t1 + PAD, 4),
            "confidence": round(conf, 3),
            "matched_text": " ".join(text_of[k] for k in run),
            "filled_gap": True,
            # "verified" means an independent ASR timing agreed with us; the
            # rest are still written but marked, so they can be reviewed or
            # dropped without touching anything the matcher produced
            "fill_check": "verified" if offset is not None else "unverified",
            "fill_offset": round(offset, 3) if offset is not None else None,
            "words": words,
        })
        filled += len(words)
        if offset is not None:
            verified += len(words)
        if verbose:
            print(f"    filled {run[0]}..{run[-1]} ({len(words)}w) "
                  f"inner={inner:.2f}s conf={conf:.3f}")

    if new_segments:
        d["segments"] = sorted(segs + new_segments, key=lambda s: s.get("time_from") or 0.0)
        d["gap_filled_words"] = d.get("gap_filled_words", 0) + filled
    return d, {"missing": len(missing), "runs": len(runs), "attempted": attempted,
               "filled": filled, "verified": verified, "no_room": no_room,
               "unbracketed": unbracketed, "bad_offset": bad_offset}


def main():
    vocab = _load_vocab(VOCAB_PATH)
    c2i = _build_char_to_id(vocab)
    asr = NeMoASR.get_instance()
    tot = {"missing": 0, "filled": 0, "verified": 0, "no_room": 0,
           "unbracketed": 0, "runs": 0, "bad_offset": 0}
    for spec in sys.argv[1:]:
        p = Path(spec)
        surah = int(p.stem)
        d, st = fill_file(p, surah, asr, vocab, c2i, verbose=True)
        for k in tot:
            tot[k] += st.get(k, 0) or 0
        print(f"  {p.parent.name}/{p.stem}: {st}", flush=True)
        if st.get("filled"):
            p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTOTAL {tot}")


if __name__ == "__main__":
    main()
