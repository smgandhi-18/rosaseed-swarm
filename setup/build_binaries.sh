#!/usr/bin/env bash
# Build stock BWA-MEM2 and the 20 RosaSeed binaries of the search space from the
# preprint source. Each binary gets its own source copy, so builds never share objects.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/work/src/RosaSeed"
BUILD="$ROOT/work/build"
BIN="$ROOT/work/bin"
JOBS_PER_BUILD="${JOBS_PER_BUILD:-4}"
PARALLEL="${PARALLEL:-3}"
mkdir -p "$BUILD" "$BIN"

BASE="-DLOAD_JTABLE_14nt -DSA_COMPRESSION_FACTOR_POWER=1 -DGAPFILL_ALWAYS_RUN_BOTH_STRANDS"

# name|ROSASEED(0/1)|extra flags
specs() {
  echo "bwa-mem2|0|"
  for pc in off t50w60 t50w80 t200w60 t200w80; do
    for frc in 1 0; do
      for ee in 1 0; do
        f="$BASE"
        if [ "$pc" != off ]; then
          t=${pc#t}; t=${t%w*}; w=${pc#*w}
          f="$f -DROSASEED_PRECHAIN_SINGLETON_SUPPRESS -DROSASEED_PRECHAIN_TRIGGER=$t -DROSASEED_PRECHAIN_WEAK_LEN=$w"
        fi
        [ "$frc" = 1 ] && f="$f -DENABLE_F_RC_CHOICE"
        [ "$ee" = 1 ] && f="$f -DGAPFILL_EARLY_EXIT"
        echo "rs_${pc}_frc${frc}_ee${ee}|1|$f"
      done
    done
  done
}

build_one() {
  IFS='|' read -r name rs flags <<< "$1"
  [ -x "$BIN/$name" ] && { echo "skip $name"; return 0; }
  d="$BUILD/$name"
  rm -rf "$d"; mkdir -p "$d"
  (cd "$SRC" && git archive HEAD) | tar -x -C "$d"
  if [ "$rs" = 1 ]; then
    make -C "$d" -j"$JOBS_PER_BUILD" arch=native CXX=g++ ROSASEED=1 CPPFLAGS_EXTRA="$flags" > "$d/build.log" 2>&1
  else
    make -C "$d" -j"$JOBS_PER_BUILD" arch=native CXX=g++ > "$d/build.log" 2>&1
  fi
  cp "$d/bwa-mem2" "$BIN/$name"
  printf 'ROSASEED=%s\nCPPFLAGS_EXTRA=%s\nsource_commit=%s\n' "$rs" "$flags" "$(git -C "$SRC" rev-parse HEAD)" > "$BIN/$name.flags"
  echo "built $name"
}
export -f build_one
export SRC BUILD BIN JOBS_PER_BUILD
specs | xargs -P "$PARALLEL" -I{} bash -c 'build_one "$@"' _ {}
ls "$BIN" | grep -v '\.flags$' | wc -l
