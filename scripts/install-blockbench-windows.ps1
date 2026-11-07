# Install the official Blockbench Windows package on the owner's local desktop.
# This script is opt-in. It is NOT run from STAR and never runs on headless Linux servers.
# Default run only checks and prints; nothing is downloaded or installed without -Install.
# Official site: https://www.blockbench.net/
# Check: powershell -ExecutionPolicy RemoteSigned -File scripts/install-blockbench-windows.ps1
# Install: powershell -ExecutionPolicy RemoteSigned -File scripts/install-blockbench-windows.ps1 -Install
[CmdletBinding()]
param([switch]$Install)

$ErrorActionPreference = 'Stop'
$packageId = 'JannisX11.Blockbench'

if ($env:OS -ne 'Windows_NT') {
    throw 'Blockbench desktop installer targets Windows only.'
}
$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) {
    throw 'Windows Package Manager (winget) was not found. Install App Installer from Microsoft, or download Blockbench at https://www.blockbench.net/'
}
Write-Host "Checking official winget package ID: $packageId"
& winget list --exact --id $packageId
if ($LASTEXITCODE -eq 0) {
    Write-Host 'Blockbench appears to be installed. To update, use: winget upgrade --exact --id JannisX11.Blockbench'
    exit 0
}
if (-not $Install) {
    Write-Host 'Not installed (or not detected). No changes were made.'
    Write-Host 'To install after reviewing this script, run it again with -Install.'
    Write-Host 'winget downloads the installer named in its package manifest and checks the manifest hash. Review its prompts.'
    Write-Host 'Manual alternative: https://www.blockbench.net/'
    exit 0
}

Write-Host 'Installing Blockbench via official Windows Package Manager...'
& winget install --exact --id $packageId --source winget
if ($LASTEXITCODE -ne 0) {
    throw "winget exited with code $LASTEXITCODE. Blockbench installation was not confirmed."
}
Write-Host 'winget reported success. Launch Blockbench from the Start menu to confirm it opens.'
