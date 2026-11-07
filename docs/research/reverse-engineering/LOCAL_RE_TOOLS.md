# Local reverse-engineering tools for STAR (2026)

Research for the `feature/local-re-tools` capability: free/open reverse-engineering
(RE) tools that run **locally on the owner's Windows PC** and can be driven
**headlessly from Python**. Scope is defensive and owner-permitted only:
analysing your own builds, crash dumps and file formats, interoperability, CTFs,
malware-analysis *learning*, and open-source decompilation. See
`star/skill_packs/re-methodology/SKILL.md` for the methodology STAR follows and
the hard guardrails (no anti-cheat/client-protection bypass, no game
cheats/exploits, no DRM/licence cracking, no malware creation).

Versions, sizes and automation APIs below were verified against GitHub release
pages, PyPI and official docs on **2026-10-13**. Items that could not be
confirmed are marked *unverified*.

## What STAR ships vs. what you install

STAR's `re_*` tools degrade gracefully:

- **Always available (pure-Python, no install, no network):** `re_identify`
  (magic/format, size, SHA-256, entropy), `re_strings` (ASCII + UTF-16LE), and
  `re_pe_info` (PE headers, sections, imported DLLs/functions, .NET flag) via a
  small built-in PE reader — no `pefile`/`LIEF` required.
- **Optional pip wheel:** `re_disassemble` uses `capstone` if importable.
- **Optional external tools (detected, never bundled):** `re_file_detect`
  (Detect-It-Easy), `re_dotnet_inspect` (ilspycmd), `re_radare2`
  (radare2/rizin), `re_ghidra_decompile` (Ghidra headless), `re_crash_dump`
  (cdb). When a tool is absent, the call returns install guidance and, where
  possible, a pure-Python fallback — it never fabricates output.

`re_tool_status` reports exactly which of these are present on the machine.

Game engineering tools (asset manifests, WebAssembly portability, PS3 ISO/game-folder scan, PS3 ELF
preflight, recompilation evidence) are in [GAME_TOOLS.md](GAME_TOOLS.md).

## Comparison table

