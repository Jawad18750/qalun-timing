#!/usr/bin/env python3
"""Per-ayah timings for the apps, folded from the word-level alignment.

The apps play by ayah from one small JSON per (reciter, surah):

    {"reciter_id": "taha_alfahd", "surah": 36,
     "ayahs": [{"ayah": 1, "start_ms": 5120, "end_ms": 12190}, …]}

(`SurahAyahTimings` in packages/quran_audio), the shape their file tier, asset tier and
mp3quran tier all speak. The NeMo corpus is richer (every word) and one 150 KB file per
surah, which is fine to fetch for a surah being played and wrong to bundle for a whole
mushaf. This folds each file's words into ayah spans and publishes them beside the audio
catalogue, under the id the APP mints for the reciter: the pipeline's directory name is
that id for our own reciters and mp3quran's server slug for theirs, and the app never
sees a server slug.

    python3 ayah_timings.py                    # → /var/www/quran-audio/public_html/timings/
    python3 ayah_timings.py --out /tmp/timings # somewhere else, to look first
    python3 ayah_timings.py --words timing-data-nemo --canon canon --manifest manifest.json \
        --out timings                          # from a download (the release's three files)

Per reciter:
    NNN.json      one surah, exactly what the apps' file tier reads
    ayahs.json    every surah in one compact file: what the apps BUNDLE, so ayah
                  playback works offline without a download:
                  {"reciter_id", "version", "surahs": {"36": [[ayah, start_ms, end_ms], …]}}
And timings/index.json: which surahs each reciter has, so the apps can one day read
coverage from here instead of a hand-kept table.

Units (see TIMING_PIPELINE.md): a word's start/end are RELATIVE to its segment's
time_from, and the last word of a segment may run past time_to; that is real, not slop,
so nothing is clamped to a segment window. Consecutive ayahs cannot overlap in the audio,
though, so where two spans cross the boundary is put at the middle of the overlap.

An ayah the aligner did not catch (98.96% word coverage, so it happens) is bridged from
its neighbours: from the previous ayah's end to the next one's start. The apps then
highlight the right line a little early or late instead of refusing to play by ayah at
all. A trailing gap is closed with the surah's duration when the manifest knows it; when
it does not, the ayah is left out and the app falls back to whole-surah playback for it.
"""
import argparse
import json
import sys
import time
from pathlib import Path

WEB_NEMO = Path("/var/www/qalun-timing/public_html/timing-data-nemo")
MP3Q_NEMO = Path("/root/qrtt/output_mp3quran_nemo")
MANIFEST = Path("/var/www/qalun-timing/public_html/manifest.json")
SURAH_INFO = Path("/root/qrtt/data/surah_info_qalun.json")
DEFAULT_OUT = Path("/var/www/quran-audio/public_html/timings")

# Our own reciters: directory name == the app's recitation id (build_catalog.py's slug).
SELF_HOSTED = [
    "ali_alyounse", "moaad_benhamed", "ahmed_algriw", "taha_alfahd", "ibrahim_kishidan",
    "walid_alnaehi", "ahmed_alqulaib", "bilal_ben_mahmoud", "mustafa_alfarjani",
    "nooreddine_almeslati", "abdulhamid_algriw",
]

# mp3quran's reciters: the pipeline named the directory after the server slug in the
# moshaf URL; the app names the recitation mp3quran_<reciter id>_<moshaf id> (see
# quranAudioRecitationIdForMp3Quran). Read off /api/v3/reciters?rewaya=5 on 2026-09-12.
MP3QURAN = {
    "trablsi": "mp3quran_201_199",   # أحمد الطرابلسي
    "tareq":   "mp3quran_212_212",   # طارق عبدالغني دعوب
    "m_akri":  "mp3quran_237_287",   # مروان العكري
    "deban":   "mp3quran_265_280",   # أحمد ديبان
    "sneineh": "mp3quran_274_274",   # محمد أبو سنينة
    "qeniwa":  "mp3quran_275_275",   # محمد الأمين قنيوة
}

VERSION = 1


