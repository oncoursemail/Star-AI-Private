"""STAR command-line interface. Local model; no model-provider key."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

_IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def loopback_endpoint(url: str) -> bool:
    """True only for a plain-http model endpoint on this machine with an explicit port.

    A prefix test let ``http://localhost:1234@example.com/v1`` through: everything before the
    ``@`` is a user name, so requests (and the prompt) would have gone to example.com.
    """
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost"} and port is not None
            and parts.username is None and parts.password is None)


def image_media_type(path: Path) -> str:
    """The media type of the picture's real format (validated by image_part), not of its file name."""
    from .pil_safe import Image
    with Image.open(path) as image:
        media_type = _IMAGE_TYPES.get(image.format or "")
    if media_type is None:
        raise ValueError("Only PNG/JPEG/WebP reference images are allowed")
    return media_type


def setup():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")


def doctor():
    from importlib.metadata import version, PackageNotFoundError
    print("STAR Genesis · Windows/local setup")
    print("Python", sys.version.split()[0])
    for package in ("openai", "mcp", "Pillow", "jsonschema", "python-dotenv", "httpx", "PyJWT"):
        try:
            print(package, version(package))
        except PackageNotFoundError:
            print(package, "MISSING")
    print("Model endpoint:", os.environ.get("STAR_BASE_URL", "http://127.0.0.1:1234/v1"))
    print("Model identifier:", os.environ.get("STAR_MODEL", "NOT CONFIGURED"))
    try:
        from .studio import launcher
        _, _, path = launcher()
        if path is None:
            # A host-defined launcher command has no local file to look for (and may name a host).
            print("Roblox MCP: custom launcher configured")
        else:
            print("Roblox MCP:", "FOUND" if path.is_file() else "NOT FOUND", path)
    except Exception as exc:
        print("Roblox MCP:", type(exc).__name__)
    print("This is not a live model or Roblox tool smoke test.")


