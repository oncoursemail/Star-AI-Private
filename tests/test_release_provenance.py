"""Static fail-closed checks for STAR's trusted release provenance boundary."""
from pathlib import Path
import re


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "windows-desktop.yml"


def _jobs():
    source = WORKFLOW.read_text(encoding="utf-8")
    build = source.split("\n  attest-release:", 1)[0]
    attest = source.split("\n  attest-release:", 1)[1].split("\n  publish-release:", 1)[0]
    publish = source.split("\n  publish-release:", 1)[1]
    return build, attest, publish


def test_pr_windows_build_never_receives_publish_or_attestation_tokens():
    build, attest, publish = _jobs()
    assert "pull_request:" in build
    permissions = build.split("\n  windows-build:", 1)[1].split("\n    steps:", 1)[0]
    assert "contents: read" in permissions
    assert "contents: write" not in permissions
    assert "id-token: write" not in permissions
    assert "attestations: write" not in permissions
    assert "attestations: write" in attest
    assert "contents: write" in publish


def test_attestation_is_main_only_and_producer_is_trusted():
    _build, attest, publish = _jobs()
    # The release is attested only after the build, the Windows tests AND the Linux React validation passed.
    assert "needs: [windows-build, windows-tests, frontend]" in attest
    assert "if: github.ref == 'refs/heads/main'" in attest
    assert re.search(r"actions/download-artifact@[0-9a-f]{40} # v8\.", attest)  # pinned commit
    assert "name: STAR-Windows-vNext" in attest
    assert re.search(r"actions/attest@[0-9a-f]{40} # v4\.", attest)  # pinned commit
    assert "subject-path: 'attest-ready/*'" in attest
    assert "needs: [windows-build, attest-release]" in publish
    assert "if: github.ref == 'refs/heads/main'" in publish


def test_both_artifacts_require_exact_source_and_signer_before_publish():
    _build, attest, publish = _jobs()
    verify = publish.index('gh attestation verify "$artifact"')
    create = publish.index('gh release create "$TAG"')
    assert verify < create
    assert '"release-ready/STAR-Setup-$TAG.exe"' in publish
    assert '"release-ready/STAR-Genesis-Windows-x64.zip"' in publish
    assert '--repo "$STAR_REPO"' in publish
    assert '--signer-workflow "$STAR_REPO/.github/workflows/windows-desktop.yml"' in publish
    assert '--source-digest "$STAR_COMMIT"' in publish
    assert '--source-ref "refs/heads/main"' in publish
    assert "attestations: read" in publish
    assert "gh release view " in publish  # existing tags remain immutable by policy
