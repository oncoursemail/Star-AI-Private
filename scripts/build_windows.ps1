$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$originalLocation = Get-Location
$profileRoot = Join-Path $repoRoot ('.local/windows-build-profiles/' + [guid]::NewGuid().ToString('N'))
$isolatedEnvironment = @{
  APPDATA = Join-Path $profileRoot 'Roaming'
  LOCALAPPDATA = Join-Path $profileRoot 'Local'
  USERPROFILE = Join-Path $profileRoot 'User'
  XDG_CONFIG_HOME = Join-Path $profileRoot 'Config'
  XDG_DATA_HOME = Join-Path $profileRoot 'Data'
  XDG_CACHE_HOME = Join-Path $profileRoot 'Cache'
  PYTHON_KEYRING_BACKEND = 'keyring.backends.null.Keyring'
  PYTHONNOUSERSITE = '1'
  QT_QPA_PLATFORM = 'offscreen'
  STAR_EXPECTED_HEAD_SHA = $null
}
$previousEnvironment = @{}
foreach ($name in $isolatedEnvironment.Keys) {
  $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Invoke-CheckedNative {
  param([string]$FilePath, [string[]]$CommandArguments, [string]$Stage)
  & $FilePath @CommandArguments
  if ($LASTEXITCODE -ne 0) { throw "$Stage failed; aborting build." }
}

function Invoke-PackagedDoctor {
  param([string]$Executable, [string]$Argument)
  $result = Start-Process -FilePath $Executable -ArgumentList $Argument -WindowStyle Hidden -Wait -PassThru
  if ($null -eq $result.ExitCode -or $result.ExitCode -ne 0) {
    throw "Packaged STAR.exe $Argument failed; aborting build."
  }
}

try {
  Set-Location $repoRoot
  # Isolate every child process, including tests and EXE doctors. Keep these
  # scratch profiles for inspection; never read, install over or delete STAR data.
  foreach ($name in $isolatedEnvironment.Keys) {
    $value = $isolatedEnvironment[$name]
    if ($name -in @('APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME')) {
      New-Item -ItemType Directory -Path $value -Force | Out-Null
    }
    [Environment]::SetEnvironmentVariable($name, $value, 'Process')
  }
  if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Install Python 3.11 x64.' }
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Node.js 22+ is needed for the React UI build.' }
  $sourceCommit = @(Invoke-CheckedNative 'py' @('-3.11', 'scripts/stamp_build_info.py', '--check-only') 'Source verification')
  if ($sourceCommit.Count -ne 1 -or $sourceCommit[0] -cnotmatch '^[0-9a-f]{40}$') { throw 'Source verification returned an invalid SHA.' }
  $sourceCommit = [string]$sourceCommit[0]
  Invoke-CheckedNative 'py' @('-3.11', '-m', 'venv', '.venv') 'Virtual environment creation'
  $python = Join-Path $repoRoot '.venv/Scripts/python.exe'
  Invoke-CheckedNative $python @('-m', 'pip', 'install', '--upgrade', 'pip') 'pip upgrade'
  Invoke-CheckedNative $python @('-m', 'pip', 'install', '-r', 'requirements-desktop.txt', '-r', 'requirements-dev.txt', 'pyinstaller>=6.10,<7') 'Python dependency install'
  Invoke-CheckedNative $python @('-m', 'pip', 'check') 'Python dependency check'
  Push-Location frontend
  try {
    Invoke-CheckedNative 'npm' @('install', '--package-lock=false', '--no-audit', '--no-fund') 'React dependency install'
    Invoke-CheckedNative 'npm' @('run', 'typecheck') 'TypeScript check'
    Invoke-CheckedNative 'npm' @('run', 'test') 'React tests'
    Invoke-CheckedNative 'npm' @('run', 'build') 'React build'
    if (-not (Test-Path 'dist/index.html' -PathType Leaf)) { throw 'React index missing.' }
  } finally { Pop-Location }
  Invoke-CheckedNative $python @('-m', 'pytest', '-q') 'Offline tests'
  Invoke-CheckedNative $python @('-m', 'compileall', '-q', 'star', 'star_desktop.py') 'Python compilation'
  # npm may update a tracked lockfile. Refuse that dirty source rather than
  # attributing an unreviewed package to the original clean commit.
  Invoke-CheckedNative $python @('scripts/stamp_build_info.py', '--expected-commit', $sourceCommit) 'Build provenance stamping'
  [Environment]::SetEnvironmentVariable('STAR_EXPECTED_HEAD_SHA', $sourceCommit, 'Process')
  Invoke-CheckedNative $python @('-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed', '--name', 'STAR', '--icon', 'assets/star.ico', '--add-data', 'frontend/dist;frontend/dist', '--add-data', 'star/build-info.json;star', '--add-data', 'star/skill_packs;star/skill_packs', '--add-data', 'star/data;star/data', '--add-data', 'star/studio_lab_specs;star/studio_lab_specs', '--add-data', 'star/voice/voices.json;star/voice', '--add-data', 'star/blender_worker.py;star', '--add-data', 'star/blender_animation_worker.py;star', '--hidden-import', 'PySide6.QtWebEngineWidgets', '--hidden-import', 'PySide6.QtWebChannel', '--hidden-import', 'mcp.client.session', '--hidden-import', 'mcp.client.stdio', '--hidden-import', 'mcp.types', '--collect-all', 'faster_whisper', '--collect-all', 'ctranslate2', '--collect-all', 'av', '--collect-all', 'pypdf', '--collect-all', 'docx', '--collect-all', 'pptx', '--collect-all', 'openpyxl', '--collect-submodules', 'pyttsx3', '--collect-submodules', 'jwt', '--collect-submodules', 'keyring', '--collect-submodules', 'cryptography', '--collect-submodules', 'obsws_python', 'star_desktop.py') 'PyInstaller'
  Invoke-CheckedNative $python @('scripts/stamp_build_info.py', '--check-only', '--expected-commit', $sourceCommit) 'Post-package source verification'
  $exe = (Resolve-Path './dist/STAR/STAR.exe').Path
  Invoke-PackagedDoctor $exe '--doctor'
  Invoke-PackagedDoctor $exe '--ui-doctor'
  Invoke-PackagedDoctor $exe '--build-doctor'
  $portable = Join-Path $repoRoot 'STAR-Genesis-Windows-x64.zip'
  Compress-Archive -Path './dist/STAR/*' -DestinationPath $portable -Force
  $packages = @($portable)
  $iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
  if (Test-Path $iscc -PathType Leaf) {
    $version = @(Invoke-CheckedNative $python @('-c', 'from star.version import __version__;print(__version__)') 'Version lookup')
    if ($version.Count -ne 1 -or $version[0] -cnotmatch '^\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)$') { throw 'Invalid package version.' }
    $version = [string]$version[0]
    $setup = Join-Path $repoRoot "dist/STAR-Setup-v$version.exe"
    if (Test-Path $setup) { throw 'Previous installer output exists; move it before rebuilding.' }
    Invoke-CheckedNative $iscc @("/DStarVersion=$version", 'installer/STAR.iss') 'Installer packaging'
    if (-not (Test-Path $setup -PathType Leaf)) { throw 'Installer output missing.' }
    $packages = @($setup, $portable)
  } else { Write-Host 'Inno Setup not installed; portable ZIP is ready.' }
  $checksums = foreach ($package in $packages) {
    $hash = (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $([System.IO.Path]::GetFileName($package))"
  }
  $checksums | Set-Content -Encoding utf8 'STAR-PREVIEW-SHA256SUMS.txt'
  Write-Host 'Build checks passed. Packages and STAR-PREVIEW-SHA256SUMS.txt are ready; installation acceptance is separate.'
} finally {
  foreach ($name in $previousEnvironment.Keys) {
    if ($null -eq $previousEnvironment[$name]) {
      Remove-Item -LiteralPath ("Env:" + $name) -ErrorAction SilentlyContinue
    } else {
      [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
  }
  Set-Location $originalLocation
}
