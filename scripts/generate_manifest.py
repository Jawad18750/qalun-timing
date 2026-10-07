#!/usr/bin/env python3
"""Scans the batch outputs and writes manifest.json for the review UI.

Re-run on a loop so the dashboard stays current while the batch is running.
Reports WORD-level coverage against the canonical Qalun text (not just ayah
counts): a surah can have every ayah touched while still missing individual
words, and those missing words are the thing worth reviewing.

Two engines are published side by side. The NeMo rebuild is authoritative where
it exists and the older ONNX run fills the rest, so the dashboard stays complete
while the rebuild is still running. Every row also carries the other engine's
numbers under "alt", because the two disagree in interesting places and the
better one is not always the same one.
"""
import json
import re
import subprocess
from pathlib import Path

# (name, tree to scan, web subdir) -- order matters: first wins when both exist.
# The ONNX row reads the deployed tree, not /root/qrtt/output: the mirror is
# additive, so it still holds the whole finished ONNX corpus, while the source
# directory was cleared for a re-run and now carries only part of it. Scanning
# the source would silently drop the surahs that run had not reached yet.
SURAH_INFO_PATH = Path("/root/qrtt/data/surah_info_qalun.json")
WEB_ROOT = Path("/var/www/qalun-timing/public_html")
SOURCES = [
    ("nemo", Path("/root/qrtt/output_nemo"), "timing-data-nemo"),
    ("onnx", WEB_ROOT / "timing-data", "timing-data"),
]
MANIFEST_PATH = WEB_ROOT / "manifest.json"
AUDIO_BASE = "https://quran-audio.abdeljawad.com/audio"
JSON_BASE = "https://qalun-timing.abdeljawad.com/timing-data"

surah_info = json.loads(SURAH_INFO_PATH.read_text(encoding="utf-8"))
SURAH_NAMES = {int(k): v["name_ar"] for k, v in surah_info.items()}
SURAH_AYAHS = {int(k): v["num_verses"] for k, v in surah_info.items()}
SURAH_WORDS = {
    int(k): sum(v.get("num_words", 0) for v in info["verses"])
    for k, info in surah_info.items()
}

# Ornamental marks (rub-el-hizb and the like) hold a token slot in quran.db's
# text but are never recited, so the matcher can never produce them. Counting
# them in the denominator understated every reciter's coverage by ~1.3 points
# and invented 4,165 phantom "missing words" across the corpus.
_QPC = json.loads(Path("/root/qrtt/data/qpc_qalun.json").read_text(encoding="utf-8"))
ORNAMENTS = {k for k, v in _QPC.items() if not any(c.isalpha() for c in v["text"])}
ORNAMENT_COUNT = {}
for _k in ORNAMENTS:
    _s = int(_k.split(":")[0])
    ORNAMENT_COUNT[_s] = ORNAMENT_COUNT.get(_s, 0) + 1


def summarize(payload):
    segs = payload.get("segments", [])
    surah = payload.get("detected_surah") or payload.get("surah")
    # A bundled file (e.g. 085.mp3 = البروج then الطارق) carries matched words
    # from every surah it contains, so the denominator must span them all --
    # otherwise coverage exceeds 100%.
    present = payload.get("surahs_present") or [surah]
    total_time = sum(s["time_to"] - s["time_from"] for s in segs)
    matched = [s for s in segs if s.get("ref_from")]
    specials = [
        s for s in segs
        if not s.get("ref_from") and (s.get("special_type") or s.get("likely_opening"))
    ]
    real_gaps = [
        s for s in segs
        if not s.get("ref_from") and not s.get("special_type")
        and not s.get("likely_opening") and s["time_to"] - s["time_from"] >= 0.5
    ]
    gap_time = sum(s["time_to"] - s["time_from"] for s in real_gaps)
    confs = [s["confidence"] for s in matched] or [0.0]

    located = set()
    ayahs = set()
    for s in matched:
        for w in (s.get("words") or []):
            loc = w.get("location")
            if loc and not w.get("is_missing") and loc not in ORNAMENTS:
                located.add(loc)
                try:
                    parts = loc.split(":")
                    if int(parts[0]) == surah:
                        ayahs.add(int(parts[1]))
                except (ValueError, IndexError):
                    pass

    total_words = sum(SURAH_WORDS.get(x, 0) - ORNAMENT_COUNT.get(x, 0) for x in present)
    return {
        "segments": len(segs),
        "matched": len(matched),
        "specials": len(specials),
        "gap_pct": round(100 * gap_time / total_time, 1) if total_time else 0.0,
        "avg_confidence": round(sum(confs) / len(confs), 3),
        "ayahs_covered": len(ayahs),
        "words_covered": len(located),
        "total_words": total_words,
        "word_coverage": round(100 * len(located) / total_words, 1) if total_words else 0.0,
        "duration_s": round(total_time, 1),
    }