| Tool | Latest (date) | Licence | Win download | Windows | Automation API | Best for |
|---|---|---|---|---|---|---|
| Ghidra | 12.1.4 (2026-09-21) | Apache-2.0 | 543 MB zip | Yes (JDK 21) | analyzeHeadless; PyGhidra 3.1.0 | Free full decompiler, scripted batch analysis |
| rizin | 0.9.1 (2026-06-29) | LGPL-3.0 | ~11 MB zip | Yes | rz-pipe (`rzpipe` 0.6.2) | Lightweight scripted disassembly |
| radare2 | 6.2.4 (2026-10-05) | LGPL-3.0 | ~13 MB zip | Yes | r2pipe 1.9.8; r2mcp | Scripted disassembly + MCP ecosystem |
| Cutter | 2.5.0 (2026-06-30) | GPL-3.0 | 134 MB zip | Yes | GUI only (embedded Python console) | Interactive work on top of rizin |
| IDA Free | 9.x line (Free build *unverified*) | Proprietary, non-commercial | *unverified* | Yes | **None** (no IDAPython, no idalib) | Manual x86/x64 only |
| Binary Ninja Free | *unverified* | Proprietary, non-commercial | *unverified* | Yes | **No API**; built-in MCP server | Manual work; LLM via its MCP |
| ILSpy / ilspycmd | 11.1 (2026-09-23) | MIT | 19 MB zip / 4.6 MB nupkg | Yes | `ilspycmd` CLI (**needs .NET 10**) | .NET decompilation to C# |
| dnSpyEx | 6.6.0 (2026-06-20) | GPL-3.0 | 95 MB win64 | Yes | dnSpy.Console.exe (*unverified*) | .NET debugging/patching |
| jadx | 1.5.6 (2026-07-10) | Apache-2.0 | ~69 MB zip | Yes (JRE) | `jadx` CLI | Android DEX/APK to Java |
| apktool | 3.0.3 (2026-07-20) | Apache-2.0 | 14.8 MB jar | Yes (Java) | CLI | APK resources/smali, rebuild |
| Frida | 17.23.3 (2026-10-09) | wxWindows | 50.7 MB wheel | Yes | `frida` Python module | Runtime hooking (dynamic) |
| x64dbg | 2026.05.27 | GPL-3.0 | 30 MB zip | Windows only | x64dbg-automate 0.9.2 (+MCP) | User-mode debugging |
| WinDbg / cdb | 1.2610.1001.0 | Proprietary, free | *unverified* | Windows only | `cdb.exe -z -c` | Crash dumps, `!analyze -v` |
| Wireshark / tshark | 4.6.9 (2026-09-23) | GPL-2.0 | *unverified* | Yes | tshark CLI; pyshark | Network traffic |
| binwalk v3 | 3.1.0 (2024-10-31) | MIT | **no official Windows build** | WSL/Docker | CLI, JSON log | Firmware carving |
| Detect-It-Easy | 3.21 (2026-04-21) | MIT | 24 MB zip | Yes | `diec -j`; die-python 0.5.0 | Packer/compiler identification |
| capstone | 5.0.9 (PyPI) | BSD | 1.3 MB wheel | Yes | Python | Disassembly library |
| unicorn | 2.1.4 (2025-09-09) | GPL-2.0 | 15.9 MB wheel | Yes | Python | CPU emulation |
| angr | 10.0.3 (2026-10-10) | BSD-2 | 8.8 MB wheel (+deps) | Yes (Py 3.12+) | Python | Symbolic execution |
| LIEF | 1.0.0 (2026-07-12) | Apache-2.0 | 4 MB wheel | Yes | Python | Parse/modify PE/ELF/Mach-O |
| pefile | 2024.8.26 | MIT | pure Python | Yes | Python | Parse PE |
| pyelftools | 0.33 (2026-05-29) | public domain | pure Python | Yes | Python | Parse ELF |
| dnfile | 0.18.0 (2026-01-31) | MIT | pure Python | Yes | Python | Parse .NET metadata |
| ImHex | 1.38.1 (2025-12-21) | GPL-2.0 | 36.5 MB msi | Yes | `imhex --pl/--magic/--hash` | Hex editing, format patterns |

## Per-tool install + headless notes (Windows)

**Ghidra 12.1.4** — Apache-2.0. Needs 64-bit JDK 21 (`winget install
EclipseAdoptium.Temurin.21.JDK`). Not on winget; download the zip from GitHub
releases or `choco install ghidra`. Set `GHIDRA_INSTALL_DIR`.
- Headless: `support\analyzeHeadless.bat C:\proj P -import a.exe -postScript
  Script.py -scriptPath C:\scripts -deleteProject`
- PyGhidra 3.1.0: `pip install pyghidra`; `pyghidra.start()` then
  `open_project(...)` / `program_context(...)` / `analyze(...)`.
- STAR's `re_ghidra_decompile` runs analyzeHeadless with the bundled
  `star/re_scripts/DecompileOne.py` post-script in a `-deleteProject -readOnly`
  temporary project and captures one function's decompiled C.
- Sources: https://github.com/NationalSecurityAgency/ghidra/releases ·
  https://ghidradocs.com/12.1_PUBLIC/Ghidra/Features/PyGhidra/pypkg/README.html

**Ghidra MCP servers** — LaurieWired/GhidraMCP 2.0 (Apache-2.0, 2026-10-10) now
runs headless via PyGhidra (`uvx --from "ghidra-mcp[headless] @
git+https://github.com/LaurieWired/GhidraMCP" ghidra-mcp --headless --binary
t.exe`). clearbluejar/pyghidra-mcp 0.2.7 is headless-first (`uvx pyghidra-mcp
<binaries>`, needs `GHIDRA_INSTALL_DIR`; beta). Sources:
https://github.com/LaurieWired/GhidraMCP · https://github.com/clearbluejar/pyghidra-mcp

