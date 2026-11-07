"""Bulk service integration against real settings, ledgers and disposable files.

Only OS credential storage and the asynchronous model call are replaced. No
test starts a GUI, reaches a server, or reads a real user's workspace.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import threading
import time

import pytest

from star import bulk_profiles
from star.bulk_operations import BulkConflictError, OperationCancelled
from star.bulk_tasks import BulkTaskService
from star.desktop_core import Settings


class FakeSecrets:
    def __init__(self):
        self.values = {}

    def put(self, account, secret):
        self.values[account] = secret

    def get(self, account):
        return self.values.get(account)

    def delete(self, account):
        self.values.pop(account, None)


class Host:
    def __init__(self, home, brain_runner=None, *, configuration_lock=None):
        self.home = home
        self.current = Settings(model="local-test")
        self.secrets = FakeSecrets()
        self.calls = []
        self.runner = brain_runner or self.brain
        self.configuration_lock = configuration_lock
        self.service = self._open()

    def _open(self):
        options = {"configuration_lock": self.configuration_lock} if self.configuration_lock is not None else {}
        return BulkTaskService(self.home, lambda: self.current, secrets=self.secrets, brain_runner=self.runner, **options)

    async def brain(self, settings, goal, secret, cancel_event):
        self.calls.append({"settings": settings, "goal": goal, "secret": secret, "event": cancel_event})
        return {"answer": "Synthetic model answer", "verified": False, "verification": "model_response_only"}

    def enable(self):
        return self.service.handle("bulkTaskSetEnabled", {"enabled": True})

    def capture(self, name="Captured", *, allow_edit=False, **settings):
        self.current = replace(self.current, **settings)
        before = set(self.service.profiles.ids())
        result = self.service.handle("bulkTaskCapture", {"name": name, "allow_edit": allow_edit})
        created = [target["id"] for target in result["targets"] if target["id"] not in before]
        assert len(created) == 1
        return created[0]

    def preview(self, targets, *, kind="brain_prompt", key="intent-1", **body):
        request = {"kind": kind, "targetIds": list(targets), "idempotencyKey": key,
                   "prompt": "Explain this project", **body}
        return self.service.handle("bulkTaskPreview", request)

    def send(self, batch):
        return self.service.handle("bulkTaskSend", {"batchId": batch["batch_id"], "intentHash": batch["intent_sha256"]})

    def restart(self):
        self.service.shutdown(wait=True)
        self.service = self._open()

    def close(self):
        self.service.shutdown(wait=True)


@pytest.fixture
def make_host(tmp_path):
    hosts = []

    def create(brain_runner=None, *, configuration_lock=None):
        host = Host(tmp_path / f"host-{len(hosts)}", brain_runner, configuration_lock=configuration_lock)
        hosts.append(host)
        return host

    yield create
    for host in hosts:
        host.close()


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    pytest.fail("The expected asynchronous service state was not reached")


def finished(host, batch):
    batch_id = batch["batch_id"]
    wait_until(lambda: host.service.engine.get_batch(batch_id)["terminal"], timeout=5)
    # A completed receipt can precede the coordinator's final cleanup by one
    # scheduler turn. Join it before preparing a dependent undo or reopening.
    with host.service._lock:
        coordinator = host.service._active.get(batch_id)
    if coordinator is not None:
        coordinator.join(timeout=3)
        assert not coordinator.is_alive()
    return host.service.handle("bulkTaskStatus", {"batchId": batch_id})


def workspace(tmp_path, name):
    root = tmp_path / name
    root.mkdir()
    (root / "note.txt").write_bytes(b"old\r\nowner text\n")
    return root


def test_service_starts_off_with_no_implicit_targets(make_host):
    host = make_host()
    assert host.service.handle("bulkTaskCatalog", {})["enabled"] is False
    assert host.service.handle("bulkTaskCatalog", {})["targets"] == []
    with pytest.raises(PermissionError, match="off"):
        host.capture()
    with pytest.raises(PermissionError, match="off"):
        host.preview([])
    host.enable()
    with pytest.raises(ValueError, match="explicitly"):
        host.preview([])
    with pytest.raises(ValueError):
        host.preview(["all"])
    assert host.service.handle("bulkTaskList", {})["batches"] == []
    assert host.calls == []


@pytest.mark.parametrize("action,extra", [
    ("bulkTaskCapture", {"endpoint": "http://192.168.1.20:8080/v1"}),  # star:allow test address
    ("bulkTaskCapture", {"workspace": "/unapproved"}),
    ("bulkTaskCapture", {"apiKey": "synthetic-unapproved-token"}),
    ("bulkTaskPreview", {"settings": {"provider": "groq"}}),
    ("bulkTaskPreview", {"shell": "arbitrary command"}),
    ("bulkTaskSend", {"endpoint": "http://192.168.1.21:8080/v1"}),  # star:allow test address
    ("bulkTaskSetEnabled", {"command": "arbitrary command"}),
])
def test_webchannel_rejects_extra_addresses_secrets_roots_and_commands(make_host, action, extra):
    host = make_host()
    with pytest.raises(ValueError, match="unsupported fields"):
        host.service.handle(action, extra)
    assert host.service.profiles.ids() == ()
    assert host.service.engine.list_batches() == []


def test_capture_uses_current_settings_and_saved_targets_do_not_follow_later_changes(make_host, tmp_path):
    host = make_host()
    host.enable()
    original = workspace(tmp_path, "original")
    other = workspace(tmp_path, "other")
    target = host.capture("Original", model="first-model", workspace=str(original), project="First project")
    host.current = replace(host.current, model="next-model", workspace=str(other), endpoint="http://127.0.0.1:9090/v1")
    batch = host.preview([target], prompt="Use the captured brain")
    host.send(batch)
    result = finished(host, batch)
    assert result["status"] == "succeeded"
    assert len(host.calls) == 1
    settings = host.calls[0]["settings"]
    assert settings.model == "first-model" and settings.workspace == str(original)
    assert settings.endpoint == "http://127.0.0.1:8080/v1" and settings.project == "First project"
    assert settings.workspace_edit is False


def test_service_rejects_cloud_capture(make_host):
    host = make_host()
    host.enable()
    with pytest.raises(PermissionError, match="local or LAN"):
        host.capture(provider="groq", model="cloud-model")
    assert host.service.profiles.ids() == ()


def test_preview_is_immutable_and_changed_idempotent_input_conflicts(make_host):
    host = make_host()
    host.enable()
    target = host.capture()
    request = {"kind": "brain_prompt", "targetIds": [target], "prompt": "Original requested task",
               "idempotencyKey": "same-intent"}
    batch = host.service.handle("bulkTaskPreview", request)
    repeated = host.service.handle("bulkTaskPreview", dict(request))
    assert repeated["batch_id"] == batch["batch_id"]
    assert host.calls == []
    request["prompt"] = "Changed task"
    with pytest.raises(BulkConflictError, match="different intent"):
        host.service.handle("bulkTaskPreview", request)
    request["targetIds"].append("all")
    batch["preview"]["items"][0]["label"] = "Modified in returned object"
    with pytest.raises(BulkConflictError, match="does not match"):
        host.service.handle("bulkTaskSend", {"batchId": batch["batch_id"], "intentHash": "0" * 64})
    assert host.service.engine.get_batch(batch["batch_id"])["status"] == "prepared"
    host.send(batch)
    result = finished(host, batch)
    assert host.calls[0]["goal"] == "Original requested task"
    assert result["preview"]["items"][0]["label"] == "Captured"
    assert "per_target" not in result and "payload_json" not in result


def test_double_send_and_reopened_history_do_not_repeat_a_brain_request(make_host):
    entered, release = threading.Event(), threading.Event()
    calls = []

    async def brain(settings, goal, secret, cancel_event):
        calls.append(goal)
        entered.set()
        while not release.is_set() and not cancel_event.is_set():
            await asyncio.sleep(0.005)
        return {"answer": "Completed once"}

    host = make_host(brain)
    host.enable()
    target = host.capture()
    batch = host.preview([target])
    try:
        host.send(batch)
        assert entered.wait(3)
        assert host.send(batch)["batch_id"] == batch["batch_id"]
        assert len(calls) == 1
    finally:
        release.set()
    assert finished(host, batch)["status"] == "succeeded"
    host.restart()
    saved = host.service.handle("bulkTaskList", {})["batches"][0]
    assert saved["batch_id"] == batch["batch_id"] and saved["status"] == "succeeded"
    assert host.send(batch)["status"] == "succeeded"
    assert len(calls) == 1


def test_only_explicit_workspaces_are_edited_and_successful_undo_restores_bytes(make_host, tmp_path):
    host = make_host()
    host.enable()
    roots = [workspace(tmp_path, name) for name in ("first", "second", "unselected")]
    original = [(root / "note.txt").read_bytes() for root in roots]
    targets = [host.capture(name=f"Project {index}", workspace=str(root), workspace_edit=True, allow_edit=True)
               for index, root in enumerate(roots)]
    batch = host.preview([targets[0], targets[0], targets[1]], kind="workspace_edit", paths=["note.txt"],
                         oldString="old", newString="new", concurrency=2)
    assert batch["targets"] == targets[:2]
    assert all((root / "note.txt").read_bytes() == before for root, before in zip(roots, original))
    assert "-old" in batch["preview"]["items"][0]["files"][0]["diff"]
    host.send(batch)
    result = finished(host, batch)
    assert result["status"] == "succeeded"
    assert all(row["result"]["verified"] for row in result["operations"])
    assert [(root / "note.txt").read_bytes() for root in roots] == [original[0].replace(b"old", b"new"),
                                                                  original[1].replace(b"old", b"new"), original[2]]
    undo = host.service.handle("bulkTaskUndoPreview", {"batchId": batch["batch_id"]})
    assert undo["status"] == "prepared" and undo["targets"] == targets[:2]
    assert (roots[0] / "note.txt").read_bytes() == original[0].replace(b"old", b"new")
    host.send(undo)
    assert finished(host, undo)["status"] == "succeeded"
    assert [(root / "note.txt").read_bytes() for root in roots] == original
    assert host.calls == []


def test_stale_last_file_refuses_the_whole_selected_workspace_before_writing(make_host, tmp_path):
    host = make_host()
    host.enable()
    root = workspace(tmp_path, "project")
    (root / "second.txt").write_bytes(b"old\n")
    original = (root / "note.txt").read_bytes()
    target = host.capture(workspace=str(root), workspace_edit=True, allow_edit=True)
    batch = host.preview([target], kind="workspace_edit", paths=["note.txt", "second.txt"], oldString="old", newString="new")
    (root / "second.txt").write_bytes(b"owner's later change\n")
    host.send(batch)
    result = finished(host, batch)
    assert result["operations"][0]["status"] == "conflict"
    assert (root / "note.txt").read_bytes() == original
    assert (root / "second.txt").read_bytes() == b"owner's later change\n"
    with pytest.raises(ValueError, match="no fully completed"):
        host.service.handle("bulkTaskUndoPreview", {"batchId": batch["batch_id"]})


def test_undo_cannot_overwrite_an_owner_change_after_the_original_edit(make_host, tmp_path):
    host = make_host()
    host.enable()
    root = workspace(tmp_path, "project")
    target = host.capture(workspace=str(root), workspace_edit=True, allow_edit=True)
    batch = host.preview([target], kind="workspace_edit", paths=["note.txt"], oldString="old", newString="new")
    host.send(batch)
    assert finished(host, batch)["status"] == "succeeded"
    undo = host.service.handle("bulkTaskUndoPreview", {"batchId": batch["batch_id"]})
    (root / "note.txt").write_bytes(b"new owner-authored content\n")
    host.send(undo)
    result = finished(host, undo)
    assert result["operations"][0]["status"] == "conflict"
    assert (root / "note.txt").read_bytes() == b"new owner-authored content\n"


@pytest.mark.parametrize("revocation", ["disable", "workspace_edit", "remove"])
def test_revoking_permission_or_target_before_send_blocks_all_edits(make_host, tmp_path, revocation):
    host = make_host()
    host.enable()
    root = workspace(tmp_path, "project")
    original = (root / "note.txt").read_bytes()
    target = host.capture(workspace=str(root), workspace_edit=True, allow_edit=True)
    batch = host.preview([target], kind="workspace_edit", paths=["note.txt"], oldString="old", newString="new")
    if revocation == "disable":
        host.service.handle("bulkTaskSetEnabled", {"enabled": False})
    elif revocation == "workspace_edit":
        host.current.workspace_edit = False
    else:
        host.service.handle("bulkTaskRemove", {"targetId": target})
    with pytest.raises((PermissionError, ValueError)):
        host.send(batch)
    assert (root / "note.txt").read_bytes() == original
    assert all(row["status"] == "pending" for row in host.service.engine.get_batch(batch["batch_id"])["operations"])


def test_selected_read_context_is_revalidated_and_cannot_be_silently_replaced(make_host, tmp_path):
    host = make_host()
    host.enable()
    root = workspace(tmp_path, "project")
    target = host.capture(workspace=str(root))
    batch = host.preview([target], paths=["note.txt"])
    (root / "note.txt").write_bytes(b"different source after preview\n")
    host.send(batch)
    result = finished(host, batch)
    assert result["operations"][0]["status"] == "conflict"
    assert host.calls == []


def test_selected_read_context_reaches_only_the_captured_brain_as_untrusted_data(make_host, tmp_path):
    host = make_host()
    host.enable()
    root = workspace(tmp_path, "project")
    (root / "unselected.txt").write_text("must not be included", encoding="utf-8")
    target = host.capture(workspace=str(root))
    batch = host.preview([target], paths=["note.txt"], prompt="Review the selected text")
    host.send(batch)
    assert finished(host, batch)["status"] == "succeeded"
    goal = host.calls[0]["goal"]
    assert "UNTRUSTED DATA" in goal and "owner text" in goal
    assert "must not be included" not in goal


def test_cancellation_is_persisted_and_pending_brain_targets_never_start(make_host):
    entered = threading.Event()
    calls = []

    async def brain(settings, goal, secret, cancel_event):
        calls.append(settings.model)
        entered.set()
        while not cancel_event.is_set():
            await asyncio.sleep(0.005)
        raise OperationCancelled("Local request cancelled; remote termination is not confirmed")

    host = make_host(brain)
    host.enable()
    targets = [host.capture(name="First", model="first"), host.capture(name="Second", model="second")]
    batch = host.preview(targets, concurrency=1)
    host.send(batch)
    assert entered.wait(3)
    host.service.handle("bulkTaskCancel", {"batchId": batch["batch_id"]})
    result = finished(host, batch)
    assert result["status"] == "cancelled" and result["cancellation_requested"] is True
    assert [row["status"] for row in result["operations"]] == ["cancelled", "cancelled"]
    assert calls == ["first"]
    host.restart()
    restored = host.service.handle("bulkTaskStatus", {"batchId": batch["batch_id"]})
    assert restored["status"] == "cancelled" and restored["cancellation_requested"] is True
    assert host.send(batch)["status"] == "cancelled" and calls == ["first"]


def test_cancellation_does_not_relabel_a_returned_completed_brain_answer(make_host):
    entered = threading.Event()

    async def brain(settings, goal, secret, cancel_event):
        entered.set()
        while not cancel_event.is_set():
            await asyncio.sleep(0.005)
        return {"answer": "Already completed despite the cancellation request"}

    host = make_host(brain)
    host.enable()
    batch = host.preview([host.capture()])
    host.send(batch)
    assert entered.wait(3)
    host.service.handle("bulkTaskCancel", {"batchId": batch["batch_id"]})
    result = finished(host, batch)
    assert result["status"] == "succeeded" and result["cancellation_requested"] is True
    assert result["operations"][0]["result"]["answer"].startswith("Already completed")


@pytest.mark.parametrize("second_endpoint", ["http://127.0.0.1:8080/v1", "http://localhost:8080/v1"])
def test_profiles_on_the_same_endpoint_serialize_even_with_different_models(make_host, second_endpoint):
    entered, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    active, peak = 0, 0
    calls = []

    async def brain(settings, goal, secret, cancel_event):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append(settings.model)
        entered.set()
        try:
            while not release.is_set() and not cancel_event.is_set():
                await asyncio.sleep(0.005)
            return {"answer": settings.model}
        finally:
            with lock:
                active -= 1

    host = make_host(brain)
    host.enable()
    targets = [host.capture(name="First model", model="first"),
               host.capture(name="Second model", model="second", endpoint=second_endpoint)]
    batch = host.preview(targets, concurrency=2, canarySize=2)
    try:
        host.send(batch)
        assert entered.wait(3)
        wait_until(lambda: host.service.engine.get_batch(batch["batch_id"])["counts"].get("running") == 2)
        assert len(calls) == 1
    finally:
        release.set()
    assert finished(host, batch)["status"] == "succeeded"
    assert sorted(calls) == ["first", "second"] and peak == 1


def test_different_endpoints_can_run_with_bounded_parallelism(make_host):
    entered, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    active, peak = 0, 0

    async def brain(settings, goal, secret, cancel_event):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                entered.set()
        try:
            while not release.is_set() and not cancel_event.is_set():
                await asyncio.sleep(0.005)
            return {"answer": settings.model}
        finally:
            with lock:
                active -= 1

    host = make_host(brain)
    host.enable()
    targets = [host.capture(name="First"), host.capture(name="Second", endpoint="http://127.0.0.1:9090/v1")]
    batch = host.preview(targets, concurrency=2, canarySize=2)
    try:
        host.send(batch)
        assert entered.wait(3)
    finally:
        release.set()
    assert finished(host, batch)["status"] == "succeeded" and peak == 2


def test_captured_lan_endpoint_uses_its_saved_key_after_current_credential_rotation(make_host, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", "synthetic-original-secret")
    host = make_host()
    host.enable()
    target = host.capture(provider="star_server", server_endpoint="http://192.168.1.10:8080/v1", model="original")  # star:allow test address
    batch = host.preview([target])
    monkeypatch.setenv("STAR_SERVER_API_KEY", "synthetic-next-secret")
    host.current = replace(host.current, server_endpoint="http://192.168.1.11:8080/v1", model="next")  # star:allow test address
    host.send(batch)
    result = finished(host, batch)
    assert result["status"] == "succeeded"
    assert host.calls[0]["settings"].server_endpoint == "http://192.168.1.10:8080/v1"  # star:allow test address
    assert host.calls[0]["secret"] == "synthetic-original-secret"
    assert "synthetic-original-secret" not in json.dumps(result)
    assert "synthetic-next-secret" not in json.dumps(result)
    assert b"synthetic-original-secret" not in host.service.engine.path.read_bytes()


def test_capture_holds_configuration_lock_until_original_endpoint_and_key_are_bound(make_host, monkeypatch):
    configuration_lock = threading.RLock()
    snapshot_reached, release_snapshot = threading.Event(), threading.Event()
    mutation_attempted, mutation_finished = threading.Event(), threading.Event()
    credential = {"value": "synthetic-original-pair-key"}
    host = make_host(configuration_lock=configuration_lock)
    host.current = replace(host.current, provider="star_server", model="original",
                           server_endpoint="http://192.168.1.10:8080/v1")  # star:allow test address
    host.enable()

    def paused_connection(settings):
        # A real connection_for reads the current OS key after receiving Settings.
        # Pause precisely at that boundary to reproduce a settings/key race.
        snapshot_reached.set()
        assert release_snapshot.wait(3)
        return settings.server_endpoint, credential["value"]

    def mutate_current_configuration():
        mutation_attempted.set()
        with configuration_lock:
            host.current = replace(host.current, model="changed", server_endpoint="http://192.168.1.11:8080/v1")  # star:allow test address
            credential["value"] = "synthetic-next-pair-key"
            mutation_finished.set()

    monkeypatch.setattr(bulk_profiles, "connection_for", paused_connection)
    with ThreadPoolExecutor(max_workers=2) as workers:
        capture = workers.submit(host.service.handle, "bulkTaskCapture", {"name": "Original pair"})
        try:
            assert snapshot_reached.wait(3)
            mutation = workers.submit(mutate_current_configuration)
            assert mutation_attempted.wait(3)
            acquired = configuration_lock.acquire(blocking=False)
            if acquired:
                configuration_lock.release()
            assert acquired is False, "Capture released configuration ownership before reading its key"
            assert not mutation_finished.is_set()
        finally:
            release_snapshot.set()
        result = capture.result(timeout=3)
        mutation.result(timeout=3)
    profile = host.service.profiles.get(result["targets"][0]["id"])
    assert profile["settings"]["server_endpoint"] == "http://192.168.1.10:8080/v1"  # star:allow test address
    assert host.service.profiles.credential(profile) == "synthetic-original-pair-key"
    assert host.current.server_endpoint == "http://192.168.1.11:8080/v1"  # star:allow test address
    assert credential["value"] == "synthetic-next-pair-key"


def test_failed_coordinator_thread_start_does_not_leave_a_false_active_batch(make_host, monkeypatch):
    host = make_host()
    host.enable()
    batch = host.preview([host.capture()])

    def no_thread_capacity(self):
        raise RuntimeError("Synthetic thread capacity failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(threading.Thread, "start", no_thread_capacity)
        with pytest.raises(RuntimeError, match="thread capacity"):
            host.send(batch)
    assert host.service.engine.get_batch(batch["batch_id"])["status"] == "prepared"
    assert host.calls == []
    host.send(batch)
    assert finished(host, batch)["status"] == "succeeded"
    assert len(host.calls) == 1


def test_second_batch_is_not_dispatched_while_another_is_active(make_host):
    entered, release = threading.Event(), threading.Event()

    async def brain(settings, goal, secret, cancel_event):
        entered.set()
        while not release.is_set() and not cancel_event.is_set():
            await asyncio.sleep(0.005)
        return {"answer": "done"}

    host = make_host(brain)
    host.enable()
    target = host.capture()
    first = host.preview([target], key="first")
    second = host.preview([target], key="second", prompt="Another intent")
    try:
        host.send(first)
        assert entered.wait(3)
        with pytest.raises(ValueError, match="active bulk batch"):
            host.send(second)
        assert host.service.engine.get_batch(second["batch_id"])["status"] == "prepared"
    finally:
        release.set()
    assert finished(host, first)["status"] == "succeeded"


@pytest.mark.parametrize("stop", ["disable", "shutdown"])
def test_disable_and_shutdown_signal_active_work_and_keep_its_history(make_host, stop):
    entered = threading.Event()

    async def brain(settings, goal, secret, cancel_event):
        entered.set()
        while not cancel_event.is_set():
            await asyncio.sleep(0.005)
        raise OperationCancelled("Local cancellation acknowledged")

    host = make_host(brain)
    host.enable()
    batch = host.preview([host.capture()])
    host.send(batch)
    assert entered.wait(3)
    if stop == "disable":
        host.service.handle("bulkTaskSetEnabled", {"enabled": False})
        assert finished(host, batch)["status"] == "cancelled"
    else:
        host.service.shutdown(wait=True)
    host.restart()
    result = host.service.handle("bulkTaskStatus", {"batchId": batch["batch_id"]})
    assert result["status"] == "cancelled" and result["cancellation_requested"] is True


def test_unexpected_brain_provider_details_do_not_reach_status(make_host):
    async def brain(settings, goal, secret, cancel_event):
        raise RuntimeError("Synthetic provider body leaked secret-should-not-appear")

    host = make_host(brain)
    host.enable()
    batch = host.preview([host.capture()])
    host.send(batch)
    result = finished(host, batch)
    assert result["status"] == "failed"
    assert "secret-should-not-appear" not in json.dumps(result)
    assert result["operations"][0]["error"] == "Brain request failed; check the captured connection, model and context"


def test_live_edit_permission_revocation_stops_remaining_files_with_receipts(make_host, tmp_path, monkeypatch):
    from star.workspace import Workspace

    host = make_host()
    host.enable()
    root = workspace(tmp_path, "revocable")
    (root / "second.txt").write_text("old", encoding="utf-8")
    target = host.capture(workspace=str(root), workspace_edit=True, allow_edit=True)
    batch = host.preview([target], kind="workspace_edit", paths=["note.txt", "second.txt"],
                         oldString="old", newString="new")
    original = Workspace.call

    def revoke_after_first_write(workspace, name, arguments, **kwargs):
        result = original(workspace, name, arguments, **kwargs)
        if name == "workspace_write":
            host.current.workspace_edit = False
        return result

    monkeypatch.setattr(Workspace, "call", revoke_after_first_write)
    host.send(batch)
    result = finished(host, batch)
    assert result["status"] == "partial"
    operation = result["operations"][0]
    assert operation["status"] == "partial"
    assert [row["path"] for row in operation["result"]["files"]] == ["note.txt"]
    assert operation["result"]["pending"] == ["second.txt"]
    assert (root / "note.txt").read_bytes() == b"new\r\nowner text\n"
    assert (root / "second.txt").read_text(encoding="utf-8") == "old"
