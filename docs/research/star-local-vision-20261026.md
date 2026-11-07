# Local vision candidates on STAR's 8 GB PC

Qwen3-VL-2B-Instruct is an explicit optional installer candidate: `setup.cmd -Only grounder -Grounder qwen3-vl-2b`. The existing default selection is unchanged. Installation verifies two pinned files and writes a separate candidate configuration; it does not start the server or enable vision actions. The server command binds to `127.0.0.1:8081`.

## Publisher evidence and storage

| Candidate | Publisher ScreenSpot-Pro result | Selected GGUF + vision files, decimal GB | Evidence and tradeoff |
| --- | ---: | ---: | --- |
| UI-TARS-2B-SFT | 27.7 | 2.449 | Existing pinned third-party conversion; native synthetic measurements below. [Publisher card](https://huggingface.co/ByteDance-Seed/UI-TARS-2B-SFT). |
| Qwen3-VL-2B-Instruct | 48.5 | 1.927 | Official Q4_K_M language weights + F16 vision encoder; smaller selected files, but no measured memory advantage established. [Official GGUF](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF). |
| Qwen3-VL-4B-Instruct | 59.5 | 3.333 | Higher publisher grounding result; more memory to measure. Research comparison only, not added to this installer. [Official GGUF](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF). |
| UI-TARS-1.5-7B | 49.6 | 5.539 | Existing pinned conversion leaves less room beside voice and games. The publisher says this released model is not specifically optimized for games. [Publisher card](https://huggingface.co/ByteDance-Seed/UI-TARS-1.5-7B). |

The Qwen results are Instruct columns in Table 4, page 18 of the [Qwen3-VL technical report](https://arxiv.org/pdf/2511.21631). The corresponding Thinking results are 32.2 for 2B and 49.2 for 4B. These are publisher benchmark results, not measurements of STAR's quantized files, current prompt, or RTX 4060 latency. Cross-paper evaluation conditions can differ. All four publisher cards identify Apache-2.0 licensing. Download size is not loaded VRAM: projector, context, compute buffers, Windows, speech and games also consume memory.

The optional 2B pin uses Qwen's official repository revision `52d6c8ffea26cc873ac5ad116f8631268d7eb503`. Its exact sizes and SHA-256 values are recorded in [pins.json](../../installer/star-home/pins.json). Pin selection was checked against official repository/LFS metadata; native installation subsequently verified the downloaded files. A different projector precision or revision is a different candidate and needs its own measurements.

## Preserve the failed center gate

Both installed 2B candidates hit all six intended 120×40 button boxes, but both failed the unchanged **mean ≤12 / maximum ≤20 px** center-distance gate. UI-TARS-2B measured **18.2389 px mean / 22.0227 px maximum**; Qwen3-VL-2B measured **37.8218 px mean / 42.7200 px maximum**. Those failures remain recorded in the [native validation record](../agents/codex-native-pc-validation-20261026.md). No threshold, prompt, fixture or coordinate offset is changed to turn either result into a pass. A text-anchor explanation is plausible, not established.

[ScreenSpot-Pro's evaluator](https://github.com/likaixin2000/ScreenSpot-Pro-GUI-Grounding/blob/main/eval_screenspot_pro.py#L123-L138) instead scores a point by whether it falls inside the target bounding box. Each candidate's six hits are useful descriptive evidence under another metric, not replacement gate results. UI-TARS requests took 1.286 s first and 0.103–0.120 s subsequently; Qwen took 0.678 s first and 0.114–0.123 s subsequently. Each series reused the **same image**; neither measures changed-screen throughput or semantic frames per second.

Global free-VRAM snapshots were 7413→4647 MiB around UI-TARS and 7401→4483 MiB around Qwen. They were uncontrolled snapshots, not isolated model allocations, and establish no memory winner. The earlier 2,536 MiB allocation claim was incorrect. Both owned servers were stopped after testing, with 7401 MiB free in the later snapshot; active `grounder.kind` remains `none`.

## Proposed independent holdout protocol

This is a proposal for a future diagnostic, not a changed repository evaluation or an executed test:

1. Freeze candidate hashes, prompt, preprocessing, coordinate convention and timeouts first. An independent reviewer or owner then creates and hashes 60 new synthetic scenes: four resolutions × three target-size bands × five cases. Balance text and icon targets, vary layouts, fonts and distractors, and exclude the six calibration scenes. Do not fit an offset or change settings after observing answers.
2. Send one request per changed scene. Invalid, nonfinite, out-of-range, missing or timed-out answers count as failures; no retries or best-of selection. Preserve raw answers and per-case results. Define bounds before any coordinate clamping.
3. Predeclare the diagnostic gate as **60/60 first-pass points inside the intended bounding box**. Report center distance, edge clearance, size/resolution strata and changed-image latency separately. Keep the earlier failed center gate in the report regardless of this result. A synthetic pass does not establish arbitrary desktop reliability.
4. Test absent/ambiguous targets separately before relying on abstention. A point-only response can guess. Native click accuracy and STOP also remain separate: explicit custom movement profiles can intentionally miss, and a point does not establish the true control's dimensions. The default desktop profile now removes deliberate misses while preserving smooth movement; gameplay defaults are unchanged. No private screenshots, actual clicks or accounts are needed for this holdout.

An independently frozen holdout can compare the installed UI-TARS and Qwen 2B candidates. Both failed the existing center-precision gate; neither is enabled. Qwen 4B remains an uninstalled research comparison whose loaded memory and accuracy require measurement. No candidate is declared best or enabled by this research note.