**radare2 6.2.4 / rizin 0.9.1** — LGPL. radare2 not on winget (`choco install
radare2` or the `-w64.zip`); `winget install Rizin.Rizin`. `pip install r2pipe`
(or `rzpipe`), both pure Python needing the exe on PATH.
- Python: `r = r2pipe.open("a.exe", flags=["-2"]); r.cmd("aaa"); r.cmdj("aflj")`
- STAR's `re_radare2` exposes only a fixed allowlist (`iI`, `ii`, `iE`, `izq`,
  `isq`, `iS`, `ie`, `aflq`, and `aaa; pdf @ <symbol>`); no free-form r2 scripts.
- MCP: r2mcp (MIT) via `r2pm -Uci r2mcp`.
- Sources: https://github.com/radareorg/radare2 · https://github.com/rizinorg/rizin

**Cutter 2.5.0** — GUI over rizin; no headless mode. `winget install Rizin.Cutter`.

**IDA Free** — cloud decompiler only (x86/x64), local debugger; **no IDAPython,
no idalib, non-commercial**. idalib ships only with paid IDA; `ida-pro-mcp`
needs IDA Pro 8.3+. Not usable for local scripted decompilation.
Source: https://hex-rays.com/ida-free · https://github.com/mrexodia/ida-pro-mcp

**Binary Ninja Free** — no API, no plugins, non-commercial; headless needs a
paid licence. Ships an official MCP server. Source: https://binary.ninja/free/

**ILSpy / ilspycmd 11.1** — MIT. `dotnet tool install --global ilspycmd`.
**ilspycmd 11.x targets .NET 10**, so install the .NET 10 SDK/runtime
(`winget install Microsoft.DotNet.SDK.10`). Usage: `ilspycmd -p -o out a.dll`.
STAR's `re_dotnet_inspect` runs `ilspycmd <assembly>`. Source:
https://github.com/icsharpcode/ILSpy

**dnSpyEx 6.6.0** — GPL. Zip only. `dnSpy.Console.exe -o out a.dll` (*unverified*
for 6.6.0). For scripted .NET work prefer ilspycmd or `dnfile` in Python.
Source: https://github.com/dnSpyEx/dnSpy/releases

**jadx 1.5.6 / apktool 3.0.3** — Apache-2.0, Android. `winget install
Skylot.jadx`; `jadx -d out --deobf app.apk`. `choco install apktool`; `java -jar
apktool.jar d app.apk -o out`. Sources: https://github.com/skylot/jadx ·
https://github.com/iBotPeaches/Apktool

**Frida 17.23.3** — dynamic instrumentation. `pip install frida frida-tools`
(abi3 win_amd64 wheels, Py 3.12-3.14). Attaches to and hooks live processes;
STAR does **not** wire this by default (it is a runtime manipulation tool, out
of scope for the static-analysis capability). Source: https://github.com/frida/frida

**x64dbg 2026.05.27** — `winget install x64dbg.x64dbg`. Automation:
`pip install x64dbg_automate[mcp]` (needs the plugin + `X64DBG_PATH`). Debugger;
not wired by default. Source: https://github.com/dariushoule/x64dbg-automate-pyclient

**WinDbg / cdb** — `winget install Microsoft.WinDbg`; cdb ships in the Windows
SDK "Debugging Tools for Windows" (winget-package inclusion *unverified*). Dump
triage: `cdb -z crash.dmp -c "!analyze -v; k; q"`. STAR's `re_crash_dump` runs
exactly that `!analyze -v; q`. Source:
https://learn.microsoft.com/windows-hardware/drivers/debugger/cdb-command-line-options

