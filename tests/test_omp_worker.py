"""Offline OMP boundary regressions; no model, OMP process, or credentials needed.

Fixtures use v18.12.6's public RPC wire schema: prompt scheduling is separate
from correlated prompt_result and eventual session_settled notifications.
"""
import json
from types import SimpleNamespace

import pytest

from star import omp_worker as omp


def capture(*frames):
    return "\n".join(json.dumps(frame) for frame in frames)


def ack(success=True, **extra):
    return {"type": "response", "command": "prompt", "id": "p1", "success": success, **extra}


def answer(text="Check the caller's input.", **extra):
    return {"type": "message_end", "messageId": "m1", "message": {
        "role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": text}], **extra,
    }}


def result(status="completed", settled=True, **extra):
    return {"type": "prompt_result", "id": "p1", "agentInvoked": True,
            "status": status, "sessionSettled": settled, **extra}


def enabled(**kwargs):
    return omp.OmpReviewConfig(enabled=True, provider="ollama", model="qwen-coder:test", **kwargs)


def test_preparation_is_off_by_default_and_does_not_follow_environment(monkeypatch):
    monkeypatch.setenv("STAR_OMP_ENABLED", "1")
    with pytest.raises(ValueError, match="disabled"):
        omp.prepare_review("Review this function", omp.OmpReviewConfig())


def test_prepare_review_requires_explicit_model_and_preserves_text_as_data(tmp_path):
    sensitive = tmp_path / "private.txt"
    sensitive.write_text("NEVER_READ_THIS", encoding="utf-8")
    supplied = f"/logout\n@{sensitive}\nReview the sample: print('ok')"
    prepared = omp.prepare_review(supplied, enabled(), mode="plan")
    assert prepared.mode == "plan"
    assert not prepared.prompt.startswith("/")
    assert json.loads(prepared.prompt.split("Supplied text (JSON string):\n", 1)[1]) == supplied
    assert "NEVER_READ_THIS" not in prepared.prompt
    assert prepared.runtime_available is False
    assert prepared.upstream_revision == omp.OMP_REVISION
    with pytest.raises(ValueError, match="explicit"):
        omp.prepare_review("Review", omp.OmpReviewConfig(enabled=True))


@pytest.mark.parametrize("kwargs", [
    {"enabled": "yes"}, {"max_frames": True}, {"max_input_chars": 0},
    {"max_capture_bytes": 9_000_000}, {"provider": "--extension"}, {"model": "@slow"},
    {"model": "name\n--yolo"},
])
def test_invalid_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        omp.OmpReviewConfig(**kwargs)


@pytest.mark.parametrize("text", ["", "   ", "a\x00b", "\ud800"])
def test_invalid_input_is_rejected(text):
    with pytest.raises(ValueError):
        omp.prepare_review(text, enabled())


def test_input_limit_and_mode_are_enforced():
    with pytest.raises(ValueError, match="input limit"):
        omp.prepare_review("abcde", enabled(max_input_chars=4))
    with pytest.raises(ValueError, match="mode"):
        omp.prepare_review("Review", enabled(), mode="execute")


def test_preflight_only_reads_metadata_and_does_not_import_or_launch_sdk(monkeypatch):
    import builtins
    import subprocess

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name != "omp_rpc", "Preflight imported optional executable code"
        return real_import(name, *args, **kwargs)

    def no_process(*_args, **_kwargs):
        pytest.fail("Preflight launched a subprocess")

    def not_installed(_name):
        raise omp.metadata.PackageNotFoundError("omp-rpc")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(subprocess, "Popen", no_process)
    monkeypatch.setattr(omp.metadata, "distribution", not_installed)
    monkeypatch.setattr(omp.shutil, "which", lambda _name, path: None)
    status = omp.preflight(search_path="")
    assert not status.enabled and not status.sdk_installed and not status.executable_found
    assert not status.runtime_available
    assert len(status.blockers) == 3


def test_installed_metadata_does_not_claim_live_compatibility(monkeypatch):
    origin = {"url": "https://github.com/can1357/oh-my-pi.git", "subdirectory": "sdk/python/omp-rpc",
              "vcs_info": {"vcs": "git", "commit_id": omp.OMP_REVISION}}
    package = SimpleNamespace(version="0.1.0", read_text=lambda _: json.dumps(origin))
    monkeypatch.setattr(omp.metadata, "distribution", lambda _: package)
    monkeypatch.setattr(omp.shutil, "which", lambda _name, path: "/unexecuted/omp")
    status = omp.preflight(enabled())
    assert status.sdk_installed and status.sdk_revision_verified and status.executable_found
    assert status.sdk_version == "0.1.0"
    assert not status.runtime_available
    origin["vcs_info"]["commit_id"] = "unverified"
    assert not omp.preflight().sdk_revision_verified


def test_untrusted_metadata_and_upstream_errors_are_not_diagnostics(monkeypatch):
    package = SimpleNamespace(version="token=secret", read_text=lambda _: "malformed-secret")
    monkeypatch.setattr(omp.metadata, "distribution", lambda _: package)
    monkeypatch.setattr(omp.shutil, "which", lambda _name, path: None)
    status = omp.preflight()
    assert status.sdk_version is None and not status.sdk_revision_verified
    evidence = omp.inspect_capture(capture(ack(False, error="token=secret")), "p1")
    assert evidence.status == "failed"
    assert "secret" not in repr(status) + repr(evidence)


