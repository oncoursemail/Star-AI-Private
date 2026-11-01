# Historical artifact import (November 1, 2026)

This is the complete unpacked October 30 performance audit archive, with three technical files redacted to replace personal filesystem locations. Source and test code remain unchanged. The original manifest is preserved as `MANIFEST.original.sha256`; its three redacted files will not match the old checksums. The publication manifest outside this folder describes the files being published.

Historical descriptions such as "not in GitHub", "private repository", "no Rust tracked", and project naming reflect the original inspection and must not be read as current status. The repository is now `oncoursemail/Star-AI-Project` (public); PR #849 is merged into `star/next` and implements an opt-in resident dense index. The CLI rank-fusion experiment here is NOT that backend.

The original bridge before the reviewed fixes is recoverable by applying `bridge-review.patch` in reverse to a copy of `litha-bridge-reviewed/`. Keep it out of production. The reviewed directory is the candidate version; its nested `.github/workflows` file is an archived proposal, not a workflow activated in the repository root.

No models, user conversations, credentials, binaries, caches, or service settings are included. Historical test logs are explicitly separated from fresh validation records.
