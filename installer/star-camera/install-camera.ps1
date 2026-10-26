# STAR Camera: installs the "STAR Camera" virtual webcam (Unity Capture DirectShow filter, MIT licence) on STAR's PC.
# Run through install-camera.cmd (administrator). What it does:
#   1. downloads UnityCaptureFilter32.dll and UnityCaptureFilter64.dll from github.com/schellingb/UnityCapture at ONE pinned
#      commit and refuses any file whose git blob SHA-1 differs from the value pinned below
#   2. registers them with regsvr32 under the device name "STAR Camera" (the filter's own /i:UnityCaptureName= option)
#   3. installs pyvirtualcam + numpy into STAR Home's venv (<root>\venv) and writes a default camera config
#   4. self-test: starts the camera process, waits for frames, stops it
# -Root D:\STAR  the STAR install root (default: the machine's STAR_ROOT variable that setup.cmd sets, else C:\STAR)
# -DryRun        print what would happen and change nothing (no download, no registration, no pip)
# -Uninstall unregisters the filter. Nothing is installed outside <root>\camera, the registry entries regsvr32 makes
# for the filter, and the venv packages.
param([switch]$Uninstall, [switch]$DryRun, [string]$Root = '')
$ErrorActionPreference = 'Stop'
if (-not $Root) { $Root = [Environment]::GetEnvironmentVariable('STAR_ROOT', 'Machine') }
if (-not $Root) { $Root = 'C:\STAR' }
$Root = $Root.TrimEnd('\')
$Commit = '3ed54c325e0ad71afcf4f246c07e5e17b3d7f2d2'
$Files = @{
  'UnityCaptureFilter32.dll' = @{ sha1 = 'da0b41011faa1de004c8b58f57ad02eea3d10233'; size = 168448 }
  'UnityCaptureFilter64.dll' = @{ sha1 = 'cd6d7de9e25fe67e6ba1c8e57b01a634412e562d'; size = 157696 }
}
$Dir  = "$Root\camera\unitycapture"
$Name = 'STAR Camera'
$Venv = "$Root\venv"
$Data = Join-Path ($env:ProgramData) 'STAR\vtuber'
$Reg64 = "$env:SystemRoot\System32\regsvr32.exe"
$Reg32 = "$env:SystemRoot\SysWOW64\regsvr32.exe"

function Get-GitBlobSha1([byte[]]$Bytes) {
  $head = [System.Text.Encoding]::ASCII.GetBytes("blob $($Bytes.Length)`0")
  $sha = [System.Security.Cryptography.SHA1]::Create()
  ($sha.ComputeHash($head + $Bytes) | ForEach-Object { $_.ToString('x2') }) -join ''
}

if ($Uninstall) {
  if (Test-Path "$Dir\UnityCaptureFilter64.dll") { & $Reg64 /s /u "$Dir\UnityCaptureFilter64.dll" }
  if (Test-Path "$Dir\UnityCaptureFilter32.dll") { & $Reg32 /s /u "$Dir\UnityCaptureFilter32.dll" }
  Write-Host "STAR Camera filter unregistered. Delete $Root\camera to remove the files."
  return
}

if ($DryRun) {
  foreach ($file in $Files.Keys) {
    $path = "$Dir\$file"
    $have = (Test-Path $path) -and ((Get-GitBlobSha1 ([IO.File]::ReadAllBytes($path))) -eq $Files[$file].sha1)
    Write-Host ('[dry-run] {0}: {1}' -f $file, $(if ($have) { 'already in place with the pinned hash' } else { "would download $($Files[$file].size) bytes from the pinned commit into $Dir and check its hash" }))
  }
  Write-Host "[dry-run] would register both DLLs with regsvr32 as '$Name', pip install pyvirtualcam numpy pillow into $Venv only if they are missing, write the default camera config, run the self-test"
  return
}
New-Item -ItemType Directory -Force $Dir | Out-Null
foreach ($file in $Files.Keys) {
  $target = Join-Path $Dir $file
  $want = $Files[$file]
  $ok = $false
  if (Test-Path $target) { $ok = (Get-GitBlobSha1 ([IO.File]::ReadAllBytes($target))) -eq $want.sha1 }
  if (-not $ok) {
    $url = "https://raw.githubusercontent.com/schellingb/UnityCapture/$Commit/Install/$file"
    Write-Host "Downloading $file ($($want.size) bytes) from the pinned commit ..."
    Invoke-WebRequest -Uri $url -OutFile "$target.part" -UseBasicParsing
    $got = Get-GitBlobSha1 ([IO.File]::ReadAllBytes("$target.part"))
    if ($got -ne $want.sha1) { Remove-Item "$target.part" -Force; throw "$file does not match the pinned hash ($got). Nothing was installed." }
    Move-Item "$target.part" $target -Force
  }
}

# Same call as Unity Capture's own InstallCustomName.bat, once per bitness (the 32-bit filter needs the 32-bit regsvr32).
& $Reg64 /s "$Dir\UnityCaptureFilter64.dll" "/i:UnityCaptureName=$Name"
if ($LASTEXITCODE -ne 0) { throw 'registering the 64-bit filter failed.' }
if (Test-Path $Reg32) {
  & $Reg32 /s "$Dir\UnityCaptureFilter32.dll" "/i:UnityCaptureName=$Name"
  if ($LASTEXITCODE -ne 0) { Write-Warning 'registering the 32-bit filter failed (a 32-bit Discord would not list the camera).' }
}
Write-Host "Registered the virtual camera '$Name'."

if (-not (Test-Path "$Venv\Scripts\python.exe")) { throw "STAR Home's venv is missing ($Venv). Run installer\star-home\setup.cmd first." }
# setup.cmd already installed these from the hash-pinned requirements-home.txt; only a stand-alone run installs them here.
& "$Venv\Scripts\python.exe" -c "import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in ('pyvirtualcam', 'numpy', 'PIL')) else 1)"
if ($LASTEXITCODE -ne 0) {
  & "$Venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check pyvirtualcam numpy pillow
  if ($LASTEXITCODE -ne 0) { throw 'pip install pyvirtualcam failed.' }
}

New-Item -ItemType Directory -Force $Data | Out-Null
if (-not (Test-Path "$Data\config.json")) {
  '{"model": "starface", "backend": "unitycapture", "device_name": "STAR Camera", "fps": 30}' | Set-Content "$Data\config.json" -Encoding ascii
}

$env:STAR_VTUBER_DIR = $Data
Push-Location "$Root\app"
try {
  Write-Host 'Self-test: starting the camera ...'
  $out = & "$Venv\Scripts\python.exe" -m star.vtuber on
  Write-Host $out
  & "$Venv\Scripts\python.exe" -m star.vtuber off | Out-Null
  if ($out -match '"alive": true') { Write-Host "OK: '$Name' sent frames. In Discord: Settings > Voice & Video > Camera > '$Name'." }
  else { Write-Warning "The camera did not start; see $Data\camera.log" }
} finally { Pop-Location }
