"""Real PowerShell installer previews and fake shortcut COM checks; no installed app changes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

REPO = Path(__file__).resolve().parents[1]
SETUP = REPO / "installer" / "star-home" / "setup.ps1"


class SetupPreferenceChecks(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def powershell(self, body, *, full=False):
        shell = shutil.which("powershell")
        if not shell:
            self.fail("Windows PowerShell is required for these source checks")
        env = {key: value for key, value in os.environ.items() if key.casefold() != "psmodulepath"}
        env.update(STAR_TEST_SETUP=str(SETUP), STAR_TEST_ROOT=str(self.root),
                   PSModulePath=str(Path(shell).parent / "Modules"))
        prefix = r"""
$ErrorActionPreference='Stop'
$base=$env:STAR_TEST_ROOT
$tokens=$null; $errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile($env:STAR_TEST_SETUP,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
function Would($text) { Write-Host "PREVIEW: $text" }
"""
        if not full:
            prefix += r"""
foreach ($name in @('Read-SetupPreferences','Get-SetupLauncher','Assert-SetupPreferenceDepth','Save-SetupLauncher',
                    'Test-DiscordShortcut','Backup-DiscordShortcut','Set-DiscordShortcuts')) {
    $node=$tree.Find({param($item) $item -is [Management.Automation.Language.FunctionDefinitionAst] -and $item.Name -eq $name},$true)
    if (-not $node) { throw "Missing source function $name" }
    . ([scriptblock]::Create($node.Extent.Text))
}
"""
        script = self.root / "check.ps1"
        script.write_text(prefix + body, encoding="utf-8-sig")
        result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(script)],
                                capture_output=True, text=True, timeout=45, cwd=REPO, env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_default_persisted_and_explicit_choices(self):
        self.powershell(r"""
$path=Join-Path $base 'setup-preferences.json'
if ((Get-SetupLauncher $path '') -cne 'official') { throw 'Wrong default' }
Save-SetupLauncher $path 'modrinth'
if ((Get-SetupLauncher $path '') -cne 'modrinth') { throw 'Preference not loaded' }
if ((Get-SetupLauncher $path 'official') -cne 'official') { throw 'Explicit choice did not win' }
if ((Get-SetupLauncher $path 'MODRINTH') -cne 'modrinth') { throw 'Explicit case not canonicalized' }
""")

    def test_saving_preserves_other_preferences_and_is_idempotent(self):
        self.powershell(r"""
$path=Join-Path $base 'setup-preferences.json'
'{"other_setting":"keep","minecraft_launcher":"official"}' | Set-Content -LiteralPath $path
Save-SetupLauncher $path 'modrinth'
$saved=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
if ($saved.other_setting -cne 'keep' -or $saved.minecraft_launcher -cne 'modrinth') { throw 'Preferences lost' }
$bytes=[IO.File]::ReadAllBytes($path); $stamp=(Get-Item -LiteralPath $path).LastWriteTimeUtc.Ticks
Save-SetupLauncher $path 'modrinth'
if ((Get-Item -LiteralPath $path).LastWriteTimeUtc.Ticks -ne $stamp) { throw 'Unchanged preference rewritten' }
if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($path)) -cne [Convert]::ToBase64String($bytes)) { throw 'Bytes changed' }
""")

    def test_invalid_saved_choice_is_not_silently_reinstalled(self):
        self.powershell(r"""
$path=Join-Path $base 'setup-preferences.json'
'{"minecraft_launcher":true}' | Set-Content -LiteralPath $path
$rejected=$false
try { Get-SetupLauncher $path '' | Out-Null } catch { $rejected=$true }
if (-not $rejected) { throw 'Invalid persisted choice accepted' }
Save-SetupLauncher $path (Get-SetupLauncher $path 'official')
if ((Get-SetupLauncher $path '') -cne 'official') { throw 'Explicit correction failed' }
""")

    def test_nested_unknown_preferences_preserved_or_rejected_before_write(self):
        path = self.root / "setup-preferences.json"
        for levels, accepted in ((12, True), (40, False)):
            value = {"leaf": "keep"}
            for _ in range(levels):
                value = {"child": value}
            original = {"other_setting": value, "minecraft_launcher": "official"}
            path.write_text(json.dumps(original), encoding="utf-8")
            before = (path.read_bytes(), path.stat().st_mtime_ns)
            self.powershell(r"""
$path=Join-Path $base 'setup-preferences.json'
$rejected=$false
try { Save-SetupLauncher $path 'modrinth' } catch { $rejected=$true }
""" + ("if ($rejected) { throw 'Supported nesting rejected' }" if accepted else
          "if (-not $rejected) { throw 'Excessive nesting accepted' }"))
            if accepted:
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                                 {**original, "minecraft_launcher": "modrinth"})
            else:
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def preview(self, preference, requested=None):
        install = self.root / "install"
        if preference is not None:
            install.mkdir()
            (install / "setup-preferences.json").write_text(json.dumps(preference), encoding="utf-8")
        original = (install / "setup-preferences.json").read_bytes() if preference is not None else None
        request = " -MinecraftLauncher " + requested if requested else ""
        output = self.powershell(r"""
