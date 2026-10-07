"""Output-layer fixes applied on top of qua_sdk's raw alignment result.

These are structural to the vendored matcher (the qua_sdk wheel's DP window
logic), not something safe to patch inside a pinned dependency. Handled here
as a post-processing pass over the exported segments, which is easy to verify
and cheap to re-apply to existing output.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

# Surahs that are NOT from the reciter's khatma: one-off recordings pulled in
# to fill a gap the original source never had. Flagged here so the marker
# rides along with the timing data itself rather than living only in a
# separate file that a downstream consumer might never read.
ALT_SOURCES_PATH = Path("/root/reciters/alt_sources.json")
try:
    ALT_SOURCES = json.loads(ALT_SOURCES_PATH.read_text(encoding="utf-8"))
except Exception:
    ALT_SOURCES = {}


def alt_source_for(reciter, surah):
    return (ALT_SOURCES.get(reciter or "", {}) or {}).get(str(surah))

MAX_MERGE_GAP_S = 3.0       # only merge a duplicate into the original if this close
MISLABEL_DOMINANCE = 0.60      # share of matched segments agreeing on one surah
MIN_SECONDARY_SEGMENTS = 5     # a real bundled surah sustains a block, not a stray
MIN_SECONDARY_TIME_SHARE = 0.05


def resolve_surah(payload, expected_surah):
    """Decides which surah(s) this file ACTUALLY contains, and filters to them.

    Two distinct realities to separate, and they look alike at a glance:

    * **Misnamed file.** The corpus is mirrored from third-party sources and
      some files are simply mislabelled at the origin -- ahmed_algriw/023.mp3
      is named المؤمنون (23) but the recitation is الحج (22). Filtering to the
      filename's surah would throw away a perfectly good alignment and leave
      an empty file, so the dominant surah wins and the file is flagged.
    * **Bundled surahs.** Short surahs are routinely recorded several to a
      file -- ahmed_algriw/085.mp3 is البروج for 197s and then الطارق (86)
      to the end. That second recitation is real, correctly aligned data;
      dropping it discarded a quarter of the audio.

    Against both sits the thing the filter exists for: isolated spurious
    matches, where one noisy phrase anchors to a textual near-duplicate
    elsewhere in the Quran. Those are a handful of scattered segments, never
    a sustained block -- so a non-dominant surah is KEPT when it holds its own
    (enough segments and enough of the audio) and dropped when it does not.
    """
    segs = payload.get("segments", []) if payload else []
    votes = Counter()
    time_by_surah = Counter()
    for seg in segs:
        ref = seg.get("ref_from") or ""
        if ":" not in ref:
            continue
        try:
            surah = int(ref.split(":")[0])
        except ValueError:
            continue
        votes[surah] += 1
        time_by_surah[surah] += seg["time_to"] - seg["time_from"]

    total_votes = sum(votes.values())
    total_time = sum(s["time_to"] - s["time_from"] for s in segs) or 1.0

    detected = expected_surah
    mismatch = False
    if total_votes:
        top, count = votes.most_common(1)[0]
        if top != expected_surah and count / total_votes >= MISLABEL_DOMINANCE:
            detected, mismatch = top, True

    keep = {detected}
    for surah, count in votes.items():
        if surah == detected:
            continue
        if (count >= MIN_SECONDARY_SEGMENTS
                and time_by_surah[surah] / total_time >= MIN_SECONDARY_TIME_SHARE):
            keep.add(surah)

    dropped = 0
    for seg in segs:
        ref = seg.get("ref_from") or ""
        if ":" not in ref:
            continue
        try:
            surah = int(ref.split(":")[0])
        except ValueError:
            continue
        if surah not in keep:
            seg["ref_from"] = None
            seg["ref_to"] = None
            seg["matched_text"] = ""
            seg["confidence"] = 0.0
            seg["words"] = []
            seg["error"] = f"Dropped: isolated match on surah {surah} (file is {detected})"
            dropped += 1

    return payload, {
        "detected_surah": detected,
        "surah_mismatch": mismatch,
        "surahs_present": sorted(keep),
        "dropped_wrong_surah": dropped,
    }


def dedup_duplicate_word_locations(payload):
    """Merges/drops repeat matches of the same canonical word.

    Root cause: audio gets split mid-word (a reciter's breath inside a long
    word read as an inter-word gap, or our own >10.5s safe-window split), so
    the two fragments are transcribed separately. The matcher's window looks
    back up to 30 words with only a 0.005/word position penalty
    (qua_sdk WraparoundDpParams), so the second fragment re-matches the word
    the first already consumed -- same location twice, two timestamps. The CTC
    aligner then squeezes the segment's remaining real words into what time is
    left, which is what reads as "highlight races ahead of the voice."
    """
    segs = payload.get("segments", []) if payload else []

    # Locations the matcher's OWN repetition detector says the reciter really
    # repeated. A genuine repeat looks identical to the split-word bug but is
    # correct data, so it must survive untouched.
    protected = set()
    for seg in segs:
        for wr in (seg.get("wrap_word_ranges") or []):
            protected.update(loc for loc in wr if isinstance(loc, str))

    seen = {}
    removed = 0
    for seg in segs:
        kept = []
        for w in (seg.get("words") or []):
            loc = w.get("location")
            if not loc or w.get("is_missing") or loc in protected:
                kept.append(w)
                continue
            prior = seen.get(loc)
            if prior is None:
                seen[loc] = w
                kept.append(w)
                continue
            removed += 1
            if (
                w.get("start") is not None and prior.get("end") is not None
                and w["start"] - prior["end"] <= MAX_MERGE_GAP_S
                and w.get("end") is not None and w["end"] > prior["end"]
            ):
                prior["end"] = w["end"]
        seg["words"] = kept
        if seg.get("ref_from"):
            seg["matched_text"] = " ".join(
                w["word"] for w in kept if w.get("word") and not w.get("is_missing")
            )
    return payload, removed


def label_opening_gap(payload):
    """An unmatched FIRST segment is overwhelmingly the Isti'adha/Basmala
    recited before ayah 1 (which is not a counted ayah in this Qalun
    numbering). Tag it so it doesn't read as an unexplained content gap."""
    segs = payload.get("segments", []) if payload else []
    if not segs:
        return payload
    first = segs[0]
    if (not first.get("ref_from") and not first.get("special_type")
            and first.get("time_from", 0) < 8.0):
        first["likely_opening"] = True
    return payload


def postprocess(payload, expected_surah, reciter=None):
    payload, info = resolve_surah(payload, expected_surah)
    alt = alt_source_for(reciter, expected_surah)
    if alt and payload is not None:
        payload["alternate_source"] = True
        payload["alternate_source_url"] = alt.get("source")
        payload["alternate_source_note"] = alt.get("note")
    info["alternate_source"] = bool(alt)
    payload, deduped = dedup_duplicate_word_locations(payload)
    payload = label_opening_gap(payload)
    info["deduped_words"] = deduped
    return payload, info
