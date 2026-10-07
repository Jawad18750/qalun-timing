# The site

The pages of <https://qalun-timing.abdeljawad.com>, as deployed. Plain HTML, no build step.

| Path | Page |
|---|---|
| `index.html` | the viewer: every reciter and surah, with coverage, the audio and the words |
| `docs/index.html` | documentation and downloads, in Arabic |
| `audio/index.html` | recitation downloads: a surah, a selection or a whole khatma, with timings |

The data they read is generated, not kept here: `manifest.json` (`scripts/generate_manifest.py`),
`audio/index.json` (`scripts/build_audio_index.py`), `timing-data-nemo/` and `canon/` (the
pipeline), `schemas/` (copied from this repository's `schemas/`).

Deploy by copying a page to the same path under `/var/www/qalun-timing/public_html/`.
