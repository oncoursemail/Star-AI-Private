"""STAR's microphone for Discord, games and Windows itself: a virtual audio cable.

    STAR's voice -> "CABLE Input" (a playback device only STAR writes to)
                 -> "CABLE Output" = the recording device named "STAR Microphone" -> Discord / a game / dictation

The driver is VB-CABLE (docs/agents/senses-voice-20261026.md, section "Driver choice"). This module
  * finds the two endpoints by name in a device list (the real PortAudio list, or any list in tests),
  * opens a Speaker that writes ONLY into the cable's playback endpoint: if the cable is not there it raises
    RouteMissing, it never falls back to the default (real) speakers; a monitor copy to real speakers exists only
    when a monitor device is named in the settings,
  * picks her listening microphone: the owner's physical microphone, never the cable (once "STAR Microphone" is the
    default recording device a bare "default input" would be STAR listening to herself),
  * writes the one-time setup script (rename endpoint, make it the default recording and communications device) and
    a verification run (list recording devices, record 3 s from "STAR Microphone" while sound plays into the cable,
    measure the level and the round trip).

`python -m star.senses.routes list|verify|script [--dry-run]`
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

MIC_NAME = "STAR Microphone"
# Playback side of the cable, recording side before and after the rename. Matching is case-insensitive substring.
PLAYBACK_PATTERNS = ("cable input", "vb-audio virtual cable")
RECORDING_PATTERNS = (MIC_NAME.lower(), "cable output")
VIRTUAL_PATTERNS = ("cable", "vb-audio", "star microphone", "voicemeeter", "virtual", "sound mapper", "stereo mix")
# MME/DirectSound names are cut at 31 characters and list the same device again: WASAPI is the one to open.
HOST_PREFERENCE = ("windows wasapi", "windows directsound", "mme")


class RouteMissing(RuntimeError):
    """The virtual cable is not installed (or not enabled). Her voice is never sent to a real speaker instead."""


def query_devices(sd=None) -> list[dict]:
    """Every audio device as a plain dict: index, name, kind (input|output), host api, default rate, channels."""
    if sd is None:
        from ..voice.devices import _sounddevice
        sd = _sounddevice()
    hostapis = [h["name"] for h in sd.query_hostapis()]
    out = []
    for index, info in enumerate(sd.query_devices()):
        host = hostapis[info["hostapi"]] if info["hostapi"] < len(hostapis) else ""
        for kind, channels in (("input", info["max_input_channels"]), ("output", info["max_output_channels"])):
            if channels > 0:
                out.append({"index": index, "name": info["name"], "kind": kind, "host": host,
                            "rate": int(info["default_samplerate"]), "channels": int(channels)})
    return out


def _rank(device: dict) -> int:
    host = device.get("host", "").lower()
    return next((i for i, h in enumerate(HOST_PREFERENCE) if h in host), len(HOST_PREFERENCE))


def _find(devices: list[dict], kind: str, patterns: tuple) -> dict | None:
    hits = [d for d in devices if d["kind"] == kind and any(p in d["name"].lower() for p in patterns)]
    # the renamed endpoint wins over the stock name; within that, WASAPI wins
    hits.sort(key=lambda d: (patterns[0] not in d["name"].lower(), _rank(d)))
    return hits[0] if hits else None


@dataclass
class VirtualMicRoute:
    playback: dict | None            # where STAR's voice is written ("CABLE Input")
    recording: dict | None           # what Discord/games record ("STAR Microphone", or "CABLE Output" before the rename)
    renamed: bool = False

    @property
    def ready(self) -> bool:
        return self.playback is not None and self.recording is not None

    def describe(self) -> str:
        playback, recording = self.playback, self.recording
        if playback is not None and recording is not None:
            return (f'Voice goes to "{playback["name"]}"; apps record "{recording["name"]}"'
                    + ("" if self.renamed else f' (not renamed to "{MIC_NAME}" yet)') + ".")
        missing = [n for n, d in (("playback", self.playback), ("recording", self.recording)) if d is None]
        return f"Virtual cable not found ({', '.join(missing)} endpoint missing): see the one-time install steps."


def find_route(devices: list[dict]) -> VirtualMicRoute:
    playback = _find(devices, "output", PLAYBACK_PATTERNS)
    recording = _find(devices, "input", RECORDING_PATTERNS)
    return VirtualMicRoute(playback, recording, bool(recording and MIC_NAME.lower() in recording["name"].lower()))


def physical_microphone(devices: list[dict], preferred: str = "") -> dict | None:
    """The owner's real microphone: a named one if given, else the first input that is not virtual."""
    inputs = [d for d in devices if d["kind"] == "input" and not any(p in d["name"].lower() for p in VIRTUAL_PATTERNS)]
    inputs.sort(key=_rank)
    if preferred:
        for d in inputs:
            if preferred.lower() in d["name"].lower():
                return d
    return inputs[0] if inputs else None


