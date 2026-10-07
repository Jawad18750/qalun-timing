#!/usr/bin/env python3
"""Rebuild the corpus with NeMo in phase 1, choosing the chunk window per file.

Only the transcription engine changes; matching, forced alignment and the ayah
split stay the pipeline's own, as the tool's author advised.

Why per-file windows. Anchoring uses exact 10-char n-gram voting over the
leading segments, so the chunk ceiling decides how much text it gets to vote
with -- and the failures that follow are chaotic rather than monotonic. Measured
over one full reciter, 20s scored 97.88%% overall but sent An-Nas to 0.0%%
(its basmala anchored to An-Naml 27:30, the only mid-text occurrence), while
10.5s scored 95.93%% and instead lost Al-Hijr to Sad across their near-identical
Iblis passages. Different files lose at different ceilings, so no single value
is right.

Every file is a known surah by its filename, so we can just score the result and
keep the better one. Most files clear the target on the first window and cost
nothing extra.

Known limitation, not fixable here: the model does not re-emit a verbatim
repetition, so ayat repeated back-to-back come out once. Al-Kafirun 109:3 and
109:5 are identical and only one survives. Segmenting on waqf rather than
silence is the real fix.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, "/root/qrtt")
os.chdir("/root/qrtt")
os.environ.setdefault("NEMO_CKPT", "/root/qrtt/phase3_full.nemo")
os.environ.setdefault("QURAN_EDITION", "qalun")
os.environ.setdefault("FORCE_SINGLE_CHAPTER", "true")

RECITERS_ROOT = Path(os.environ.get("RECITERS_ROOT", "/var/www/quran-audio/audio"))
OUTPUT_ROOT = Path(os.environ.get("OUTPUT_ROOT", "/root/qrtt/output_nemo"))
WINDOWS = [float(x) for x in os.environ.get("WINDOWS", "10.5,20.0").split(",")]
# Long files are tried at the WIDE window first. Phase 1 keeps the per-chunk
# logits for the whole file, so halving the chunk size roughly doubles peak
# memory -- trying 10.5s first on a 2-hour surah OOM-killed the run at file 229
# on this 8GB box. The wide window is also what long files ended up choosing
# anyway (002, 003, 004, 009 all preferred it), so this costs nothing.
LONG_S = float(os.environ.get("LONG_S", "1500"))
TARGET = float(os.environ.get("COVERAGE_TARGET", "0.97"))

from nemo_adapter import NeMoASR
import src.phase1_transcribe.fastconformer as fc
fc.FastConformerONNX = NeMoASR
import src.phase1_transcribe.stream as stream
stream.FastConformerONNX = NeMoASR

_Q = json.loads(Path("/root/qrtt/data/qpc_qalun.json").read_text(encoding="utf-8"))
WORDS_BY_SURAH = {}
for _k, _v in _Q.items():
    # ornamental marks hold a word slot in quran.db but are never recited
    if any(c.isalpha() for c in _v["text"]):
        WORDS_BY_SURAH.setdefault(int(_v["surah"]), set()).add(_k)


def coverage(payload, surah):
    """Share of the EXPECTED surah's words that got a timing.

    Deliberately not the union over surahs_present: a spurious second surah
    would inflate the denominator and disguise itself as a low score.
    """
    need = WORDS_BY_SURAH.get(surah) or set()
    if not need:
        return 0.0
    got = {w["location"]
           for s in (payload or {}).get("segments", []) if s.get("ref_from")
           for w in (s.get("words") or []) if w.get("location")}
    return len(need & got) / len(need)


def discover_jobs():
    for slug in sorted(d.name for d in RECITERS_ROOT.iterdir() if d.is_dir()):
        for f in sorted((RECITERS_ROOT / slug).glob("*.mp3")):
            m = re.match(r"^(\d{3})$", f.stem)
            if m:
                yield slug, int(m.group(1)), f


def main():
    from src.core.main_flow import process_audio
    from postprocess import postprocess

    print("Preloading model + Qalun matching resources...", flush=True)
    t0 = time.time()
    from src.phase2_matching.normalize import get_arabic_resources
    NeMoASR.get_instance(device="cpu")
    get_arabic_resources()
    print(f"Preload done in {time.time()-t0:.1f}s", flush=True)

    jobs = list(discover_jobs())
    print(f"{len(jobs)} files to process", flush=True)
    done = skipped = failed = retried = 0

    for i, (slug, surah, audio_path) in enumerate(jobs, 1):
        out_dir = OUTPUT_ROOT / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{surah:03d}.json"

        # Resume, but only accept earlier work that already met the target;
        # anything weaker gets another window rather than standing.
        prior_cov, prior = -1.0, None
        if out_path.exists():
            try:
                prior = json.loads(out_path.read_text(encoding="utf-8"))
                prior_cov = coverage(prior, surah)
                if prior_cov >= TARGET:
                    skipped += 1
                    continue
            except Exception:
                prior, prior_cov = None, -1.0

        # the window that produced the stored attempt is not worth repeating
        prior_win = (prior or {}).get("chunk_window")
        try:
            approx_s = audio_path.stat().st_size * 8 / 128000      # ~128kbps
        except OSError:
            approx_s = 0.0
        order = sorted(WINDOWS, reverse=True) if approx_s > LONG_S else list(WINDOWS)
        todo = [w for w in order if w != prior_win] or order

        t_file = time.time()
        best = (prior_cov, prior, prior_win) if prior is not None else (-1.0, None, None)
        try:
            for w in todo:
                stream._MAX_MODEL_CHUNK_S = w
                os.environ["EXPECTED_SURAH"] = str(surah)
                payload, prof = process_audio(audio_data=str(audio_path),
                                              model_name="Base", profile_name="auto",
                                              return_profiling=True)
                payload, st = postprocess(payload, expected_surah=surah, reciter=slug)
                cov = coverage(payload, surah)
                payload = {"reciter": slug, "surah": surah,
                           "detected_surah": st["detected_surah"],
                           "surah_mismatch": st["surah_mismatch"],
                           "surahs_present": st["surahs_present"],
                           "alternate_source": st["alternate_source"],
                           "chunk_window": w, **(payload or {})}
                if cov > best[0]:
                    best = (cov, payload, w)
                if cov >= TARGET:
                    break
                retried += 1

            cov, payload, w = best
            if payload is None:
                raise ValueError("no window produced a result")
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            done += 1
            el = time.time() - t_file
            dur = getattr(prof, "audio_duration_s", 0.0)
            print(f"[{i}/{len(jobs)}] {slug}/{surah:03d}: {dur:.0f}s in {el:.1f}s "
                  f"({dur/el if el else 0:.1f}x), win={w}, cov={100*cov:.1f}%"
                  + ("  <-- below target" if cov < TARGET else ""), flush=True)
        except Exception as e:
            failed += 1
            import traceback
            print(f"[{i}/{len(jobs)}] {slug}/{surah:03d}: FAILED: {e}", flush=True)
            traceback.print_exc()

    print(f"\nDone. processed={done} skipped={skipped} failed={failed} "
          f"extra_window_runs={retried}", flush=True)


if __name__ == "__main__":
    main()
