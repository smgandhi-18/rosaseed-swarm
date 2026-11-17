#!/usr/bin/env bash
# Download T2T-CHM13v2.0 chr22 and simulate read sets A (search) and B (held out).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
D="$ROOT/work/data"
mkdir -p "$D"
if [ ! -s "$D/chr22.fa" ]; then
  # T2T-CHM13v2.0 chromosome 22 (GenBank CP068256.2, 51,324,926 bp)
  curl -sSfL "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&id=CP068256.2&rettype=fasta&retmode=text" \
    | sed '1s/.*/>chr22/' > "$D/chr22.fa.tmp"
  mv "$D/chr22.fa.tmp" "$D/chr22.fa"
fi
sim() {  # $1 = set name, $2 = seed
  if [ ! -s "$D/reads_$1_1.fq" ]; then
    wgsim -N 100000 -1 150 -2 150 -d 400 -s 50 -e 0.01 -r 0.001 -S "$2" \
      "$D/chr22.fa" "$D/reads_$1_1.fq" "$D/reads_$1_2.fq" > "$D/reads_$1.mut.txt"
  fi
}
sim A 11
sim B 22
ls -l "$D"
