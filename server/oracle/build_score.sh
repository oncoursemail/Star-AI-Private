#!/usr/bin/env bash
# Build llama-score on Linux against an already built llama.cpp tree (headers + shared libraries of THAT tree).
#   bash server/oracle/build_score.sh <llama.cpp source dir> <dir with libllama.so> <output binary>
# Example (brain 1 container): bash build_score.sh /opt/star/src/llama.cpp-ramforge /opt/star/bin-ramforge /opt/star/oracle/llama-score
set -euo pipefail
src=${1:?llama.cpp source dir}
lib=${2:?directory with libllama.so and libggml*.so}
out=${3:?output path}
here=$(cd "$(dirname "$0")" && pwd)
g++ -O2 -std=c++17 -pthread -I "$src/include" -I "$src/ggml/include" -I "$src/vendor" \
    "$here/llama_score.cpp" -L "$lib" -lllama -lggml -lggml-base -Wl,-rpath,"$lib" -o "$out"
echo "built $out"
