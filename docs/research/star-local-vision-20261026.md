# Local vision candidates on STAR's 8 GB PC

Qwen3-VL-2B-Instruct is an explicit optional installer candidate: `setup.cmd -Only grounder -Grounder qwen3-vl-2b`. The existing default selection is unchanged. Installation verifies two pinned files and writes a separate candidate configuration; it does not start the server or enable vision actions. The server command binds to `127.0.0.1:8081`.

## Publisher evidence and storage

| Candidate | Publisher ScreenSpot-Pro result | Selected GGUF + vision files, decimal GB | Evidence and tradeoff |
| --- | ---: | ---: | --- |
| UI-TARS-2B-SFT | 27.7 | 2.449 | Existing pinned third-party conversion; native synthetic measurements below. [Publisher card](https://huggingface.co/ByteDance-Seed/UI-TARS-2B-SFT). |
| Qwen3-VL-2B-Instruct | 48.5 | 1.927 | Official Q4_K_M language weights + F16 vision encoder; candidate for lower storage and potentially more headroom. [Official GGUF](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF). |
| Qwen3-VL-4B-Instruct | 59.5 | 3.333 | Higher publisher grounding result; more memory to measure. Research comparison only, not added to this installer. [Official GGUF](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF). |
| UI-TARS-1.5-7B | 49.6 | 5.539 | Existing pinned conversion leaves less room beside voice and games. The publisher says this released model is not specifically optimized for games. [Publisher card](https://huggingface.co/ByteDance-Seed/UI-TARS-1.5-7B). |

The Qwen results are Instruct columns in Table 4, page 18 of the [Qwen3-VL technical report](https://arxiv.org/pdf/2511.21631). The corresponding Thinking results are 32.2 for 2B and 49.2 for 4B. These are publisher benchmark results, not measurements of STAR's quantized files, current prompt, or RTX 4060 latency. Cross-paper evaluation conditions can differ. All four publisher cards identify Apache-2.0 licensing. Download size is not loaded VRAM: projector, context, compute buffers, Windows, speech and games also consume memory.

The optional 2B pin uses Qwen's official repository revision `52d6c8ffea26cc873ac5ad116f8631268d7eb503`. Its exact sizes and SHA-256 values are recorded in [pins.json](../../installer/star-home/pins.json). Public repository/LFS metadata was checked without downloading weights. A different projector precision or revision is a different candidate and needs its own measurements.

## Preserve the failed center gate

The owner-run UI-TARS-2B session reported 2,536 MiB additional GPU use and about 4,647 MiB free. Six synthetic requests selected `unit1000`; all six points landed inside their intended 120×40 buttons. Center-distance mean **18.24 px** and maximum **22.02 px** failed the predeclared **mean ≤12 / maximum ≤20 px** gate. That failure remains recorded in the [native validation record](../agents/codex-native-pc-validation-20261026.md). No threshold, prompt, fixture or coordinate offset is changed to turn it into a pass. A text-anchor explanation is plausible, not established.

[ScreenSpot-Pro's evaluator](https://github.com/likaixin2000/ScreenSpot-Pro-GUI-Grounding/blob/main/eval_screenspot_pro.py#L123-L138) instead scores a point by whether it falls inside the target bounding box. The six hits are therefore useful descriptive evidence under another metric, not a replacement gate result. The session's first request took 1.286 s and subsequent requests approximately 0.10–0.12 s on the **same image**; this does not measure changed-screen throughput or semantic frames per second.

## Proposed independent holdout protocol

This is a proposal for a future diagnostic, not a changed repository evaluation or an executed test:

1. Freeze candidate hashes, prompt, preprocessing, coordinate convention and timeouts first. An independent reviewer or owner then creates and hashes 60 new synthetic scenes: four resolutions × three target-size bands × five cases. Balance text and icon targets, vary layouts, fonts and distractors, and exclude the six calibration scenes. Do not fit an offset or change settings after observing answers.
2. Send one request per changed scene. Invalid, nonfinite, out-of-range, missing or timed-out answers count as failures; no retries or best-of selection. Preserve raw answers and per-case results. Define bounds before any coordinate clamping.
3. Predeclare the diagnostic gate as **60/60 first-pass points inside the intended bounding box**. Report center distance, edge clearance, size/resolution strata and changed-image latency separately. Keep the earlier failed center gate in the report regardless of this result. A synthetic pass does not establish arbitrary desktop reliability.
4. Test absent/ambiguous targets separately before relying on abstention. A point-only response can guess. Native click accuracy and STOP also remain separate: explicit custom movement profiles can intentionally miss, and a point does not establish the true control's dimensions. The default desktop profile now removes deliberate misses while preserving smooth movement; gameplay defaults are unchanged. No private screenshots, actual clicks or accounts are needed for this holdout.

Testing the installed candidate on an independently frozen protocol can resolve the metric question before another download. Qwen 2B is the next optional comparison for headroom; Qwen 4B is a later quality comparison if measured memory permits. Neither is declared best or enabled by this research note.
