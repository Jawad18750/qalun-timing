#!/usr/bin/env python3
"""The corpus packed for download, with an index: the assets of a GitHub release.

Runs anywhere, against the server's folders or a copy of them (the server's disk and CPU
are kept for serving; Jawad, 2026-10-07), and writes

    downloads/
      qalun-timings-words.tar.gz          word-level alignment, every reciter (timing-data-nemo/)
      qalun-timings-ayahs.tar.gz          per-ayah timings, every reciter (the apps' format)
      qalun-canon.tar.gz                  the reference text, one file per surah (canon/)
      words-<reciter>.tar.gz              word-level alignment, one reciter
      reciters.json                       who, which riwayah, where the audio is, coverage
      manifest.json                       per-surah review numbers (copied)
      SHA256SUMS                          for everything above
      index.json                          the files, sizes, hashes and the date

The names carry no date, so https://github.com/<repo>/releases/latest/download/<name> is
always the newest; the release's tag and index.json say when it was made.

so someone trying another model (Zipformer, another FastConformer, …) can take the
reference, the audio list and our output in three files, and compare against it.

The timings are CC BY 4.0. The Quran text inside them (`word`, `matched_text`, canon/) is
مصحف الأوقاف الليبية برواية قالون and keeps that edition's terms; the audio is its
publishers', listed per reciter and not copied here.

    python3 build_downloads.py --out DIR                       # on the server
    python3 build_downloads.py --root MIRROR --out DIR         # a copy made with
        rsync -a server:/var/www/qalun-timing/public_html/{timing-data-nemo,canon,manifest.json} MIRROR/web/
        rsync -a server:/var/www/quran-audio/public_html/{timings,api} MIRROR/audio/
"""
import argparse
import hashlib
import json
import shutil
import tarfile
import time
from pathlib import Path

WEB = Path("/var/www/qalun-timing/public_html")
AUDIO_WEB = Path("/var/www/quran-audio/public_html")


def _roots(root):
    global WORDS, CANON, MANIFEST, AYAHS, SELF_HOSTED_CATALOGUE
    web, audio = (root / "web", root / "audio") if root else (WEB, AUDIO_WEB)
    WORDS = web / "timing-data-nemo"
    CANON = web / "canon"
    MANIFEST = web / "manifest.json"
    AYAHS = audio / "timings"
    SELF_HOSTED_CATALOGUE = audio / "api" / "v3" / "reciters.json"

# The mp3quran.net قالون reciters aligned from their own servers: directory = the apps'
# recitation id. Names and folders as mp3quran.net's /api/v3/reciters?rewaya=5 gives them.
MP3QURAN = {
    "mp3quran_201_199": ("أحمد الطرابلسي", "https://cdn.mp3quran.net/audio/ahmad-tarabulsi/r1/"),
    "mp3quran_212_212": ("طارق عبدالغني دعوب", "https://cdn.mp3quran.net/audio/tareq-daawob/r1/"),
    "mp3quran_237_287": ("مروان العكري", "https://cdn.mp3quran.net/audio/marwan-akri/r1/"),
    "mp3quran_265_280": ("أحمد ديبان", "https://cdn.mp3quran.net/audio/ahmad-deeban/r5/"),
    "mp3quran_274_274": ("محمد أبو سنينة", "https://cdn.mp3quran.net/audio/muhammad-abusnaina/r1/"),
    "mp3quran_275_275": ("محمد الأمين قنيوة", "https://cdn.mp3quran.net/audio/muhammad-qeniwa/r1/"),
}

