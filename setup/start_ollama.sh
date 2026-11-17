#!/usr/bin/env bash
# Run the project-local Ollama server as a user unit, pinned to CPUs 2-5 (+SMT siblings);
# the model itself runs on the GPU. Models are stored under work/ollama/models.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
O="$ROOT/work/ollama"
systemd-run --user --unit=rsswarm-ollama --collect -p CPUAffinity="2-5 26-29" \
  -E OLLAMA_MODELS="$O/models" -E OLLAMA_HOST=127.0.0.1:11435 -E OLLAMA_NUM_PARALLEL=3 \
  -E OLLAMA_KEEP_ALIVE=-1 -E OLLAMA_CONTEXT_LENGTH=8192 -E OLLAMA_FLASH_ATTENTION=1 -E OLLAMA_KV_CACHE_TYPE=q8_0 \
  "$O/dist/bin/ollama" serve
