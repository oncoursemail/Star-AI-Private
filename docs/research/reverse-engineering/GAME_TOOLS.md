# Game engineering tools in the RE gateway

These tools live in `star/reverse_engineering.py` with the other `re_*` tools. Like them they are
OFF until the owner sets `reverse_engineering_enabled` in the settings file and selects a workspace
folder. They read only files the user points at (workspace-relative, or inside `re_game_path`), never
run them, and never use the network. A prompt about asset manifests, WebAssembly, WebGPU, porting a
game to the web, PS3 or recompilation offers only these game tools; a binary-analysis prompt offers the
full RE set.

## `re_verify_asset_manifest`

Checks every asset listed in a JSON manifest against its size and SHA-256 (detects same-size
corruption, missing, changed and unreadable files). Manifest format:

```json
{"schema_version": "star-asset-manifest-v1", "package_id": "my-game", "version": "1",
 "assets": [{"path": "assets/level1.bin", "size_bytes": 1024, "sha256": "<64 hex>",
             "source": "https://example.org/where-it-came-from", "license": "CC-BY-4.0"}]}
```

Verdicts: `PASS` (all sizes and hashes match), `FAIL`, `INCOMPLETE` (15 s budget ran out). Optional
`expected_manifest_sha256` pins the manifest itself. Limits: 128 assets, 128 MiB per file, 512 MiB in
total. Paths must be portable (no `..`, drive letters, backslashes, Windows device names, links); the
gateway's credential-file blocks apply. A PASS proves byte consistency with the manifest, not who wrote
it or whether the source/license labels are true.

## `re_wasm_portability`

Parses a `.wasm` module's sections and reports: each memory (initial/max pages and MiB, shared,
Memory64, imported), the `target_features` custom section, import modules and host APIs seen in
imports (WebGPU `wgpu*`, WebGL `gl*`, WASI, Emscripten runtime). Findings follow from those facts:
Memory64 needs runtime support, a shared memory means threads and a cross-origin-isolated page
(COOP/COEP), WebGPU imports need a GPU adapter (no automatic WebGL fallback), WASI imports need a WASI
runtime or browser shim, SIMD/exception-handling need target support. It does not probe a browser or
GPU and does not prove the module runs anywhere.

Background research: `docs/research/STAR_GRAND_V_RESEARCH_20261019.md`.

## PS3 tools: your own ISO or game folder

Set `re_game_path` in the settings file to your PS3 ISO image (`.iso`) or extracted game folder (for
example the folder holding `PS3_GAME/` or `PARAM.SFO`). The tools read it in place: nothing is copied
into the workspace or the repo, nothing is extracted, nothing is downloaded. Use `"source": "game_path"`
to target it; `"source": "workspace"` (default) reads the workspace, where an `.iso` file can be read
with `iso_member`.

- `re_ps3_game_scan` lists PARAM.SFO fields (TITLE, TITLE_ID, versions) and every executable
  (EBOOT.BIN, .self, .sprx, .elf, .prx) as `elf_ppu`, `elf_spu`, `sce_encrypted` or `unknown`
  (inside an ISO, `unknown` usually means an encrypted disc region).
- `re_ps3_elf_preflight` checks one PPU/SPU ELF: header, load map, PS3 profile limits (SPU 256 KiB local
  store, PPU 32-bit effective addresses), entry mapping and `.opd` metadata. For an ISO game path,
  `path` names the file inside the ISO, e.g. `PS3_GAME/USRDIR/EBOOT.ELF`.
- `re_verify_recompilation_evidence` compares a semantic contract with reference and candidate JSON
  observation records from a recompilation run and returns the first counterexample.

Encrypted SELF/EBOOT.BIN files are reported as `encrypted_container`: STAR has no console keys and
decrypts nothing; point the preflight at a decrypted ELF if you have one. The repo `.gitignore` keeps
ISOs, SELF/SPRX, EBOOT, PUP/RAP and key files out of commits.

Background research: `docs/research/STAR_PS3RECOMP_RESEARCH_20261019.md`.
