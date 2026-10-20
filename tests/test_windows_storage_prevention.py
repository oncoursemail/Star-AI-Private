"""Offline storage-policy behavior and workflow gate checks; no GitHub/EXE calls."""
from __future__ import annotations

import ast
import copy
import importlib.util
import io
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("preview_budget", ROOT / "scripts/check_windows_preview_budget.py")
budget = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(budget)
WORKFLOW = (ROOT / ".github/workflows/windows-desktop.yml").read_text(encoding="utf-8")
OFFLINE_WORKFLOW = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")


def inventory(pages, metadata=None):
    info = metadata if metadata is not None else {
        "id": budget.REPOSITORY_ID, "full_name": budget.REPOSITORY, "private": True}
    def read(path):
        return copy.deepcopy(info if path == "" else pages[int(path.rsplit("=", 1)[1]) - 1])
    return read


def item(identifier, size=1, expired=False):
    return {"id": identifier, "size_in_bytes": size, "expired": expired}


class BudgetTests(unittest.TestCase):
    def test_only_explicit_non_main_single_format_is_admitted(self):
        budget.require_request("workflow_dispatch", "refs/heads/fix/preview", "setup")
        budget.require_request("workflow_dispatch", "refs/heads/fix/preview", "portable")
        for request in (("pull_request", "refs/pull/4/merge", "setup"),
                        ("push", "refs/heads/fix/a", "setup"),
                        ("workflow_dispatch", "refs/heads/main", "setup"),
                        ("workflow_dispatch", "refs/tags/v1.0.0", "portable"),
                        ("workflow_dispatch", "refs/heads/fix/a", "both"),
                        ("workflow_dispatch", "refs/heads/fix/a", "none")):
            with self.subTest(request=request), self.assertRaises(budget.PreviewRefused):
                budget.require_request(*request)

    def test_existing_bytes_incoming_and_archive_reserve_are_all_counted(self):
        self.assertEqual(budget.admit(80_000_000, 300_000_000)["projected_bytes"], 390_000_000)
        self.assertEqual(budget.admit(90_000_000, 300_000_000)["projected_bytes"], budget.BUDGET_BYTES)
        with self.assertRaises(budget.PreviewRefused):
            budget.admit(90_000_001, 300_000_000)
        with self.assertRaises(budget.PreviewRefused):
            budget.admit(0, 600_000_000)

    def test_invalid_byte_counts_do_not_get_coerced(self):
        for existing, incoming in ((True, 5), (-1, 5), (0, 0), (0, "1"), (0, True)):
            with self.subTest(values=(existing, incoming)), self.assertRaises(budget.PreviewRefused):
                budget.admit(existing, incoming)

    def test_complete_pages_count_all_families_and_skip_expired_bytes(self):
        pages = [{"total_count": 101, "artifacts": [item(i, 2) for i in range(1, 101)]},
                 {"total_count": 101, "artifacts": [item(101, 999, True)]}]
        self.assertEqual(budget.retained_bytes(inventory(pages)), 200)
        self.assertEqual(budget.retained_bytes(inventory([{"total_count": 0, "artifacts": []}])), 0)

    def test_wrong_repository_or_visibility_is_refused(self):
        for change in ({"id": True}, {"id": 999}, {"full_name": "oncoursemail/Star-AI"}, {"private": False}):
            with self.subTest(change=change), self.assertRaises(budget.PreviewRefused):
                budget.retained_bytes(inventory([], {
                    "id": budget.REPOSITORY_ID, "full_name": budget.REPOSITORY, "private": True, **change}))

    def test_partial_duplicate_changing_and_malformed_pages_are_refused(self):
        variants = [
            [{"total_count": 2, "artifacts": [item(1)]}],
            [{"total_count": 2, "artifacts": [item(1), item(1)]}],
            [{"total_count": 1, "artifacts": [item(1, -1)]}],
            [{"total_count": 1, "artifacts": [item(1, True)]}],
            [{"total_count": 1, "artifacts": [item(1, 1, "false")]}],
            [{"total_count": 101, "artifacts": [item(i) for i in range(1, 101)]},
             {"total_count": 102, "artifacts": [item(101)]}],
        ]
        for pages in variants:
            with self.subTest(pages=pages), self.assertRaises(budget.PreviewRefused):
                budget.retained_bytes(inventory(pages))
        with patch.object(budget, "MAX_PAGES", 1), self.assertRaises(budget.PreviewRefused):
            budget.retained_bytes(inventory([
                {"total_count": 101, "artifacts": [item(i) for i in range(1, 101)]}]))

    def make_files(self, root):
        for relative in ("dist/STAR-Setup-v1.0.0.exe", "STAR-Genesis-Windows-x64.zip",
                         "STAR-PREVIEW-SHA256SUMS.txt", "ui-previews/home.png"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"inert fixture")

    def test_selected_files_include_one_binary_checksum_and_all_screenshots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_files(root)
            files = budget.selected_files(root, "setup")
            self.assertEqual({path.name for path in files}, {
                "STAR-Setup-v1.0.0.exe", "STAR-PREVIEW-SHA256SUMS.txt", "home.png"})
            files = budget.selected_files(root, "portable")
            self.assertNotIn("STAR-Setup-v1.0.0.exe", {path.name for path in files})
            (root / "dist/STAR-Setup-v0.9.0.exe").write_bytes(b"old")
            with self.assertRaises(budget.PreviewRefused):
                budget.selected_files(root, "setup")

    def test_missing_or_empty_required_preview_files_refuse(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_files(root)
            (root / "ui-previews/home.png").write_bytes(b"")
            with self.assertRaises(budget.PreviewRefused):
                budget.selected_files(root, "portable")
            (root / "ui-previews/home.png").unlink()
            with self.assertRaises(budget.PreviewRefused):
                budget.selected_files(root, "portable")

    def test_default_or_pr_entrypoint_never_contacts_github_or_emits_approval(self):
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REF": "refs/pull/1/merge"}, clear=True), \
                patch.object(budget, "read_github") as read, patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(budget.main(), 1)
            read.assert_not_called()

    def test_endpoint_scope_refuses_before_reading_a_token(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(budget.PreviewRefused, "Endpoint"):
            budget.read_github("/actions/artifacts/123")

    def test_http_is_read_only_without_redirects_or_error_body_disclosure(self):
        calls = []
        class Opener:
            def open(self, request, timeout):
                calls.append((request.get_method(), request.full_url, timeout))
                return io.BytesIO(b"{}")
        environment = {"GITHUB_REPOSITORY": budget.REPOSITORY, "GH_TOKEN": "fixture-only"}
        with patch.dict(os.environ, environment), patch("urllib.request.build_opener", return_value=Opener()):
            budget.read_github("")
        self.assertEqual(calls, [("GET", "https://api.github.com/repos/" + budget.REPOSITORY, 15)])
        self.assertIsNone(budget.NoRedirect().redirect_request(None))
        class Failure:
            def open(self, *args, **kwargs):
                raise urllib.error.HTTPError("https://api.github.com", 403, "private-body", {}, None)
        with patch.dict(os.environ, environment), patch("urllib.request.build_opener", return_value=Failure()), \
                self.assertRaisesRegex(budget.PreviewRefused, r"^Read-only inventory request failed: HTTP 403$"):
            budget.read_github("")


def job(name, source=WORKFLOW):
    return re.split(r"(?m)^  [\w-]+:\n", source.split("\n  " + name + ":\n", 1)[1], maxsplit=1)[0]


def steps(name, source=WORKFLOW):
    return re.split(r"(?m)^      - ", job(name, source))[1:]


def condition(source, *, event, ref, requested="none", admitted="", docs_only="false"):
    found = re.search(r"(?m)^        if: (.+)$", source)
    if not found:
        return True
    expression = found[1].strip().removeprefix("${{").removesuffix("}}").strip()
    for key, value in {"github.event_name": event, "github.ref": ref,
                       "inputs.preview_format": requested,
                       "steps.scope.outputs.docs_only": docs_only,
                       "steps.preview-budget.outputs.format": admitted}.items():
        expression = expression.replace(key, repr(value))
    expression = expression.replace("always()", "True").replace("&&", " and ").replace("||", " or ")
    def evaluate(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BoolOp):
            values = [evaluate(value) for value in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = evaluate(node.left), evaluate(node.comparators[0])
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
        raise AssertionError("Unexpected workflow predicate; extend the independent evaluator")
    return bool(evaluate(ast.parse(expression, mode="eval").body))


class OfflineWorkflowTests(unittest.TestCase):
    def test_pr_and_star_pushes_upload_nothing_even_after_failed_or_unknown_scope(self):
        uploads = [step for name in ("checks", "react", "pyright") for step in steps(name, OFFLINE_WORKFLOW)
                   if "actions/upload-artifact@" in step]
        self.assertEqual(len(uploads), 1)
        for docs_only in ("false", "true", ""):
            for event, ref in (("pull_request", "refs/pull/7/merge"), ("push", "refs/heads/star/next")):
                with self.subTest(event=event, docs_only=docs_only):
                    self.assertFalse(condition(uploads[0], event=event, ref=ref, docs_only=docs_only))
        self.assertTrue(condition(uploads[0], event="push", ref="refs/heads/main", docs_only="false"))
        self.assertFalse(condition(uploads[0], event="push", ref="refs/heads/main", docs_only="true"))
        self.assertIn("retention-days: 3", uploads[0])

    def test_required_offline_validation_is_still_fail_closed_on_unknown_scope(self):
        required = {
            "checks": ("Compile Python sources", "Validate research evaluation catalog", "Run all offline regression tests"),
            "react": ("Install reviewed frontend dependencies", "Typecheck React and validate components",
                      "Confirm built offline application entry point"),
            "pyright": ("Run pyright on star/ (settings in pyrightconfig.json)",
                        "Fail on errors beyond scripts/pyright_baseline.json"),
        }
        for name, names in required.items():
            for title in names:
                step = next(step for step in steps(name, OFFLINE_WORKFLOW) if step.startswith("name: " + title + "\n"))
                self.assertNotIn("continue-on-error", step)
                self.assertTrue(condition(step, event="pull_request", ref="refs/pull/7/merge", docs_only=""))
        for command in ("npm run typecheck --prefix frontend", "npm run test --prefix frontend",
                        "npm run build --prefix frontend", "test -s frontend/dist/index.html"):
            self.assertIn(command, job("react", OFFLINE_WORKFLOW))
        self.assertIn("python -m pytest -q", job("checks", OFFLINE_WORKFLOW))
        self.assertIn("ruff check star --output-format=github", job("checks", OFFLINE_WORKFLOW))

    def test_capture_still_runs_and_has_no_artifact_consumer(self):
        self.assertNotIn("actions/download-artifact@", OFFLINE_WORKFLOW)
        capture = next(step for step in steps("react", OFFLINE_WORKFLOW)
                       if step.startswith("name: Capture actual React website, desktop and mobile screenshots\n"))
        self.assertTrue(condition(capture, event="pull_request", ref="refs/pull/7/merge", docs_only="false"))
        self.assertIn("continue-on-error: true", capture)  # Existing best-effort capture policy is unchanged.
        self.assertIn("--screenshot=", capture)


class WorkflowTests(unittest.TestCase):
    def uploads(self, **context):
        return [step for name in ("frontend", "windows-tests", "windows-build") for step in steps(name)
                if "actions/upload-artifact@" in step and condition(step, **context)]

    def test_ordinary_pr_and_unrequested_branch_runs_have_zero_uploads(self):
        for event, ref in (("pull_request", "refs/pull/7/merge"),
                           ("workflow_dispatch", "refs/heads/fix/preview")):
            self.assertEqual(self.uploads(event=event, ref=ref), [])

    def test_only_one_admitted_manual_preview_format_and_screenshots_are_uploaded(self):
        for requested, name in (("setup", "STAR-Ultimate-Windows-Setup"),
                                ("portable", "STAR-Ultimate-Windows-Portable")):
            uploaded = self.uploads(event="workflow_dispatch", ref="refs/heads/fix/preview",
                                    requested=requested, admitted=requested)
            self.assertEqual(len(uploaded), 2)
            self.assertTrue(any("name: " + name in step for step in uploaded))
            self.assertTrue(any("name: STAR-OLED-GUI-Previews" in step for step in uploaded))
            self.assertFalse(any("name: STAR-Windows-vNext" in step for step in uploaded))
            self.assertEqual(self.uploads(event="workflow_dispatch", ref="refs/heads/fix/preview",
                                          requested=requested, admitted=""), [])

    def test_main_handoff_is_mandatory_and_never_a_split_or_duplicate_preview(self):
        for event in ("push", "workflow_dispatch"):
            uploaded = self.uploads(event=event, ref="refs/heads/main")
            self.assertTrue(any("name: STAR-Windows-vNext" in step for step in uploaded))
            self.assertFalse(any("name: STAR-Ultimate-Windows-" in step for step in uploaded))
        self.assertNotIn("STAR-Fast-Brain-Preview", WORKFLOW)

    def test_windows_validation_has_no_artifact_handoff_or_upload_before_package_checks(self):
        self.assertNotIn("star-frontend-dist", WORKFLOW)
        self.assertNotIn("actions/upload-artifact@", job("frontend"))
        for name in ("windows-tests", "windows-build"):
            text = job(name)
            self.assertIn("needs: frontend", text)
            self.assertNotIn("actions/download-artifact@", text)
            for command in ("npm run typecheck", "npm run test", "npm run build"):
                self.assertIn(command, text)
        build = job("windows-build")
        self.assertLess(build.index("./scripts/smoke_windows_installer.ps1"), build.index("actions/upload-artifact@"))
        self.assertIn("python -m pytest", job("windows-tests"))
        self.assertIn("shard: [1, 2]", job("windows-tests"))
        self.assertNotIn("continue-on-error", WORKFLOW)

    def test_retention_and_trusted_release_dependencies_are_preserved(self):
        for step in steps("windows-build"):
            if "actions/upload-artifact@" in step:
                days = 1 if "name: STAR-Windows-vNext" in step else 3
                self.assertIn(f"retention-days: {days}", step)
        self.assertIn("needs: [windows-build, windows-tests]", job("attest-release"))
        self.assertIn("if: github.ref == 'refs/heads/main'", job("attest-release"))
        publish_needs = re.search(r"needs: \[([^\]]+)\]", job("publish-release"))[1]
        self.assertTrue({"windows-build", "attest-release"} <= {name.strip() for name in publish_needs.split(",")})
        self.assertLess(job("publish-release").index("gh attestation verify"), job("publish-release").index("gh release create"))
        self.assertNotIn("contents: write", job("windows-build"))
        self.assertNotIn("attestations: write", job("windows-build"))

    def test_native_smoke_is_unconditional_and_limited_to_disposable_runner(self):
        smoke = next(step for step in steps("windows-build") if "./scripts/smoke_windows_installer.ps1" in step)
        self.assertIsNone(re.search(r"(?m)^        if:", smoke))
        source = (ROOT / "scripts/smoke_windows_installer.ps1").read_text(encoding="utf-8")
        self.assertIn("$env:RUNNER_ENVIRONMENT -ne 'github-hosted'", source)
        self.assertIn("$process.Path -eq $installedExe", source)
        self.assertIn("WaitForExit($Seconds * 1000)", source)
        self.assertIn("foreach ($attempt in 1, 2)", source)
        self.assertIn("--doctor", source)
        self.assertIn("--ui-doctor", source)
        self.assertIn("--build-doctor", source)
        self.assertNotIn("Remove-Item", source)


if __name__ == "__main__":
    unittest.main()
