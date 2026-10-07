#!/usr/bin/env python3
"""Emits the canonical Qalun text per surah for the review UI.

The reader must render the mushaf's OWN text as ground truth and merely
decorate it with whatever timings the aligner produced. Rendering only the
matched words (what it did before) meant any word the ASR missed silently
vanished from the page -- which reads as "the text is wrong", when in fact
the reference was correct and the alignment was simply incomplete.

Output: canon/<NNN>.json = {"surah":N,"name":"...","ayahs":{"1":["word",...]}}
built straight from assets/data/quran.db, the same DB the apps ship.
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

NUMERAL_RE = re.compile(r'^[٠-٩]+$')


def main(db_path, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)

    names = {n: ar for n, ar in con.execute("SELECT num, name_ar FROM surahs")}
    per_surah = {}
    for surah, ayah, text in con.execute(
        "SELECT surah_num, ayah_num, text_ar FROM verses ORDER BY surah_num, ayah_num"
    ):
        words = text.split()
        if not words or not NUMERAL_RE.fullmatch(words[-1]):
            raise ValueError(f"unexpected trailing token at {surah}:{ayah}: {text!r}")
        per_surah.setdefault(surah, {})[str(ayah)] = words[:-1]

    total_words = 0
    for surah, ayahs in per_surah.items():
        total_words += sum(len(w) for w in ayahs.values())
        (out / f"{surah:03d}.json").write_text(
            json.dumps(
                {"surah": surah, "name": names.get(surah, ""), "ayahs": ayahs},
                ensure_ascii=False, separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    print(f"wrote {len(per_surah)} surah files, {total_words} words to {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
