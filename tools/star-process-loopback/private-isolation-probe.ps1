# DOUBLE-OPT-IN, owner-run private differential process-loopback rehearsal.
# Both observers target OUR OWN disposable children. One renders a quiet tone;
# the other is an unrelated silent process. No mic, game, OBS or broadcast.
param(
    [switch]$OwnerApproved,
    [switch]$AllowAudibleTone,
    [ValidateRange(2600, 3200)][int]$DurationMs = 3000
)
$ErrorActionPreference = 'Stop'
if (-not $OwnerApproved -or -not $AllowAudibleTone) {
    throw 'Explicit owner opt-in (-OwnerApproved -AllowAudibleTone) is required.'
}
if (-not $IsWindows -and $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Private Windows-only process loopback.'
}
if ([Environment]::OSVersion.Version.Build -lt 20348) {
    throw 'Windows process-specific loopback requires build 20348+.'
}
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue) -or
    -not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw '.NET 9 SDK and Python 3.12+ are required for owner-run isolation audit.'
}
$root = $PSScriptRoot
$repo = (Resolve-Path (Join-Path $root '../..')).Path
$items = @(
    (Join-Path $root 'Program.cs'),
    (Join-Path $root 'Star.ProcessLoopback.csproj'),
    (Join-Path $root 'tone-fixture/Program.cs'),
    (Join-Path $root 'tone-fixture/Star.ToneFixture.csproj'),
    (Join-Path $repo 'star/process_loopback_activity.py'),
    (Join-Path $repo 'star/process_loopback_isolation_audit.py')
)
foreach ($path in $items) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw 'Dedicated diagnostic, tone fixture or offline auditor source is missing.'
    }
}
$work = Join-Path ([IO.Path]::GetTempPath()) ('star-paired-loopback-' + [guid]::NewGuid().ToString('N'))
$diag = Join-Path $work 'native'
$tone = Join-Path $work 'tone'
$silent = Join-Path $work 'silent'
$pythonRoot = Join-Path $work 'audit'
$pythonPackage = Join-Path $pythonRoot 'star'
$bundle = Join-Path $work 'trace'
$toneProcess = $null
$silentProcess = $null
$positiveCapture = $null
$negativeCapture = $null
$oldPythonPath = $env:PYTHONPATH
try {
    New-Item -ItemType Directory -Force -Path $diag, $tone, $silent, $pythonPackage, $bundle | Out-Null
    Copy-Item -LiteralPath (Join-Path $root 'Program.cs') -Destination $diag
    Copy-Item -LiteralPath (Join-Path $root 'Star.ProcessLoopback.csproj') -Destination $diag
    Copy-Item -LiteralPath (Join-Path $root 'tone-fixture/Program.cs') -Destination $tone
    Copy-Item -LiteralPath (Join-Path $root 'tone-fixture/Star.ToneFixture.csproj') -Destination $tone
    Copy-Item -LiteralPath (Join-Path $repo 'star/process_loopback_activity.py') -Destination $pythonPackage
    Copy-Item -LiteralPath (Join-Path $repo 'star/process_loopback_isolation_audit.py') -Destination $pythonPackage
    Set-Content -LiteralPath (Join-Path $pythonPackage '__init__.py') -Value '' -Encoding UTF8

    # Builds are disposable and do not install packages into Star's runtime.
    $silenceProject = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net9.0</TargetFramework><AssemblyName>StarSilentControl</AssemblyName><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>'
    Set-Content -LiteralPath (Join-Path $silent 'StarSilentControl.csproj') -Value $silenceProject -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $silent 'Program.cs') -Value 'System.Threading.Thread.Sleep(8000);' -Encoding UTF8
    foreach ($project in @(
        (Join-Path $diag 'Star.ProcessLoopback.csproj'),
        (Join-Path $tone 'Star.ToneFixture.csproj'),
        (Join-Path $silent 'StarSilentControl.csproj')
    )) {
        & dotnet build $project -c Release -v:q --nologo | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Disposable diagnostic/control build failed.' }
    }
    $nativeDll = Join-Path $diag 'bin/Release/net9.0/Star.ProcessLoopback.dll'
    $toneExe = Join-Path $tone 'bin/Release/net9.0/StarToneProbe.exe'
    $toneDll = Join-Path $tone 'bin/Release/net9.0/StarToneProbe.dll'
    $silentExe = Join-Path $silent 'bin/Release/net9.0/StarSilentControl.exe'
    foreach ($path in @($nativeDll, $toneExe, $toneDll, $silentExe)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw 'Expected private control binary missing.'
        }
    }
    $selfTest = @(& dotnet $toneDll --self-test)
    if ($LASTEXITCODE -ne 0 -or $selfTest.Count -ne 1 -or
        $selfTest[0] -notmatch '"audio_playback_started":false') {
        throw 'Tone waveform self-test must pass without opening an audio output.'
    }
    # Only this script's fresh, unrelated child-process identities are observed.
    $silentProcess = Start-Process -FilePath $silentExe -PassThru -WindowStyle Hidden
    $toneProcess = Start-Process -FilePath $toneExe -ArgumentList @(
        '--play-test-tone', '--owner-approved', '--paired-lead-in'
    ) -PassThru -WindowStyle Hidden

    $positivePath = Join-Path $bundle 'positive.jsonl'
    $negativePath = Join-Path $bundle 'negative.jsonl'
    $positiveErr = Join-Path $work 'positive.err'
    $negativeErr = Join-Path $work 'negative.err'
    # Captures start before the fixture's delayed short tone. Both capture
    # processes run concurrently; a sequential comparison would be invalid.
    $positiveCapture = Start-Process -FilePath 'dotnet' -ArgumentList @(
        ('"' + $nativeDll + '"'), '--observe', '--pid', $toneProcess.Id,
        '--expect-exe', 'StarToneProbe.exe', '--duration-ms', $DurationMs
    ) -PassThru -WindowStyle Hidden -RedirectStandardOutput $positivePath -RedirectStandardError $positiveErr
    $negativeCapture = Start-Process -FilePath 'dotnet' -ArgumentList @(
        ('"' + $nativeDll + '"'), '--observe', '--pid', $silentProcess.Id,
        '--expect-exe', 'StarSilentControl.exe', '--duration-ms', $DurationMs
    ) -PassThru -WindowStyle Hidden -RedirectStandardOutput $negativePath -RedirectStandardError $negativeErr

    if (-not $positiveCapture.WaitForExit(7000) -or
        -not $negativeCapture.WaitForExit(7000)) {
        throw 'Timed out waiting for independent native process captures.'
    }
    if ($positiveCapture.ExitCode -ne 0 -or $negativeCapture.ExitCode -ne 0) {
        throw 'Native capture process exited nonzero; paired evidence untrusted.'
    }
    # Stop audible control as soon as both probes complete, before parsing.
    Stop-Process -Id $toneProcess.Id -Force -ErrorAction SilentlyContinue
    $env:PYTHONPATH = $pythonRoot
    & python -m star.process_loopback_isolation_audit --bundle-dir $bundle --owner-approved
    if ($LASTEXITCODE -ne 0) {
        throw 'Offline isolation trace comparison invalid or inconclusive.'
    }
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    foreach ($child in @($positiveCapture, $negativeCapture, $toneProcess, $silentProcess)) {
        if ($null -ne $child) {
            Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue
        }
    }
    # No PCM is written: JSONL window summaries and build files are ephemeral.
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
