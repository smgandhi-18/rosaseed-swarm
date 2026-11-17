#!/usr/bin/env bash
# Clone the public preprint release of RosaSeed at a fixed commit.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMMIT=865bec6
DEST="$ROOT/work/src/RosaSeed"
if [ ! -d "$DEST/.git" ]; then
  git clone --quiet https://github.com/smgandhi-18/RosaSeed.git "$DEST"
fi
git -C "$DEST" checkout --quiet "$COMMIT"
HEAD=$(git -C "$DEST" rev-parse HEAD)
case "$HEAD" in
  ${COMMIT}*) echo "RosaSeed at $HEAD" ;;
  *) echo "wrong commit $HEAD" >&2; exit 1 ;;
esac
