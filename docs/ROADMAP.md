# Roadmap

## A better engine: letter-level alignment

[QuranReciteToText](https://github.com/Iam-Muslim/QuranReciteToText)'s `phoneme-الحمدلله`
branch aligns with a Zipformer CTC model over phonemes
([Quran-Lab/zipformer_p-arabic-v3](https://huggingface.co/Quran-Lab/zipformer_p-arabic-v3),
65.5M parameters, trained on 59,000+ hours) and gives **word and letter** timestamps, at
20 to 40x real time on a CPU, and its matcher tracks pauses, restarts and repetitions.
Moving the corpus to it needs:

1. **The Qalun reference.** It ships a Hafs reference (6,236 ayahs). Qalun differs in
   numbering, in ayah boundaries and in letters (مالك/ملك, the split last ayah of
   الفاتحة …); our `qpc_qalun.json` / `surah_info_qalun.json` are the starting point, and
   its phonetizer already supports Qalun's madd and yaa settings.
2. **The model's terms (read 2026-10-07).** Access is granted by hand on Hugging Face
   under the Quran-Lab No-Profit License 1.2 (NPL-1.2). What it means here:
   - Anything produced with the model, timings included, is a "Derivative" and has to be
     published under NPL-1.2 itself, with no other terms (section 7). Zipformer timings
     can therefore never join the CC BY 4.0 data; they go out on their own, marked
     experimental, under NPL-1.2, until a comparison says they are better.
   - Nothing built on them may be charged for, placed behind a payment, or carry
     advertising (sections 3 and 9). The apps that use these timings are free and carry
     no advertising.
   - No attribution is owed, but the LICENSE file travels with every copy (section 6).
   - Access was also given on three conditions: never charge for it, never present its
     output as an authoritative ruling on anyone's recitation, and say in any application
     that automatic tajweed feedback can be wrong and does not replace a teacher.
   - It recognises **Hafs** phonemes (its reference phonemises the 6,236 Hafs ayahs), so
     point 1 is a Qalun phonemisation of our text, not a lookup.
3. **Keeping what the apps rely on**: the same JSON formats (letters as an addition),
   the Qalun numbering, and a fresh measurement of onset latency before the apps' 350 ms
   lead-in is changed or dropped.

## Running alignment on GitHub Actions, not on our server

Our server serves the apps and the audio; it has 2 cores. Alignment is CPU work that
public repositories can do on GitHub's own machines (4 cores, 16 GB, up to 20 jobs at
once, no time cost to us): a workflow with a job per reciter (or per group of surahs)
fetches the audio from the URLs in `reciters.json`, runs the aligner, and uploads the
JSON as an artifact; a final job validates it against `schemas/`, folds the ayahs and
attaches everything to a release. The server only downloads the release.

It is blocked on the Qalun reference (point 1), not on CPU; the terms are settled above.

## A hand-timed evaluation set

Coverage today is the aligner's own report. A few surahs timed by hand, word by word, for
a few reciters (short and long surahs, fast and slow readers, one with repetitions) would
let any engine be measured: onset and offset error per word, ayah boundary error.