function winget { $global:LASTEXITCODE=1; 'fixture missing package' }
function Get-NetIPAddress { }
function Get-NetIPConfiguration { }
foreach ($name in @('New-Item','Set-Content','Copy-Item','Move-Item','Remove-Item','Start-Process',
                    'Invoke-WebRequest','Register-ScheduledTask','Start-ScheduledTask')) {
    Set-Item -Path "function:$name" -Value { throw 'MUTATION IN FULL DRY RUN' }
}
& $env:STAR_TEST_SETUP -Root (Join-Path $base 'install') -Yes -Only apps -DryRun
""".rstrip() + request + "\n", full=True)
        if original is None:
            self.assertFalse(install.exists(), "preview created an install/preferences folder")
        else:
            self.assertEqual((install / "setup-preferences.json").read_bytes(), original)
        return output

    def test_full_preview_uses_modrinth_preference_but_keeps_java(self):
        output = self.preview({"minecraft_launcher": "modrinth"})
        self.assertIn("Modrinth preference", output)
        self.assertNotIn("would: winget install Mojang.MinecraftLauncher", output)
        self.assertIn("Java 21", output)
        self.assertIn("Discord", output)

    def test_full_preview_explicit_choice_wins_without_writing(self):
        output = self.preview({"minecraft_launcher": "modrinth"}, "official")
        self.assertTrue("would: winget install Mojang.MinecraftLauncher" in output or
                        "Minecraft Launcher: already installed" in output)

    def test_new_preference_preview_creates_nothing(self):
        output = self.preview(None, "modrinth")
        self.assertIn("remember Minecraft launcher preference 'modrinth'", output)
        self.assertNotIn("would: winget install Mojang.MinecraftLauncher", output)

    def shortcuts(self, body):
        return self.powershell(r"""
$desktop=Join-Path $base 'desktop'; $startup=Join-Path $base 'startup'; $client=Join-Path $base 'Discord'
$backups=Join-Path $base 'shortcut-backups'
New-Item -ItemType Directory -Path $desktop,$startup,$client | Out-Null
$global:Links=@{}; $global:Saves=New-Object System.Collections.ArrayList
$shell=New-Object psobject
$shell | Add-Member ScriptMethod CreateShortcut {
    param($path)
    if ($global:Links.ContainsKey($path)) { return $global:Links[$path] }
    $link=[pscustomobject]@{ Path=$path; TargetPath=''; Arguments=''; WorkingDirectory=''; Description='' }
    $link | Add-Member ScriptMethod Save {
        [void]$global:Saves.Add($this.Path)
        [IO.File]::WriteAllText($this.Path,'saved fixture shortcut')
    }
    $global:Links[$path]=$link
    return $link
}
function Add-FixtureLink($path,$target,$arguments) {
    $link=$shell.CreateShortcut($path); $link.TargetPath=$target; $link.Arguments=$arguments
    [IO.File]::WriteAllText($path,'original fixture shortcut')
}
$normal=Join-Path $desktop 'Discord.lnk'; $legacy=Join-Path $desktop 'Discord (STAR).lnk'
$startupLink=Join-Path $startup 'Discord (STAR).lnk'
$update=Join-Path $client 'Update.exe'
$accessible='--processStart Discord.exe --process-start-args "--force-renderer-accessibility"'
""" + body)

    def test_known_original_consolidates_without_duplicate_on_rerun(self):
        self.shortcuts(r"""
Add-FixtureLink $normal (Join-Path $client 'Discord.exe') '--processStart Discord.exe'
Add-FixtureLink $legacy $update $accessible
Set-DiscordShortcuts $shell $desktop $startup $client $backups
Set-DiscordShortcuts $shell $desktop $startup $client $backups
if (Test-Path -LiteralPath $legacy) { throw 'Generated duplicate remains' }
if (@(Get-ChildItem -LiteralPath $desktop -Filter '*.lnk').Count -ne 1) { throw 'Desktop is not consolidated' }
if ($global:Links[$normal].TargetPath -cne $update -or $global:Links[$normal].Arguments -cne $accessible) { throw 'Canonical launch changed' }
if (-not (Test-Path -LiteralPath $startupLink)) { throw 'Startup alias missing' }
if ($global:Links[$startupLink].Arguments -cne $accessible) { throw 'Startup accessibility lost' }
if (Test-Path -LiteralPath $backups) { throw 'Known links did not need backup' }
""")

    def test_custom_links_are_backed_up_preserved_and_warned(self):
        output = self.shortcuts(r"""
Add-FixtureLink $normal (Join-Path $base 'OtherApp.exe') '--custom'
Add-FixtureLink $legacy $update '--custom'
Add-FixtureLink $startupLink $update '--custom'
Set-DiscordShortcuts $shell $desktop $startup $client $backups
Set-DiscordShortcuts $shell $desktop $startup $client $backups
if ($global:Saves.Count) { throw 'Custom links overwritten' }
if (@(Get-ChildItem -LiteralPath $backups -Filter '*.lnk').Count -ne 3) { throw 'Backup missing or duplicated' }
foreach ($path in @($normal,$legacy,$startupLink)) {
    if ([IO.File]::ReadAllText($path) -cne 'original fixture shortcut') { throw 'Custom link changed' }
}
""")
        self.assertIn("Custom Discord desktop shortcut kept unchanged", output)

    def test_shortcut_preview_never_saves_deletes_or_backs_up(self):
        self.shortcuts(r"""
Add-FixtureLink $normal (Join-Path $client 'Discord.exe') '--processStart Discord.exe'
Add-FixtureLink $legacy $update $accessible
Add-FixtureLink $startupLink $update '--custom'
Set-DiscordShortcuts $shell $desktop $startup $client $backups -Preview
if ($global:Saves.Count -or (Test-Path -LiteralPath $backups)) { throw 'Preview changed shortcuts/backups' }
foreach ($path in @($normal,$legacy,$startupLink)) {
    if ([IO.File]::ReadAllText($path) -cne 'original fixture shortcut') { throw 'Preview touched a link' }
}
""")


if __name__ == "__main__":
    unittest.main(verbosity=2)