def sync_web_copy(root, subdir):
    """/root is not traversable by the web worker (nobody); mirror the JSON
    outputs into the web root rather than loosening /root's permissions."""
    if not root.is_dir():
        return
    dest = WEB_ROOT / subdir
    if root.resolve() == dest.resolve():      # already the published copy
        return
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["rsync", "-a", "--include=*/", "--include=*.json", "--exclude=*",
         f"{root}/", f"{dest}/"],
        check=True,
    )


def scan(source, root, subdir):
    """Every (reciter, surah) this engine produced, keyed for cross-referencing."""
    out = {}
    if not root.is_dir():
        return out
    json_base = f"https://qalun-timing.abdeljawad.com/{subdir}"
    for reciter_dir in sorted(root.iterdir()):
        if not reciter_dir.is_dir():
            continue
        slug = reciter_dir.name
        for f in sorted(reciter_dir.glob("*.json")):
            m = re.match(r"^(\d{3})\.json$", f.name)
            if not m:
                continue
            surah = int(m.group(1))
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:
                out[(slug, surah)] = {"reciter": slug, "surah": surah,
                                      "source": source, "error": str(e)}
                continue
            detected = payload.get("detected_surah", surah)
            out[(slug, surah)] = {
                "reciter": slug,
                "surah": surah,
                "source": source,
                "chunk_window": payload.get("chunk_window"),
                "detected_surah": detected,
                "surah_mismatch": bool(payload.get("surah_mismatch")),
                "surahs_present": payload.get("surahs_present") or [detected],
                "alternate_source": bool(payload.get("alternate_source")),
                "alternate_source_note": payload.get("alternate_source_note"),
                "alternate_source_url": payload.get("alternate_source_url"),
                "extra_surah_names": [
                    SURAH_NAMES.get(x, "") for x in (payload.get("surahs_present") or [])
                    if x != detected
                ],
                "surah_name": SURAH_NAMES.get(surah, ""),
                "detected_name": SURAH_NAMES.get(detected, ""),
                "total_ayahs": SURAH_AYAHS.get(detected, 0),
                "audio_url": f"{AUDIO_BASE}/{slug}/{surah:03d}.mp3",
                "json_url": f"{json_base}/{slug}/{surah:03d}.json",
                **summarize(payload),
            }
        for f in sorted(reciter_dir.glob("*.FAILED.txt")):
            m = re.match(r"^(\d{3})\.FAILED\.txt$", f.name)
            if m:
                surah = int(m.group(1))
                out.setdefault((slug, surah), {
                    "reciter": slug, "surah": surah, "source": source,
                    "surah_name": SURAH_NAMES.get(surah, ""), "failed": True,
                })
    return out


# fields worth showing for the engine that did NOT win the row
ALT_FIELDS = ("source", "chunk_window", "word_coverage", "words_covered",
              "total_words", "avg_confidence", "gap_pct", "ayahs_covered",
              "surah_mismatch", "surahs_present", "json_url", "failed")


def main():
    scanned = []
    for source, root, subdir in SOURCES:
        sync_web_copy(root, subdir)
        scanned.append((source, scan(source, root, subdir)))

    keys = sorted({k for _, s in scanned for k in s})
    entries = []
    for key in keys:
        found = [(src, s[key]) for src, s in scanned if key in s]
        # SOURCES order decides the winner, so NeMo takes the row wherever the
        # rebuild has reached and ONNX covers everything it has not
        _, primary = found[0]
        entry = dict(primary)
        others = [e for _, e in found[1:]]
        if others:
            entry["alt"] = [{k: o.get(k) for k in ALT_FIELDS if k in o} for o in others]
        entries.append(entry)

    by_source = {}
    for e in entries:
        by_source[e["source"]] = by_source.get(e["source"], 0) + 1

    MANIFEST_PATH.write_text(
        json.dumps({"entries": entries, "count": len(entries),
                    "by_source": by_source,
                    "sources": [s for s, _, _ in SOURCES]}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"wrote {len(entries)} entries to {MANIFEST_PATH} ({by_source})")


if __name__ == "__main__":
    main()
