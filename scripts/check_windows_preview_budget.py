#!/usr/bin/env python3
"""Admit one owner-requested non-main preview; read-only GitHub API, no cleanup.

The 400 MB repository cap and 10 MB archive reserve are deliberately conservative.
This is not a measurement of account billing or space used by other repositories.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

REPOSITORY = "oncoursemail/Star-AI-Private"
REPOSITORY_ID = 1412474221
BUDGET_BYTES = 400_000_000
ARCHIVE_RESERVE_BYTES = 10_000_000
MAX_PAGES = 100


class PreviewRefused(ValueError):
    """The requested upload is not proven to fit this policy."""


def require(condition, message):
    if not condition:
        raise PreviewRefused(message)


def require_request(event, ref, requested):
    require(event == "workflow_dispatch", "Previews require an explicit workflow dispatch")
    require(isinstance(ref, str) and ref.startswith("refs/heads/")
            and ref != "refs/heads/main", "Previews must use a non-main branch")
    require(requested in ("setup", "portable"), "Select exactly one preview format")


def retained_bytes(read):
    meta = read("")
    require(isinstance(meta, dict) and type(meta.get("id")) is int
            and meta["id"] == REPOSITORY_ID and meta.get("full_name") == REPOSITORY
            and meta.get("private") is True, "Private source repository identity changed")
    seen, totals, byte_count = set(), set(), 0
    for page in range(1, MAX_PAGES + 1):
        data = read(f"/actions/artifacts?per_page=100&page={page}")
        require(isinstance(data, dict), "Invalid artifact inventory")
        batch, total = data.get("artifacts"), data.get("total_count")
        require(isinstance(batch, list) and len(batch) <= 100
                and type(total) is int and total >= 0, "Invalid artifact page")
        totals.add(total)
        for item in batch:
            require(isinstance(item, dict) and type(item.get("id")) is int
                    and item["id"] > 0 and type(item.get("size_in_bytes")) is int
                    and item["size_in_bytes"] >= 0 and type(item.get("expired")) is bool,
                    "Invalid artifact metadata")
            require(item["id"] not in seen, "Artifact inventory changed during pagination")
            seen.add(item["id"])
            if not item["expired"]:
                byte_count += item["size_in_bytes"]
        require(len(totals) == 1, "Artifact inventory total changed during pagination")
        if len(batch) < 100:
            require(len(seen) == total, "Incomplete artifact inventory")
            return byte_count
    raise PreviewRefused("Artifact inventory exceeded the page limit")


def selected_files(root, requested):
    root = root.resolve()
    if requested == "setup":
        binaries = list((root / "dist").glob("STAR-Setup-v*.exe"))
    else:
        require(requested == "portable", "Select exactly one preview format")
        binaries = [root / "STAR-Genesis-Windows-x64.zip"]
    require(len(binaries) == 1, "Expected exactly one selected binary")
    screenshots = list((root / "ui-previews").glob("*.png"))
    require(bool(screenshots), "Expected generated GUI review screenshots")
    files = binaries + [root / "STAR-PREVIEW-SHA256SUMS.txt"] + screenshots
    for path in files:
        require(path.resolve().is_relative_to(root) and not path.is_symlink()
                and path.is_file() and path.stat().st_size > 0,
                "Preview contains a missing, empty, or unexpected file")
    return files


def admit(existing, incoming):
    require(type(existing) is int and existing >= 0
            and type(incoming) is int and incoming > 0, "Invalid byte accounting")
    projected = existing + incoming + ARCHIVE_RESERVE_BYTES
    require(projected <= BUDGET_BYTES,
            "Requested preview does not fit the 400 MB repository policy; "
            "package checks completed on this runner, but no preview upload is approved")
    return {"retained_bytes": existing, "new_file_bytes": incoming,
            "archive_reserve_bytes": ARCHIVE_RESERVE_BYTES,
            "projected_bytes": projected, "budget_bytes": BUDGET_BYTES}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read_github(path):
    require(path == "" or (path.startswith("/actions/artifacts?per_page=100&page=")
            and path.rsplit("=", 1)[1].isdigit()), "Endpoint outside read-only inventory scope")
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY, "Unexpected workflow repository")
    token = os.environ.get("GH_TOKEN")
    require(bool(token), "The job's read-only GitHub token is unavailable")
    request = urllib.request.Request("https://api.github.com/repos/" + REPOSITORY + path,
                                    method="GET", headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "STAR-Windows-preview-budget"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            payload = response.read(2_000_001)
        require(len(payload) <= 2_000_000, "Inventory response exceeded its size limit")
        return json.loads(payload)
    except urllib.error.HTTPError as exc:
        raise PreviewRefused(f"Read-only inventory request failed: HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise PreviewRefused("Read-only inventory request could not be verified") from None


def main():
    try:
        requested = os.environ.get("STAR_PREVIEW_FORMAT", "none")
        require_request(os.environ.get("GITHUB_EVENT_NAME"), os.environ.get("GITHUB_REF"), requested)
        files = selected_files(Path.cwd(), requested)
        result = admit(retained_bytes(read_github), sum(path.stat().st_size for path in files))
        output = os.environ.get("GITHUB_OUTPUT")
        require(bool(output), "Workflow output path is unavailable")
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"format={requested}\n")
        print(json.dumps({"preview_format": requested, "status": "approved_for_upload", **result}))
        return 0
    except (PreviewRefused, OSError) as exc:
        message = str(exc) if isinstance(exc, PreviewRefused) else "Local preview files could not be verified"
        print(json.dumps({"status": "preview_refused", "error": message}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
