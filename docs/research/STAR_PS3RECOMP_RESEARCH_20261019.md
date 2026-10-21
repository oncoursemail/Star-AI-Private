# ps3recomp: source audit and an original STAR improvement

**Research date:** 19 October 2026. **Audited source:** `sp00nznet/ps3recomp`, commit [`749182eebb936f086a007f63e1c7d853f3cf708a`][commit]. This is also the target of the annotated `v0.16.0` release tag. **Method:** GitHub API metadata, pinned source inspection, release notes, issue discussions, and recorded CI results. No upstream program, downloaded binary, game, or firmware was executed in this audit.

## Findings that matter for STAR

ps3recomp is a substantial open-source PS3 recompilation toolkit. Its useful engineering is the combination of machine-code analysis, separate PPU and SPU lifters, runtime replacements for console services, graphics translation, and tests that compare machine behavior. It is not an AI model or an automatic guarantee that an arbitrary PS3 title becomes a correct, fast desktop application. Its own platform matrix distinguishes building the runtime from running an actual game. [Architecture][architecture] · [Platform and title status][readme]

The strongest transferable improvement is **complete, scoped evidence before declaring success**. Source inspection identified several places where incomplete input or incomplete testing can remain nonfatal: truncated ELF tables, PPU cases skipped during test generation, and a differential-test wrapper that discards the executable's failure status before asking a mismatch-only classifier for its verdict. These observations support three original STAR capabilities: strict PS3 ELF preflight, structured recompilation evidence verification, and guidance grounded in this pinned research. They do not establish that every upstream result is wrong.

This document separates **observed source behavior**, **maintainer reports**, and **engineering inference**. Recommendations describe what STAR should implement; they are not evidence that those features have already shipped.

## 1. What was actually released

The latest release inspected was [`v0.16.0`, “Forty-Four”][release], published on 19 October 2026 at 16:50:19 UTC. Its annotated tag object, [`7850b7af66bc1a519e0d2ac0c1615f93bfb84ebb`][tag], resolves to the audited commit. The release provides Windows x64, macOS arm64, and Linux x64 ZIPs plus `SHA256SUMS.txt`. The packaging workflow builds an SDK around the runtime library, headers, and Python tools. These are toolkit distributions, not completed ports of every game. [Release workflow][release_workflow]

The release notes describe fixes from 44 pull requests: RSX texture and transfer behavior, flip completion ordering, shader caches, SPU image selection, SPURS atomic updates, filesystem flags, and host portability. This is evidence of active work on real compatibility problems. A particularly relevant fix selects the lifted SPU image by the thread's actual bytes instead of whichever image registered first at an entry address. The same release explicitly holds back the memory-domain proposal in PR #296 because it breaks another title's boot. Both points show why individual improvements need cross-title regression evidence. [Release notes][release]

The repository's own license is [MIT][license]. STAR can learn engineering principles from these published sources without incorporating their implementation. Any future use of another project's source should preserve its actual provenance; this proposed add-on is original code.

## 2. Architecture, from guest bytes to host behavior

The pipeline is more than assembly-to-C text conversion:

| Stage | Source-confirmed responsibility | Why the distinction matters |
|---|---|---|
| ELF and image analysis | Parse headers, program and section tables, imports, exports, and relocations; the PPU loader emits load-segment, function, entry, TOC, and import metadata. | A syntactically recognized file is not proof that all declared bytes and addresses are usable. |
| PPU lifting | Translate PowerPC/VMX instructions into host code operating on an explicit guest register and memory model. | Width, endian order, carry bits, condition registers, floating-point behavior, and call ABI remain semantic obligations. |
| SPU lifting | Translate a separate instruction set with local-store addressing, vector registers, branches, channels, and DMA helpers. | PPU assumptions cannot simply be reused for SPU programs. |
| Runtime and system services | Supply guest memory, dispatch, threads, synchronization, SPURS scheduling, and HLE library behavior. | Correct individual instructions can still produce incorrect program behavior when ordering or service contracts differ. |
| Graphics and host integration | Translate guest RSX commands and shaders, present frames, and connect input/audio/filesystem behavior. | A CPU test or a headless draw submission does not certify the visible game. |

Sources: [ELF parser][elf] · [PPU loader][loader] · [PPU lifter][ppu] · [SPU lifter][spu] · [Runtime architecture][architecture] · [Module status][modules].

The PPU loader can resolve a main executable's entry as a function descriptor and records the code address and TOC separately, retaining a direct-entry fallback. This matters for STAR preflight: requiring the raw PPU ELF entry value itself to reside in executable bytes can reject a legitimate descriptor-based image. SPU entry handling is different. Structural checks must therefore declare the precise architecture profile they support. [Loader implementation][loader]

