"""Owner and developer commands for the Metallic update channel.

  keygen   [--key PATH] [--write-trust]   make the signing key (outside every repo) and show its public half
  publish  --root OUT --channel beta --component launcher --version 0.2.0 --src DIR [--entry Metallic.exe] [--notes ..]
  promote  --root OUT --from beta --to stable [--component launcher ...]
  verify   --root OUT --channel stable     signature, expiry and every blob hash of a release folder
  serve    --dir OUT [--port 8099]         local test server (127.0.0.1 only unless --bind is given)
  check    --url URL --home DIR            what an install would do (uses the shipped trust list or --trust)
  install  --url URL --home DIR --component launcher
  rollback --home DIR --component launcher
  forge-upload --forge URL --repo owner/name --tag channel-stable --dir FLAT_OUT --token-file FILE
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import forge, publish as pub
from .client import UpdateError, Updater, platform_id
from .keys import SigningKeyError, TrustStore, default_key_path, generate, load_private, write_trust
from .manifest import ManifestError
from .sources import DirSource, HttpSource


def _out(obj) -> None:
    print(json.dumps(obj, indent=1))


def _source(url: str):
    return DirSource(Path(url)) if Path(url).is_dir() else HttpSource(url)


def _updater(a) -> Updater:
    trust = TrustStore.load(Path(a.trust) if a.trust else None)
    return Updater(Path(a.home), _source(a.url) if getattr(a, "url", None) else DirSource(Path(a.home)), trust,
                   channel=a.channel, layout=a.layout, launcher_version=a.launcher_version, platform=platform_id())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m launcher.updates", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("keygen")
    s.add_argument("--key", help=f"private key file (default {default_key_path()})")
    s.add_argument("--write-trust", action="store_true", help="also add the public key to the trust list shipped with the launcher")
    s.add_argument("--note", default="Metallic release key")

    s = sub.add_parser("publish")
    s.add_argument("--root", required=True)
    s.add_argument("--channel", default="beta")
    s.add_argument("--component", required=True)
    s.add_argument("--version", required=True)
    s.add_argument("--src", required=True)
    s.add_argument("--entry")
    s.add_argument("--notes", default="")
    s.add_argument("--platform", default="any")
    s.add_argument("--min-launcher")
    s.add_argument("--installer", help="first-install file offered on the website downloads page")
    s.add_argument("--layout", default="tree", choices=list(pub.LAYOUTS))
    s.add_argument("--ttl-days", type=int, default=60)
    s.add_argument("--withdraw", action="append", default=[], help="a version of this component to withdraw")
    s.add_argument("--allow-downgrade", action="store_true")
    s.add_argument("--key")

    s = sub.add_parser("promote")
    s.add_argument("--root", required=True)
    s.add_argument("--from", dest="src", default="beta")
    s.add_argument("--to", default="stable")
    s.add_argument("--component", action="append")
    s.add_argument("--layout", default="tree", choices=list(pub.LAYOUTS))
    s.add_argument("--ttl-days", type=int, default=60)
    s.add_argument("--key")

    s = sub.add_parser("verify")
    s.add_argument("--root", required=True)
    s.add_argument("--channel", default="stable")
    s.add_argument("--layout", default="tree", choices=list(pub.LAYOUTS))
    s.add_argument("--trust")

    s = sub.add_parser("serve")
    s.add_argument("--dir", required=True)
    s.add_argument("--port", type=int, default=8099)
    s.add_argument("--bind", default="127.0.0.1")

    for name in ("check", "install", "rollback", "status"):
        s = sub.add_parser(name)
        s.add_argument("--url")
        s.add_argument("--home", required=True)
        s.add_argument("--channel", default="stable")
        s.add_argument("--layout", default="tree", choices=list(pub.LAYOUTS))
        s.add_argument("--trust")
        s.add_argument("--launcher-version", default="0.0.0")
        if name in ("install", "rollback"):
            s.add_argument("--component", required=True)

    s = sub.add_parser("forge-upload")
    s.add_argument("--forge", required=True)
    s.add_argument("--repo", required=True)
    s.add_argument("--tag", required=True)
    s.add_argument("--dir", required=True)
    s.add_argument("--token-file", required=True)

    a = p.parse_args(argv)
    try:
        if a.cmd == "keygen":
            info = generate(Path(a.key) if a.key else default_key_path())
            if a.write_trust:
                info["trust_file"] = str(write_trust(info["public"], a.note))
            info["next"] = "Back this file up somewhere offline. Without it you cannot sign updates or rotate keys."
            _out(info)
        elif a.cmd == "publish":
            key = load_private(Path(a.key) if a.key else None)
            root = Path(a.root)
            comp = pub.build_component(root, a.component, a.version, Path(a.src), layout=a.layout, entry=a.entry,
                                       notes=a.notes, platform=a.platform, min_launcher=a.min_launcher,
                                       installer=Path(a.installer) if a.installer else None)
            m = pub.publish(root, a.channel, {a.component: comp}, key, layout=a.layout, ttl_days=a.ttl_days,
                            withdraw={a.component: a.withdraw} if a.withdraw else None,
                            allow_downgrade=a.allow_downgrade)
            _out({"channel": a.channel, "sequence": m["sequence"], "expires": m["expires"],
                  "component": a.component, "version": a.version, "bytes": comp["size"], "signed_by": key.keyid})
        elif a.cmd == "promote":
            key = load_private(Path(a.key) if a.key else None)
            m = pub.promote(Path(a.root), a.src, a.to, a.component, key, layout=a.layout, ttl_days=a.ttl_days)
            _out({"channel": a.to, "sequence": m["sequence"],
                  "components": {n: c["version"] for n, c in m["components"].items()}})
        elif a.cmd == "verify":
            m = pub.verify_tree(Path(a.root), a.channel, TrustStore.load(Path(a.trust) if a.trust else None), a.layout)
            _out({"ok": True, "channel": a.channel, "sequence": m["sequence"], "expires": m["expires"],
                  "components": {n: c["version"] for n, c in m["components"].items()}})
        elif a.cmd == "serve":
            from .server import start
            server, base = start(Path(a.dir), a.port, a.bind)
            print(f"serving {a.dir} at {base} (Ctrl+C to stop)", flush=True)
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                server.shutdown()
        elif a.cmd == "check":
            _out(_updater(a).check())
        elif a.cmd == "status":
            _out(_updater(a).status())
        elif a.cmd == "install":
            r = _updater(a).update(a.component, progress=lambda e: print(json.dumps(e), file=sys.stderr))
            _out(r)
            return 0 if r["ok"] else 1
        elif a.cmd == "rollback":
            r = _updater(a).rollback(a.component, reason="rolled back from the command line")
            _out(r)
            return 0 if r["ok"] else 1
        elif a.cmd == "forge-upload":
            _out(forge.upload_release(a.forge, Path(a.token_file), a.repo, a.tag, Path(a.dir)))
    except (SigningKeyError, ManifestError, UpdateError, forge.ForgeError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
