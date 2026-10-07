# Data formats

Every file below has a JSON Schema in [`../schemas/`](../schemas/) (draft 2020-12), checked
against every published file. All files are UTF-8 JSON. Times in the word files are
**seconds** (floats); times in the per-ayah files are **milliseconds** (integers).

## Locations and numbering

A word is addressed as `surah:ayah:word`, all 1-based, in the **Qalun** numbering of
مصحف الأوقاف الليبية: 6,214 ayahs, the basmala never an ayah (الفاتحة's first ayah is
«الحمد لله رب العالمين»). Word `k` of ayah `a` of surah `s` is `canon/<sss>.json` →
`ayahs[a][k-1]`. Hafs-numbered data (6,236 ayahs) will not line up: the ayah boundaries
differ in dozens of places, not only at the basmala.

Words that are not Quran text (the isti'adha, the basmala, a tahmeed) carry the
**sentinel** location `0:0:N`, N counting their words.

## Word-level alignment: `timing-data-nemo/<reciter>/<NNN>.json`

Schema: [`words-surah.schema.json`](../schemas/words-surah.schema.json). One audio file of one
reciter, normally one surah.

```json
{
  "reciter": "abdulhamid_algriw", "surah": 1, "detected_surah": 1,
  "surah_mismatch": false, "surahs_present": [1], "alternate_source": false,
  "chunk_window": 20.0,
  "segments": [
    {"segment": 3, "time_from": 13.08, "time_to": 18.28,
     "ref_from": "1:1:1", "ref_to": "1:1:4", "matched_text": "اِ۬لْحَمْدُ لِلهِ …",
     "confidence": 0.93, "has_missing_words": false, "has_repeated_words": false,
     "special_type": null, "error": null,
     "words": [{"word": "اِ۬لْحَمْدُ", "location": "1:1:1", "start": 0.0, "end": 0.8}, …]}
  ]
}
```

| field | |
|---|---|
| `reciter` | the recitation id. For the mp3quran.net reciters the file says mp3quran's server slug (`trablsi`); the directory is the apps' id (`mp3quran_201_199`) |
| `surahs_present` | more than one when a file holds two surahs (`085` = البروج then الطارق) |
| `alternate_source` | this surah is a separate recording filling a gap in the khatma (`alternate_source_url`, `alternate_source_note` say which) |
| `chunk_window` | recognition window, seconds (10.5 or 20) |
| `gap_filled_words` | words added by the second pass |
| segment `special_type` | `null`, `"Basmala"`, `"Isti'adha"` or `"Tahmeed"` |
| segment `error` | e.g. `"Low confidence (0%)"`, `"Dropped: isolated match on surah N …"` |
| segment `repeated_ranges`, `repeated_text`, `wrap_word_ranges` | the reciter read a stretch again (takrar) |
| segment `words` | may be **empty**: the segment sits on text the matcher had already used up |

### Traps

1. **Word `start`/`end` are relative to the segment.** `absolute = segment.time_from +
   word.start`. Every segment's first word starts near 0.0.
2. **Gap-filled segments have another shape.** They carry `filled_gap: true`,
   `fill_check` (`"verified"` when a second recognition of that stretch confirmed the
   words) and `fill_offset`, and they have **no** `segment`, `has_missing_words`,
   `has_repeated_words`, `special_type` or `error` keys. About 2% of segments.
3. **The last word may end after `time_to`** (up to ~1.4 s). It is real: do not clamp a word
   to its segment.
4. **Times are quantised to 0.08 s**, the model's frame stride.
5. **The same text can be placed twice**: the basmala's «الرحمن الرحيم» on الفاتحة's ayah 2,
   a re-read ayah, a repeated phrase. Take an ayah's readings in recitation order rather
   than the earliest and latest word of that ayah (see `scripts/ayah_timings.py`).
6. `ref_from`/`ref_to` are `""` or `null` on non-Quran segments.

## Per-ayah timings: `timings/<reciter>/<NNN>.json` and `ayahs.json`

Schemas: [`ayahs-surah.schema.json`](../schemas/ayahs-surah.schema.json),
[`ayahs-compact.schema.json`](../schemas/ayahs-compact.schema.json).

```json
{"reciter_id": "abdulhamid_algriw", "surah": 1,
 "ayahs": [{"ayah": 1, "start_ms": 13080, "end_ms": 17080}, …]}
```

`ayahs.json` holds every surah of one reciter compactly, `{"surahs": {"1": [[ayah,
start_ms, end_ms], …]}}`, with `version` and `generated`; the apps bundle it and treat
`generated` as its revision.

Folded from the word files by `scripts/ayah_timings.py`: each ayah's first reading after
the previous ayah, a reading split by a stray word of another ayah kept whole; an ayah
the aligner never heard is bridged between its neighbours (zero-length if they touch);
spans never overlap and never run backwards.

**Starts are late.** Measured on 674 boundaries, `start_ms` is a median 110 ms after the
first sound of the ayah (p95 350 ms). The apps seek to `start_ms − 350` (never before the
previous ayah's `end_ms`) and fade in over 150 ms.

`timings/index.json` ([schema](../schemas/timings-index.schema.json)) lists each reciter's
surahs and how many ayahs were bridged.

## Reference text: `canon/<NNN>.json`

Schema: [`canon-surah.schema.json`](../schemas/canon-surah.schema.json).

```json
{"surah": 2, "name": "البَقَرَة", "ayahs": {"1": ["أَلَٓمِّٓۖ", "ذَٰلِكَ", …]}, "ornaments": {"13": [1]}}
```

`ornaments` lists, per ayah, the 1-based word positions that are ornaments (۞ and the
like): they are in the text, never recited, and not counted in coverage.

## `reciters.json` and `manifest.json`

[`reciters.schema.json`](../schemas/reciters.schema.json): per reciter, `audio` is a URL
template (`{surah:03d}` → `001` … `114`) of the exact files that were aligned; the timings
match those files. The Libyan khatmas are served re-encoded to 64 kbps mono 22.05 kHz,
which keeps the timing of the originals.

`manifest.json` has one entry per surah file: `segments`, `matched`, `specials`,
`gap_pct`, `avg_confidence`, `ayahs_covered`, `words_covered`, `total_words`,
`word_coverage` (%), `duration_s`, `audio_url`, `json_url`.
