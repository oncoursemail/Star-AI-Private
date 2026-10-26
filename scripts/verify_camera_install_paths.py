"""Check real camera-installer preview paths against runtime resolution; no installation or migration."""
from __future__ import annotations

import os
import ctypes
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.vtuber.control import data_dir  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "installer" / "star-camera" / "install-camera.ps1"


def literal(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def preview(root: Path, override: Path | None, unrelated_programdata: Path, *, existing: bool, uninstall: bool = False) -> Path:
    powershell = shutil.which("powershell")
    if not powershell:
        raise RuntimeError("Windows PowerShell is required for the installer preview verification")
    source = rf"""
$ErrorActionPreference = 'Stop'
$env:STAR_VTUBER_DIR = {literal(override or '')}
$env:ProgramData = {literal(unrelated_programdata)}
$tokens=$null; $errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile({literal(SCRIPT)},[ref]$tokens,[ref]$errors)
if ($errors.Count) {{ throw ($errors | Out-String) }}
$uninstallNode=$tree.Find({{param($node) $node -is [Management.Automation.Language.IfStatementAst] -and $node.Extent.Text.StartsWith('if ($Uninstall) {{')}},$true)
if ($uninstallNode.FindAll({{param($node) $node -is [Management.Automation.Language.CommandAst] -and $node.InvocationOperator -eq [Management.Automation.Language.TokenKind]::Ampersand}},$true).Count) {{ throw 'Unsafe direct native invocation in uninstall preview' }}
foreach ($name in @('New-Item','Set-Content','Copy-Item','Move-Item','Remove-Item','Start-Process','Invoke-WebRequest')) {{
    Set-Item -Path "function:$name" -Value {{ throw 'MUTATION in camera preview' }}
}}
. {literal(SCRIPT)} -Root {literal(root)} -DryRun {'-Uninstall' if uninstall else ''}
if ({'$true' if existing else '$false'}) {{
    $guard=$tree.Find({{param($node)
        $node -is [Management.Automation.Language.IfStatementAst] -and
        $node.Extent.Text.StartsWith('if (-not (Test-Path "$Data\config.json"))')
    }},$true)
    if (-not $guard) {{ throw 'Existing camera configuration guard is missing' }}
    . ([scriptblock]::Create($guard.Extent.Text))
}}
[Console]::WriteLine('SELECTED_DATA:' + $Data)
"""
    result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", source],
                            capture_output=True, text=True, timeout=45, cwd=REPO,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    selected = [line.removeprefix("SELECTED_DATA:") for line in result.stdout.splitlines()
                if line.startswith("SELECTED_DATA:")]
    assert len(selected) == 1, result.stdout
    assert ("would unregister both camera filters" if uninstall else "camera config and status folder:") in result.stdout
    return Path(selected[0])


def windows_arguments(executable: str, arguments: list[str]) -> list[str]:
    api = getattr(ctypes, "windll")
    shell = api.shell32
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    count = ctypes.c_int()
    parsed = shell.CommandLineToArgvW(subprocess.list2cmdline([executable]) + " " + " ".join(arguments), ctypes.byref(count))
    if not parsed:
        raise OSError("Windows argument parser failed")
    try:
        return [parsed[i] for i in range(count.value)][1:]
    finally:
        api.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        api.kernel32.LocalFree(parsed)


def verify_registration(root: Path) -> None:
    powershell = shutil.which("powershell")
    assert powershell is not None
    folder = root / "camera" / "unitycapture"
    folder.mkdir(parents=True)
    for bitness in (32, 64):
        (folder / f"UnityCaptureFilter{bitness}.dll").write_bytes(b"offline fixture, never loaded")
    source = rf"""
$ErrorActionPreference = 'Stop'
$env:STAR_VTUBER_DIR = ''
$tokens=$null; $errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile({literal(SCRIPT)},[ref]$tokens,[ref]$errors)
if ($errors.Count) {{ throw ($errors | Out-String) }}
$helper=$tree.Find({{param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-CameraRegsvr32'}},$true)
$uninstallNode=$tree.Find({{param($node) $node -is [Management.Automation.Language.IfStatementAst] -and $node.Extent.Text.StartsWith('if ($Uninstall) {{')}},$true)
$text=Get-Content -LiteralPath {literal(SCRIPT)} -Raw
$start=$text.IndexOf('# Same call as Unity Capture')
$end=$text.IndexOf('if (-not (Test-Path "$Venv\Scripts\python.exe"))')
if (-not $helper -or -not $uninstallNode -or $start -lt 0 -or $end -le $start) {{ throw 'Registration blocks missing' }}
$registration=$text.Substring($start,$end-$start)
foreach($block in @($helper.Extent.Text,$uninstallNode.Extent.Text,$registration)) {{
    $parsed=[Management.Automation.Language.Parser]::ParseInput($block,[ref]$tokens,[ref]$errors)
    if ($errors.Count -or $parsed.FindAll({{param($node) $node -is [Management.Automation.Language.CommandAst] -and $node.InvocationOperator -eq [Management.Automation.Language.TokenKind]::Ampersand}},$true).Count) {{ throw 'Unsafe direct native invocation in fixture' }}
}}
foreach ($name in @('New-Item','Set-Content','Copy-Item','Move-Item','Remove-Item','Start-Process','Invoke-WebRequest')) {{
    Set-Item -Path "function:$name" -Value {{ throw 'MUTATION in camera fixture' }}
}}
. {literal(SCRIPT)} -Root {literal(root)} -DryRun
function Start-Process {{
    param($FilePath,[string[]]$ArgumentList,$WindowStyle,[switch]$Wait,[switch]$PassThru)
    $script:Calls += [pscustomobject]@{{Exe=$FilePath;Args=@($ArgumentList);Style=$WindowStyle;Wait=[bool]$Wait;Pass=[bool]$PassThru}}
    if (-not $script:Codes.Count) {{ throw 'Unexpected extra native invocation' }}
    [pscustomobject]@{{ExitCode=$script:Codes.Dequeue()}}
}}
$results=@()
foreach($case in @(
    @{{Mode='register';Codes=@(0,0)}}, @{{Mode='register';Codes=@(5)}},
    @{{Mode='register';Codes=@(0,7)}}, @{{Mode='register';Codes=@($null)}},
    @{{Mode='uninstall';Codes=@(0,0)}}, @{{Mode='uninstall';Codes=@(5,7)}},
    @{{Mode='uninstall';Codes=@($null)}})) {{
    $script:Calls=@(); $script:Codes=New-Object System.Collections.Queue
    foreach($code in $case.Codes) {{ $script:Codes.Enqueue($code) }}
    $global:LASTEXITCODE=99
    $caught=$false; $detail=''; $warnings=@(); $DryRun=$false
    try {{
        if ($case.Mode -eq 'uninstall') {{ $Uninstall=$true; & ([scriptblock]::Create($uninstallNode.Extent.Text)) }}
        else {{ $warnings=@(& ([scriptblock]::Create($registration)) 3>&1 | Where-Object {{ $_ -is [Management.Automation.WarningRecord] }}) }}
    }} catch {{ $caught=$true; $detail=$_.Exception.Message }}
    $results += [pscustomobject]@{{Mode=$case.Mode;Threw=$caught;Detail=$detail;Warnings=$warnings.Count;Calls=@($script:Calls)}}
}}
[Console]::WriteLine('REG_RESULTS:' + (ConvertTo-Json -InputObject @($results) -Depth 6 -Compress))
"""
    result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", source], capture_output=True,
                            text=True, timeout=45, cwd=REPO,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line.removeprefix("REG_RESULTS:") for line in result.stdout.splitlines() if line.startswith("REG_RESULTS:")]
    assert len(lines) == 1, result.stdout
    results = json.loads(lines[0])
    assert [case["Threw"] for case in results] == [False, True, False, True, False, True, True], results
    assert [len(case["Calls"]) for case in results] == [2, 1, 2, 1, 2, 2, 1]
    assert results[2]["Warnings"] == 1
    assert "exit 5" in results[1]["Detail"]
    assert "exit code" in results[3]["Detail"] and "unknown" in results[3]["Detail"]
    for case in results:
        for index, call in enumerate(case["Calls"]):
            bitness = 64 if index == 0 else 32
            assert Path(call["Exe"]).parent.name.lower() == ("system32" if bitness == 64 else "syswow64")
            assert call["Style"] == "Hidden" and call["Wait"] and call["Pass"]
            expected = ["/s"] + (["/u"] if case["Mode"] == "uninstall" else [])
            expected += [str(folder / f"UnityCaptureFilter{bitness}.dll")]
            if case["Mode"] == "register":
                expected += ["/i:UnityCaptureName=STAR Camera"]
            assert windows_arguments(call["Exe"], call["Args"]) == expected
    preview(root, None, root / "unused ProgramData", existing=False, uninstall=True)
    assert all((folder / f"UnityCaptureFilter{bits}.dll").read_bytes() == b"offline fixture, never loaded" for bits in (32, 64))


