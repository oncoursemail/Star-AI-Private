# CI-only: install the exact newly built Setup in a unique disposable runner folder.
# This supplements native human acceptance; it does not claim a real-user upgrade.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$githubHosted = $env:GITHUB_ACTIONS -eq 'true' -and $env:RUNNER_OS -eq 'Windows' -and
  $env:RUNNER_ENVIRONMENT -eq 'github-hosted'
# Windows Sandbox (scripts/ci/run_in_sandbox.ps1): a fresh Windows that is thrown away afterwards. Its only
# user is WDAGUtilityAccount. Checked from the process token and the real AppData folder Inno writes to,
# never from environment variables, so the owner's PC (whose runner runs as the owner) can never match.
$sandboxProfile = Join-Path $env:SystemDrive 'Users\WDAGUtilityAccount\'
$disposableSandbox = $env:STAR_DISPOSABLE_WINDOWS -eq '1' -and
  [Security.Principal.WindowsIdentity]::GetCurrent().Name -match '\\WDAGUtilityAccount$' -and
  ([Environment]::GetFolderPath('ApplicationData') + '\').StartsWith($sandboxProfile, [StringComparison]::OrdinalIgnoreCase)
# Throwaway CI VM restored from a snapshot after every run (docs/agents/winvm-20261020.md): local user `ci`
# plus a marker file baked into the image. The owner's PC has neither.
$vmProfile = Join-Path $env:SystemDrive 'Users\ci\'
$disposableVm = $env:STAR_DISPOSABLE_WINDOWS -eq '1' -and
  [Security.Principal.WindowsIdentity]::GetCurrent().Name -match '\\ci$' -and
  ([Environment]::GetFolderPath('ApplicationData') + '\').StartsWith($vmProfile, [StringComparison]::OrdinalIgnoreCase) -and
  (Test-Path -LiteralPath 'C:\ProgramData\STAR-CI\disposable-vm.txt' -PathType Leaf)
if (-not ($githubHosted -or $disposableSandbox -or $disposableVm) -or -not $env:RUNNER_TEMP) {
  throw 'Installer smoke checks require a disposable Windows: a GitHub-hosted runner, Windows Sandbox or the CI VM'
}
if ($env:STAR_EXPECTED_HEAD_SHA -notmatch '^[0-9a-f]{40}$') {
  throw 'An exact expected source SHA is required'
}

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$setups = @(Get-ChildItem -LiteralPath (Join-Path $root 'dist') -Filter 'STAR-Setup-v*.exe' -File)
if ($setups.Count -ne 1) { throw 'Expected exactly one fresh Setup output' }
$sourceExe = Join-Path $root 'dist/STAR/STAR.exe'
$sourceHash = (Get-FileHash -LiteralPath $sourceExe -Algorithm SHA256).Hash
$setupHash = (Get-FileHash -LiteralPath $setups[0].FullName -Algorithm SHA256).Hash
$scope = Join-Path ([IO.Path]::GetFullPath($env:RUNNER_TEMP)) ('STAR-Installer-Smoke-' + [Guid]::NewGuid().ToString('N'))
$install = Join-Path $scope 'app'
$installedExe = Join-Path $install 'STAR.exe'
$smokeProfileRoot = Join-Path $scope 'profile'
$savedAppData = $env:APPDATA
$savedLocalAppData = $env:LOCALAPPDATA
$savedQtPlatform = $env:QT_QPA_PLATFORM
New-Item -ItemType Directory -Path $install, $smokeProfileRoot -ErrorAction Stop | Out-Null
$env:APPDATA = Join-Path $smokeProfileRoot 'Roaming'
$env:LOCALAPPDATA = Join-Path $smokeProfileRoot 'Local'
$env:QT_QPA_PLATFORM = 'offscreen'
New-Item -ItemType Directory -Path $env:APPDATA, $env:LOCALAPPDATA -ErrorAction Stop | Out-Null
$appMarker = Join-Path $install 'ci-owner-note.txt'
# Inno resolves {userappdata} through Windows, not necessarily the overridden env.
# This is a synthetic marker on a fresh hosted runner, never a real-user profile.
$knownStarProfile = Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'STAR'
New-Item -ItemType Directory -Path $knownStarProfile -Force -ErrorAction Stop | Out-Null
$profileMarker = Join-Path $knownStarProfile ('ci-preserve-' + [Guid]::NewGuid().ToString('N') + '.txt')
[IO.File]::WriteAllText($appMarker, 'synthetic CI owner file; preserve across setup')
[IO.File]::WriteAllText($profileMarker, 'synthetic CI profile; preserve across setup')
$markerHashes = @((Get-FileHash -LiteralPath $appMarker).Hash, (Get-FileHash -LiteralPath $profileMarker).Hash)

function Stop-InstalledCiApp {
  # Setup launches STAR even in silent mode. Stop only this uniquely scoped copy.
  foreach ($process in @(Get-Process -Name STAR -ErrorAction SilentlyContinue)) {
    if ($process.Path -eq $installedExe) { Stop-Process -Id $process.Id -Force -ErrorAction Stop }
  }
}

function Invoke-CheckedProcess([string]$File, [string[]]$Arguments, [int]$Seconds) {
  $process = Start-Process -FilePath $File -ArgumentList $Arguments -PassThru
  # Start-Process -Wait can wait for Setup's auto-launched GUI descendants.
  # Wait on this exact process handle instead, with a finite native timeout.
  if (-not $process.WaitForExit($Seconds * 1000)) {
    $process.Kill()
    throw "CI process exceeded its $Seconds second timeout"
  }
  if ($null -eq $process.ExitCode -or $process.ExitCode -ne 0) {
    throw "CI process failed with exit code $($process.ExitCode)"
  }
}

try {
  foreach ($attempt in 1, 2) {
    Stop-InstalledCiApp
    $log = Join-Path $scope "setup-$attempt.log"
    Invoke-CheckedProcess $setups[0].FullName @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
      '/CURRENTUSER', ('/DIR="{0}"' -f $install), ('/LOG="{0}"' -f $log)) 180
    Stop-InstalledCiApp
    if ((Get-FileHash -LiteralPath $installedExe -Algorithm SHA256).Hash -ne $sourceHash) {
      throw 'Installed STAR.exe differs from the exact packaged output'
    }
    foreach ($argument in '--doctor', '--ui-doctor', '--build-doctor') {
      Invoke-CheckedProcess $installedExe @($argument) 90
    }
    if ((Get-FileHash -LiteralPath $appMarker).Hash -ne $markerHashes[0] -or
        (Get-FileHash -LiteralPath $profileMarker).Hash -ne $markerHashes[1]) {
      throw 'Installer smoke check lost or modified a synthetic preservation marker'
    }
    $stale = Join-Path $install '_internal/ci-stale-runtime-marker.txt'
    if ($attempt -eq 1) {
      [IO.File]::WriteAllText($stale, 'synthetic old runtime file')
    } elseif (Test-Path -LiteralPath $stale) {
      throw 'Reinstall kept a stale runtime file'
    }
  }
  if ((Get-FileHash -LiteralPath $setups[0].FullName -Algorithm SHA256).Hash -ne $setupHash) {
    throw 'The tested Setup output changed during validation'
  }
  'Exact Setup fresh install, same-version reinstall, installed doctors, and synthetic preservation checks passed.'
} finally {
  try { Stop-InstalledCiApp } finally {
    $env:APPDATA = $savedAppData
    $env:LOCALAPPDATA = $savedLocalAppData
    $env:QT_QPA_PLATFORM = $savedQtPlatform
  }
  # Runner teardown owns this unique scope. Do not delete profiles or installations.
}