def open_voice_output(devices: list[dict], *, monitor: str = "", prefill_ms: int = 60):
    """A Speaker that writes only into the cable (and into `monitor`, a device name, when one is configured)."""
    route = find_route(devices)
    if route.playback is None:
        raise RouteMissing(route.describe())
    from .output import SoundOutput
    cable = SoundOutput(route.playback["index"], rate=route.playback["rate"],
                        channels=min(2, route.playback["channels"]), prefill_ms=prefill_ms)
    if not monitor:
        return cable
    heard = next((d for d in devices if d["kind"] == "output" and monitor.lower() in d["name"].lower()), None)
    if heard is None:
        raise RouteMissing(f'The monitor device "{monitor}" was not found.')
    return _Tee(cable, SoundOutput(heard["index"], rate=heard["rate"], channels=min(2, heard["channels"])))


class _Tee:
    """Cable output plus a monitor copy for the owner's ears (only when configured)."""

    def __init__(self, main, monitor) -> None:
        self.main, self.monitor = main, monitor

    def play(self, pcm: bytes, rate: int) -> None:
        self.main.play(pcm, rate)
        self.monitor.play(pcm, rate)

    def stop(self) -> None:
        self.main.stop()
        self.monitor.stop()

    def reset(self) -> None:
        self.main.reset()
        self.monitor.reset()

    def pending_seconds(self) -> float:
        return self.main.pending_seconds()

    def played_seconds(self) -> float:
        return self.main.played_seconds()

    def level(self) -> float:
        return self.main.level()

    def __enter__(self):
        self.main.__enter__()
        self.monitor.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        self.main.close()
        self.monitor.close()

    def close(self) -> None:
        self.main.close()
        self.monitor.close()


# -- one-time setup (PowerShell, elevated, on her PC) ------------------------------------------------------
SETUP_SCRIPT = r'''# STAR Microphone setup: run ONCE in an elevated PowerShell on her PC, after VB-CABLE is installed and rebooted.
# Use -WhatIf first: it prints what it would change and changes nothing.
param([switch]$WhatIf)
$ErrorActionPreference = "Stop"
$name = "__MIC_NAME__"
$cap = Get-PnpDevice -Class AudioEndpoint -PresentOnly | Where-Object { $_.InstanceId -like "*{0.0.1.*" -and $_.FriendlyName -match "CABLE Output|__MIC_NAME__" }
if (-not $cap) { throw "No recording endpoint named CABLE Output or $name. Install VB-CABLE and reboot first." }
$guid = ($cap.InstanceId -replace '.*\.(\{[0-9a-fA-F-]+\})$', '$1')
$endpointId = "{0.0.1.00000000}." + $guid
"Recording endpoint: $($cap.FriendlyName)  id $endpointId"

# 1. Rename. Windows shows "<device description> (<adapter name>)"; both live in the MMDevices property store.
$key = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture\$guid\Properties"
$desc = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"       # PKEY_Device_DeviceDesc
$adapter = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"    # PKEY_DeviceInterface_FriendlyName
"Would set $key  $desc = $name   $adapter = $name"
if (-not $WhatIf) {
  # The property store is owned by TrustedInstaller: take ownership of the two values' key, grant Administrators write.
  $sid = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-32-544")
  Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public class Priv { [DllImport("ntdll.dll")] public static extern int RtlAdjustPrivilege(int p, bool e, bool t, out bool o); }
"@
  $o = $false; [void][Priv]::RtlAdjustPrivilege(9, $true, $false, [ref]$o); [void][Priv]::RtlAdjustPrivilege(17, $true, $false, [ref]$o)
  $k = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey("SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture\$guid\Properties",
        [Microsoft.Win32.RegistryKeyPermissionCheck]::ReadWriteSubTree, [System.Security.AccessControl.RegistryRights]::TakeOwnership)
  $acl = $k.GetAccessControl(); $acl.SetOwner($sid); $k.SetAccessControl($acl)
  $k = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey("SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture\$guid\Properties",
        [Microsoft.Win32.RegistryKeyPermissionCheck]::ReadWriteSubTree, [System.Security.AccessControl.RegistryRights]::ChangePermissions)
  $acl = $k.GetAccessControl()
  $acl.AddAccessRule((New-Object System.Security.AccessControl.RegistryAccessRule($sid, "FullControl", "ContainerInherit", "None", "Allow")))
  $k.SetAccessControl($acl)
  Set-ItemProperty -Path $key -Name $desc -Value $name
  Set-ItemProperty -Path $key -Name $adapter -Value $name
  "Renamed. (Windows may need the audio service restarted or a sign-out to show it everywhere.)"
}

# 2. Make it the default recording device and the default communications device (IPolicyConfig; roles 0 console,
#    1 multimedia, 2 communications).
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
[Guid("F8679F50-850A-41CF-9C72-430F290290C8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPolicyConfig {
  int GetMixFormat(string d, IntPtr f); int GetDeviceFormat(string d, int b, IntPtr f); int ResetDeviceFormat(string d);
  int SetDeviceFormat(string d, IntPtr e, IntPtr m); int GetProcessingPeriod(string d, int b, IntPtr a, IntPtr c);
  int SetProcessingPeriod(string d, IntPtr a); int GetShareMode(string d, IntPtr m); int SetShareMode(string d, IntPtr m);
  int GetPropertyValue(string d, int b, IntPtr k, IntPtr v); int SetPropertyValue(string d, int b, IntPtr k, IntPtr v);
  int SetDefaultEndpoint(string d, int role); int SetEndpointVisibility(string d, int v);
}
[ComImport, Guid("870af99c-171d-4f9e-af0d-e63df40c2bc9")] class PolicyConfigClient {}
public static class DefaultMic {
  public static void Set(string id) { var p = (IPolicyConfig)new PolicyConfigClient();
    for (int r = 0; r < 3; r++) { int hr = p.SetDefaultEndpoint(id, r); if (hr != 0) throw new Exception("SetDefaultEndpoint role " + r + " failed: 0x" + hr.ToString("x")); } }
}
"@
"Would make $endpointId the default recording + communications device."
if (-not $WhatIf) { [DefaultMic]::Set($endpointId); "Done." }
"Next: Sound control panel > Recording > $name > Properties > Advanced: choose 2 channel, 24 bit, 48000 Hz (what Discord and games use)."
'''.replace("__MIC_NAME__", MIC_NAME)


