from litha.ornith_profiles import (
    ORNITH_PROFILES,
    DeploymentClass,
    promotion_requirements,
    recommend_ornith,
)


def test_9b_is_the_consumer_gpu_candidate():
    p = ORNITH_PROFILES["ornith-1.5:9b"]
    assert p.parameters_b == 8.95
    assert p.deployment is DeploymentClass.LOCAL_8GB
    assert p.native_context == 262_144
    assert p.quantized_size_gb == 6.6


def test_8gb_gpu_gets_conservative_context_not_native_maximum():
    r = recommend_ornith(vram_gb=8, ram_gb=32)
    assert r.profile.model_id == "ornith-1.5:9b"
    assert r.recommended_context == 32_768
    assert r.recommended_context < r.profile.native_context
    assert r.allow_interactive is True
    assert r.requires_benchmark_gate is True


def test_bigger_gpu_can_start_at_64k_but_still_needs_gate():
    r = recommend_ornith(vram_gb=16, ram_gb=64)
    assert r.recommended_context == 65_536
    assert r.requires_benchmark_gate


def test_low_vram_cpu_offload_is_not_silently_marked_interactive():
    r = recommend_ornith(vram_gb=4, ram_gb=64, prefer_interactive=True)
    assert r.profile.model_id == "ornith-1.5:9b"
    assert r.allow_interactive is False
    assert r.recommended_context == 16_384


def test_too_little_memory_fails_closed():
    try:
        recommend_ornith(vram_gb=4, ram_gb=8)
    except ValueError as exc:
        assert "No Ornith profile" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_promotion_gate_covers_agent_failure_modes():
    req = promotion_requirements(ORNITH_PROFILES["ornith-1.5:9b"])
    assert "tool_call_success_rate" in req
    assert "agent_loop_termination_rate" in req
    assert "coding_regression_score" in req
    assert "vision_regression_score" in req
