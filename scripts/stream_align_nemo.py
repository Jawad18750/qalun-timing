#!/usr/bin/env python3
"""Qalun word-timings for the mp3quran reciters, on the NeMo engine.

Same contract as stream_align.py: each surah is streamed to a temp file,
aligned, the JSON kept, and the audio deleted immediately in a finally block.
Peak disk is one file, and we never re-host anyone else's recitation.

Two things differ. Phase 1 is NeMo rather than the published ONNX graph, which
is intermittently corrupt. And the chunk ceiling is chosen per file by scoring
the result against the surah we know it is: long files start at the wide window
because phase 1 holds the per-chunk logits and halving the chunk size roughly
doubles peak memory, which OOM-killed the main rebuild twice on this box.

Writes to its own OUT_ROOT so the earlier ONNX pass stays intact for comparison.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QURAN_EDITION", "qalun")
os.environ.setdefault("ENABLE_AUTO_UPDATE", "false")
os.environ.setdefault("FORCE_SINGLE_CHAPTER", "true")
os.environ.setdefault("ASR_CHUNK_WORKERS", "1")
os.environ.setdefault("NEMO_CKPT", "/root/qrtt/phase3_full.nemo")

APP = Path(__file__).parent.resolve()
sys.path.insert(0, str(APP))

OUT_ROOT = Path(os.environ.get("OUT_ROOT", "/root/qrtt/output_mp3quran_nemo"))
ROSTER = Path(os.environ.get("ROSTER", "/root/qrtt/mp3quran_qalun.json"))
TMP = Path("/tmp/stream_align_nemo.mp3")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0 Safari/537.36")
ONLY = os.environ.get("ONLY_SLUG")
WINDOWS = [float(x) for x in os.environ.get("WINDOWS", "10.5,20.0").split(",")]
TARGET = float(os.environ.get("COVERAGE_TARGET", "0.97"))
LONG_S = float(os.environ.get("LONG_S", "1500"))

from nemo_adapter import NeMoASR
import src.phase1_transcribe.fastconformer as fc
fc.FastConformerONNX = NeMoASR
import src.phase1_transcribe.stream as stream
stream.FastConformerONNX = NeMoASR

_QPC = json.loads(Path("/root/qrtt/data/qpc_qalun.json").read_text(encoding="utf-8"))
WORDS_BY_SURAH = {}
for _k, _v in _QPC.items():
    if any(c.isalpha() for c in _v["text"]):      # ornaments are never recited
        WORDS_BY_SURAH.setdefault(int(_v["surah"]), set()).add(_k)


def coverage(payload, surah):
    need = WORDS_BY_SURAH.get(surah) or set()
    if not need:
        return 0.0
    got = {w["location"]
           for s in (payload or {}).get("segments", []) if s.get("ref_from")
           for w in (s.get("words") or []) if w.get("location")}
    return len(need & got) / len(need)


def fetch(url, dest):
    r = subprocess.run(
        ["curl", "-fsSL", "--retry", "4", "--retry-delay", "3", "--retry-all-errors",
         "--max-time", "1800", "-A", UA, "-o", str(dest), url],
        capture_output=True,
    )
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size < 1024:
        return None
    return dest.stat().st_size


def main():
    from src.core.main_flow import process_audio
    from postprocess import postprocess
    from src.phase2_matching.normalize import get_arabic_resources

    print("Preloading NeMo + Qalun resources...", flush=True)
    t0 = time.time()
    NeMoASR.get_instance(device="cpu")
    get_arabic_resources()
    print(f"Preload done in {time.time()-t0:.1f}s", flush=True)

    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    jobs = []
    for rec in roster:
        if ONLY and rec["slug"] != ONLY:
            continue
        for s in rec["surahs"]:
            jobs.append((rec["slug"], rec["name"], rec["server"], s))
    print(f"{len(jobs)} surahs queued across {len({j[0] for j in jobs})} reciters",
          flush=True)

    done = skipped = failed = 0
    start = time.time()
    for i, (slug, name, server, surah) in enumerate(jobs, 1):
        out_dir = OUT_ROOT / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{surah:03d}.json"

        prior_cov = -1.0
        prior = None
        if out_path.exists():
            try:
                prior = json.loads(out_path.read_text(encoding="utf-8"))
                prior_cov = coverage(prior, surah)
                if prior_cov >= TARGET:
                    skipped += 1
                    continue
            except Exception:
                prior, prior_cov = None, -1.0

        url = f"{server.rstrip('/')}/{surah:03d}.mp3"
        TMP.unlink(missing_ok=True)
        t = time.time()
        size = fetch(url, TMP)
        if size is None:
            failed += 1
            print(f"[{i}/{len(jobs)}] {slug}/{surah:03d}: DOWNLOAD FAILED {url}", flush=True)
            continue

        try:
            approx_s = size * 8 / 128000
            order = sorted(WINDOWS, reverse=True) if approx_s > LONG_S else list(WINDOWS)
            prior_win = (prior or {}).get("chunk_window")
            todo = [w for w in order if w != prior_win] or order

            best = (prior_cov, prior, prior_win) if prior is not None else (-1.0, None, None)
            for w in todo:
                stream._MAX_MODEL_CHUNK_S = w
                os.environ["EXPECTED_SURAH"] = str(surah)
                payload, prof = process_audio(
                    audio_data=str(TMP), model_name="Base",
                    profile_name="auto", return_profiling=True,
                )
                payload, st = postprocess(payload, expected_surah=surah)
                cov = coverage(payload, surah)
                payload = {"reciter": slug, "reciter_name": name, "surah": surah,
                           "source": url,
                           "detected_surah": st["detected_surah"],
                           "surah_mismatch": st["surah_mismatch"],
                           "surahs_present": st["surahs_present"],
                           "chunk_window": w, **(payload or {})}
                if cov > best[0]:
                    best = (cov, payload, w)
                if cov >= TARGET:
                    break

            cov, payload, w = best
            if payload is None:
                raise ValueError("no window produced a result")
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            done += 1
            el = time.time() - t
            dur = getattr(prof, "audio_duration_s", 0.0)
            print(f"[{i}/{len(jobs)}] {slug}/{surah:03d}: {dur:.0f}s audio, "
                  f"{size/1048576:.0f}MB streamed, {el:.0f}s "
                  f"({dur/el if el else 0:.1f}x), win={w}, cov={100*cov:.1f}%"
                  + ("  <-- below target" if cov < TARGET else ""), flush=True)
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(jobs)}] {slug}/{surah:03d}: FAILED: {e}", flush=True)
            (out_dir / f"{surah:03d}.FAILED.txt").write_text(str(e))
        finally:
            TMP.unlink(missing_ok=True)      # never accumulate audio

    print(f"\nDone. processed={done} skipped={skipped} failed={failed} "
          f"in {(time.time()-start)/3600:.2f}h", flush=True)


if __name__ == "__main__":
    main()
