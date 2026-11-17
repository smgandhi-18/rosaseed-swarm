#!/usr/bin/env bash
# Install the Ollama release binary inside work/ollama (no root, no system service).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
O="$ROOT/work/ollama"
VER=v0.40.16
mkdir -p "$O/dist" "$O/models"
if [ ! -x "$O/dist/bin/ollama" ]; then
  curl -sSfL "https://github.com/ollama/ollama/releases/download/$VER/ollama-linux-amd64.tar.zst" -o "$O/ollama.tar.zst"
  tar --zstd -xf "$O/ollama.tar.zst" -C "$O/dist"
  rm -f "$O/ollama.tar.zst"
fi
"$O/dist/bin/ollama" --version || true
