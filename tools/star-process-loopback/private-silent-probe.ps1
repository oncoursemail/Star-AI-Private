# Owner-initiated private Windows process-loopback activation probe.
# This launches ONLY a purpose-built silent StarVoiceProbe.exe subprocess.
# NO audio, microphone, game, OBS, broadcast or third-party app is opened.
param(
    [switch]$OwnerApproved,
    [ValidateRange(300, 2000)][int]$DurationMs = 900
)
$ErrorActionPreference = 'Stop'
if (-not $OwnerApproved) { throw 'Explicit owner opt-in (-OwnerApproved) is required.' }
if (-not $IsWindows -and $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Windows is required.'
}
if ([Environment]::OSVersion.Version.Build -lt 20348) {
    throw 'Windows process loopback requires build 20348+.'
}
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw '.NET 9 SDK is required.'
}
if (-not (Test-Path (Join-Path $PSScriptRoot 'Program.cs')) -or
    -not (Test-Path (Join-Path $PSScriptRoot 'Star.ProcessLoopback.csproj'))) {
    throw 'Run next to the native diagnostic project.'
}
$work = Join-Path ([IO.Path]::GetTempPath()) ('star-private-loopback-' + [guid]::NewGuid().ToString('N'))
$diagDir = Join-Path $work 'diagnostic'
$probeDir = Join-Path $work 'probe'
$target = $null
try {
    New-Item -Path $diagDir, $probeDir -ItemType Directory -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Program.cs') -Destination $diagDir
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Star.ProcessLoopback.csproj') -Destination $diagDir
    # A no-microphone, no-speaker, no-network 6s fixture.
    $fixtureProject = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net9.0</TargetFramework><AssemblyName>StarVoiceProbe</AssemblyName><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>'
    Set-Content -LiteralPath (Join-Path $probeDir 'StarVoiceProbe.csproj') -Value $fixtureProject -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $probeDir 'Program.cs') -Value 'System.Threading.Thread.Sleep(6000);' -Encoding UTF8
    & dotnet build (Join-Path $probeDir 'StarVoiceProbe.csproj') -c Release -v:q --nologo | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Silent fixture build failed.' }
    & dotnet build (Join-Path $diagDir 'Star.ProcessLoopback.csproj') -c Release -v:q --nologo | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Diagnostic build failed.' }
    $fixture = Join-Path $probeDir 'bin/Release/net9.0/StarVoiceProbe.exe'
    $native = Join-Path $diagDir 'bin/Release/net9.0/Star.ProcessLoopback.dll'
    if (-not (Test-Path -LiteralPath $fixture) -or -not (Test-Path -LiteralPath $native)) {
        throw 'Expected private probe executables were not produced.'
    }
    $target = Start-Process -FilePath $fixture -PassThru -WindowStyle Hidden
    # Invoke only against the child started above; never a user-supplied PID.
    $raw = @(& dotnet $native --observe --pid $target.Id --expect-exe StarVoiceProbe.exe --duration-ms $DurationMs)
    if ($LASTEXITCODE -ne 0) { throw 'Native process-loopback capture failed.' }
    if ($raw.Count -lt 3 -or $raw.Count -gt 100) { throw 'Unexpected diagnostic record count.' }
    $priorCallbacks = 0L
    $priorFrames = 0L
    $pcmWindows = 0
    $unknownWindows = 0
    $lastElapsed = -1
    $rows = @($raw | ForEach-Object { $_ | ConvertFrom-Json })
    if ($rows[0].state -ne 'capture_started' -or
        $rows[$rows.Count - 1].state -ne 'capture_complete_no_silence_claim') {
        throw 'Native capture did not complete a proper diagnostic sequence.'
    }
    for ($i = 0; $i -lt $rows.Count; $i++) {
        $row = $rows[$i]
        if ($row.schema -ne 'star.process_loopback.diagnostic.v1' -or
            $row.verified_silence -ne $false -or
            $row.broadcast_authorized -ne $false -or
            $row.gameplay_authorized -ne $false -or
            $row.activity_is_audio_observation_only -ne $true -or
            $row.bad_packets -ne 0) {
            throw 'Invalid or authority-claiming process diagnostic.'
        }
        if ($row.elapsed_ms -lt $lastElapsed -or
            $row.callback_generation -lt $priorCallbacks -or
            $row.sample_frames -lt $priorFrames -or
            ($row.callback_generation - $priorCallbacks) -ne $row.activity_callbacks -or
            ($row.sample_frames - $priorFrames) -ne $row.activity_sample_frames) {
            throw 'Inconsistent native interval activity evidence.'
        }
        if ($i -gt 0) {
            if ($row.activity_callbacks -gt 0) { $pcmWindows++ }
            else { $unknownWindows++ }
        }
        $lastElapsed = $row.elapsed_ms
        $priorCallbacks = $row.callback_generation
        $priorFrames = $row.sample_frames
    }
    # This fixture never intentionally generates sound. In some Windows
    # configurations process-loopback still delivers *zero-amplitude PCM*.
    # Neither present nor absent callback data proves physical silence.
    [pscustomobject]@{
        status = 'private_native_activation_observed'
        duration_requested_ms = $DurationMs
        diagnostic_records = $rows.Count
        callback_count = $priorCallbacks
        sample_frames = $priorFrames
        pcm_windows = $pcmWindows
        missing_pcm_windows = $unknownWindows
        maximum_peak_milli = $rows[$rows.Count - 1].max_peak_milli
        audio_playback_tested = $false
        silence_verified = $false
        streaming_authorized = $false
        actual_gameplay_tested = $false
    } | ConvertTo-Json -Compress
}
finally {
    if ($null -ne $target) {
        Stop-Process -Id $target.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}