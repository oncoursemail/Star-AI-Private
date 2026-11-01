#!/usr/bin/env bash
# Install ComfyUI (official repository, pinned release) with its own Python environment, and one
# image model that fits an 8 GB card: FLUX.2 klein 4B (distilled, fp8), Apache-2.0.
#
#   MEDIA_HOME=/path/to/media bash scripts/media/setup_comfyui.sh [code|models|all]
#
# Needs `uv`, `git` and `curl` on PATH. Nothing is installed outside MEDIA_HOME. No custom nodes.
# Downloads: about 3 GB of Python packages (PyTorch with CUDA) and 8.26 GB of model files.
# Every model file is fetched from a fixed revision and checked against its SHA-256.
set -euo pipefail

MEDIA_HOME="${MEDIA_HOME:?set MEDIA_HOME to the folder that will hold ComfyUI}"
STEP="${1:-all}"
COMFY_REPO="https://github.com/Comfy-Org/ComfyUI"      # github.com/comfyanonymous/ComfyUI redirects here
COMFY_TAG="v0.39.0"                                    # released 2026-10-05
COMFY_COMMIT="b0b743566f65daafc423b4fea8a2fbda94b3384a"
PYTHON_VERSION="3.13"
TORCH_INDEX="https://download.pytorch.org/whl/cu130"   # the README's index for NVIDIA 20-series and newer

COMFY="$MEDIA_HOME/ComfyUI"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$MEDIA_HOME/tools/python}"
export UV_LINK_MODE=copy PYTHONUTF8=1

# repo | revision | file in the repo | folder under ComfyUI/models | size in bytes | sha256
MODELS=(
"black-forest-labs/FLUX.2-klein-4b-fp8|5b4408e59397a4a37ccb46afe426d8ed86379441|flux-2-klein-4b-fp8.safetensors|diffusion_models|4070624520|97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6"
"Comfy-Org/vae-text-encorder-for-flux-klein-4b|5f526678002e43af5551dadb73ce2e8c91b43afe|split_files/text_encoders/qwen_3_4b_fp4_flux2.safetensors|text_encoders|3848213998|3eab03a77adb0ee5304a4e677d5c10ac22f9049c1d7c894adca4f8bb39206ca8"
"Comfy-Org/vae-text-encorder-for-flux-klein-4b|5f526678002e43af5551dadb73ce2e8c91b43afe|split_files/vae/flux2-vae.safetensors|vae|336211292|868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3"
# Z-Image Turbo (Tongyi-MAI, Apache-2.0; Comfy-Org repack): STAR's default picture model when installed (star/comfy.py ZIMAGE_FILES)
"Comfy-Org/z_image_turbo|6fc90a3b1b653e935a0d175e260736de25b84df5|split_files/diffusion_models/z_image_turbo_bf16.safetensors|diffusion_models|12309866400|2407613050b809ffdff18a4ac99af83ea6b95443ecebdf80e064a79c825574a6"
"Comfy-Org/z_image_turbo|6fc90a3b1b653e935a0d175e260736de25b84df5|split_files/text_encoders/qwen_3_4b_fp4_mixed.safetensors|text_encoders|3479416193|7ca32dcf07dfe7692945d80fff86e3a74cb83c6206b9b223ac6836b939bb85d6"
"Comfy-Org/z_image_turbo|6fc90a3b1b653e935a0d175e260736de25b84df5|split_files/vae/ae.safetensors|vae|335304388|afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38"
)

install_code() {
  mkdir -p "$MEDIA_HOME"
  if [ ! -d "$COMFY/.git" ]; then
    git clone --depth 1 --branch "$COMFY_TAG" "$COMFY_REPO" "$COMFY"
  fi
  local head; head="$(git -C "$COMFY" rev-parse HEAD)"
  if [ "$head" != "$COMFY_COMMIT" ]; then
    echo "ComfyUI is at $head, expected $COMFY_TAG ($COMFY_COMMIT). Not continuing." >&2; exit 2
  fi
  [ -d "$COMFY/.venv" ] || uv venv --python "$PYTHON_VERSION" "$COMFY/.venv"
  local py="$COMFY/.venv/Scripts/python.exe"; [ -f "$py" ] || py="$COMFY/.venv/bin/python"
  uv pip install --python "$py" torch torchvision torchaudio --extra-index-url "$TORCH_INDEX"
  uv pip install --python "$py" -r "$COMFY/requirements.txt" --extra-index-url "$TORCH_INDEX"
  "$py" -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available(),torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
}

install_models() {
  local row repo rev file folder size sha target got
  if [ ! -d "$COMFY/.git" ]; then
    echo "ComfyUI is not installed in $COMFY yet: run the 'code' step first." >&2; exit 4
  fi
  for row in "${MODELS[@]}"; do
    IFS='|' read -r repo rev file folder size sha <<<"$row"
    target="$COMFY/models/$folder/$(basename "$file")"
    mkdir -p "$(dirname "$target")"
    if [ -f "$target" ] && [ "$(stat -c %s "$target")" = "$size" ]; then
      echo "have $(basename "$file")"
    else
      echo "downloading $(basename "$file") ($size bytes)"
      curl -fL --retry 5 --retry-delay 5 -C - -o "$target.part" "https://huggingface.co/$repo/resolve/$rev/$file"
      mv "$target.part" "$target"
    fi
    got="$(sha256sum "$target" | cut -d' ' -f1)"
    if [ "$got" != "$sha" ]; then
      echo "SHA-256 mismatch for $target: $got" >&2; exit 3
    fi
    echo "verified $(basename "$file")"
  done
}

case "$STEP" in
  code) install_code ;;
  models) install_models ;;
  all) install_code; install_models ;;
  *) echo "usage: setup_comfyui.sh [code|models|all]" >&2; exit 64 ;;
esac
echo "done: $STEP"