LICENCE = {
    "timings": "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), credit: "
               "Abdeljawad Almiladi, qalun-timing.abdeljawad.com",
    "text": "The Quran text in the files (word, matched_text, canon) is مصحف الأوقاف الليبية "
            "برواية قالون and keeps that edition's terms (reported: free for non-commercial use; "
            "commercial use needs the Libyan Ministry of Awqaf's permission).",
    "audio": "Not included. Each reciter's audio belongs to its publisher (see source); the "
             "URLs are where the aligned files are served.",
    "model": "Aligned with mohammed/fastconformer-quran-ar (CC BY 4.0) on Hugging Face.",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pack(dest, root, members, arcroot):
    """[members] (paths under [root]) into a reproducible .tar.gz under [arcroot]/."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    with tarfile.open(tmp, "w:gz", compresslevel=9) as tar:
        for path in sorted(members):
            info = tar.gettarinfo(str(path), arcname=f"{arcroot}/{path.relative_to(root)}")
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = int(path.stat().st_mtime)
            with open(path, "rb") as fh:
                tar.addfile(info, fh)
    tmp.replace(dest)


def surah_files(directory):
    return [p for p in directory.glob("[0-9][0-9][0-9].json")]


def reciters(manifest):
    by = {}
    for e in manifest.get("entries", []):
        by.setdefault(e["reciter"], []).append(e)
    names = {}
    try:
        for r in json.loads(SELF_HOSTED_CATALOGUE.read_text(encoding="utf-8"))["reciters"]:
            m = r["moshaf"][0]
            names[m["slug"]] = (r["name"], m["server"], m.get("source"), m["name"])
    except (OSError, ValueError, KeyError):
        pass
    out = []
    for d in sorted(p for p in WORDS.iterdir() if p.is_dir()):
        slug = d.name
        surahs = sorted(int(p.stem) for p in surah_files(d))
        if not surahs:
            continue
        if slug in names:
            name, server, source, riwayah = names[slug]
        elif slug in MP3QURAN:
            name, server = MP3QURAN[slug]
            source, riwayah = "mp3quran.net", "قالون عن نافع - مرتل"
        else:
            name, server, source, riwayah = slug, None, None, None
        entries = by.get(slug, [])
        words = sum(e.get("total_words") or 0 for e in entries)
        covered = sum(e.get("words_covered") or 0 for e in entries)
        out.append({
            "id": slug,
            "name": name,
            "riwayah": riwayah,
            "source": source,
            "audio": None if server is None else server + "{surah:03d}.mp3",
            "surahs": surahs,
            "word_coverage": round(100 * covered / words, 2) if words else None,
            "duration_s": round(sum(e.get("duration_s") or 0 for e in entries), 1) or None,
            "words": f"words-{slug}.tar.gz",
            "ayahs": f"https://quran-audio.abdeljawad.com/timings/{slug}/ayahs.json"
            if (AYAHS / slug / "ayahs.json").exists() else None,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--root", type=Path, help="a copy of the server's folders (see above)")
    args = ap.parse_args()
    _roots(args.root)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    built = []
    whole = [
        ("qalun-timings-words.tar.gz", WORDS,
         [p for d in WORDS.iterdir() if d.is_dir() for p in surah_files(d)], "timing-data-nemo"),
        ("qalun-timings-ayahs.tar.gz", AYAHS,
         [p for d in AYAHS.iterdir() if d.is_dir() for p in d.glob("*.json")]
         + [AYAHS / "index.json"], "timings"),
        ("qalun-canon.tar.gz", CANON, list(CANON.glob("*.json")), "canon"),
    ]
    for name, root, members, arcroot in whole:
        pack(out / name, root, members, arcroot)
        built.append(out / name)

    rows = reciters(manifest)
    for r in rows:
        d = WORDS / r["id"]
        pack(out / r["words"], WORDS, surah_files(d), "timing-data-nemo")
        built.append(out / r["words"])

    (out / "reciters.json").write_text(json.dumps(
        {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "licence": LICENCE, "reciters": rows},
        ensure_ascii=False, indent=1), encoding="utf-8")
    built.append(out / "reciters.json")
    shutil.copyfile(MANIFEST, out / "manifest.json")
    built.append(out / "manifest.json")

    sums = {p: sha256(p) for p in built}
    (out / "SHA256SUMS").write_text(
        "".join(f"{h}  {p.relative_to(out)}\n" for p, h in sums.items()), encoding="utf-8")
    (out / "index.json").write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "licence": LICENCE,
        "files": [{"path": str(p.relative_to(out)), "bytes": p.stat().st_size, "sha256": h}
                  for p, h in sums.items()],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(p.stat().st_size for p in built)
    print(f"wrote {len(built)} files, {total / 1e6:.1f} MB → {out}")


if __name__ == "__main__":
    main()
