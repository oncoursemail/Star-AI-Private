"""Build a local source-install preview from committed files only; never publish it."""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

REPO = Path(__file__).resolve().parents[1]
INCLUDE = (
    "star", "installer/star-home", "installer/star-camera", "assets/vtuber",
    "frontend/public/assets/mascot/faces", "requirements-home.in", "requirements-home.txt",
    "requirements-home-torch.txt", "STAR-FIRST-START.md", "docs/design/STAR_VTUBER_DIRECTION_20261025.md",
    "Set Up Star.cmd", "Preview Star Setup.cmd", "STAR-LIVE-TEST.md",
    "docs/STAR_ALLOWANCE_CARD_OPTIONS_20261025.md", "docs/agents/codex-art-studio-20261026.md",
    "docs/agents/codex-stream-setup-20261026.md", "docs/agents/codex-pc-optimization-20261026.md",
    "docs/agents/codex-avatar-expressions-20261026.md", "docs/agents/codex-twitch-chat-20261026.md",
    "docs/agents/codex-own-pc-validation-20261026.md",
    "docs/agents/codex-twitch-chat-review-20261026.md",
    "docs/agents/codex-autonomy-hardening-validation-20261026.md",
    "docs/agents/codex-autonomy-recovery-20261026.md",
    "docs/agents/codex-home-voice-lifecycle-20261026.md",
    "docs/agents/codex-social-lifecycle-20261026.md",
    "docs/agents/codex-minecraft-setup-20261026.md",
    "docs/research/star-emotion-evidence-20261026.md",
    "docs/agents/codex-emotion-recovery-20261026.md",
    "docs/agents/codex-emotion-timing-20261026.md",
    "docs/agents/codex-memory-validation-20261026.md",
    "docs/agents/codex-memory-cards-20261026.md",
    "docs/agents/codex-memory-provenance-20261026.md",
    "docs/agents/codex-home-brain-boundaries-20261026.md",
    "docs/agents/codex-home-instance-20261026.md",
    "docs/agents/codex-home-audio-startup-20261026.md",
    "docs/agents/codex-release-prep-validation-20261026.md",
)
EXPECTED = ("star/home/__main__.py", "installer/star-home/setup.cmd", "installer/star-home/pins.json",
            "star/art_studio.py", "star/stream_setup.py", "star/twitch_chat.py", "STAR-FIRST-START.md",
            "Set Up Star.cmd", "Preview Star Setup.cmd", "STAR-LIVE-TEST.md",
            "star/home/onboarding.py", "star/games/minecraft_setup.py",
            "assets/vtuber/modes/cat-concept.png", "assets/vtuber/modes/puppy-concept.png")


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True).stdout


def verify(path: Path) -> dict:
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Bundle CRC verification failed")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Bundle contains duplicate entries")
        manifest = json.loads(archive.read("BUNDLE-MANIFEST.json"))
        files = {name for name in names if not name.endswith("/") and name != "BUNDLE-MANIFEST.json"}
        if set(manifest["files"]) != files:
            raise ValueError("Bundle manifest differs from archive contents")
        for name, digest in manifest["files"].items():
            if sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError("Bundle content hash mismatch")
        if not set(EXPECTED).issubset(files):
            raise ValueError("Bundle is missing an installation component")
    return {"verified": True, "files": len(files), "source_commit": manifest["source_commit"],
            "target_pc_tested": False, "live_accounts_connected": False}


def build(output: Path) -> dict:
    commit = git("rev-parse", "HEAD").decode().strip()
    raw = git("archive", "--format=zip", "HEAD", "--", *INCLUDE)
    files = {}
    payloads = {}
    with ZipFile(BytesIO(raw)) as source:
        for entry in source.infolist():
            if entry.is_dir():
                continue
            name = entry.filename
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or any(part in {".git", "__pycache__", "node_modules"} for part in p.parts):
                raise ValueError("Unexpected private/build path in source bundle")
            if p.suffix.lower() in {".pem", ".key", ".p12", ".db", ".sqlite3", ".gguf", ".safetensors"} or p.name == ".env":
                raise ValueError("Credentials, user databases and model weights are excluded")
            payloads[name] = source.read(entry)
            files[name] = sha256(payloads[name]).hexdigest()
    if not set(EXPECTED).issubset(files):
        raise ValueError("Commit every required installation component before packaging")
    manifest = {"schema": 1, "kind": "local_source_install_preview", "source_commit": commit,
                "target_pc_tested": False, "production_live2d_rig": False, "files": files}
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError("Choose a new bundle filename; existing bundles are preserved")
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, payload in sorted(payloads.items()):
            archive.writestr(name, payload)
        archive.writestr("BUNDLE-MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    result = verify(output)
    digest = sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".sha256").write_text(digest + "  " + output.name + "\n", encoding="ascii")
    return {**result, "bundle": str(output), "bytes": output.stat().st_size, "sha256": digest}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.output) if args.verify else build(args.output), indent=2))


if __name__ == "__main__":
    main()
