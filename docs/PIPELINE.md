# How the timings are made

A summary in English. The engineering log, with every measurement and the reasons behind
each choice, is in Arabic in [PIPELINE.ar.md](PIPELINE.ar.md); the evaluation of a waqf
(pause) segmenter we did not adopt is in [WAQF_SEGMENTER.ar.md](WAQF_SEGMENTER.ar.md).

## Inputs

- **Audio**: one MP3 per surah. The Libyan khatmas are mirrored and re-encoded to 64 kbps
  mono 22.05 kHz (duration checked against the source), and aligned in that form; the
  mp3quran.net reciters are streamed from their server, aligned, and not kept
  (`scripts/stream_align_nemo.py`).
- **Reference text**: مصحف الأوقاف الليبية برواية قالون, word for word as the apps show it
  (77,909 words, 6,214 ayahs), in the pipeline's own format (`data/qpc_qalun.json`,
  `data/surah_info_qalun.json`) and as `canon/` for review.

## Steps

1. **Recognition (phase 1).** `mohammed/fastconformer-quran-ar`
   (`phase3_full_wer0.0014.nemo`, CC BY 4.0), run directly through its preprocessor,
   encoder and CTC head (`scripts/nemo_adapter.py`) rather than `ASRModel.transcribe()`,
   which raises on this checkpoint and hides the per-frame logits the alignment needs.
   The published ONNX export of the same model gives intermittently corrupt output at
   some window lengths; the `.nemo` does not. On a 2-core CPU it runs at about 20x real
   time.
2. **Windows.** Audio is split on silence and recognised in windows of at most 10.5 s or
   20 s. Each file is tried at one, scored, and retried at the other if word coverage is
   under 97%; the better result is kept (`scripts/batch_run_nemo.py`). Different files
   fail at different ceilings, so no single value is right. Files over 25 minutes start
   at 20 s to bound memory.
3. **Matching (phase 2).** The recognised text is matched against the reference to find
   the surah and ayahs, with the surah forced from the file name (`FORCE_SINGLE_CHAPTER`)
   and a wider anchoring window for files that open with noise.
4. **Forced alignment (phase 3).** CTC forced alignment over the model's own logits
   places every word; times are real, not interpolated (word lengths in surah طه range
   0.16 to 3.84 s, median 0.80 s). Word smoothing (stretching each word to touch the
   next) is off.
5. **Post-processing** (`scripts/postprocess.py`): duplicate word locations from a word
   cut across a window boundary are removed while real repetitions are kept
   (`wrap_word_ranges`); a file holding two surahs keeps both; separate recordings that
   fill a gap in a khatma are flagged `alternate_source`.
6. **Gap filling** (`scripts/fill_gaps.py`): words the first pass missed are searched for
   in the audio between their aligned neighbours, re-recognised, and written as
   `filled_gap` segments, `verified` when the second recognition agrees.
7. **Manifest** (`scripts/generate_manifest.py`): per-file coverage, confidence and gaps,
   ornaments (۞) excluded; publishes the files for the browser.
8. **Per-ayah fold** (`scripts/ayah_timings.py`): each ayah from its words, in recitation
   order, bridged where missing; what the apps play from.

## Known weaknesses

- **Back-to-back repetition**: the model does not re-emit a verbatim repetition, so an
  ayah read twice in a row (109:3 and 109:5 are identical) can come out once.
- **Late onsets**: an ayah's recorded start is a median 110 ms after its first sound.
- **No ground truth**: coverage is the aligner's own report.

## Reproducing

The scripts here are ours. They import the August 2026 layout of
[QuranReciteToText](https://github.com/Iam-Muslim/QuranReciteToText)
(`src/core`, `src/phase1_transcribe`, `src/phase2_matching`, `src/phase3_alignment`,
`src/phase4_splitting`, `config.py`) and the `qua_sdk` wheel it vendors. That project has
no licence, so neither is redistributed here, and its current branches have since been
restructured. Rerunning the exact pipeline therefore needs that snapshot, which a licence
from its author would let us publish. The scripts still document every step, and the ayah
fold runs on the published JSON alone, reproducing the server's output exactly:

```sh
tar xzf qalun-timings-words.tar.gz && tar xzf qalun-canon.tar.gz
python3 scripts/ayah_timings.py --words timing-data-nemo --canon canon \
    --manifest manifest.json --out timings
python3 -m unittest scripts/test_ayah_timings.py
```

Paths in the scripts are the server's (`/root/qrtt`, `/var/www/...`); most read them from
environment variables.
