"""Bulk editing uses disposable workspaces and injected failures, never live projects."""
from __future__ import annotations

import copy
from hashlib import sha256
import json
import os
import threading

import pytest

from star import bulk_workspace as bulk
from star.workspace import Workspace


def edit(path, old="old", new="new", **extra):
    return {"path": path, "old_string": old, "new_string": new, **extra}


def two_files(tmp_path):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_bytes(b"old\n")
    return bulk.preview_edits(tmp_path, [edit("a.txt"), edit("b.txt")])


def test_preview_is_read_only_json_and_apply_undo_preserve_exact_bytes(tmp_path):
    path = tmp_path / "notes.txt"
    original = "first\r\nold\r\n\u96ea without final newline".encode("utf-8")
    path.write_bytes(original)
    plan = bulk.preview_edits(tmp_path, [edit("notes.txt", "first\nold\n", "first\nnew\n")])
    assert path.read_bytes() == original
    assert plan == json.loads(json.dumps(plan))
    item = plan["files"][0]
    assert item["match_strategy"] == "line_endings"
    assert item["before_sha256"] == sha256(original).hexdigest()
    assert "-old" in item["diff"] and "+new" in item["diff"]
    assert plan["total_content_bytes"] == len(original) + len(item["after"].encode("utf-8"))
    with pytest.raises(PermissionError):
        bulk.apply_preview(tmp_path, plan)
    with pytest.raises(PermissionError):
        bulk.apply_preview(tmp_path, plan, allow_write=1)
    result = bulk.apply_preview(tmp_path, plan, allow_write=True)
    assert result["status"] == "completed" and result["verified"] is True
    assert result["files"][0]["after_sha256"] == sha256(path.read_bytes()).hexdigest()
    assert path.read_bytes() == original.replace(b"old", b"new")
    reverse = bulk.undo_preview(plan)
    assert reverse["files"][0]["before_sha256"] == item["after_sha256"]
    assert reverse["direction"] == "undo"
    assert bulk.apply_preview(tmp_path, reverse, allow_write=True)["status"] == "completed"
    assert path.read_bytes() == original
    assert bulk.undo_preview(reverse) == plan


@pytest.mark.parametrize("outcome", ["completed", "uncertain"])
def test_long_unicode_paths_keep_structured_receipts_within_history_budget(tmp_path, outcome):
    # Exercise result serialization without depending on Windows long-path
    # configuration. Each component fits a 255-byte filename and the 499-code
    # point relative paths approach the supported 500-character input bound.
    baseline = two_files(tmp_path)
    component = "\U0001f4be" * 60
    paths = ["/".join([component] * 8 + ["\U0001f4be" * 5 + f"{index:02}.txt"])
             for index in range(bulk.MAX_FILES)]
    assert all(len(path) == 499 for path in paths)
    assert all(len(part.encode("utf-8")) <= 255 for path in paths for part in path.split("/"))
    plan = bulk._validated_plan(bulk._make_plan(
        baseline["root"], baseline["root_identity"],
        [bulk._file_plan(path, "old", "new", 1, "exact") for path in paths]))
    receipts = [bulk._receipt(item) for item in plan["files"]]
    if outcome == "completed":
        result = bulk._result(plan, receipts, [])
    else:
        item = plan["files"][-1]
        result = bulk._result(
            plan, receipts[:-1], [],
            error=bulk._error(bulk.BulkEditVerificationError()), failed_path=item["path"],
            uncertain=[{"path": item["path"], "expected_after_sha256": item["after_sha256"],
                        "observed_sha256": "0" * 64}])
    # The durable engine writes compact, unescaped UTF-8 JSON. The old 16 KiB
    # cap discarded these structured file outcomes in favor of a text preview.
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True,
                         allow_nan=False, separators=(",", ":")).encode("utf-8")
    assert 16_384 < len(encoded) <= 65_536
    restored = json.loads(encoded)
    assert restored == result
    assert [item["path"] for item in restored["files"] + restored["uncertain"]] == paths