There is also a real runtime SPU interpreter. `spu_interp_run_until` executes instructions and can rejoin a registered lifted function; unsupported interpreter operations stop execution. The fallback and handoff documents explain how this connects to lifted paths. Therefore the README's broad ahead-of-time description needs qualification: the actual design can combine lifted code with runtime interpretation. That is a practical compatibility mechanism, not proof of pure ahead-of-time coverage. [Interpreter][interpreter] · [Handoff design][handoff]

Some documentation reflects earlier milestones. `docs/PPU_RECOMP.md` reports roughly 99.8% coverage by counting emitted TODO no-ops and still lists full-image output splitting as future work, whereas the current lifter contains output chunking. Treat that percentage as a historical, corpus-dependent emission measure, not an independently verified percentage of instruction semantics or game compatibility. [Older PPU notes][ppu_doc] · [Current lifter][ppu]

## 3. Evidence of real engineering, with its scope intact

### Recorded CI

At the exact audited commit, GitHub reports successful [Windows][ci_windows], [macOS][ci_mac], [Linux][ci_linux], and [Linux Vulkan][ci_vulkan] workflow runs. The Linux run contains GCC/Clang and Debug/Release jobs. Its workflow builds the runtime, runs Python lifter suites and C tests, checks the PPU boot scaffold, and exercises headless host behavior, SPU coherency, scheduling, task wakeups, and RSX components. These are meaningful checks. This audit read their recorded outcomes; it did not rerun them. [Linux workflow source][linux_workflow]

The pinned README explicitly says that successful runtime builds and tests do not mean a game ran. Its in-tree gameplay row is affirmative for Windows and negative for macOS and Linux, while describing downstream ports that carry additional patches. That boundary should survive every summary STAR makes. [Platform matrix][readme]

### Semantics-oriented testing

The PPU conformance generator creates instruction encodings, decodes and lifts them, compiles the generated host statements, and compares resulting registers, condition bits, vectors, and memory against expected values. This is stronger evidence than inspecting generated text alone. The PPU and SPU lift selftests also offer a useful pattern: compile synthetic guest functions, lift them, compile the result for the host, and compare outputs with native versions of the same corpus. [PPU conformance][ppu_test] · [PPU selftest][lift_selftest] · [SPU selftest][spu_selftest]

The SPU differential harness compares interpreter and lifted behavior with references. Its float referee uses exact rational arithmetic to adjudicate selected disagreements instead of assuming that a second implementation is infallible. The code explicitly models SPU-specific floating-point cases, including extended exponent values, truncation, and undefined conversion scales. This is an excellent design lesson: record which oracle and semantic rule support each result. Agreement between two implementations and agreement with a specification are different kinds of evidence. This audit inspected that model; it did not independently prove its ISA fidelity. [Differential harness][diff] · [Exact referee][referee] · [Oracle setup][oracle]

### Gameplay and performance claims

The maintainers report Simpsons Arcade reaching playable stages and online play, and Tornado Outbreak reaching its first level under control at about 10–16 fps. Community reports include inFamous gameplay on macOS around 13 fps. These are title- and scenario-specific reports; this audit did not reproduce them. They do not justify a universal performance advantage over an emulator or a claim that every port is playable. [Title status][readme] · [inFamous development report][infamous]

## 4. Concrete opportunities found in source

### A. Distinguish permissive parsing from verified structure

`ELFHeader.parse` selects ELF64 only when the class equals its known ELF64 value, and big-endian only when the encoding equals its known big-endian value. Other values fall through to the alternate interpretation rather than receiving an explicit invalid-enum rejection. `_parse_program_headers` and `_parse_section_headers` break when the declared next entry extends past the available file. These routines are useful analysis code, but their permissiveness should not become STAR's claim that the complete declared structure is valid. [Parser][elf]

**STAR opportunity:** reject unsupported identification values; check complete table bounds, entry sizes, segment file bounds, `filesz <= memsz`, address ranges, and architecture-specific entry rules. Report encrypted/container formats as unsupported by this preflight. Separate malformed data from a valid format outside the supported profile. A successful result should mean only that the specified structural checks passed.

### B. Keep unsupported instructions visible

The PPU lifter's final translation fallback emits a TODO comment followed by a semicolon. Some unsupported operand paths similarly emit comments. Consequently, generation or compilation alone cannot establish semantic coverage. The SPU lifter's general unsupported fallback is stronger, emitting a runtime trap helper, although some unresolved branch paths still emit TODO comments. Cache hints or deliberately modeled no-ops should be distinguished from genuinely unsupported behavior rather than mechanically treating every comment alike. [PPU translation][ppu] · [SPU translation][spu]

**STAR opportunity:** maintain an explicit inventory of required instructions, branches, and cases. An unsupported item remains an unresolved obligation. Successful host compilation must not promote it to verified behavior.

### C. Prevent the test inventory from silently shrinking

