#!/usr/bin/env python3
"""Word coverage of the NeMo rebuild against the ONNX output, file by file.

Only files present in both trees are compared, so this stays meaningful while
the rebuild is still running. Ornamental marks are excluded: they occupy a word
slot in quran.db but are never recited.
"""
import json, statistics as st
from pathlib import Path

ROOT = Path("/root/qrtt")
NEW, OLD = ROOT / "output_nemo", ROOT / "output"

q = json.loads((ROOT / "data/qpc_qalun.json").read_text(encoding="utf-8"))
BYS = {}
for k, v in q.items():
    if any(c.isalpha() for c in v["text"]):
        BYS.setdefault(int(v["surah"]), set()).add(k)


def stats(p):
    d = json.loads(p.read_text(encoding="utf-8"))
    pres = d.get("surahs_present") or [d.get("detected_surah")]
    need = set()
    for s in pres:
        need |= BYS.get(s, set())
    matched = [x for x in d["segments"] if x.get("ref_from")]
    got = {w["location"] for x in matched for w in (x.get("words") or []) if w.get("location")}
    conf = sum(x["confidence"] for x in matched) / len(matched) if matched else 0.0
    gaps, durs = [], []
    for x in d["segments"]:
        ws = [w for w in (x.get("words") or []) if w.get("start") is not None]
        durs += [w["end"] - w["start"] for w in ws]
        gaps += [b["start"] - a["end"] for a, b in zip(ws, ws[1:])]
    return len(need & got), len(need), conf, durs, gaps


rows, og, on_, ng, nn = [], 0, 0, 0, 0
oc, nc, alld, allg = [], [], [], []
for f in sorted(NEW.rglob("[0-9][0-9][0-9].json")):
    o = OLD / f.parent.name / f.name
    if not o.exists():
        continue
    a, b, c1, _, _ = stats(o)
    x, y, c2, d2, g2 = stats(f)
    og += a; on_ += b; ng += x; nn += y
    oc.append(c1); nc.append(c2); alld += d2; allg += g2
    rows.append((f"{f.parent.name}/{f.stem}", 100*a/b, 100*x/y))

if not rows:
    print("no overlapping files yet"); raise SystemExit

rows.sort(key=lambda r: r[2] - r[1])
print(f"  {'file':34s} {'ONNX':>7} {'NeMo':>7} {'delta':>8}")
for n, a, b in rows[:8]:
    print(f"  {n:34s} {a:6.1f}% {b:6.1f}% {b-a:+7.2f}pp")
if len(rows) > 12:
    print("   ...")
for n, a, b in rows[-4:]:
    print(f"  {n:34s} {a:6.1f}% {b:6.1f}% {b-a:+7.2f}pp")

print(f"\n  files compared : {len(rows)}")
print(f"  coverage       : ONNX {100*og/on_:.2f}%   NeMo {100*ng/nn:.2f}%   "
      f"{100*ng/nn - 100*og/on_:+.2f}pp")
print(f"  confidence     : ONNX {100*sum(oc)/len(oc):.1f}%   NeMo {100*sum(nc)/len(nc):.1f}%")
print(f"  worse than ONNX: {sum(1 for _, a, b in rows if b < a - 0.5)} of {len(rows)}")
if alld:
    ident = 100*sum(1 for d in alld if abs(d - st.median(alld)) < 1e-9)/len(alld)
    contig = 100*sum(1 for g in allg if abs(g) < 1e-6)/len(allg) if allg else 0
    print(f"  word dur       : median {st.median(alld):.3f}s  identical {ident:.1f}%  "
          f"contiguous {contig:.1f}%")
