#!/usr/bin/env bash
# Everything after the rebuild, in the only order this box can afford.
#
# Strictly sequential throughout: each stage loads its own copy of the NeMo
# model, and with ~1GB free this machine cannot hold two at once. Running the
# gap filler alongside the batch is what OOM-killed the rebuild twice.
set -u
LOG=/root/qrtt/logs/finish_all.log
exec >>"$LOG" 2>&1
echo "=== finish_all started $(date -u +%FT%TZ) ==="

echo "--- [1/5] waiting for the rebuild ---"
while pgrep -f batch_run_nemo >/dev/null; do sleep 60; done
echo "--- rebuild done: $(ls /root/qrtt/output_nemo/*/[0-9][0-9][0-9].json 2>/dev/null | wc -l) files ---"
sleep 20

echo "--- [2/5] gap fill, main corpus, one reciter at a time ---"
for d in /root/qrtt/output_nemo/*/; do
  echo "--- $(basename "$d") ($(ls "$d"/[0-9][0-9][0-9].json 2>/dev/null | wc -l) files) ---"
  /root/nemoenv/bin/python /root/qrtt/fill_gaps.py "$d"/[0-9][0-9][0-9].json
done

echo "--- [3/5] manifest ---"
cd /root/qrtt && python3 generate_manifest.py

echo "--- [4/5] mp3quran on NeMo (7 Qalun reciters, audio never kept) ---"
/root/nemoenv/bin/python /root/qrtt/stream_align_nemo.py

echo "--- [5/5] gap fill, mp3quran ---"
for d in /root/qrtt/output_mp3quran_nemo/*/; do
  [ -d "$d" ] || continue
  echo "--- $(basename "$d") ---"
  /root/nemoenv/bin/python /root/qrtt/fill_gaps.py "$d"/[0-9][0-9][0-9].json
done

cd /root/qrtt && python3 generate_manifest.py
echo "=== finish_all DONE $(date -u +%FT%TZ) ==="
