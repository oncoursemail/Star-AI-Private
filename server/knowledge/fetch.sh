#!/bin/bash
# Fetch (or update) the licensed documentation repositories listed in corpora.json.
# Shallow clones only (depth 1). Run inside the container as user `star`:
#   runuser -u star -- bash /opt/star/knowledge/app/fetch.sh
# Prints "<name> <commit> <commit date>" per source. Re-run to update; then `python -m starkb build`
# and `python -m starkb embed` (only chunks whose text changed are embedded again).
set -eu
HOME_DIR="${STAR_KB_HOME:-/opt/star/knowledge}"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME_DIR/sources"
python3 - "$APP_DIR/corpora.json" <<'PY' | while read -r NAME REPO BRANCH; do
import json, sys
seen = set()
for s in json.load(open(sys.argv[1], encoding="utf-8"))["sources"]:
    checkout = s.get("checkout", s["name"])
    if s.get("kind", "git") != "git" or checkout in seen:
        continue   # fetched pages have their own fetcher; one checkout may serve two sources
    seen.add(checkout)
    print(checkout, s["repo"], s["branch"])
PY
  # One checkout is a work unit; use the same stale-aware lock check as Python jobs.
  PYTHONPATH="$APP_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -m starkb.quiet
  DEST="$HOME_DIR/sources/$NAME"
  if [ -d "$DEST/.git" ]; then
    git -C "$DEST" fetch --quiet --depth 1 origin "$BRANCH"
    git -C "$DEST" reset --quiet --hard FETCH_HEAD
  else
    git clone --quiet --depth 1 --branch "$BRANCH" "$REPO" "$DEST"
  fi
  echo "$NAME $(git -C "$DEST" rev-parse HEAD) $(git -C "$DEST" log -1 --format=%cI)"
done