def test_replace_all_and_indentation_use_existing_matcher(tmp_path):
    (tmp_path / "repeat.txt").write_bytes(b"old old old\n")
    (tmp_path / "indented.txt").write_bytes(b"  alpha\n  beta\n")
    plan = bulk.preview_edits(tmp_path, [edit("repeat.txt", replace_all=True),
                                         edit("indented.txt", "alpha\nbeta", "alpha\ngamma")])
    assert plan["files"][0]["replacements"] == 3
    assert plan["files"][1]["match_strategy"] == "whitespace"
    bulk.apply_preview(tmp_path, plan, allow_write=True)
    assert (tmp_path / "repeat.txt").read_bytes() == b"new new new\n"
    assert (tmp_path / "indented.txt").read_bytes() == b"  alpha\n  gamma\n"


@pytest.mark.parametrize("invalid", [
    [], {}, [None], [{"path": "a.txt", "old_string": "old"}],
    [edit("a.txt", extra="x")], [edit("a.txt", replace_all=1)], [edit("a.txt", old=1)],
    [edit("a.txt", new="bad\x00text")], [edit("a.txt")] * 17,
])
def test_edit_schema_is_strict(tmp_path, invalid):
    (tmp_path / "a.txt").write_bytes(b"old")
    with pytest.raises((ValueError, TypeError)):
        bulk.preview_edits(tmp_path, invalid)
    assert (tmp_path / "a.txt").read_bytes() == b"old"


@pytest.mark.parametrize("path", [
    ".env", ".env.local", ".git/config", ".github/workflows/check.yml", "private.key", "private.pem",
    ".env.", "notes.txt:stream", "NUL.txt", "C:notes.txt", "../outside.txt", "./notes.txt",
    "sub/../notes.txt", "sub//notes.txt", "sub\\notes.txt", "/absolute.txt",
])
def test_protected_or_ambiguous_paths_are_refused(tmp_path, path):
    (tmp_path / "notes.txt").write_bytes(b"old")
    (tmp_path / ".env").write_bytes(b"old")
    (tmp_path / "private.key").write_bytes(b"old")
    (tmp_path / "private.pem").write_bytes(b"old")
    with pytest.raises((PermissionError, ValueError)):
        bulk.preview_edits(tmp_path, [edit(path)])
    assert (tmp_path / ".env").read_bytes() == b"old"


def test_duplicate_files_are_refused_before_writing(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"old")
    with pytest.raises(ValueError, match="once"):
        bulk.preview_edits(tmp_path, [edit("a.txt"), edit("a.txt")])


@pytest.mark.parametrize("kind", ["file_link", "directory_link", "hardlink"])
def test_aliases_are_refused_even_inside_workspace(tmp_path, kind):
    folder = tmp_path / "real"
    folder.mkdir()
    (folder / "a.txt").write_bytes(b"old")
    try:
        if kind == "file_link":
            os.symlink(folder / "a.txt", tmp_path / "alias.txt")
            path = "alias.txt"
        elif kind == "directory_link":
            os.symlink(folder, tmp_path / "alias", target_is_directory=True)
            path = "alias/a.txt"
        else:
            os.link(folder / "a.txt", tmp_path / "alias.txt")
            path = "real/a.txt"  # The original hardlinked name is refused too.
    except (OSError, NotImplementedError):
        pytest.skip("This environment cannot create the required filesystem alias")
    with pytest.raises(PermissionError):
        bulk.preview_edits(tmp_path, [edit(path)])
    assert (folder / "a.txt").read_bytes() == b"old"


@pytest.mark.parametrize("data", [b"old\x00binary", b"old\xff", b"x" * (bulk.MAX_FILE_BYTES + 1)],
                         ids=["nul", "bad-utf8", "oversize"])
