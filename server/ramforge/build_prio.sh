#!/bin/bash
# Build the priority-patched llama-server next to (never over) the live one. Run as user star on brain 1.
#   SRC  the live source tree (default /opt/star/src/llama.cpp-ramforge: b58ca6a + RAMForge + 0002, uncommitted)
#   DST  new tree (default /opt/star/src/llama.cpp-prio), binaries in $DST/build/bin
# Patch 0003: low_priority requests read their prompt in chunks (64 tokens, LLAMA_LOW_PRIO_CHUNK) and wait while a
# normal request has work; the router drops the child connection when a client goes away mid-prompt.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-/opt/star/src/llama.cpp-ramforge}
DST=${DST:-/opt/star/src/llama.cpp-prio}
if [ ! -d "$DST" ]; then
  mkdir -p "$DST"
  tar -C "$SRC" --exclude=./build -cf - . | tar -C "$DST" -xf -
  (cd "$DST" && git -c user.name=prio -c user.email=prio@localhost add -A >/dev/null \
     && git -c user.name=prio -c user.email=prio@localhost commit -qm "live state")
fi
cd "$DST"
git checkout -q -- tools/server
git apply "$HERE/patches/0003-server-low-priority-slots.patch"
nice -n 19 cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DGGML_OPENMP=ON -DLLAMA_CURL=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_OPENSSL=ON
nice -n 19 cmake --build build -j "${JOBS:-16}" --target llama-server
echo "built: $DST/build/bin"
