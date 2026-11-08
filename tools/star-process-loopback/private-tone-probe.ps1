# Private POSITIVE control for Windows process-isolated loopback.
# Explicitly plays a short quiet 440Hz test tone from OUR OWN child process.
# No game, microphone, OBS, speech, browser, user audio or broadcast.
param(
    [switch]$OwnerApproved,
    [switch]$AllowAudibleTone,
    [ValidateRange(1000, 2200)][int]$DurationMs = 1800
)
$ErrorActionPreference = 'Stop'
if (-not $OwnerApproved -or -not $AllowAudibleTone) {
    throw 'Explicit owner opt-in (-OwnerApproved -AllowAudibleTone) is required.'
}
if (-not $IsWindows -and $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Windows is required.'
}
if ([Environment]::OSVersion.Version.Build -lt 20348) {
    throw 'Windows process loopback requires build 20348+.'
}
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw '.NET 9 SDK is required.'
}
$root = $PSScriptRoot
$fixtureSource = Join-Path $root 'tone-fixture'
foreach ($path in @((Join-Path $root 'Program.cs'),
                   (Join-Path $root 'Star.ProcessLoopback.csproj'),
                   (Join-Path $fixtureSource 'Program.cs'),
                   (Join-Path $fixtureSource 'Star.ToneFixture.csproj'))) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw 'Private fixture source or native diagnostic missing.'
    }
}
$work = Join-Path ([IO.Path]::GetTempPath()) ('star-tone-loopback-' + [guid]::NewGuid().ToString('N'))
$diagDir = Join-Path $work 'diagnostic'
$fixtureDir = Join-Path $work 'tone'
$target = $null
try {
    New-Item -Path $diagDir, $fixtureDir -ItemType Directory -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root 'Program.cs') -Destination $diagDir
    Copy-Item -LiteralPath (Join-Path $root 'Star.ProcessLoopback.csproj') -Destination $diagDir
    Copy-Item -LiteralPath (Join-Path $fixtureSource 'Program.cs') -Destination $fixtureDir
    Copy-Item -LiteralPath (Join-Path $fixtureSource 'Star.ToneFixture.csproj') -Destination $fixtureDir
    & dotnet build (Join-Path $fixtureDir 'Star.ToneFixture.csproj') -c Release -v:q --nologo | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Private tone fixture build failed.' }
    & dotnet build (Join-Path $diagDir 'Star.ProcessLoopback.csproj') -c Release -v:q --nologo | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Native diagnostic build failed.' }
    $fixture = Join-Path $fixtureDir 'bin/Release/net9.0/StarToneProbe.exe'
    $native = Join-Path $diagDir 'bin/Release/net9.0/Star.ProcessLoopback.dll'
    if (-not (Test-Path -LiteralPath $fixture -PathType Leaf) -or
        -not (Test-Path -LiteralPath $native -PathType Leaf)) {
        throw 'Expected short-lived private test binaries missing.'
    }
    $selfTest = @(& dotnet (Join-Path $fixtureDir 'bin/Release/net9.0/StarToneProbe.dll') --self-test)
    if ($LASTEXITCODE -ne 0 -or
        $selfTest.Count -ne 1 -or
        $selfTest[0] -notmatch '"audio_playback_started":false') {
        throw 'Test-tone fixture failed non-playing deterministic self-test.'
    }
    # Only an isolated, short-lived child of this script can be observed.
    # No externally supplied PID, executable, path or audio source is accepted.
    $target = Start-Process -FilePath $fixture -ArgumentList @('--play-test-tone', '--owner-approved') -PassThru -WindowStyle Hidden
    $raw = @(& dotnet $native --observe --pid $target.Id --expect-exe StarToneProbe.exe --duration-ms $DurationMs)
    if ($LASTEXITCODE -ne 0) { throw 'Process-isolated native capture failed.' }
    if ($raw.Count -lt 7 -or $raw.Count -gt 70) { throw 'Unexpected diagnostic record count.' }
    $rows = @($raw | ForEach-Object { $_ | ConvertFrom-Json })
    if ($rows[0].state -ne 'capture_started' -or
        $rows[$rows.Count - 1].state -ne 'capture_complete_no_silence_claim') {
        throw 'Native capture had an invalid state sequence.'
    }
    [long]$priorCallbacks = 0
    [long]$priorFrames = 0
    $lastElapsed = -1
    $nonzeroWindows = 0
    $nullWindows = 0
    foreach ($row in $rows) {
        if ($row.schema -ne 'star.process_loopback.diagnostic.v1' -or
            $row.verified_silence -ne $false -or
            $row.broadcast_authorized -ne $false -or
            $row.gameplay_authorized -ne $false -or
            $row.activity_is_audio_observation_only -ne $true -or
            $row.bad_packets -ne 0 -or
            $row.elapsed_ms -lt $lastElapsed -or
            $row.callback_generation -lt $priorCallbacks -or
            $row.sample_frames -lt $priorFrames -or
            ($row.callback_generation - $priorCallbacks) -ne $row.activity_callbacks -or
            ($row.sample_frames - $priorFrames) -ne $row.activity_sample_frames) {
            throw 'Untrusted, contradictory or authority-claiming diagnostic.'
        }
        if ($lastElapsed -ge 0 -and $row.elapsed_ms -le $lastElapsed) {
            throw 'Non-increasing observation timestamp.'
        }
        if ($row.activity_callbacks -eq 0) {
            if ($null -ne $row.activity_peak_milli -or $null -ne $row.activity_rms_milli) {
                throw 'Missing samples were falsely represented as digital silence.'
            }
            $nullWindows++
        } else {
            if ($row.activity_sample_frames -le 0 -or
                $null -eq $row.activity_peak_milli -or $null -eq $row.activity_rms_milli -or
                $row.activity_peak_milli -lt 0 -or $row.activity_peak_milli -gt 300 -or
                $row.activity_rms_milli -lt 0 -or $row.activity_rms_milli -gt 300) {
                throw 'Malformed amplitude or unexpected output level.'
            }
            if ($row.activity_peak_milli -ge 2 -and $row.activity_rms_milli -ge 1) {
                $nonzeroWindows++
            }
        }
        $lastElapsed = $row.elapsed_ms
        $priorCallbacks = $row.callback_generation
        $priorFrames = $row.sample_frames
    }
    if ($nonzeroWindows -lt 2 -or $priorFrames -le 0 -or
        $rows[$rows.Count - 1].max_peak_milli -lt 2 -or
        $rows[$rows.Count - 1].max_peak_milli -gt 300) {
        throw 'Positive-control amplitude not observed in the isolated process tree.'
    }
    # A process-local PCM positive control verifies only that some sound from
    # the fixture reached WASAPI; not physical audibility, TTS, or cancellation.
    [pscustomobject]@{
        status = 'private_process_tone_positive_control_observed'
        duration_requested_ms = $DurationMs
        diagnostic_records = $rows.Count
        callback_count = $priorCallbacks
        sample_frames = $priorFrames
        nonzero_amplitude_windows = $nonzeroWindows
        missing_pcm_windows = $nullWindows
        maximum_peak_milli = $rows[$rows.Count - 1].max_peak_milli
        synthetic_output_requested = $true
        physical_audibility_verified = $false
        actual_star_speech_tested = $false
        audio_interruption_verified = $false
        streaming_authorized = $false
        gameplay_tested = $false
    } | ConvertTo-Json -Compress
}
finally {
    if ($null -ne $target) {
        Stop-Process -Id $target.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