**Wireshark/tshark 4.6.9** — `winget install WiresharkFoundation.Wireshark`;
`tshark -r cap.pcapng -Y http -T json`. Network, out of scope for the static
binary capability. 4.6.9 is a security release — keep updated.
Source: https://www.wireshark.org/news/20260923.html

**binwalk v3 (Rust) 3.1.0** — MIT. **No official Windows build.** Use
`pip install binwalk3` (bundles a Windows binary) or run under WSL/Docker.
`binwalk -e fw.bin`. Source: https://github.com/ReFirmLabs/binwalk

**Detect-It-Easy 3.21** — MIT. `winget install horsicq.DIE-engine`. CLI:
`diec -j target.exe` (JSON). `pip install die-python` for bindings. STAR's
`re_file_detect` runs `diec -j <file>` and falls back to `re_identify`.
Source: https://github.com/horsicq/Detect-It-Easy

**capstone / unicorn / angr / LIEF** — self-contained wheels (no compiler):
`pip install capstone` (5.0.9), `unicorn` (2.1.4), `angr` (10.0.3, Py 3.12+),
`lief` (1.0.0). `capstone` powers STAR's `re_disassemble`.

**pefile / pyelftools / dnfile** — pure-Python parsers. STAR implements its own
minimal PE reader so `re_pe_info` works even when these are absent; installing
`pefile`/`LIEF` can later enrich it.

**ImHex 1.38.1** — GPL. `winget install WerWolv.ImHex`. Headless pattern run:
`imhex --pl format -i file.bin -p fmt.hexpat`. An `--mcp` subcommand exists in
source (*presence in 1.38.1 unverified*). Source: https://github.com/WerWolv/ImHex

## Existing RE MCP servers (reference)

GhidraMCP (LaurieWired), pyghidra-mcp (clearbluejar), r2mcp/radare2-mcp, Binary
Ninja's built-in MCP, ida-pro-mcp (needs IDA Pro), x64dbg-automate MCP /
Wasdubya/x64dbgMCP, jadx-mcp-server (talks to a running jadx-gui, not headless).
STAR does **not** auto-connect any of these; they can be added later through the
reviewed MCP connector path (`star/mcp_connections.py`) rather than by widening
the built-in tool registry.

## Pure / self-contained pip packages on Windows (Py 3.12/3.13, win_amd64)

| Package | Version | Wheel | 3.12/3.13 |
|---|---|---|---|
| pefile | 2024.8.26 | pure | Yes |
| pyelftools | 0.33 | pure | Yes |
| dnfile | 0.18.0 | pure | Yes |
| capstone | 5.0.9 | win_amd64 (bundled DLL) | Yes |
| lief | 1.0.0 | cp312-abi3 win_amd64 | Yes |
| unicorn | 2.1.4 | cp37-abi3 win_amd64 | Yes |
| r2pipe / rzpipe | 1.9.8 / 0.6.2 | pure (need exe on PATH) | Yes |
| pyghidra | 3.1.0 | pure (needs Ghidra + JDK 21) | Yes |
| die-python | 0.5.0 | cp312/cp313 win_amd64 | Yes |
| frida | 17.23.3 | abi3 win_amd64 | Yes |

## Unverified items

IDA Free and Binary Ninja Free exact versions/sizes; whether the winget WinDbg
package includes `cdb.exe`; `dnSpy.Console` in 6.6.0; the binwalk v3 JSON-log
flag; and whether ImHex 1.38.1 ships `--mcp`.

## Legal / ethical note

Reverse engineering for interoperability, security research, teaching and your
own software is broadly permitted; circumventing technological protection
measures (DRM, anti-cheat), distributing or building game cheats/exploits, and
authoring malware are not. STAR enforces this in code (`star/reverse_engineering.py`
`check_intent` / `definitions` gating) and in the `re-methodology` skill pack:
the RE tools are simply not offered for a forbidden request, and analysis is
confined to the owner-selected workspace.
