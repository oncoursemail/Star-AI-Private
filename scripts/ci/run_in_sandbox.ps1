# Run the installer smoke test (scripts/smoke_windows_installer.ps1) inside a fresh Windows Sandbox.
# UNTESTED until the owner enables Windows Sandbox (optional feature Containers-DisposableClientVM + reboot).
# The build stays on the runner (it uses a throwaway profile and the host caches); only the step that installs
# STAR into the real per-user locations runs in the Sandbox, which is thrown away afterwards.
# Inputs: the checkout (read-only), portable PowerShell from the runner tools (read-only), one writable out folder.
param([int]$TimeoutSeconds = 600)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:RUNNER_ENVIRONMENT -eq 'github-hosted' -or
    ($env:STAR_DISPOSABLE_WINDOWS -eq '1' -and (Test-Path -LiteralPath 'C:\ProgramData\STAR-CI\disposable-vm.txt'))) {
  # A GitHub-hosted runner or the snapshot-restored CI VM is itself disposable: run the check directly
  # (the smoke script checks the machine again from the process token, not from these variables).
  & (Join-Path $PSScriptRoot '..\smoke_windows_installer.ps1')
  exit $LASTEXITCODE
}
$sandboxExe = Join-Path $env:SystemRoot 'System32\WindowsSandbox.exe'
if (-not (Test-Path -LiteralPath $sandboxExe)) {
  throw 'The installer test needs a disposable Windows. Windows Sandbox is not enabled on this runner (owner step: enable the optional feature "Windows Sandbox", reboot).'
}
if (@(Get-Process -Name WindowsSandbox, WindowsSandboxClient, WindowsSandboxRemoteSession -ErrorAction SilentlyContinue).Count) {
  throw 'A Windows Sandbox is already open; Windows allows one at a time.'
}
if ($env:STAR_EXPECTED_HEAD_SHA -notmatch '^[0-9a-f]{40}$') { throw 'An exact expected source SHA is required' }
$pwshDir = Split-Path -Parent (Get-Command pwsh).Source
$workspace = [IO.Path]::GetFullPath($env:GITHUB_WORKSPACE)
$base = Join-Path $env:RUNNER_TEMP ('wsb-' + [Guid]::NewGuid().ToString('N'))
$out = Join-Path $base 'out'
New-Item -ItemType Directory -Path $out | Out-Null

# Runs inside the Sandbox as WDAGUtilityAccount. Writes its log and exit code to the only writable folder.
$job = @"
`$ErrorActionPreference = 'Stop'
`$env:RUNNER_TEMP = 'C:\ci-temp'
`$env:STAR_DISPOSABLE_WINDOWS = '1'
`$env:STAR_EXPECTED_HEAD_SHA = '$($env:STAR_EXPECTED_HEAD_SHA)'
New-Item -ItemType Directory -Force -Path `$env:RUNNER_TEMP | Out-Null
`$code = 1
try {
  & 'C:\ci\src\scripts\smoke_windows_installer.ps1' *>&1 | Tee-Object -FilePath 'C:\ci\out\smoke.log'
  `$code = 0
} catch {
  `$_ | Out-String | Add-Content -LiteralPath 'C:\ci\out\smoke.log'
} finally {
  Set-Content -LiteralPath 'C:\ci\out\exit-code.txt' -Value `$code
  shutdown.exe /s /t 0
}
"@
Set-Content -LiteralPath (Join-Path $out 'job.ps1') -Value $job -Encoding utf8
$wsb = @"
<Configuration>
  <vGPU>Disable</vGPU>
  <Networking>Disable</Networking>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <PrinterRedirection>Disable</PrinterRedirection>
  <MemoryInMB>4096</MemoryInMB>
  <MappedFolders>
    <MappedFolder><HostFolder>$workspace</HostFolder><SandboxFolder>C:\ci\src</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$pwshDir</HostFolder><SandboxFolder>C:\ci\pwsh</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$out</HostFolder><SandboxFolder>C:\ci\out</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand><Command>C:\ci\pwsh\pwsh.exe -NoProfile -ExecutionPolicy Bypass -File C:\ci\out\job.ps1</Command></LogonCommand>
</Configuration>
"@
$config = Join-Path $base 'smoke.wsb'
Set-Content -LiteralPath $config -Value $wsb -Encoding utf8

$started = Get-Date
Start-Process -FilePath $sandboxExe -ArgumentList "`"$config`""
$exitFile = Join-Path $out 'exit-code.txt'
while (-not (Test-Path -LiteralPath $exitFile)) {
  if (((Get-Date) - $started).TotalSeconds -gt $TimeoutSeconds) {
    Get-Process -Name WindowsSandbox, WindowsSandboxClient, WindowsSandboxRemoteSession -ErrorAction SilentlyContinue |
      Stop-Process -Force
    throw "Windows Sandbox installer test exceeded $TimeoutSeconds seconds"
  }
  Start-Sleep -Seconds 2
}
$code = [int](Get-Content -LiteralPath $exitFile -Raw).Trim()
if (Test-Path -LiteralPath (Join-Path $out 'smoke.log')) { Get-Content -LiteralPath (Join-Path $out 'smoke.log') }
"Windows Sandbox installer test: exit $code after $([int]((Get-Date) - $started).TotalSeconds) s (Sandbox start included)."
if ($code -ne 0) { throw 'Installer smoke test failed inside Windows Sandbox' }
