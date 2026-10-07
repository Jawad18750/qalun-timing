# Contributing · المساهمة

Contributions are welcome, in Arabic or English.

**Report a wrong timing.** Open an issue with the reciter id, the surah, the word or ayah
(`surah:ayah:word`), and what you hear: the browser at
<https://qalun-timing.abdeljawad.com> plays any word from its timing.

**Try another model.** Align some files with your engine, write them in the same format
([docs/FORMATS.md](docs/FORMATS.md), [schemas/](schemas/)), and open an issue or a pull
request with the files (or a link) and how you ran it. Same reciters, same audio URLs
(`reciters.json`), same Qalun numbering, so results can be compared word for word. Say
whether your onsets are accurate: the apps currently start 350 ms early to make up for
late starts.

**Time something by hand.** A hand-timed surah, even a short one, is the most useful
thing there is; see [docs/ROADMAP.md](docs/ROADMAP.md).

**Code.** `scripts/` is MIT. Keep the formats backward compatible: the apps read them.
Run `python3 -m unittest scripts/test_ayah_timings.py` before sending a change to the fold.

By contributing data you agree to it being published under CC BY 4.0 with the rest.