# -- verification --------------------------------------------------------------------------------------------
def _test_signal(rate: int, seconds: float = 3.0) -> np.ndarray:
    """A voice-band sweep with an impulse train: easy to find again in a recording (level and round trip)."""
    t = np.arange(int(rate * seconds)) / rate
    sweep = 0.25 * np.sin(2 * np.pi * (200 * t + 900 * t ** 2 / seconds))
    sweep[: int(0.3 * rate)] = 0.0
    sweep[int(0.3 * rate) + 1: int(0.35 * rate)] += 0.5       # a click to time the round trip
    return sweep.astype(np.float32)


def verify(devices: list[dict] | None = None, *, seconds: float = 3.0, dry_run: bool = False, sd=None,
           out=print) -> dict:
    """List recording devices, play a test signal into the cable and record `seconds` from "STAR Microphone"."""
    if devices is None:
        if dry_run:
            try:
                devices = query_devices(sd)
            except Exception as exc:
                out(f"(dry run) cannot list devices here: {exc}")
                devices = []
        else:
            devices = query_devices(sd)
    out("Recording devices:")
    for d in sorted((d for d in devices if d["kind"] == "input"), key=_rank):
        out(f"  [{d['index']:>2}] {d['name']}  ({d['host']}, {d['rate']} Hz, {d['channels']} ch)")
    route = find_route(devices)
    out(route.describe())
    report: dict[str, Any] = {"route_ready": route.ready, "renamed": route.renamed, "dry_run": dry_run}
    playback, recording = route.playback, route.recording
    if dry_run or playback is None or recording is None:
        out("(dry run) would play a 3 s sweep into the cable and record 3 s from the recording endpoint."
            if dry_run else "Nothing to record: install the cable first.")
        return report
    if sd is None:
        from ..voice.devices import _sounddevice
        sd = _sounddevice()
    rate = recording["rate"]
    signal = _test_signal(rate, seconds)
    play_channels = min(2, playback["channels"])
    frames = np.repeat(signal[:, None], play_channels, axis=1) if play_channels > 1 else signal[:, None]
    started = time.perf_counter()
    recorded = sd.playrec(frames, samplerate=rate, channels=min(2, recording["channels"]),
                          device=(recording["index"], playback["index"]), dtype="float32")
    sd.wait()
    mono = recorded.mean(axis=1)
    level = float(np.sqrt(np.mean(mono ** 2)))
    lag = _round_trip(signal, mono, rate)
    report.update({"rate": rate, "recorded_rms": round(level, 4), "round_trip_ms": lag,
                   "format_ok": rate == 48000, "seconds": round(time.perf_counter() - started, 2)})
    out(f"Recorded {seconds:.0f} s from \"{recording['name']}\": level {level:.4f}, "
        f"round trip {lag if lag is not None else 'not found'} ms, rate {rate} Hz"
        + ("" if rate == 48000 else "  <- set the endpoint to 48000 Hz (Advanced tab)"))
    if level < 0.01:
        out("The recording is silent: the cable is not passing sound (is another app holding it exclusive?).")
    return report


def _round_trip(sent: np.ndarray, got: np.ndarray, rate: int) -> float | None:
    n = min(len(sent), len(got))
    if n < rate // 2 or float(np.max(np.abs(got[:n]))) < 1e-4:
        return None
    size = 1 << int(np.ceil(np.log2(2 * n)))
    cc = np.fft.irfft(np.fft.rfft(got[:n], size) * np.conj(np.fft.rfft(sent[:n], size)), size)
    lag = int(np.argmax(cc[: n // 2]))
    return round(lag * 1000.0 / rate, 1)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "list"
    dry = "--dry-run" in args
    if command == "script":
        print(SETUP_SCRIPT)
        return 0
    if command in ("list", "verify"):
        report = verify(dry_run=dry or command == "list")
        return 0 if report.get("route_ready") or dry or command == "list" else 1
    print("usage: python -m star.senses.routes list | verify [--dry-run] | script")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