async def main(args):
    if args.command in {"project-catalog", "github-inventory", "github-resolve", "github-read"}:
        from .github_inventory import cli_result
        result = await cli_result(args.command, repository_id=getattr(args, "repository_id", None),
                                  path=getattr(args, "path", ""), revision=getattr(args, "revision", "HEAD"),
                                  credential_source=getattr(args, "credential_source", None))
        print(json.dumps(result, indent=2))
        return
    if args.command == "doctor":
        doctor()
        return
    if args.command == "live-show":
        # An explicit request: validate and plan only. Reads the named files, writes and sends nothing.
        from .live_show import _read_bounded, plan_report
        report = plan_report(_read_bounded(Path(args.manifest)),
                             _read_bounded(Path(args.reviews)) if args.reviews else None,
                             _read_bounded(Path(args.questions)) if args.questions else None,
                             post_episode=args.post_episode)
        print(json.dumps(report, indent=2, allow_nan=False))
        return
    if args.command == "evals":
        from .evals import load_catalog, summarize_verdicts
        catalog = load_catalog(ROOT / "evals" / "roblox_cases.json")
        print(json.dumps(summarize_verdicts(catalog, {}), indent=2))
        print("Not-run cases are NOT test passes. See docs/RESEARCH_ROADMAP.md")
        return
    if args.command in {"tools", "studios"}:
        from .studio import connect, list_tools
        async with connect() as session:
            tools = await list_tools(session)
            if args.command == "tools":
                for t in tools:
                    print(t["name"])
            else:
                if "list_roblox_studios" not in {t["name"] for t in tools}:
                    raise RuntimeError("list_roblox_studios is not exposed by this MCP server")
                response = await session.call_tool("list_roblox_studios", arguments={})
                print(json.dumps(response.model_dump(by_alias=True, exclude_none=True), indent=2))
        return
    if args.command in {"knowledge-add", "knowledge-find", "knowledge-review", "reference-add"}:
        from .knowledge import KnowledgeStore
        store = KnowledgeStore(ROOT / ".local" / "star-knowledge")
        try:
            if args.command == "knowledge-add":
                note_id = store.add_note(project=args.project, kind=args.kind,
                    text=args.text, source=args.source, revision=args.revision)
                print("Candidate note stored, unreviewed:", note_id)
            elif args.command == "knowledge-find":
                print(json.dumps([n.__dict__ for n in store.find(args.project, args.query,
                      reviewed_only=not args.include_candidates)], indent=2))
            elif args.command == "knowledge-review":
                store.review_note(project=args.project, note_id=args.note_id, evidence=args.evidence)
                print("Note marked reviewed with a separate evidence record:", args.note_id)
            else:
                from .media import image_part
                path = Path(args.file).expanduser().resolve()
                image_part(path)  # Verify image bytes; extension alone isn't enough.
                # The stored type follows the bytes: a PNG saved as "shot.jpg" used to be recorded as JPEG.
                mime = image_media_type(path)
                digest, dest = store.ingest_artifact(project=args.project, path=path,
                    origin=f"local-upload:{path.name}", media_type=mime)
                print("Locally stored image:", digest, "at", dest)
        finally:
            store.close()
        return
    if args.command == "anime-check":
        # Local planning files only; prints the problems found and exits 1 when there are any.
        from .anime_production import check_file
        kind, errors = check_file(Path(args.file), plan=Path(args.plan) if args.plan else None)
        print(json.dumps({"file": Path(args.file).name, "kind": kind, "valid": not errors, "errors": errors}, indent=2))
        if errors:
            raise SystemExit(1)
        return
    if args.command == "memory":
        from .memory import Memory
        db = Memory(ROOT / ".local" / "star-memory.sqlite3")
        print(db.get(args.project) or "No checkpoint for this project")
        db.close()
        return
    if args.command == "self-build":
        from openai import AsyncOpenAI
        from .selfbuild import develop
        from .github_app import from_env
        model = os.environ.get("STAR_MODEL", "").strip()
        if not model or model == "your-loaded-lm-studio-model-id":
            raise RuntimeError("Load a local model in LM Studio and configure STAR_MODEL")
        base_url = os.environ.get("STAR_BASE_URL", "http://127.0.0.1:1234/v1")
        if not loopback_endpoint(base_url):
            raise RuntimeError("Self-build requires a loopback local model endpoint")
        github = from_env() if args.publish_draft else None
        async with AsyncOpenAI(base_url=base_url, api_key="local-only", timeout=180.0, max_retries=0) as client:
            result = await develop(client=client, model=model, repository=ROOT, task=args.task,
                                   github=github)
        print(json.dumps(result, indent=2))
        return
    if args.command in {"github-check", "github-sync"}:
        from .github_app import from_env, valid_upload_path
        bot = from_env()
        if args.command == "github-check":
            response = await bot.check()
            print("Accessible GitHub App repositories:")
            for repo in response.get("repositories", []):
                print(repo.get("full_name", "unknown"))
            return
        base = await bot.create_branch(args.branch)
        sources = [p for p in ROOT.rglob("*") if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(ROOT.resolve()) and valid_upload_path(p.relative_to(ROOT).as_posix())]
        if not sources:
            raise RuntimeError("No allowlisted source files")
        for p in sorted(sources):
            rel = p.relative_to(ROOT).as_posix()
            await bot.write_branch_file(args.branch, rel, p.read_bytes(), f"STAR: update {rel}")
            print("Published draft change:", rel)
        pr = await bot.open_pr(base, args.branch, "STAR proposed updates", "Automatically published to a development branch by STAR Genesis. Human review before merging is recommended. This does not publish games or update production.")
        print("Draft pull request:", pr.get("html_url", "created"))
        return
    if args.command == "ask":
        from openai import AsyncOpenAI
        from .agent import execute
        from .studio import connect, list_tools
        from .memory import Memory
        from .knowledge import KnowledgeStore
        from .media import image_part
        project = args.project
        # Every refusal comes before anything is stored: a refused run used to have copied its
        # reference images into the knowledge store already (and left both databases open).
        model = os.environ.get("STAR_MODEL", "").strip()
        if not model or model == "your-loaded-lm-studio-model-id":
            raise RuntimeError("Set STAR_MODEL to the identifier of your loaded model in LM Studio")
        base_url = os.environ.get("STAR_BASE_URL", "http://127.0.0.1:1234/v1")
        if not loopback_endpoint(base_url):
            raise RuntimeError("STAR v0.1 requires a local loopback model endpoint")
        if args.unsafe_luau and not args.edit:
            raise RuntimeError("--unsafe-luau requires --edit in a disposable place")
        if args.edit and (args.no_studio or not args.studio_id):
            raise RuntimeError("Automatic editing requires a selected disposable Studio instance ID")
        if args.edit and os.environ.get("STAR_SANDBOX_STUDIO_ID", "") != args.studio_id:
            raise RuntimeError("Edit blocked: pin your disposable Studio ID in STAR_SANDBOX_STUDIO_ID first")
        if not args.no_studio and not args.studio_id:
            raise RuntimeError("Run `studios` and specify --studio-id, or use --no-studio")
        references = []
        for image in args.image:
            path = Path(image).expanduser().resolve()
            image_part(path)  # Validate format and size before preserving raw image.
            references.append((path, image_media_type(path)))
        knowledge = KnowledgeStore(ROOT / ".local" / "star-knowledge")
        try:
            approved = knowledge.find(project, args.prompt, reviewed_only=True, limit=8)
            for path, media_type in references:
                knowledge.ingest_artifact(project=project, path=path, origin=f"task-reference:{path.name}",
                                          media_type=media_type)
        finally:
            knowledge.close()
        trusted_notes = "\n".join(f"[{n.kind} ref={n.source} rev={n.revision}] {n.text}" for n in approved)
        db = Memory(ROOT / ".local" / "star-memory.sqlite3")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        target = ROOT / "runs" / run_id
        target.mkdir(parents=True)
        raw_path = target / "conversation.json"
        logs = target / "events.jsonl"
        def checkpoint(text):
            db.put(project, text)
        def event(info):
            with logs.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(info, ensure_ascii=False) + "\n")
            print("[STAR]", json.dumps(info, ensure_ascii=False))
        async with AsyncOpenAI(base_url=base_url, api_key="local-only", timeout=180.0, max_retries=0) as client:
            if args.no_studio:
                answer, messages, archive = await execute(client=client, model=model, prompt=args.prompt,
                    image_paths=[Path(p).expanduser() for p in args.image], project_memory=db.get(project) + "\nAPPROVED PROJECT KNOWLEDGE:\n" + trusted_notes,
                    checkpoint=checkpoint, max_calls=int(os.environ.get("STAR_MAX_MODEL_CALLS", "12")),
                    context_chars=int(os.environ.get("STAR_CONTEXT_CHARS", "25000")), on_event=event)
            else:
                async with connect() as session:
                    # --edit is a request, not a permission: the open place must pass the sandbox
                    # rule (star/studio_loop.py: a blank, unsaved place) or the run only reads.
                    from . import studio_loop
                    discovered = await list_tools(session)
                    studio = await studio_loop.open_guarded(session, discovered, studio_id=args.studio_id,
                                                            opted_in=args.edit)
                    event({"event": "studio_place", **studio.verdict.public()})
                    answer, messages, archive = studio_loop.with_report(await execute(
                        client=client, model=model, prompt=args.prompt,
                        image_paths=[Path(p).expanduser() for p in args.image], studio=studio,
                        discovered=discovered, studio_id=args.studio_id, may_edit=studio.verdict.editable,
                        allow_luau=studio.verdict.editable and args.unsafe_luau,
                        project_memory=db.get(project) + "\nAPPROVED PROJECT KNOWLEDGE:\n" + trusted_notes, checkpoint=checkpoint,
                        max_calls=int(os.environ.get("STAR_MAX_MODEL_CALLS", "12")),
                        context_chars=int(os.environ.get("STAR_CONTEXT_CHARS", "25000")), on_event=event), studio)
        raw_path.write_text(json.dumps({"messages":messages, "archive":archive}, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        (target / "answer.md").write_text(answer, encoding="utf-8")
        # The checkpoint is a factual record of the task; never claim any untested action succeeded.
        if not db.get(project):
            db.put(project, "Initial task completed; full transcript saved locally in " + str(raw_path) + ". Verify the final answer and tool logs for exact results.")
        db.event(project, {"run_id": run_id, "answer": answer[:8000]})
        db.close()
        print("\n" + answer + "\n\nSaved:", target)
        return
    raise ValueError("Unknown command")


def cli():
    setup()
    parser = argparse.ArgumentParser(prog="star", description="STAR Genesis · offline-capable local Roblox AI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("evals", help="List Roblox evaluation definitions and their not-run status")
    sub.add_parser("tools")
    show = sub.add_parser("live-show", help="Validate and plan an episode manifest offline (no rendering, posting or network)")
    show.add_argument("manifest")
    show.add_argument("--reviews", help="JSON list of review records for the readiness check")
    show.add_argument("--questions", help="JSON list of moderated audience questions")
    show.add_argument("--post-episode", action="store_true")
    sub.add_parser("studios")
    know = sub.add_parser("knowledge-add", help="Store a candidate project note for later review")
    know.add_argument("--project", required=True)
    know.add_argument("--kind", required=True, choices=["requirement", "reference", "decision", "fix", "observation", "unknown"])
    know.add_argument("--text", required=True)
    know.add_argument("--source", required=True)
    know.add_argument("--revision", default="unknown")
    find = sub.add_parser("knowledge-find", help="Search stored knowledge by project")
    find.add_argument("--project", required=True)
    find.add_argument("query", nargs="?", default="")
    find.add_argument("--include-candidates", action="store_true")
    review = sub.add_parser("knowledge-review", help="Human acceptance of an evidence-backed note")
    review.add_argument("--project", required=True)
    review.add_argument("--note-id", required=True, type=int)
    review.add_argument("--evidence", required=True)
    ref = sub.add_parser("reference-add", help="Preserve an immutable local image reference")
    ref.add_argument("--project", required=True)
    ref.add_argument("file")
    mem = sub.add_parser("memory")
    mem.add_argument("--project", default="STAR")
    build = sub.add_parser("self-build")
    build.add_argument("task", help="Improvement confined to new skill modules and docs")
    build.add_argument("--publish-draft", action="store_true", help="Publish using STAR's configured GitHub App")
    sub.add_parser("github-check")
    sub.add_parser("project-catalog", help="Show owner-confirmed project names and repository IDs")
    inventory = sub.add_parser("github-inventory", help="List all repositories visible to the configured read credential")
    inventory.add_argument("--credential-source", choices=("env", "gh"))
    for command in ("github-resolve", "github-read"):
        read = sub.add_parser(command, help="Resolve stable repository identity or read bounded source")
        read.add_argument("--repository-id", required=True, type=int)
        read.add_argument("--credential-source", choices=("env", "gh"))
        read.add_argument("--revision", default="HEAD", help="Branch or commit; HEAD uses the current default branch")
        if command == "github-read":
            read.add_argument("path")
    sync = sub.add_parser("github-sync")
    sync.add_argument("--branch", required=True, help="star/<development-branch>")
    anime = sub.add_parser("anime-check", help="Validate an anime planning file (pilot.json, benchmark_template.json or a cue sheet .csv)")
    anime.add_argument("file")
    anime.add_argument("--plan", help="for a .csv: the pilot.json it must match")
    ask = sub.add_parser("ask")
    ask.add_argument("prompt")
    ask.add_argument("--image", action="append", default=[])
    ask.add_argument("--project", default="STAR")
    ask.add_argument("--studio-id", default="")
    ask.add_argument("--no-studio", action="store_true")
    ask.add_argument("--edit", action="store_true", help="Auto-allow bounded edits in a selected disposable Studio instance")
    ask.add_argument("--unsafe-luau", action="store_true", help="Enables FULL Luau execution. Only use in disposable offline test place")
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except (RuntimeError, ValueError, OSError) as exc:
        print("STAR stopped:", str(exc), file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__":
    cli()
