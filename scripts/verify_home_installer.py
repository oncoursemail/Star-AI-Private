"""Exercise installer preview and failed package verification without installing anything."""
from pathlib import Path
import subprocess
import tempfile


REPO = Path(__file__).resolve().parents[1]
SETUP = REPO / "installer/star-home/setup.ps1"


def run_ps(source: str) -> str:
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", source],
                            capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


def literal(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="star-setup-check-") as temp:
        root = Path(temp) / "Star's PC" / "not-created"
        # Any mutation in uninstall preview fails before reaching an actual Windows operation.
        out = run_ps(f"""
$ErrorActionPreference = 'Stop'
function Unregister-ScheduledTask {{ throw 'MUTATION: unregister' }}
function Remove-Item {{ throw 'MUTATION: remove' }}
function Start-Process {{ throw 'MUTATION: launch' }}
& {literal(SETUP)} -Root {literal(root)} -DryRun -Uninstall
""")
        assert "dry-run" in out.lower() and "keep all data" in out
        assert not root.exists()
        # Extract the real installer function through its syntax tree, then inject a failing pip.
        out = run_ps(f"""
$ErrorActionPreference = 'Stop'
$tokens=$null; $errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile({literal(SETUP)},[ref]$tokens,[ref]$errors)
if ($errors.Count) {{ throw ($errors | Out-String) }}
$node=$tree.Find({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Install-Pinned'}},$true)
. ([scriptblock]::Create($node.Extent.Text))
$script:count=0; $script:seen=@(); $VenvPy='unused-python'
function Run-Native {{ param($Exe,$Arguments); $script:count++; $script:seen=$Arguments; @{{Code=1;Output='hash mismatch'}} }}
$caught=$false
try {{ Install-Pinned 'missing-lock-file.txt' 'fixture' }} catch {{ $caught=$true }}
if (-not $caught -or $script:count -ne 1 -or $script:seen -notcontains '--require-hashes') {{ throw 'Unverified retry or missing hash enforcement' }}
'failed pip stopped after one verified attempt'
""")
        assert "one verified attempt" in out
        # Full preview: stub mutation commands, retain real control flow and read-only system probes.
        out = run_ps(f"""
$ErrorActionPreference = 'Stop'
foreach ($name in @('New-Item','Set-Content','Copy-Item','Remove-Item','Move-Item','Start-Process',
    'Invoke-WebRequest','Start-Transcript','Register-ScheduledTask','Unregister-ScheduledTask',
    'Start-ScheduledTask','robocopy')) {{ Set-Item -Path "function:$name" -Value {{ throw 'MUTATION in preview' }} }}
& {literal(SETUP)} -Root {literal(root)} -DryRun -Yes -Grounder none
""")
        assert "0 failed step(s)" in out, out
        assert not root.exists()
    print("Installer verified: PowerShell syntax, uninstall preview, full preview, hash failure stops without retry")


if __name__ == "__main__":
    main()