In `test_ppu_lift.py`, generation skips scalar or vector cases when decoding produces a different mnemonic or when the lifted statement begins with a comment. It reports the skipped count, but the generated C result fails on failed checks, not skipped cases. A targeted memory-barrier ratchet explicitly prevents those cases from disappearing; the same complete inventory requirement is not applied globally. This does not show that current CI omitted a particular required instruction. It shows how future coverage could shrink while the surviving cases stay green. [Conformance generation][ppu_test]

**STAR opportunity:** declare expected case IDs before evaluating observations. Missing, duplicate, unexpected, skipped, and undefined cases require distinct outcomes. Zero observed cases must never satisfy a nonempty required inventory.

### D. Preserve process failure and completion evidence

The differential wrapper contains the consequential fragment `> "$OUT/run_$mode.log" 2>&1 || true`: it discards the executable's nonzero status so disagreements can be adjudicated later. It then relies on the float referee's result. The referee collects unresolved mismatch lines and finishes with `sys.exit(1 if bad else 0)`; it does not require a test-completion marker or a positive trial count. [Wrapper][diff_wrapper] · [Referee][referee]

**Static control-flow finding:** an empty log makes the standalone referee return success. In the wrapper, a runtime failure that produces an ordinary error line but no recognized mismatch can likewise reach the printed PASS result: the original exit status is discarded, and the classifier has no unresolved mismatch to reject. The intervening `rg | tail` pipeline supplies no completion check. This was established by reading the code, not by executing an upstream crash scenario.

The differential C harness already emits useful completion and trial summaries. A verifier can require those facts while allowing an explicitly modeled mismatch-adjudication phase. **STAR opportunity:** keep process status, completion, coverage, and semantic agreement as separate mandatory evidence fields. Absence of a failure message is insufficient. [Harness summaries][diff]

### E. Separate cold boot, warm boot, milestones, and pixels

The regression-gate documentation candidly acknowledges that runs are not hermetic: installation changes state, so a later run may stop exercising first-boot paths. Missing local port directories are skipped, and some configured ports accept any terminal state while comparing milestones. Optional screenshot checks are distinct from the default headless path. These are reasonable development choices, but a broad “all games passed” claim would exceed their scope. [Regression design][regression] · [Port configuration][ports]

**STAR opportunity:** record scenario identity and required coverage, and separate cold/seeded state from warm state. CPU semantics, boot progress, rendering, input response, audio, and performance each need their own evidence.

## 5. The proposed STAR add-on

The following design is original and deliberately bounded:

| Capability | Useful behavior | Claim boundary |
|---|---|---|
| `re_ps3_elf_preflight` | Inspect an authorized local file; identify supported PPU/SPU ELF profiles; return bounded structural diagnostics and artifact identity. | Does not execute, decrypt, recompile, or certify gameplay. |
| `re_verify_recompilation_evidence` | Compare declared expected cases with structured observations; reject contradictory identity, missing coverage, failed completion, mismatched values, and unsupported outcomes. | Checks supplied evidence; it cannot independently prove that an untrusted producer really ran a test. |
| `re_recompilation_guidance` | Supply architecture-specific investigation steps and immutable source references; explain what stronger evidence remains necessary. | Adds retrievable engineering knowledge and tool behavior, not foundation-model training or new permissions. |

An evidence contract should bind the source artifact, generated artifact, test suite, and oracle identifiers. Case values should carry widths or an exact byte representation so signed integers, endian order, and vector lanes cannot be accidentally normalized away. Expected data should be distinct from observed data. A producer must not be allowed to rewrite its own required inventory during verification.

For future executable semantics work, build original synthetic fixtures around high-value boundaries: carries and overflow, shift counts, signed comparisons, vector-lane order, floating-point exceptional encodings, DMA ordering, and SPU image identity. Preserve counterexamples with the exact input, expected output, observed output, toolchain, and reference revision. A tiny reproducible disagreement is more useful than an unexplained compatibility percentage. The current add-on can validate receipts without claiming to implement that complete execution laboratory.

STAR becomes materially better at researching and reviewing recompilation when it refuses to collapse “parsed,” “generated,” “compiled,” “executed,” “matched,” and “playable” into one success state. That improvement is measurable with original synthetic tests for malformed inputs, empty reports, missing cases, duplicate observations, wrong artifact identities, and incomplete runs. Performance and game compatibility require separate measured work.

## Implementation accompanying this research

Shipped in STAR (branch star/re-gateway-tools-20261021) behind the default-off RE setting: `re_ps3_game_scan` (reads the owner's own PS3 ISO or extracted game folder in place: PARAM.SFO and every executable classified as PPU/SPU ELF or encrypted SELF), `re_ps3_elf_preflight` (now also reads files inside an ISO) and `re_verify_recompilation_evidence`. The proposed `re_recompilation_guidance` tool returned fixed text and was dropped; its content is this document. Usage: [game tools](reverse-engineering/GAME_TOOLS.md).
