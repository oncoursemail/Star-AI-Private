#!/bin/bash
# Build the API-lock llama-server (patch 0004) next to (never over) the live one. Run as user star on brain 1.
#   SRC  the live source tree (default /opt/star/src/llama.cpp-ramforge: b11541 + RAMForge 0001 + 0002, uncommitted)
#   DST  new tree (default /opt/star/src/llama.cpp-apilock), binaries in $DST/build/bin
# The binary behaves like the live one unless a request carries "api_lock" and LLAMA_API_LOCK_TABLE names a table.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-/opt/star/src/llama.cpp-ramforge}
DST=${DST:-/opt/star/src/llama.cpp-apilock}
g() { git -c safe.directory="$DST" -c user.name=apilock -c user.email=apilock@localhost "$@"; }
if [ ! -d "$DST" ]; then
  mkdir -p "$DST"
  tar -C "$SRC" --exclude=./build -cf - . | tar -C "$DST" -xf -
  (cd "$DST" && g add -A >/dev/null && g commit -qm "live state")
fi
cd "$DST"
g checkout -q -- common tools/server tests
rm -f common/api-lock.cpp common/api-lock.h tests/test-api-lock.cpp
g apply "$HERE/0004-api-lock-sampler.patch"
nice -n 19 cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DGGML_OPENMP=ON -DLLAMA_CURL=OFF \
  -DLLAMA_BUILD_TESTS=ON -DLLAMA_OPENSSL=ON >/dev/null
nice -n 19 cmake --build build -j "${JOBS:-8}" --target llama-server test-api-lock
"$DST/build/bin/test-api-lock" "$HERE/cases.json"
echo "built: $DST/build/bin"