def load_surah_lengths(canon=None):
    """surah → its ayah count, from the pipeline's surah info, or from canon/ files."""
    if canon is not None:
        out = {}
        for path in sorted(Path(canon).glob("[0-9][0-9][0-9].json")):
            c = json.loads(path.read_text(encoding="utf-8"))
            out[int(c["surah"])] = len(c["ayahs"])
        return out
    info = json.loads(SURAH_INFO.read_text(encoding="utf-8"))
    return {int(k): v["num_verses"] for k, v in info.items()}


def load_durations():
    """(reciter dir, surah) → seconds, from the review manifest where it knows them."""
    if not MANIFEST.exists():
        return {}
    out = {}
    for e in json.loads(MANIFEST.read_text(encoding="utf-8")).get("entries", []):
        d = e.get("duration_s")
        if d:
            out[(e["reciter"], int(e["surah"]))] = float(d)
    return out


def _runs(payload, surah):
    """Time-ordered runs of one ayah: consecutive words of the same ayah, merged.

    The aligner can place the same words twice: the basmala's «الرحمن الرحيم» tagged as
    الفاتحة's second ayah, a reciter going back over an ayah, a passage that repeats
    word for word. Taking every word of an ayah into one span (min start, max end), as
    this did, stretched that ayah over its neighbours, and the overlap repair then gave
    ayahs that end before they start: 1:1 of five reciters among ~220 of them
    (2026-10-07). Each reading of an ayah is kept apart here instead.

    A segment the aligner placed on one ayah but left without words (it happens when
    the same text was already used up earlier) still says where that ayah is read.
    """
    items = []  # (start, end, ayah)
    for seg in payload.get("segments", []):
        base = float(seg.get("time_from") or 0.0)
        words = seg.get("words", []) or []
        placed = False
        for w in words:
            parts = str(w.get("location", "")).split(":")
            if len(parts) != 3:
                continue
            s, a = int(parts[0]), int(parts[1])
            # Basmala/Isti'adha carry the sentinel 0:0:N; a bundled file (085 = البروج then
            # الطارق) carries a second surah the app plays from its own file.
            if s != surah or a < 1:
                continue
            items.append((base + float(w["start"]), base + float(w["end"]), a))
            placed = True
        if not placed and not seg.get("special_type"):
            ref_from, ref_to = str(seg.get("ref_from") or ""), str(seg.get("ref_to") or "")
            f, t = ref_from.split(":"), ref_to.split(":")
            if (len(f) == 3 and len(t) == 3 and f[:2] == t[:2] and int(f[0]) == surah
                    and int(f[1]) >= 1 and seg.get("time_to") is not None):
                items.append((base, float(seg["time_to"]), int(f[1])))
    items.sort()
    runs = []  # [start, end, ayah]
    for start, end, a in items:
        if runs and runs[-1][2] == a:
            runs[-1][1] = max(runs[-1][1], end)
        else:
            runs.append([start, end, a])
    return runs


# A word may start a little before the previous ayah's last word ends (the last word's
# end can overrun its segment, see TIMING_PIPELINE.md): within this, still in order.
_SLACK = 0.5

# How much of other ayahs may interrupt one reading of an ayah and still be a mistag: a
# stray word lasts under a second, a re-read ayah several.
_STRAY = 2.0


def ayah_spans(payload, surah):
    """ayah → [start, end] seconds: each ayah's reading, taken in recitation order.

    Ayah after ayah, the first reading that starts after the previous ayah's (less a
    little slack) is the one; a reading that comes before it is an echo (or a mistag)
    and is passed over, and a later one is a repetition and is passed over too.
    """
    runs = _runs(payload, surah)
    spans = {}
    prev_end = 0.0
    for a in sorted({r[2] for r in runs}):
        for i, (start, end, ayah) in enumerate(runs):
            if ayah != a or start < prev_end - _SLACK:
                continue
            # The same reading split by a stray word or two of another ayah goes on past
            # them; anything longer in between is the reciter reading on, or going back,
            # and the reading ends there.
            stray = 0.0
            for nstart, nend, nayah in runs[i + 1:]:
                if nayah == a:
                    end = max(end, nend)
                    stray = 0.0
                    continue
                stray += nend - nstart
                if stray > _STRAY:
                    break
            spans[a] = [start, end]
            prev_end = end
            break
    return spans


