"""The ayah fold keeps each reading of an ayah apart and takes them in recitation order.

    python3 -m unittest scripts/reciters/test_ayah_timings.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ayah_timings as at  # noqa: E402


def seg(t0, t1, words, ref=None, special=None):
    """words: [(location, start, end)] relative to t0."""
    s = {"time_from": t0, "time_to": t1, "special_type": special,
         "words": [{"location": loc, "start": a, "end": b} for loc, a, b in words]}
    if ref:
        s["ref_from"], s["ref_to"] = ref
    return s


class FoldTest(unittest.TestCase):
    def test_basmala_tail_is_not_fatiha_ayah_two(self):
        # عبدالحميد القريو, الفاتحة: the basmala's «الرحمن الرحيم» was placed on 1:2 at 7.4 s,
        # before 1:1; the real 1:2 at 19.5 s came out with no words. The old fold gave
        # 1:1 = 13.08 → 12.85 (ending before it started) and 1:2 zero long.
        payload = {"segments": [
            seg(0.4, 4.9, [("0:0:1", 0, .8)], special="Isti'adha"),
            seg(7.42, 12.7, [("1:2:1", 1.2, 2.6), ("1:2:2", 2.64, 5.2)]),
            seg(13.08, 18.28, [("1:1:1", 0, .8), ("1:1:4", 2.8, 4.0)]),
            seg(19.48, 22.52, [], ref=("1:2:1", "1:2:2")),
            seg(23.8, 25.96, [("1:3:1", 0, 2.1)]),
        ]}
        spans = at.ayah_spans(payload, 1)
        self.assertEqual([round(x, 2) for x in spans[1]], [13.08, 17.08])
        self.assertEqual([round(x, 2) for x in spans[2]], [19.48, 22.52])
        rows = at.bridge(spans, 3, None)
        for (a, s, e), (_, s2, _) in zip(rows, rows[1:]):
            self.assertLessEqual(s, e, a)
            self.assertLessEqual(e, s2, a)

    def test_a_reading_split_by_a_stray_word_stays_whole(self):
        payload = {"segments": [
            seg(0, 10, [("2:5:1", 0, 1), ("2:6:1", 3, 3.4), ("2:5:7", 6, 9)]),
            seg(10, 14, [("2:6:1", 0, 4)]),
        ]}
        spans = at.ayah_spans(payload, 2)
        self.assertEqual(spans[5], [0, 9])
        self.assertEqual(spans[6], [10, 14], "6 is where it is really read, after 5")

    def test_a_repeated_ayah_is_taken_once_in_order(self):
        payload = {"segments": [
            seg(0, 5, [("3:1:1", 0, 5)]),
            seg(5, 10, [("3:2:1", 0, 5)]),
            seg(10, 15, [("3:1:1", 0, 5)]),
            seg(15, 20, [("3:2:1", 0, 5)]),
            seg(20, 25, [("3:3:1", 0, 5)]),
        ]}
        spans = at.ayah_spans(payload, 3)
        self.assertEqual(spans, {1: [0, 5], 2: [5, 10], 3: [20, 25]})


if __name__ == "__main__":
    unittest.main()
