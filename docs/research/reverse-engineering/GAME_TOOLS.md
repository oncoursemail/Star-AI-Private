# Game engineering tools in the RE gateway

These tools live in `star/reverse_engineering.py` with the other `re_*` tools. Like them they are
OFF until the owner turns on Settings > reverse-engineering tools (`reverse_engineering_enabled`) and
selects a workspace folder. They read only workspace-relative files the user points at, never run them,
and never use the network. A prompt about asset manifests, WebAssembly, WebGPU or porting a game to the
web offers only these game tools; a binary-analysis prompt offers the full RE set.

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
