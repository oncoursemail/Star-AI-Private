#!/bin/bash
# Build the per-core-pinning llama-server next to (never over) the live one. Run as user star on brain 1.
#   SRC  the live source tree (default /opt/star/src/llama.cpp-ramforge)
#   DST  new tree (default /opt/star/src/llama.cpp-pin), binaries in $DST/build/bin
# Patch 0004: GGML_RF_PIN=1 (with --numa distribute + GGML_NUMA_BLOCK=1) pins thread j of node k to ONE cpu: the
# node's physical cores sorted by (L3 id, cpu), then their SMT siblings. Unset = unchanged behaviour.
# Measured 2026-10-21 (docs/agents/speed-queue-20261021.md): +10-20% prompt speed alone, but -31%/-55% when two
# pinned models work at once, so it is NOT live.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-/opt/star/src/llama.cpp-ramforge}
DST=${DST:-/opt/star/src/llama.cpp-pin}
if [ ! -d "$DST" ]; then
  mkdir -p "$DST"
  tar -C "$SRC" --exclude=./build -cf - . | tar -C "$DST" -xf -
  (cd "$DST" && patch -p1 < "$HERE/patches/0004-ggml-rf-pin-per-core.patch")
fi
cd "$DST"
nice -n 19 cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DGGML_OPENMP=ON -DLLAMA_CURL=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_OPENSSL=ON
nice -n 19 cmake --build build -j "${JOBS:-8}" --target llama-server
echo "built: $DST/build/bin"
