# Qalun recitation timings · توقيتات تلاوات قالون

Open, word-level and ayah-level timings for complete recitations of the Quran in the
**Qalun ʿan Nafiʿ** riwayah, mostly by Libyan reciters: where every word and every ayah
starts and ends in each surah's audio. They drive the follow-along highlighting and
ayah-by-ayah playback of the apps مصحف الجماهيرية, مصاحف ليبيا and أذان وأذكار, and they
are here so others can use them, check them, and help make them better.

> توقيتات مفتوحة، كلمةً كلمة وآيةً آية، لختمات كاملة برواية قالون عن نافع، أكثرها لقرّاء
> ليبيين. تشغّل التظليل مع التلاوة والتشغيل آيةً آية في تطبيقات مصحف الجماهيرية ومصاحف ليبيا
> وأذان وأذكار، وهي هنا ليستعملها غيرنا ويراجعها ويساعد في تحسينها. المساهمة مرحّب بها:
> افتح issue أو pull request.

**Browse:** <https://qalun-timing.abdeljawad.com> (every file, with its audio and the
reference text side by side) · **Docs:** <https://qalun-timing.abdeljawad.com/docs/>

## What is here

| | |
|---|---|
| Reciters | 16 with word-level alignment (11 self-hosted Libyan khatmas + 5 from mp3quran.net), 17 with per-ayah timings |
| Surah files | 1,713 word-level, 1,711 per-ayah |
| Words timed | ~1.16 million |
| Word coverage | 98.8 to 99.97% per reciter (aligner self-report, see [Known limits](#known-limits)) |
| Numbering | Qalun, as مصحف الأوقاف الليبية: 6,214 ayahs, and the basmala is not an ayah in any surah, الفاتحة included |

## Download

From the [latest release](../../releases/latest) (or `releases/latest/download/<name>`):

| Asset | What |
|---|---|
| `qalun-timings-words.tar.gz` | word-level alignment, every reciter (`timing-data-nemo/<reciter>/<NNN>.json`) |
| `words-<reciter>.tar.gz` | the same, one reciter |
| `qalun-timings-ayahs.tar.gz` | per-ayah timings, every reciter (`timings/<reciter>/<NNN>.json`, `ayahs.json`, `index.json`) |
| `qalun-canon.tar.gz` | the reference text, one file per surah: what every word location points into |
| `reciters.json` | who, which riwayah, the audio URL of each surah, coverage, duration |
| `manifest.json` | per-surah numbers: segments, coverage, confidence, gaps, duration |
| `SHA256SUMS`, `index.json` | checksums; the release's files and date |

The audio is **not** redistributed: `reciters.json` gives the URL of every file that was
aligned (served by us for the Libyan khatmas, by mp3quran.net for the others).

## Formats

Every file has a JSON Schema in [`schemas/`](schemas/), and [docs/FORMATS.md](docs/FORMATS.md)
explains each field. Read its **traps** section before writing a parser: word times are
relative to their segment, gap-filled segments have a different shape, the basmala uses a
sentinel location, and the last word of a segment may run past the segment's end.

## How it was made

[docs/PIPELINE.md](docs/PIPELINE.md) in English, and the full engineering log in Arabic in
[docs/PIPELINE.ar.md](docs/PIPELINE.ar.md). In short: a FastConformer CTC model trained on
Quran recitation (`mohammed/fastconformer-quran-ar`, CC BY 4.0) recognises the audio in
windows, a matcher finds the ayahs against the Qalun reference text, CTC forced alignment
places every word, a second pass fills the words the first one missed, and the per-ayah
files are folded from the words.

The scripts in [`scripts/`](scripts/) are ours. They run on top of
[QuranReciteToText](https://github.com/Iam-Muslim/QuranReciteToText) (its August 2026
layout, `src/phase1_transcribe` … `phase4_splitting`), which has no licence and is
therefore **not** included here; see [docs/PIPELINE.md](docs/PIPELINE.md#reproducing).

## Known limits

- **Coverage is the aligner's own report, not measured accuracy.** There is no
  hand-timed reference set yet. Building one, even for a few surahs, would be the most
  useful contribution there is.
- **Word starts are late.** Against the audio, an ayah's recorded start is a median 110 ms
  late (p95 350 ms): the start lands inside the first word. The apps compensate by
  starting playback 350 ms early (never before the previous ayah's end) with a short
  fade. An aligner with accurate onsets would let that go; say so if yours has them.
- 42 ayahs in the per-ayah files are zero-length: ayahs the aligner never heard, between
  neighbours that touch. A few hundred words per reciter are missing at the word level.
- The mp3quran.net reciters have no per-surah coverage numbers in `manifest.json` yet.

## Help wanted

Other models (Zipformer, other FastConformer checkpoints, phoneme or letter-level
aligners), a hand-timed evaluation set, error reports on a specific surah and word: see
[CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

## Licence

- **Code** (`scripts/`): [MIT](LICENSE).
- **Timings** (the numbers and structure of every data file): [CC BY 4.0](DATA-LICENSE.md),
  credit «Abdeljawad Almiladi, qalun-timing.abdeljawad.com».
- **Quran text** inside the data (`word`, `matched_text`, `canon/`): مصحف الأوقاف الليبية
  برواية قالون, under that edition's terms; see [DATA-LICENSE.md](DATA-LICENSE.md).
- **Audio**: its publishers'; not included.

## Credits

The acoustic model: [mohammed/fastconformer-quran-ar](https://huggingface.co/mohammed/fastconformer-quran-ar)
(CC BY 4.0). The pipeline it runs in: [QuranReciteToText](https://github.com/Iam-Muslim/QuranReciteToText)
by Iam-Muslim, ported from [hetchyy's Quranic Universal Aligner](https://huggingface.co/spaces/hetchyy/quranic-universal-aligner)
(MIT), with silence splitting from the Adaptive Silence Engine (Itqan's Munajjam, PR #65).
The recitations: قناة القرآن الكريم الليبية (quranly.com.ly), ourquraan.com, midad.com,
archive.org, mp3quran.net and the reciters themselves, جزاهم الله خيراً.