def test_nontext_and_large_files_are_refused(tmp_path, data):
    (tmp_path / "a.txt").write_bytes(data)
    with pytest.raises(ValueError):
        bulk.preview_edits(tmp_path, [edit("a.txt")])


def test_missing_file_or_directory_is_not_created_or_replaced(tmp_path):
    (tmp_path / "folder").mkdir()
    with pytest.raises(FileNotFoundError):
        bulk.preview_edits(tmp_path, [edit("missing.txt")])
    with pytest.raises(PermissionError):
        bulk.preview_edits(tmp_path, [edit("folder")])
    assert not (tmp_path / "missing.txt").exists()
    assert (tmp_path / "folder").is_dir()


def test_combined_before_after_budget_is_enforced(tmp_path):
    data = b"old\n" + b"x" * 199_996
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_bytes(data)
    with pytest.raises(ValueError, match="combined"):
        bulk.preview_edits(tmp_path, [edit(name) for name in ("a.txt", "b.txt", "c.txt")])
    assert (tmp_path / "a.txt").read_bytes() == data


def test_diff_is_bounded_and_truncation_explicit(tmp_path):
    before = "".join(f"old line {i}\n" for i in range(300))
    (tmp_path / "a.txt").write_text(before, encoding="utf-8", newline="")
    plan = bulk.preview_edits(tmp_path, [edit("a.txt", before, before.replace("old", "new"))])
    item = plan["files"][0]
    assert len(item["diff"]) <= bulk.MAX_DIFF_CHARS
    assert item["diff_truncated"] is True
    assert item["after"] == before.replace("old", "new")


def test_stale_last_file_prevents_all_writes(tmp_path):
    plan = two_files(tmp_path)
    (tmp_path / "b.txt").write_bytes(b"owner change\n")
    with pytest.raises(bulk.BulkEditConflict):
        bulk.apply_preview(tmp_path, plan, allow_write=True)
    assert (tmp_path / "a.txt").read_bytes() == b"old\n"
    assert (tmp_path / "b.txt").read_bytes() == b"owner change\n"


def test_undo_refuses_owner_changes_in_any_file_before_writing(tmp_path):
    plan = two_files(tmp_path)
    bulk.apply_preview(tmp_path, plan, allow_write=True)
    (tmp_path / "b.txt").write_bytes(b"new owner text\n")
    with pytest.raises(bulk.BulkEditConflict):
        bulk.apply_preview(tmp_path, bulk.undo_preview(plan), allow_write=True)
    assert (tmp_path / "a.txt").read_bytes() == b"new\n"
    assert (tmp_path / "b.txt").read_bytes() == b"new owner text\n"


