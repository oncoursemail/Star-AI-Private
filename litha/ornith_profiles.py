"""Evidence-bounded Ornith model profiles for Litha.

This module does not download, start, or trust a model. It centralizes public
capability metadata and produces conservative deployment recommendations that
other Litha components can consume. The values here are intentionally bounded:
"native context" is a model capability, not a promise that a given machine can
serve that context efficiently.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DeploymentClass(str, Enum):
    LOCAL_8GB = "local_8gb"
    WORKSTATION = "workstation"
    SERVER = "server"
    MULTI_GPU = "multi_gpu"


@dataclass(frozen=True)
class OrnithProfile:
    model_id: str
    parameters_b: float
    architecture: str
    quantized_size_gb: float | None
    native_context: int
    vision: bool
    tools: bool
    thinking: bool
    deployment: DeploymentClass
    notes: str


ORNITH_PROFILES: dict[str, OrnithProfile] = {
    "ornith-1.5:9b": OrnithProfile(
        model_id="ornith-1.5:9b",
        parameters_b=8.95,
        architecture="dense",
        quantized_size_gb=6.6,
        native_context=262_144,
        vision=True,
        tools=True,
        thinking=True,
        deployment=DeploymentClass.LOCAL_8GB,
        notes=(
            "Best first Ornith candidate for Litha consumer-GPU evaluation. "
            "The model file can fit an 8 GB class GPU, but long KV caches, "
            "vision projector memory, and runtime overhead still require "
            "context budgeting and empirical measurement."
        ),
    ),
    "ornith-1.5:35b": OrnithProfile(
        model_id="ornith-1.5:35b",
        parameters_b=35.5,
        architecture="moe",
        quantized_size_gb=23.0,
        native_context=262_144,
        vision=True,
        tools=True,
        thinking=True,
        deployment=DeploymentClass.WORKSTATION,
        notes=(
            "MoE quality candidate for a high-RAM workstation or 24 GB+ GPU. "
            "Do not silently CPU-offload on latency-sensitive interactive chat."
        ),
    ),
    "ornith-1.5:122b": OrnithProfile(
        model_id="ornith-1.5:122b",
        parameters_b=122.0,
        architecture="moe",
        quantized_size_gb=None,
        native_context=262_144,
        vision=True,
        tools=True,
        thinking=True,
        deployment=DeploymentClass.SERVER,
        notes="Server-class evaluation candidate; require measured memory and latency before routing.",
    ),
    "ornith-1.5:397b": OrnithProfile(
        model_id="ornith-1.5:397b",
        parameters_b=397.0,
        architecture="moe",
        quantized_size_gb=None,
        native_context=262_144,
        vision=True,
        tools=True,
        thinking=True,
        deployment=DeploymentClass.MULTI_GPU,
        notes="Large multi-GPU research candidate, never a default local fallback.",
    ),
}


@dataclass(frozen=True)
class OrnithRecommendation:
    profile: OrnithProfile
    recommended_context: int
    reason: str
    allow_interactive: bool
    requires_benchmark_gate: bool = True


def recommend_ornith(
    *,
    vram_gb: float,
    ram_gb: float,
    prefer_interactive: bool = True,
) -> OrnithRecommendation:
    """Return a conservative Ornith candidate for the supplied hardware.

    The function deliberately does not claim exact tokens/second. Hardware,
    backend build, KV-cache precision, prompt length, offload split and vision
    all affect measured throughput. Litha should benchmark before promotion.
    """
    if vram_gb <= 0 or ram_gb <= 0:
        raise ValueError("VRAM and RAM must be positive")

    p9 = ORNITH_PROFILES["ornith-1.5:9b"]
    if vram_gb >= 7.5 and ram_gb >= 16:
        # 32K is a practical starting point for 8 GB cards. The model advertises
        # 256K native context, but allocating that blindly can evict weights/KV.
        ctx = 32_768 if vram_gb < 12 else 65_536
        return OrnithRecommendation(
            profile=p9,
            recommended_context=ctx,
            reason="9B is the only Ornith-1.5 profile appropriate for an 8 GB-class local GPU.",
            allow_interactive=True,
        )

    if ram_gb >= 32:
        return OrnithRecommendation(
            profile=p9,
            recommended_context=16_384,
            reason="Use the 9B profile with measured partial offload; keep latency-gated.",
            allow_interactive=not prefer_interactive,
        )

    raise ValueError("No Ornith profile is recommended for this memory budget")


def promotion_requirements(profile: OrnithProfile) -> tuple[str, ...]:
    """Evidence Litha must collect before making a profile a preferred route."""
    requirements = [
        "cold_start_seconds",
        "first_token_seconds",
        "generation_tokens_per_second",
        "prompt_tokens_per_second",
        "peak_vram_bytes",
        "peak_ram_bytes",
        "tool_call_success_rate",
        "coding_regression_score",
        "agent_loop_termination_rate",
    ]
    if profile.vision:
        requirements.append("vision_regression_score")
    return tuple(requirements)
