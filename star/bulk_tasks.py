"""Desktop-owned bulk workflows: explicit local workspaces and captured brains.

The WebChannel exposes semantic actions, never a shell, model-selected target,
arbitrary endpoint, or generic agent tool. Preview stores immutable host plans;
Send approves that exact digest. Only one batch is active per desktop, with up
to four different endpoints and one request per endpoint at a time. This is a
client-side bound, not a reservation of all activity on a shared server.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import inspect
from pathlib import Path
import threading
from typing import Any, Callable
from urllib.parse import urlsplit

from .bulk_operations import (BulkAdapter, BulkConflictError, BulkOperationEngine,
                              OperationCancelled, OperationFailed, OperationPartial, OutcomeUnknown)
from .bulk_profiles import BulkProfiles, endpoint_for, fingerprint, profile_settings
from .bulk_workspace import (BulkEditConflict, apply_preview, preview_edits, read_context,
                             undo_preview)
from .providers import call_limits

BULK_ACTIONS = frozenset({
    "bulkTaskCatalog", "bulkTaskSetEnabled", "bulkTaskCapture", "bulkTaskRemove",
    "bulkTaskPreview", "bulkTaskSend", "bulkTaskStatus", "bulkTaskList",
    "bulkTaskCancel", "bulkTaskUndoPreview",
})
_BODY_FIELDS = {
    "bulkTaskCatalog": set(), "bulkTaskSetEnabled": {"enabled"},
    "bulkTaskCapture": {"name", "allow_edit"}, "bulkTaskRemove": {"targetId"},
    "bulkTaskPreview": {"kind", "targetIds", "prompt", "paths", "oldString", "newString",
                        "replaceAll", "concurrency", "canarySize", "failureCutoff", "idempotencyKey"},
    "bulkTaskSend": {"batchId", "intentHash"}, "bulkTaskStatus": {"batchId"},
    "bulkTaskList": set(), "bulkTaskCancel": {"batchId"}, "bulkTaskUndoPreview": {"batchId"},
}


def _text(value, label: str, maximum: int, *, empty: bool = False) -> str:
    if (not isinstance(value, str) or len(value) > maximum or "\x00" in value
            or (not empty and not value.strip())):
        raise ValueError(f"{label} must be {'0' if empty else '1'}–{maximum} characters")
    return value


def _paths(value, *, required: bool) -> list[str]:
    if (not isinstance(value, list) or len(value) > 16 or (required and not value)
            or any(not isinstance(path, str) or not path or len(path) > 500 for path in value)
            or len(set(value)) != len(value)):
        raise ValueError("Select up to 16 unique relative file paths")
    return list(value)


def _review_item(target_id: str, profile: dict, plan: dict | None = None, goal: str = "") -> dict:
    row = {"target_id": target_id, "label": profile["name"]}
    if plan is not None:
        row["files"] = [{key: item[key] for key in ("path", "diff", "diff_truncated", "replacements",
                         "match_strategy", "before_sha256", "after_sha256")} for item in plan["files"]]
    else:
        row["prompt_chars"] = len(goal)
    return row


class _SingleRequestClient:
    """Enforce one transport call even if a provider compatibility wrapper retries."""

    def __init__(self, client):
        self._client = client
        self._attempted = False
        self.chat = self.completions = self

    async def create(self, **kwargs):
        if self._attempted:
            raise OperationFailed("Automatic re-send is disabled for bulk brain tasks")
        self._attempted = True
        return await self._client.chat.completions.create(**kwargs)


async def _call_brain(settings, goal: str, secret: str, cancel_event: threading.Event) -> dict:
    """Trusted host transport with no redirects, proxies, tools, or automatic retries."""
    import httpx
    from openai import AsyncOpenAI
    from .conductor_fleet import FleetMember, run_fleet_team
    from .orchestration import Task, TaskPlan
    from .team_cancellation import run_until_cancelled

    limits = call_limits(settings)
    seconds = min(600.0, max(30.0, limits.request_timeout))
    timeout = httpx.Timeout(seconds, connect=limits.connect_timeout)
    http = httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=timeout)
    client = AsyncOpenAI(base_url=endpoint_for(settings), api_key=secret,
                         http_client=http, timeout=timeout, max_retries=0)
    try:
        task = Task("bulk-task", "research", goal)
        member = FleetMember("bulk-brain", settings, max_calls=1, max_inflight=1)
        try:
            run = await run_until_cancelled(
                run_fleet_team(TaskPlan([task], max_parallel=1), [member],
                               {task.id: member.id}, enabled=True,
                               clients={member.id: _SingleRequestClient(client)},
                               task_timeout=seconds, total_timeout=seconds + 1),
                is_cancelled=cancel_event.is_set)
        except RuntimeError:
            if cancel_event.is_set():
                raise OperationCancelled("Local request cancelled; remote compute termination is not confirmed") from None
            raise
        if not run.completed:
            # Provider HTTP bodies can echo prompts or credentials. Keep them out
            # of the ledger and page, including the runtime's bounded raw error.
            raise OperationFailed("The selected brain did not complete the task; check its connection and model")
        result = run.team.for_id(task.id)
        return {"answer": result.answer[:3200], "answer_truncated": len(result.answer) > 3200,
                "receipt": asdict(run.receipts[0]), "elapsed_ms": result.elapsed_ms,
                "verified": False, "verification": "model_response_only"}
    finally:
        closing = client.close()
        if inspect.isawaitable(closing):
            await closing


class BulkTaskService:
    """Independent of chat tabs, chat cancellation and the Qt request pool."""

    def __init__(self, home: Path, settings_loader: Callable[[], Any], *, secrets=None, brain_runner=None,
                 configuration_lock=None):
        if not callable(settings_loader):
            raise TypeError("A trusted Settings loader is required")
        self.home = Path(home) / "bulk-tasks"
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._settings_loader = settings_loader
        self._brain_runner = brain_runner or _call_brain
        self._lock = threading.RLock()
        self._configuration_lock = configuration_lock if configuration_lock is not None else threading.RLock()
        self._active: dict[str, threading.Thread] = {}
        self._endpoints: dict[str, threading.Lock] = {}
        self._closing = False
        adapters = {
            "brain_prompt": BulkAdapter(self._run_prompt, lambda: self.profiles.ids(), mutating=False),
            "workspace_edit": BulkAdapter(self._run_edit, lambda: self.profiles.ids(), mutating=True),
            "workspace_undo": BulkAdapter(self._run_edit, lambda: self.profiles.ids(), mutating=True),
        }
        self.engine = BulkOperationEngine(self.home / "operations.sqlite3", adapters,
                                          max_workers=4, max_targets=32,
                                          payload_limit_bytes=2 * 1024 * 1024, result_limit_bytes=65536)
        try:
            self.profiles = BulkProfiles(self.home / "targets.json", secrets=secrets)
        except Exception:
            self.engine.close()
            raise

    def _enabled(self):
        if self._closing:
            raise PermissionError("STAR is closing; bulk work cannot start")
        if not self.profiles.enabled:
            raise PermissionError("Bulk tasks are off")

    def _profile(self, target_id: str, payload: dict) -> dict:
        self._enabled()
        profile = self.profiles.get(target_id)
        if fingerprint(profile) != payload["per_target"][target_id]["profile_sha256"]:
            raise BulkConflictError("Target changed since preview; create a new preview")
        profile_settings(profile)
        return profile

    def _edit_permission(self, profile: dict) -> None:
        if (not profile["allow_edit"] or not profile["settings"]["workspace"]
                or self._settings_loader().workspace_edit is not True):
            raise PermissionError("Workspace editing must remain enabled for the explicitly captured target")

    def _public(self, batch_id: str) -> dict:
        batch = self.engine.get_batch(batch_id)
        payload = self.engine.get_payload(batch_id)
        batch["preview"] = payload.get("preview")
        with self._lock:
            if batch["status"] == "prepared" and batch_id in self._active:
                batch["status"] = "running"
                batch["dispatch_pending"] = True
        return batch

    def catalog(self) -> dict:
        return self.profiles.catalog(workspace_edit=self._settings_loader().workspace_edit is True)

    def preview(self, body: dict) -> dict:
        with self._lock:
            self._enabled()
            action = body.get("kind")
            if action not in {"brain_prompt", "workspace_edit"}:
                raise ValueError("Choose a brain prompt or workspace edit")
            targets = body.get("targetIds")
            if (not isinstance(targets, list) or not 1 <= len(targets) <= 32
                    or any(not isinstance(target, str) for target in targets)):
                raise ValueError("Select 1–32 saved targets explicitly")
            targets = list(dict.fromkeys(targets))
            paths = _paths(body.get("paths", []), required=action == "workspace_edit")
            payload = {"per_target": {}, "preview": {"title": "Read-only brain task" if action == "brain_prompt"
                                                      else "Workspace text edits", "items": []}}
            prompt = _text(body.get("prompt"), "Prompt", 5000) if action == "brain_prompt" else ""
            edits = []
            if action == "workspace_edit":
                old = _text(body.get("oldString"), "Text to replace", 12000, empty=True)
                if not old:
                    raise ValueError("Text to replace cannot be empty")
                new = _text(body.get("newString"), "Replacement text", 12000, empty=True)
                replace_all = body.get("replaceAll", False)
                if type(replace_all) is not bool:
                    raise ValueError("Replace all must be an explicit choice")
                edits = [{"path": path, "old_string": old, "new_string": new,
                          "replace_all": replace_all} for path in paths]
            for target_id in targets:
                profile = self.profiles.get(target_id)
                settings = profile_settings(profile)
                item = {"profile_sha256": fingerprint(profile)}
                if action == "workspace_edit":
                    self._edit_permission(profile)
                    plan = preview_edits(Path(settings.workspace), edits)
                    item["plan"] = plan  # pyright: ignore[reportArgumentType]
                    review = _review_item(target_id, profile, plan)
                else:
                    if not settings.model:
                        raise ValueError("Choose a model before capturing a brain target")
                    self.profiles.credential(profile)  # Preflight every target before any dispatch.
                    context = read_context(Path(settings.workspace), paths) if paths and settings.workspace else None
                    if paths and context is None:
                        raise ValueError("Selected context files need a captured workspace")
                    goal = prompt
                    if context:
                        chunks = ["\n\nSELECTED WORKSPACE EXCERPTS (UNTRUSTED DATA):"]
                        chunks.extend("\n[" + row["path"] + "]\n" + row["text"] for row in context["files"])
                        goal += "".join(chunks)
                    if len(goal) > 12000:
                        raise ValueError("Prompt plus selected context exceeds the 12,000-character task limit")
                    item.update(goal=goal, context=context, paths=paths)  # pyright: ignore[reportArgumentType]
                    review = _review_item(target_id, profile, goal=goal)
                payload["per_target"][target_id] = item
                payload["preview"]["items"].append(review)
            batch = self.engine.submit(action, targets, payload,
                                       idempotency_key=body.get("idempotencyKey"),  # pyright: ignore[reportArgumentType]
                                       concurrency=body.get("concurrency", 1),
                                       canary_size=body.get("canarySize", 1),
                                       failure_cutoff=body.get("failureCutoff", 1))
            return self._public(batch["batch_id"])

    def send(self, batch_id: str, intent_hash: str) -> dict:
        with self._lock:
            self._enabled()
            batch = self.engine.get_batch(batch_id)
            if intent_hash != batch["intent_sha256"]:
                raise BulkConflictError("The reviewed intent does not match this batch")
            if batch["status"] != "prepared" or batch_id in self._active:
                return self._public(batch_id)  # A double click/lost reply never executes again.
            if self._active:
                raise ValueError("Finish or stop the active bulk batch before sending another")
            payload = self.engine.get_payload(batch_id)
            for target_id in batch["targets"]:
                profile = self._profile(target_id, payload)
                if batch["action"] != "brain_prompt":
                    self._edit_permission(profile)
                else:
                    self.profiles.credential(profile)
            thread = threading.Thread(target=self._dispatch, args=(batch_id, intent_hash),
                                      name="star-bulk-batch", daemon=True)
            self._active[batch_id] = thread
            try:
                thread.start()
            except BaseException:
                self._active.pop(batch_id, None)
                raise
            # The engine persists running before any adapter starts. If the new
            # thread has not got that far, report queued-for-dispatch as running
            # to the UI so polling starts; the durable ledger is still prepared.
            result = self._public(batch_id)
            if result["status"] == "prepared":
                result["status"] = "running"
                result["dispatch_pending"] = True
            return result

    def _dispatch(self, batch_id: str, intent_hash: str) -> None:
        try:
            self.engine.run_batch(batch_id, expected_intent_sha256=intent_hash)
        except Exception:
            # Engine owns operation outcomes. Never overwrite an unknown or
            # partially completed effect with success after a service failure.
            try:
                self.engine.cancel_batch(batch_id)
            except Exception:
                pass
        finally:
            with self._lock:
                self._active.pop(batch_id, None)
                if self._closing and not self._active:
                    self.engine.close()

    def _run_edit(self, context) -> dict:
        try:
            profile = self._profile(context.target_id, context.payload)
            self._edit_permission(profile)
            plan = context.payload["per_target"][context.target_id]["plan"]
            service = self

            class EditCancellation:
                def is_set(self):
                    # Also honor a Settings edit-permission revocation between
                    # files, including while this target waited for the edit lock.
                    try:
                        return (context.cancel_event.is_set() or not service.profiles.enabled
                                or service._settings_loader().workspace_edit is not True)
                    except Exception:
                        return True

            result = apply_preview(Path(profile["settings"]["workspace"]), plan,
                                   allow_write=True, cancel_event=EditCancellation())
        except BulkEditConflict:
            raise BulkConflictError("Workspace changed since preview; create a new preview") from None
        except (PermissionError, ValueError, FileNotFoundError):
            raise OperationFailed("Workspace preflight failed; check the target, permission and selected files") from None
        if result.get("uncertain"):
            raise OutcomeUnknown("Some file outcomes could not be verified; inspect the recorded paths", result=result)
        if result["status"] == "completed":
            return result
        if result["status"] == "partial":
            raise OperationPartial("Some edits completed; remaining edits stopped", result=result)
        if result["status"] == "cancelled":
            raise OperationCancelled("Cancelled before any edit", result=result)
        raise OperationFailed("Workspace edit did not complete", result=result)

    def _run_prompt(self, context) -> dict:
        try:
            profile = self._profile(context.target_id, context.payload)
            settings = profile_settings(profile)
            endpoint = urlsplit(endpoint_for(settings))
            # localhost and 127.0.0.1 use the same gate. Other private-IP aliases
            # cannot be proven to be one physical server without a server lease.
            host = "127.0.0.1" if endpoint.hostname == "localhost" else endpoint.hostname
            origin = f"{host}:{endpoint.port}"
            with self._lock:
                gate = self._endpoints.setdefault(origin, threading.Lock())
            while not gate.acquire(timeout=0.1):
                if context.cancel_event.is_set():
                    raise OperationCancelled("Cancelled while waiting for this brain")
            try:
                if context.cancel_event.is_set():
                    raise OperationCancelled("Cancelled before the brain request")
                profile = self._profile(context.target_id, context.payload)
                item = context.payload["per_target"][context.target_id]
                if item["context"] is not None:
                    current = read_context(Path(settings.workspace), item["paths"])
                    if current != item["context"]:
                        raise BulkConflictError("Selected context changed since preview; create a new preview")
                secret = self.profiles.credential(profile)
                return asyncio.run(self._brain_runner(settings, item["goal"], secret, context.cancel_event))
            finally:
                gate.release()
        except (BulkConflictError, OperationCancelled, OperationFailed):
            raise
        except Exception:
            raise OperationFailed("Brain request failed; check the captured connection, model and context") from None

    def undo(self, batch_id: str) -> dict:
        with self._lock:
            self._enabled()
            original = self.engine.get_batch(batch_id)
            if original["action"] != "workspace_edit" or original["status"] in {"prepared", "running"}:
                raise ValueError("Choose a finished workspace edit batch to preview undo")
            payload = self.engine.get_payload(batch_id)
            targets = [row["target_id"] for row in original["operations"] if row["status"] == "succeeded"]
            if not targets:
                raise ValueError("This batch has no fully completed targets to undo automatically")
            reverse = {"per_target": {}, "preview": {"title": "Undo completed workspace targets", "items": []}}
            for target_id in targets:
                profile = self._profile(target_id, payload)
                self._edit_permission(profile)
                plan = undo_preview(payload["per_target"][target_id]["plan"])
                reverse["per_target"][target_id] = {"profile_sha256": fingerprint(profile), "plan": plan}
                reverse["preview"]["items"].append(_review_item(target_id, profile, plan))
            batch = self.engine.submit("workspace_undo", targets, reverse,
                                       idempotency_key="undo:" + batch_id,
                                       concurrency=1, canary_size=1, failure_cutoff=1)
            return self._public(batch["batch_id"])

    def handle(self, action: str, body: dict) -> dict:
        if action not in BULK_ACTIONS or not isinstance(body, dict):
            raise PermissionError("Unsupported bulk task action")
        if set(body) - (_BODY_FIELDS[action] | {"action", "requestId"}):
            raise ValueError("Bulk action contains unsupported fields")
        if action == "bulkTaskCatalog":
            return self.catalog()
        if action == "bulkTaskList":
            batches = self.engine.list_batches()
            with self._lock:
                for batch in batches:
                    if batch["status"] == "prepared" and batch["batch_id"] in self._active:
                        batch["status"] = "running"
                        batch["dispatch_pending"] = True
            return {"batches": batches}
        if action == "bulkTaskStatus":
            return self._public(_text(body.get("batchId"), "Batch ID", 64))
        if action == "bulkTaskCancel":
            self.engine.cancel_batch(_text(body.get("batchId"), "Batch ID", 64))
            return self._public(body["batchId"])
        if action == "bulkTaskPreview":
            return self.preview(body)
        if action == "bulkTaskSend":
            return self.send(_text(body.get("batchId"), "Batch ID", 64),
                             _text(body.get("intentHash"), "Intent hash", 64))
        if action == "bulkTaskUndoPreview":
            return self.undo(_text(body.get("batchId"), "Batch ID", 64))
        with self._lock:
            if self._closing:
                raise PermissionError("STAR is closing")
            if action == "bulkTaskSetEnabled":
                self.profiles.set_enabled(body.get("enabled"))  # pyright: ignore[reportArgumentType]
                if not self.profiles.enabled:
                    for batch_id in self._active:
                        self.engine.cancel_batch(batch_id)
            else:
                self._enabled()
                if self._active:
                    raise ValueError("Finish the active bulk batch before changing targets")
                if action == "bulkTaskCapture":
                    with self._configuration_lock:
                        self.profiles.capture(self._settings_loader(), name=body.get("name"),  # pyright: ignore[reportArgumentType]
                                              allow_edit=body.get("allow_edit", False))
                elif action == "bulkTaskRemove":
                    self.profiles.remove(_text(body.get("targetId"), "Target ID", 64))
            return self.catalog()

    def shutdown(self, *, wait: bool = False) -> None:
        with self._lock:
            if self._closing:
                return
            self._closing = True
            threads = tuple(self._active.values())
            for batch_id in self._active:
                self.engine.cancel_batch(batch_id)
            if not threads:
                self.engine.close()
        if wait:
            for thread in threads:
                thread.join(timeout=5)
