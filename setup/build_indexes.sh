#!/usr/bin/env bash
# Build the BWA-MEM2 index and the RosaSeed 2-step index (14 nt jump table) for chr22.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
D="$ROOT/work/data"
I="$ROOT/work/index"
mkdir -p "$I/bwa" "$I/rs_chr22"
if [ ! -s "$I/bwa/chr22.fa.bwt.2bit.64" ]; then
  ln -sf "$D/chr22.fa" "$I/bwa/chr22.fa"
  "$ROOT/work/bin/bwa-mem2" index "$I/bwa/chr22.fa"
fi
if [ ! -s "$I/rs_chr22/cp_occ_full.bin" ]; then
  (cd "$ROOT/work/src/RosaSeed/index-builder" && ./build_2step_pipeline.sh -j 14 -o "$I/rs_chr22" "$D/chr22.fa")
fi
ls -l "$I/bwa" "$I/rs_chr22"