def test_replaced_workspace_identity_is_refused(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    plan = two_files(root)
    root.rename(tmp_path / "moved")
    root.mkdir()
    (root / "a.txt").write_bytes(b"old\n")
    (root / "b.txt").write_bytes(b"old\n")
    with pytest.raises(bulk.BulkEditConflict, match="identity"):
        bulk.apply_preview(root, plan, allow_write=True)
    assert (root / "a.txt").read_bytes() == b"old\n"
    assert (tmp_path / "moved" / "a.txt").read_bytes() == b"old\n"


@pytest.mark.parametrize("field,value", [("after", "unreviewed"), ("after_sha256", "0" * 64),
                                          ("diff", "misleading"), ("before_bytes", True),
                                          ("replacements", True), ("match_strategy", []), ("extra", "unknown")])
def test_tampered_file_plan_is_refused(tmp_path, field, value):
    plan = two_files(tmp_path)
    plan["files"][1][field] = value
    with pytest.raises(ValueError):
        bulk.apply_preview(tmp_path, plan, allow_write=True)
    assert (tmp_path / "a.txt").read_bytes() == b"old\n"


@pytest.mark.parametrize("field,value", [("file_count", True), ("total_content_bytes", 1),
                                          ("version", True), ("direction", []),
                                          ("root_identity", {"device": 0, "inode": True}),
                                          ("unknown", "extra")])
def test_tampered_plan_metadata_is_refused(tmp_path, field, value):
    plan = two_files(tmp_path)
    plan[field] = value
    with pytest.raises(ValueError):
        bulk.apply_preview(tmp_path, plan, allow_write=True)
    assert (tmp_path / "a.txt").read_bytes() == b"old\n"


def test_cancel_before_first_write_reports_untouched_files(tmp_path):
    plan = two_files(tmp_path)
    stop = threading.Event()
    stop.set()
    result = bulk.apply_preview(tmp_path, plan, allow_write=True, cancel_event=stop)
    assert result["status"] == "cancelled" and result["cancel_requested"]
    assert result["files"] == [] and result["pending"] == ["a.txt", "b.txt"]
    assert result["verified"] is False
    assert (tmp_path / "a.txt").read_bytes() == b"old\n"


def test_cancel_between_files_keeps_verified_receipts(tmp_path, monkeypatch):
    plan = two_files(tmp_path)
    stop = threading.Event()
    original = Workspace.call

    def call(self, name, args, **kwargs):
        result = original(self, name, args, **kwargs)
        stop.set()
        return result

    monkeypatch.setattr(Workspace, "call", call)
    result = bulk.apply_preview(tmp_path, plan, allow_write=True, cancel_event=stop)
    assert result["status"] == "partial" and result["cancel_requested"]
    assert result["applied_count"] == 1 and result["files"][0]["verified"]
    assert result["pending"] == ["b.txt"]
    assert (tmp_path / "a.txt").read_bytes() == b"new\n"
    assert (tmp_path / "b.txt").read_bytes() == b"old\n"


def test_failure_before_second_write_never_claims_batch_success(tmp_path, monkeypatch):
    plan = two_files(tmp_path)
    original = Workspace.call

    def call(self, name, args, **kwargs):
        if args["path"] == "b.txt":
            raise OSError("private exception detail must not be returned")
        return original(self, name, args, **kwargs)

    monkeypatch.setattr(Workspace, "call", call)
    result = bulk.apply_preview(tmp_path, plan, allow_write=True)
    assert result["status"] == "partial" and not result["verified"]
    assert result["applied_count"] == 1 and result["pending"] == ["b.txt"]
    assert result["error"]["type"] == "OSError"
    assert "private exception" not in json.dumps(result)
    assert (tmp_path / "a.txt").read_bytes() == b"new\n"
    assert (tmp_path / "b.txt").read_bytes() == b"old\n"


def test_exception_after_write_still_records_observed_effect(tmp_path, monkeypatch):
    plan = two_files(tmp_path)
    original = Workspace.call

    def call(self, name, args, **kwargs):
        original(self, name, args, **kwargs)
        raise RuntimeError("injected post-write hook failure")

    monkeypatch.setattr(Workspace, "call", call)
    result = bulk.apply_preview(tmp_path, plan, allow_write=True)
    assert result["status"] == "partial" and not result["verified"]
    assert result["files"][0]["after_sha256"] == sha256((tmp_path / "a.txt").read_bytes()).hexdigest()
    assert result["pending"] == ["b.txt"] and result["uncertain"] == []


def test_wrong_write_bytes_are_uncertain_and_stop_later_files(tmp_path, monkeypatch):
    plan = two_files(tmp_path)
    original = Workspace.call

    def call(self, name, args, **kwargs):
        return original(self, name, {**args, "content": "different bytes"}, **kwargs)

    monkeypatch.setattr(Workspace, "call", call)
    result = bulk.apply_preview(tmp_path, plan, allow_write=True)
    assert result["status"] == "partial" and result["files"] == []
    assert result["uncertain"] == [{"path": "a.txt", "expected_after_sha256": plan["files"][0]["after_sha256"],
                                       "observed_sha256": sha256(b"different bytes").hexdigest()}]
    assert result["pending"] == ["b.txt"]
    assert (tmp_path / "b.txt").read_bytes() == b"old\n"


def test_each_file_is_rechecked_after_other_files_write(tmp_path, monkeypatch):
    plan = two_files(tmp_path)
    original = Workspace.call

    def call(self, name, args, **kwargs):
        result = original(self, name, args, **kwargs)
        (tmp_path / "b.txt").write_bytes(b"concurrent owner edit")
        return result

    monkeypatch.setattr(Workspace, "call", call)
    result = bulk.apply_preview(tmp_path, plan, allow_write=True)
    assert result["status"] == "partial" and result["error"]["type"] == "BulkEditConflict"
    assert result["applied_count"] == 1 and result["pending"] == ["b.txt"]
    assert (tmp_path / "b.txt").read_bytes() == b"concurrent owner edit"


def test_caller_cannot_change_plan_mid_apply(tmp_path, monkeypatch):
    plan = two_files(tmp_path)
    original_plan = copy.deepcopy(plan)
    original = Workspace.call

    def call(self, name, args, **kwargs):
        plan["files"][1]["after"] = "mutated caller object"
        return original(self, name, args, **kwargs)

    monkeypatch.setattr(Workspace, "call", call)
    result = bulk.apply_preview(tmp_path, plan, allow_write=True)
    assert result["status"] == "completed"
    assert (tmp_path / "b.txt").read_bytes() == original_plan["files"][1]["after"].encode("utf-8")


def test_reverse_plan_has_no_filesystem_side_effect(tmp_path):
    plan = two_files(tmp_path)
    original = copy.deepcopy(plan)
    (tmp_path / "a.txt").unlink()
    reverse = bulk.undo_preview(plan)
    assert reverse["files"][0]["before"] == plan["files"][0]["after"]
    assert plan == original and not (tmp_path / "a.txt").exists()


def test_context_preserves_bytes_and_exposes_comparable_identity(tmp_path):
    original = "\u96ea\r\ncontent".encode("utf-8")
    (tmp_path / "a.txt").write_bytes(original)
    context = bulk.read_context(tmp_path, ["a.txt"])
    assert context["root"] == str(tmp_path.resolve())
    assert context["root_identity"]["inode"] == tmp_path.stat().st_ino
    assert context["files"] == [{"path": "a.txt", "text": original.decode("utf-8"),
                                  "sha256": sha256(original).hexdigest()}]
    assert context == json.loads(json.dumps(context))
    assert (tmp_path / "a.txt").read_bytes() == original
    (tmp_path / "a.txt").write_bytes(b"owner changed context")
    assert bulk.read_context(tmp_path, ["a.txt"]) != context


def test_context_rejects_oversized_selection_without_truncation(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"abc")
    (tmp_path / "b.txt").write_bytes(b"defg")
    with pytest.raises(ValueError, match="budget"):
        bulk.read_context(tmp_path, ["a.txt", "b.txt"], max_chars=6)
    assert bulk.read_context(tmp_path, ["a.txt", "b.txt"], max_chars=7)["files"][1]["text"] == "defg"
    with pytest.raises(ValueError):
        bulk.read_context(tmp_path, ["a.txt"], max_chars=True)
    with pytest.raises(ValueError):
        bulk.read_context(tmp_path, ["a.txt"], max_chars=12001)


def test_context_reuses_scope_and_duplicate_guards(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"ordinary")
    (tmp_path / ".env").write_bytes(b"never context")
    with pytest.raises(PermissionError):
        bulk.read_context(tmp_path, [".env"])
    with pytest.raises(ValueError, match="once"):
        bulk.read_context(tmp_path, ["a.txt", "a.txt"])
    with pytest.raises(ValueError):
        bulk.read_context(tmp_path, ["../outside"])
    assert bulk.read_context(tmp_path, [])["files"] == []