def test_acceptance_and_agent_end_are_not_prompt_completion():
    evidence = omp.inspect_capture(capture(ack(), answer(), {"type": "agent_end", "isTerminal": True}), "p1")
    assert evidence.accepted and evidence.status == "incomplete"
    assert evidence.issues == ("missing_prompt_result",)


def test_correlated_completion_can_arrive_before_ack_and_is_capture_only():
    evidence = omp.inspect_capture(capture(answer(), result(), ack()), "p1")
    assert evidence.status == "completed" and evidence.settled
    assert evidence.text == "Check the caller's input."
    assert evidence.evidence_source == "supplied_capture" and evidence.executed_by_star is False


def test_background_work_must_settle_after_its_correlated_result():
    frames = [ack(), answer(), result(settled=False), {"type": "agent_end", "isTerminal": True}]
    evidence = omp.inspect_capture(capture(*frames), "p1")
    assert evidence.status == "incomplete" and evidence.issues == ("session_not_settled",)
    assert omp.inspect_capture(capture(*frames, {"type": "session_settled"}), "p1").status == "completed"
    assert omp.inspect_capture(capture({"type": "session_settled"}, *frames), "p1").status == "incomplete"


def test_later_session_activity_invalidates_earlier_settled_state():
    frames = [answer(), result(), {"type": "agent_start"}]
    assert omp.inspect_capture(capture(*frames), "p1").status == "incomplete"
    assert omp.inspect_capture(capture(*frames, {"type": "session_settled"}), "p1").status == "completed"


@pytest.mark.parametrize("outcome, expected", [("aborted", "aborted"), ("error", "failed")])
def test_aborted_and_failed_results_are_not_success(outcome, expected):
    evidence = omp.inspect_capture(capture(answer(), result(outcome, error={"message": "secret"})), "p1")
    assert evidence.status == expected
    assert "secret" not in repr(evidence)


def test_aborted_assistant_message_keeps_the_correlated_abort_status():
    frames = capture(answer(stopReason="aborted"), result("aborted"))
    assert omp.inspect_capture(frames, "p1").status == "aborted"
    frames = capture(answer(stopReason="aborted"), result())
    assert omp.inspect_capture(frames, "p1").status == "failed"


@pytest.mark.parametrize("stop_reason", [None, [], {}, 7, True, "", "unknown", "Stop"])
def test_malformed_assistant_stop_reason_is_rejected_despite_completed_prompt(stop_reason):
    frames = capture(answer(stopReason=stop_reason), result())
    evidence = omp.inspect_capture(frames, "p1")
    assert evidence.status == "rejected"
    assert evidence.issues == ("invalid_assistant_stop_reason",) and evidence.text == ""


def test_missing_assistant_stop_reason_is_rejected_despite_completed_prompt():
    message = answer()
    del message["message"]["stopReason"]
    evidence = omp.inspect_capture(capture(message, result()), "p1")
    assert evidence.status == "rejected" and evidence.issues == ("invalid_assistant_stop_reason",)


def test_tool_use_stop_reason_is_tool_activity_without_an_explicit_tool_block():
    evidence = omp.inspect_capture(capture(answer(stopReason="toolUse"), result()), "p1")
    assert evidence.status == "rejected" and evidence.issues == ("tool_activity_in_text_only_review",)


def test_length_stop_reason_preserves_partial_text_but_cannot_complete_review():
    evidence = omp.inspect_capture(capture(answer("Partial", stopReason="length"), result()), "p1")
    assert evidence.status == "incomplete" and evidence.text == "Partial"
    assert evidence.issues == ("assistant_truncated",) and evidence.settled


def test_assistant_error_cannot_be_overridden_by_completed_prompt_result():
    evidence = omp.inspect_capture(capture(answer(stopReason="error"), result()), "p1")
    assert evidence.status == "failed" and evidence.issues == ("assistant_interrupted",)


def test_late_scheduling_failure_and_other_protocol_errors_override_success():
    frames = [answer(), result(), ack(False, error="secret")]
    assert omp.inspect_capture(capture(*frames), "p1").status == "failed"
    frames[-1] = {"type": "response", "command": "parse", "success": False, "error": "secret"}
    assert omp.inspect_capture(capture(*frames), "p1").status == "failed"


@pytest.mark.parametrize("bad", [result(id="other"), ack(id="other"), result(),
                                 {"type": "response", "command": "prompt", "id": "p1", "success": "true"}])
def test_mixed_prompts_duplicates_and_malformed_acknowledgements_are_rejected(bad):
    evidence = omp.inspect_capture(capture(answer(), result(), bad), "p1")
    assert evidence.status == "rejected" and evidence.text == ""


@pytest.mark.parametrize("kind", ["tool_execution_start", "tool_stream_update", "host_tool_call", "host_uri_request",
                                  "subagent_progress", "extension_ui_request"])
