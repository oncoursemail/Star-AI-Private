# Grand-V research and practical upgrades for STAR AI

Research date: 2026-10-19. Source snapshot: `6cef9e1fcca97dde758be845930a7bb9738339b9` in `SebasKitten/Grand-V` on GitLab. This document records source inspection, maintainer statements, and proposed original STAR engineering work. It does not claim that Grand-V binaries or complete gameplay were tested.

## Main finding

Grand-V is an AI-assisted project that presents GTA V running in a browser. The supplied releases link currently distributes its **native desktop launcher and hosting backend**. That distinction matters: the accessible repository publishes Rust launcher source, while its description of a reverse-engineered RAGE engine running through WebAssembly memory64, shared-memory workers, and WebGPU is a broader project claim. The inspected tree does not contain the complete game engine or a reproducible browser-game build. STAR can learn useful engineering from the available source without assuming the absent implementation has been independently verified. [Project description](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/README.md), [pinned source tree](https://gitlab.com/SebasKitten/Grand-V/-/tree/6cef9e1fcca97dde758be845930a7bb9738339b9).

The strongest immediate STAR opportunity is concrete: improve asset integrity verification, preserve the scope of evidence, and require measured results before promoting a lesson. These improvements can benefit Paintball, Metallic, Roblox assets, browser previews, and other projects without depending on GTA-specific code.

## 1. What was inspected

Public GitLab API responses, release metadata, repository history, the full recursive file inventory, launcher documentation, the Rust package manifest, all launcher Rust modules, and compatibility-test sources were inspected. The snapshot contains **50 tree entries, including 37 files**. Downloaded text was read as research material; no downloaded code, launcher binary, game executable, or game asset was executed. [Tree API at the inspected commit](https://gitlab.com/api/v4/projects/87786272/repository/tree?ref=6cef9e1fcca97dde758be845930a7bb9738339b9&recursive=true&per_page=100).

Search-engine results for the former GitHub location showed older repository contents. Direct GitLab inspection established the current release and source availability. This is itself a useful STAR lesson: search snippets should help locate evidence, while decisions about current repository contents should use the live source and a pinned revision.

### Release snapshot

| Field | Observed value |
|---|---|
| Release | GrandV Desktop Launcher — 2026.10.18 |
| Tag | `launcher-2026.10.18` |
| Publication | 2026-10-18 at 16:25:46 UTC |
| Platforms | Windows x64, Linux x64, macOS Apple Silicon, macOS Intel |
| Integrity artifact | `SHA256SUMS.txt` |
| Included game assets | None, according to release notes |

The release describes a mirror of existing packages, with repackaging rather than a new launcher-code build. It identifies original source snapshot `43bf0f383753b4c4900a0c6e94051af8c1b2efe8`, binary-build commit `9105343dab655367f42293ea343c6693867a0a38`, and macOS repair commit `baf26a5d16cdf006212e280c48cb0cb21c412283`. These are maintainer-provided provenance statements, not reproduced builds from this research. [Release record](https://gitlab.com/SebasKitten/Grand-V/-/releases/launcher-2026.10.18), [release API](https://gitlab.com/api/v4/projects/87786272/releases/launcher-2026.10.18).

The checksum manifest was retrieved, but the packages were not downloaded and independently hashed. The release also states that full macOS/Linux gameplay validation remains pending. Its macOS packages are locally signed without Developer ID signing or notarization. [Checksum manifest](https://gitlab.com/api/v4/projects/87786272/packages/generic/grandv-launcher/2026.10.18/SHA256SUMS.txt), [release notes](https://gitlab.com/SebasKitten/Grand-V/-/releases/launcher-2026.10.18).

## 2. What the source confirms

### A compiled desktop host

The Rust crate is `gta-browser-launcher`, version `0.1.0`, using edition 2024. Its dependencies identify an eframe desktop interface, Tokio asynchronous execution, Axum/Hyper HTTP and WebSocket handling, rustls TLS, certificate-generation support, JSON serialization, QR generation, and browser launching. Release configuration enables thin link-time optimization and stripping. These are concrete implementation choices; they do not establish a performance advantage over the previous implementation. [Cargo manifest](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/Cargo.toml).

The architecture separates the native host from browser execution. The desktop process manages files, networking, and the user-facing hosting lifecycle; the browser receives the game frontend and requested assets. Replacing that host with Rust is a narrower change than translating a complete game into a different language.

### Asset serving and bounded requests

The HTTP implementation supports ordinary file requests, HEAD, single byte ranges, and a batch endpoint with optional gzip. It supplies cross-origin isolation headers and suitable WASM/JavaScript content types. Batch requests are limited to 1,000 ranges and 64 MiB of selected data, but the implementation assembles the batch in memory before sending it. Compression can require additional memory. This creates an opportunity for an original STAR host to combine streamed responses with a global budget across simultaneous requests. [HTTP implementation](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/src/server.rs).

Current settings make the direct-hosting connection limit configurable, with zero meaning unlimited. Automatic Cloudflare tunnel mode selects 200. Therefore, an older documentation reference to 128 connection slots should not be treated as the current fixed limit. Application connections, proxy in-flight requests, relay sessions, and players are distinct quantities. [Configuration implementation](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/src/config.rs).

### Experimental multiplayer has a defined scope

The relay supports two players per room and 64 concurrent sessions. Clients must provide the supported protocol, access code, and compatible build/map identifiers. The server assigns player IDs and forwards validated, sequenced pose updates. It advertises 20 Hz, applies a message token budget, coalesces recent poses, bounds control-event queues, and removes stalled peers. The inspected code does not implement authoritative world simulation, synchronized missions, NPC behavior, or comprehensive multiplayer physics. [Relay implementation](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/src/relay.rs).

The reusable lesson is to handle transient state and reliable events differently. A slow consumer usually needs the newest position, while join/leave events need explicit delivery handling. Higher room capacity alone would not turn this relay into a competitive multiplayer backend.

### Lifecycle, storage, and diagnostics

The storage module uses atomic writes, bounds individual save files and profiles, validates paths, checks existing ancestors against symlink/junction escapes, and manages deletion metadata. These are relevant patterns for STAR-generated projects and local asset tooling. They should be implemented and tested against STAR's own formats and filesystem requirements. [Storage implementation](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/src/storage.rs).

Tunnel ownership is explicit: the launcher tracks and stops the process it creates. Diagnostic history is bounded to 1,500 lines and 512 KiB. These practices can keep repeated STAR tool runs from leaving orphan services or growing logs indefinitely. [Tunnel implementation](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/src/tunnel.rs), [diagnostics implementation](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/src/diagnostics.rs).

## 3. AI and REA: the useful connection

An October 12 historical README attributes the project heavily to REA and AI, and says the author used OpenAI's AI. This is evidence of the author's described workflow. It does not establish which exact model performed every task, how much work was autonomous, or that every stated gameplay capability was independently validated. [Historical README](https://gitlab.com/SebasKitten/Grand-V/-/blob/b1fe3388149be5e08cc397757bb6b849caf63324/README.md).

REA is an analysis toolkit exposed through MCP and a CLI. It connects an agent to inspection of binaries, JavaScript/Electron applications, .NET assemblies, websites, and other artifacts. Its documented workflow is to gather evidence, inspect relevant behavior, and let the agent use those findings to explain or implement a feature. It is not a substitute model or a universal source-code converter. [Official REA README, inspected revision](https://github.com/morluto/rea/blob/2e5171e391b83f8a467d0861fd452c1f78621fd8/README.md), [official REA site](https://rea.tools).

For STAR, the useful sequence is:

1. Identify the behavior being investigated and the supplied artifact.
2. Select an appropriate inspection tool.
3. Preserve source locations, hashes, observations, and uncertainty.
4. Write an explicit behavior contract.
5. Implement an original version in the target project.
6. Test it and retain the successful, reproducible lesson.

Source inspection, runtime execution, and gameplay testing should remain distinguishable. A tool returning plausible pseudocode is evidence to investigate, not proof that the reconstruction is correct.

## 4. What STAR should improve first

### A. Detect same-size asset corruption

Grand-V's package-validation routine checks the manifest format, listed paths, file presence, and expected byte lengths. It does not compare content digests. Consequently, a changed file with the same length can satisfy that routine's checks. This conclusion follows from the inspected validation function, not from executing a malicious or corrupted Grand-V package. [Asset validator](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/src/config.rs).

An original STAR validator should require a versioned manifest containing each relative path, byte size, and SHA-256 digest. Provenance fields can record the source, applicable asset license, and build identity. Verification should stream bytes, enforce resource limits, reject ambiguous paths and duplicates, and distinguish missing files from digest mismatches.

A checksum proves consistency with the supplied manifest, not that the manifest came from a trusted publisher. If both content and manifest can be replaced together, matching hashes do not authenticate the release. Repository revision, trusted manifest provenance, and any applicable release signature remain separate evidence.

The audit should also describe its filesystem assumptions. A report applies to the bytes read during that run; later edits invalidate the result. Files changing during verification should produce an unstable-input failure or an explicitly bounded retry. Windows drive paths, UNC paths, reserved names, and junctions need deliberate treatment because STAR must work on the owner's Windows desktop. Metadata-only inspection should never be presented as equivalent to hashing content, and an optional deep scan should expose its byte budget before processing a very large project.

Focused acceptance cases should include valid assets, missing files, truncation, equal-length corruption, malformed hashes, escaping paths, and incompatible manifest versions. The existing project's package-test source provides context for what its manifest checks cover; STAR should use independently authored fixtures. [Grand-V asset-package test](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/tests/asset_package.rs).

### B. Preserve evidence scope in STAR's learning system

Every imported reference should distinguish:

| Evidence class | What it establishes |
|---|---|
| Maintainer statement | What the author says the project does |
| Source inspection | Behavior visible in identified code |
| Static fixture test | Behavior of a limited automated fixture |
| Runtime test | Observed execution on a recorded environment |
| Gameplay test | Recorded behavior in an actual game scenario |
| Benchmark | A measured workload with an explicit comparison |

These categories should be attached to individual claims. A report may contain several classes without allowing one successful fixture to certify the entire product. In particular, Grand-V's compatibility tests use temporary data and loopback fixtures; their existence supports an engineering test strategy, not an inference that every target platform plays the full game correctly. [Compatibility-test source](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/tests/compatibility.rs).

### C. Add browser capability and performance evidence

Before approving a generated browser project, STAR should collect observations for the exact capabilities it uses: secure context, isolation, WebGPU device creation, required WASM features, worker initialization, and successful asset loading. Unsupported capabilities should produce a clear diagnostic or a tested fallback.

Performance reports should record environment, workload, warm/cold state, sample count, and limits. Useful outcomes include time to interaction, frame-time percentiles, long stalls, memory high-water marks, and load failures. An FPS cap, a successful compilation, or choosing Rust cannot substitute for these measurements.

### D. Improve hosting boundaries

The launcher documents an important public-hosting limitation: its multiplayer code protects the relay, while the public URL also exposes hosted files and existing save APIs. It also explains origin-specific browser storage and shared per-IP limits behind its tunnel. STAR's own future host should give public content, user saves, multiplayer admission, and administrative controls explicit, independently tested access boundaries. [Hosting documentation](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/README.md).

## 5. An achievable implementation sequence

**First, integrate the reference and asset-verification work.** Add this pinned research to STAR's private development documentation, an original offline manifest-audit tool, and focused tests. Preserve the project's established tool registry and enablement controls. Report exactly which validator guarantees are implemented.

**Second, connect the results to lessons.** Save a structured candidate containing the question, reference revision, relevant evidence, implementation location, validation result, and remaining uncertainty. Promote it only through STAR's existing acceptance mechanism. This improves retrieval and future decisions; it does not claim automatic model-weight training.

**Third, apply the tool to an owned project.** Build a manifest for a small, representative Paintball or Metallic asset set, then deliberately alter a fixture while preserving its byte length. Confirm that the original healthy set passes and the changed fixture fails with an actionable report. Extend coverage only to resolve concrete remaining risks.

**Fourth, measure browser and hosting changes separately.** Introduce capability reports and resource budgets before broad deployment. Use representative multi-client sessions and actual target devices where those are required. Track full-game checks separately from native launcher startup and backend fixtures.

### Apply the learning to the right project

For Paintball, asset integrity can help detect damaged or mismatched local content, but it does not by itself fix material replication, grenade timing, bot behavior, or interaction bugs. Those require tests of the actual gameplay and networking paths. For Metallic, the relevant lessons are version agreement, streaming budgets, controlled service ownership, and separation of player-facing endpoints from management operations. A successful browser-host experiment does not establish Minecraft server tick performance or Paper API compatibility.

For STAR itself, candidate lessons should contain a narrow trigger: for example, verify a packaged asset set before declaring it complete. Retrieval should bring that lesson into tasks with the same failure mode. Keeping the trigger and proof narrow makes the knowledge more useful than a broad instruction to imitate an entire reference project. The measurable improvement is fewer undetected content defects and more accurate completion reports.

## 6. Limits and integration status

No GTA game code or assets were imported into STAR by this research. No license file was found in the inspected Grand-V tree, and its Cargo manifest has no license declaration; the precise description is **public launcher source**, rather than a fully verified open-source game engine. The proposed STAR implementation is original and should cite the reference for the engineering observation it motivated. [Pinned tree](https://gitlab.com/SebasKitten/Grand-V/-/tree/6cef9e1fcca97dde758be845930a7bb9738339b9), [Cargo manifest](https://gitlab.com/SebasKitten/Grand-V/-/blob/6cef9e1fcca97dde758be845930a7bb9738339b9/LauncherApp/rust/Cargo.toml).

This document specifies research findings and implementation targets. The actual integration report must identify the STAR branch, changed files, executed tests, and enabled behavior. Success means STAR gains a tested capability and a reusable evidence-backed lesson. A claim that STAR surpasses a complete GTA browser port requires a much broader implementation and comparable gameplay evidence.


## 7. Implementation accompanying this research

The accompanying STAR changes implement three read-only tools through the existing optional reverse-engineering gateway: `re_verify_asset_manifest`, `re_game_portability_plan`, and `re_reference_guidance`. The verifier checks a new strict STAR manifest with content hashes; it does not accept Grand-V's size-only manifest as equivalent evidence. The planner uses caller-supplied capability reports and preserves unknowns. The guidance provides nine scoped engineering principles with source references, preconditions, and acceptance checks across six topics.

See [Reference engineering tool guide](../REFERENCE_ENGINEERING.md) for the exact schemas, limits, opt-in behavior, validation commands and limitations. This is source-backed planning and local asset checking. Actual browser/Studio execution, REA installation, benchmark comparison, automatic lesson import and model training are outside the implemented change.