def main() -> None:
    with TemporaryDirectory(prefix="star-camera-paths-") as temp:
        base = Path(temp)
        unrelated = base / "unrelated ProgramData"
        cases = [(base / "fresh install", None, False),
                 (base / "Star's install", None, True),
                 (base / "another root", base / "Star's selected camera", True),
                 (base / "root without camera", base / "new override", False)]
        for root, override, existing in cases:
            with patch.dict(os.environ, {"STAR_ROOT": str(root), "STAR_VTUBER_DIR": str(override or "")}):
                expected = data_dir()
            config = expected / "config.json"
            if existing:
                expected.mkdir(parents=True)
                config.write_bytes(b'{"backend":"obs","mode":"cat","owner_setting":"keep"}\n')
            original = (config.read_bytes(), config.stat().st_mtime_ns) if existing else None
            selected = preview(root, override, unrelated, existing=existing)
            assert selected == expected, (selected, expected)
            if existing:
                assert (config.read_bytes(), config.stat().st_mtime_ns) == original
            else:
                assert not expected.exists(), "preview created the camera data folder"
            assert not (root / "camera").exists(), "preview installed driver files"
            assert not unrelated.exists(), "camera setup touched the unrelated ProgramData folder"
        verify_registration(base / "Star's registration path")
        print("Camera installer verified: four path previews; configs kept; seven awaited reg/unreg outcome cases; Windows argv quoting; uninstall preview inert")


if __name__ == "__main__":
    main()
