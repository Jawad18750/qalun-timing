#!/usr/bin/env python3
"""The audio download page's index: every aligned recitation, surah by surah, with sizes.

The site's /audio/ page reads one file, audio/index.json, to offer each reciter's
recordings for download (one surah, a selection, or the whole khatma), alongside their
timings. The audio is not copied anywhere: each entry points at the server that already
serves it (ours for the Libyan khatmas, cdn.mp3quran.net for theirs), and the sizes come
from a HEAD request to that server, so the page can say how much a khatma weighs before
anyone starts it.

    python3 build_audio_index.py --out audio/index.json
    python3 build_audio_index.py --reciters reciters.json --canon canon --out audio/index.json

With no arguments it reads reciters.json from the latest release and the surah names from
the site's canon/. Run it after a release that adds or changes a reciter; it sends one
HEAD request per surah file (about 1,700), a few at a time, and touches nothing else.
"""
import argparse
import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RELEASE = "https://github.com/Jawad18750/qalun-timing/releases/latest/download/reciters.json"
SITE = "https://qalun-timing.abdeljawad.com"
UA = {"User-Agent": "qalun-timing audio index (+https://qalun-timing.abdeljawad.com)"}

# Harakat, Quranic annotation marks and tatweel: the names are shown as labels, not text.
_MARKS = re.compile("[ـً-ٰٟۖ-ۭ]")


def _get(url, method="GET"):
    req = urllib.request.Request(url, method=method, headers=UA)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.headers, (r.read() if method == "GET" else b"")
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def _surah_names(canon):
    names = []
    for s in range(1, 115):
        if canon:
            d = json.loads((Path(canon) / f"{s:03d}.json").read_text(encoding="utf-8"))
        else:
            d = json.loads(_get(f"{SITE}/canon/{s:03d}.json")[1])
        names.append(_MARKS.sub("", d["name"]).strip())
    return names


def _size(url):
    try:
        headers, _ = _get(url, "HEAD")
        return int(headers.get("Content-Length") or 0)
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reciters", help="reciters.json (default: the latest release's)")
    ap.add_argument("--canon", help="canon/ folder (default: the site's)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    data = json.loads(Path(a.reciters).read_text(encoding="utf-8") if a.reciters
                      else _get(RELEASE)[1])
    names = _surah_names(a.canon)

    jobs = [(r["id"], s, r["audio"].format(surah=s))
            for r in data["reciters"] for s in r["surahs"]]
    with ThreadPoolExecutor(8) as pool:
        sizes = dict(zip(((rid, s) for rid, s, _ in jobs),
                         pool.map(lambda j: _size(j[2]), jobs)))

    reciters = []
    for r in data["reciters"]:
        files = {str(s): sizes[(r["id"], s)] for s in r["surahs"]}
        missing = [s for s, n in files.items() if not n]
        if missing:
            print(f"{r['id']}: no size for surah {', '.join(missing)}")
        reciters.append({
            "id": r["id"],
            "name": r["name"],
            "riwayah": r.get("riwayah"),
            "source": r.get("source"),
            "audio": r["audio"],
            "self_hosted": r["audio"].startswith("https://quran-audio.abdeljawad.com/"),
            "duration_s": r.get("duration_s"),
            "word_coverage": r.get("word_coverage"),
            "words": f"{SITE}/timing-data-nemo/{r['id']}/{{surah:03d}}.json",
            "ayahs": r.get("ayahs"),
            "bytes": sum(files.values()),
            "files": files,
        })

    out = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "licence": {
            "audio": "Each recording belongs to its publisher (see source). Files are served "
                     "from where they are hosted, for listening, study and research with the "
                     "timings; republishing them needs the publisher's permission.",
            "timings": data.get("licence", {}).get("timings"),
        },
        "surahs": names,
        "reciters": reciters,
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                           encoding="utf-8")
    total = sum(r["bytes"] for r in reciters)
    print(f"wrote {a.out}: {len(reciters)} reciters, {len(jobs)} files, {total / 1e9:.1f} GB")


if __name__ == "__main__":
    main()