def bridge(spans, count, duration):
    """Fill missing ayahs from their neighbours and keep the sequence monotonic."""
    known = sorted(spans)
    if not known:
        return []
    filled = {}
    for a in range(1, count + 1):
        if a in spans:
            filled[a] = list(spans[a])
            continue
        prev = max((k for k in known if k < a), default=None)
        nxt = min((k for k in known if k > a), default=None)
        if prev is not None and nxt is not None:
            filled[a] = [spans[prev][1], spans[nxt][0]]
        elif prev is None and nxt is not None:
            # Missing at the head: whatever precedes the first known ayah, which is the
            # basmala or silence. Start a second before it rather than at zero, so a
            # long isti'adha is not credited to the first ayah.
            filled[a] = [max(0.0, spans[nxt][0] - 1.0), spans[nxt][0]]
        elif prev is not None and duration:
            filled[a] = [spans[prev][1], duration]
        # else: trailing and no duration: left out on purpose
    ordered = [a for a in range(1, count + 1) if a in filled]
    # Consecutive spans meeting in the middle of any overlap; a following ayah can never
    # start before the previous one ends. The meeting point stays inside both spans, so
    # neither is turned inside out.
    for i in range(1, len(ordered)):
        p, c = filled[ordered[i - 1]], filled[ordered[i]]
        if c[0] < p[1]:
            mid = min(max((c[0] + p[1]) / 2, p[0]), max(c[1], p[0]))
            p[1] = mid
            c[0] = mid
        if c[1] < c[0]:
            c[1] = c[0]
    return [(a, int(round(filled[a][0] * 1000)), int(round(filled[a][1] * 1000)))
            for a in ordered]


def convert(tree, dirname, app_id, lengths, durations, out):
    src = tree / dirname
    if not src.is_dir():
        return None
    dest = out / app_id
    dest.mkdir(parents=True, exist_ok=True)
    compact = {}
    bridged = 0
    for path in sorted(src.glob("[0-9][0-9][0-9].json")):
        surah = int(path.stem)
        if surah < 1 or surah > 114:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"  {dirname}/{path.name}: unreadable ({e})", file=sys.stderr)
            continue
        spans = ayah_spans(payload, surah)
        rows = bridge(spans, lengths[surah], durations.get((dirname, surah)))
        if not rows:
            continue
        bridged += len(rows) - len(spans)
        (dest / f"{surah:03d}.json").write_text(json.dumps({
            "reciter_id": app_id,
            "surah": surah,
            "ayahs": [{"ayah": a, "start_ms": s, "end_ms": e} for a, s, e in rows],
        }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        compact[str(surah)] = [[a, s, e] for a, s, e in rows]
    if not compact:
        return None
    (dest / "ayahs.json").write_text(json.dumps({
        "reciter_id": app_id,
        "version": VERSION,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "surahs": compact,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"surahs": sorted(int(k) for k in compact), "bridged_ayahs": bridged,
            "slug": dirname}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    # From a download instead of the server: every reciter directory under --words (named
    # by recitation id), ayah counts from --canon, durations from --manifest if given.
    ap.add_argument("--words", type=Path)
    ap.add_argument("--canon", type=Path)
    ap.add_argument("--manifest", type=Path)
    args = ap.parse_args()
    global MANIFEST
    if args.manifest:
        MANIFEST = args.manifest
    lengths = load_surah_lengths(args.canon)
    durations = load_durations()
    index = {}
    if args.words:
        for d in sorted(p for p in args.words.iterdir() if p.is_dir()):
            r = convert(args.words, d.name, d.name, lengths, durations, args.out)
            if r:
                index[d.name] = {**r, "source": "nemo"}
    for slug in ([] if args.words else SELF_HOSTED):
        r = convert(WEB_NEMO, slug, slug, lengths, durations, args.out)
        if r:
            index[slug] = {**r, "source": "nemo"}
    for slug, app_id in ({} if args.words else MP3QURAN).items():
        r = convert(MP3Q_NEMO, slug, app_id, lengths, durations, args.out)
        if r:
            index[app_id] = {**r, "source": "mp3quran-nemo"}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "index.json").write_text(json.dumps({
        "version": VERSION,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reciters": index,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    for rid, r in index.items():
        print(f"  {rid:<24} {len(r['surahs']):>3} surahs  {r['bridged_ayahs']:>4} ayahs bridged")
    print(f"wrote {len(index)} reciters → {args.out}")


if __name__ == "__main__":
    main()
