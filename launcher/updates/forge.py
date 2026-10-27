"""Mirror a flat release folder into a Forgejo/Gitea release as assets (the forge serves them at
`<forge>/<owner>/<repo>/releases/download/<tag>/<asset>`, which is a valid update base for layout "flat").

Blobs are immutable, so an asset that already exists is skipped; the manifest and its signature change on every publish
and are replaced. The API token is read from a file and never printed or logged.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


class ForgeError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _call(method: str, url: str, token: str, body: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Authorization": f"token {token}", **(headers or {})})
    try:
        # Authenticated publishing uses the configured address directly, never a redirect target.
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=120) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and method == "GET":
            return None
        raise ForgeError(f"{method} {urllib.parse.urlsplit(url).path} -> {exc.code}") from exc
    except OSError as exc:
        raise ForgeError(f"forge unreachable: {exc}") from exc


def _multipart(name: str, data: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="attachment"; filename="{name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n").encode()
    return head + data + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def upload_release(forge_url: str, token_file: Path, repo: str, tag: str, folder: Path, *, prerelease: bool = False) -> dict:
    """`repo` is "owner/name". Returns {"uploaded": [...], "skipped": n}."""
    token = Path(token_file).read_text(encoding="utf-8").strip()
    api = forge_url.rstrip("/") + f"/api/v1/repos/{repo}"
    rel = _call("GET", f"{api}/releases/tags/{urllib.parse.quote(tag)}", token)
    if rel is None:
        body = json.dumps({"tag_name": tag, "name": tag, "prerelease": prerelease,
                           "body": "Metallic update channel files. Do not edit by hand."}).encode()
        rel = _call("POST", f"{api}/releases", token, body, {"Content-Type": "application/json"})
    existing = {a["name"]: a["id"] for a in rel.get("assets", [])}
    uploaded, skipped = [], 0
    for p in sorted(Path(folder).iterdir()):
        if not p.is_file() or p.suffix == ".tmp":
            continue
        mutable = p.name.endswith((".json", ".sig"))
        if p.name in existing:
            if not mutable:
                skipped += 1
                continue
            _call("DELETE", f"{api}/releases/{rel['id']}/assets/{existing[p.name]}", token)
        body, ctype = _multipart(p.name, p.read_bytes())
        _call("POST", f"{api}/releases/{rel['id']}/assets?name={urllib.parse.quote(p.name)}", token, body,
              {"Content-Type": ctype})
        uploaded.append(p.name)
    return {"uploaded": uploaded, "skipped": skipped}
