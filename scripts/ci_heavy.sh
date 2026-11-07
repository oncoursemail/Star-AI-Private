#!/bin/sh
# Run one heavy CI command (test suite, frontend build, type check).
# On the shared self-hosted machine (brain 2 container ci-runner: the GitHub and the Forgejo runner side by side)
# /var/lib/ci-heavy/heavy.lock exists, and only one heavy command at a time runs there across both runners.
# Anywhere else (a hosted runner, a developer PC) the command just runs.
lock=/var/lib/ci-heavy/heavy.lock
if [ -w "$lock" ] && command -v flock >/dev/null 2>&1; then
  echo "ci_heavy: $(date -u +%H:%M:%S) waiting for $lock" >&2
  exec flock "$lock" sh -c 'echo "ci_heavy: $(date -u +%H:%M:%S) lock held" >&2; exec "$@"' ci_heavy "$@"
fi
exec "$@"
