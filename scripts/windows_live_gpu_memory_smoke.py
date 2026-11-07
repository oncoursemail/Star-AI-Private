"""Explicit, read-only NVIDIA VRAM sampling on a private Windows host.

Usage:
  python -m scripts.windows_live_gpu_memory_smoke --read-only \
      --executable "C:\\Windows\\System32\\nvidia-smi.exe" \
      --gpu-uuid "GPU-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

This never runs a game, model, OBS, stream or GPU memory allocation. The
operator selects the fixed executable and a device UUID using independent
local inventory. Reports bounded anonymized numbers only; does not publish
device UUIDs, usernames, file paths, or other host identifiers.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from star.stream_windows_gpu_probe import (
    GPUProbeUnavailable,
    WindowsNVIDIAMemoryProbe,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--executable", required=True)
    parser.add_argument("--gpu-uuid", required=True)
    args = parser.parse_args()
    if not args.read_only:
        parser.error("explicit --read-only required")
    try:
        probe = WindowsNVIDIAMemoryProbe(
            Path(args.executable),
            args.gpu_uuid,
        )
        result = probe.read()
    except (ValueError, GPUProbeUnavailable):
        print(
            json.dumps(
                {
                    "passed": False,
                    "stage": "pinned_gpu_read_only_probe_unavailable",
                    "gpu_memory_attestation": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "passed": True,
                "stage": "pinned_gpu_read_only_observation",
                "total_vram_mib": result.total_mib,
                "free_vram_mib": result.free_mib,
                "gpu_memory_attestation": False,
                "stream_or_game_started": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