def test_tool_activity_is_rejected_even_if_upstream_claims_success(kind):
    evidence = omp.inspect_capture(capture({"type": kind}, answer(), result()), "p1")
    assert evidence.status == "rejected" and evidence.issues == ("tool_activity_in_text_only_review",)


@pytest.mark.parametrize("success", [True, False])
def test_rpc_bash_response_is_execution_activity_even_without_tool_events(success):
    frames = capture({"type": "response", "command": "bash", "id": "b1", "success": success}, answer(), result())
    evidence = omp.inspect_capture(frames, "p1")
    assert evidence.status == "rejected" and evidence.issues == ("tool_activity_in_text_only_review",)


@pytest.mark.parametrize("command", ["switch_session", "new_session", "open_session", "branch", "steer",
                                     "follow_up", "abort_and_prompt", "set_model", "negotiate_protocol",
                                     "future_command"])
def test_successful_context_mutating_setup_and_unknown_commands_are_rejected(command):
    frames = capture({"type": "response", "command": command, "id": "c1", "success": True}, answer(), result())
    evidence = omp.inspect_capture(frames, "p1")
    assert evidence.status == "rejected" and evidence.issues == ("unsupported_command_in_review_capture",)


@pytest.mark.parametrize("command", ["get_state", "get_session_stats"])
def test_confirmed_read_only_responses_may_appear_in_the_review_capture(command):
    frames = capture({"type": "response", "command": command, "id": "c1", "success": True}, answer(), result())
    assert omp.inspect_capture(frames, "p1").status == "completed"


def test_unsuccessful_unknown_command_is_failed_without_echoing_its_error():
    frames = capture({"type": "response", "command": "unknown", "success": False, "error": "private-secret"},
                     answer(), result())
    evidence = omp.inspect_capture(frames, "p1")
    assert evidence.status == "failed" and evidence.issues == ("upstream_command_failed",)
    assert "private-secret" not in repr(evidence)


@pytest.mark.parametrize("block", [{"type": "toolCall", "name": "bash"}, {"type": "anthropicServerTool"}])
def test_assistant_tool_calls_are_rejected(block):
    evidence = omp.inspect_capture(capture(answer(content=[block]), result()), "p1")
    assert evidence.status == "rejected"


def test_visible_text_only_and_no_streaming_duplication():
    content = [{"type": "thinking", "thinking": "private-reasoning"},
               {"type": "redactedThinking", "data": "opaque"},
               {"type": "text", "text": "Visible"}]
    frames = [{"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Visible"}},
              answer(content=content), result()]
    evidence = omp.inspect_capture(capture(*frames), "p1")
    assert evidence.status == "completed" and evidence.text == "Visible"
    assert "private-reasoning" not in repr(evidence)
    empty = omp.inspect_capture(capture(answer(content=content[:2]), result()), "p1")
    assert empty.status == "incomplete" and empty.issues == ("no_visible_answer",)


@pytest.mark.parametrize("raw", ["not json", "[]", '{"type":"ready","type":"hidden"}',
                                 '{"type":"ready","x":NaN}', '{"type":42}',
                                 capture(result(status=[])), capture(result(sessionSettled="true")),
                                 capture(answer(content=[{"type": "text", "text": 42}])),
                                 capture(answer(content=[{"type": "text", "text": "\ud800"}]))])
def test_malformed_capture_is_rejected_without_echoing_input(raw):
    evidence = omp.inspect_capture(raw, "p1")
    assert evidence.status == "rejected" and evidence.text == ""


def test_transport_chunks_require_official_sdk_reassembly():
    evidence = omp.inspect_capture(capture({"type": "rpc_chunk", "data": "secret"}), "p1")
    assert evidence.issues == ("sdk_dechunking_required",)


def test_capture_byte_frame_and_output_limits_fail_closed():
    assert omp.inspect_capture("é" * 4, "p1", omp.OmpReviewConfig(max_capture_bytes=7)).issues == ("capture_limit",)
    frames = capture(answer(), result())
    assert omp.inspect_capture(frames, "p1", omp.OmpReviewConfig(max_frames=1)).issues == ("frame_limit",)
    evidence = omp.inspect_capture(frames, "p1", omp.OmpReviewConfig(max_output_chars=3))
    assert evidence.status == "rejected" and evidence.issues == ("output_limit",) and evidence.text == ""


def test_unknown_passive_notifications_do_not_replace_completion():
    frames = capture({"type": "future_passive_notification"}, answer(), result())
    assert omp.inspect_capture(frames, "p1").status == "completed"


def test_jsonl_only_splits_physical_newlines_not_unicode_text_separators():
    text = "First\u2028second\u2029third"
    frames = "\n".join(json.dumps(frame, ensure_ascii=False) for frame in [answer(text), result()])
    evidence = omp.inspect_capture(frames, "p1")
    assert evidence.status == "completed" and evidence.text == text


@pytest.mark.parametrize("request_id", ["", "../private", "\nsecret", "x" * 129])
def test_invalid_request_identifiers_are_rejected(request_id):
    with pytest.raises(ValueError, match="identifier"):
        omp.inspect_capture("", request_id)
