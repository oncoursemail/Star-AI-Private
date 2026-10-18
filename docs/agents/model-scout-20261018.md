# Model scout 2026-10-18: new base model or draft model for star-fast? (Claude, board #176)

Branch `star/model-scout-20261018` (from star/next 798d88e7). Docs only: nothing in `server/brain/models.ini` changes here.
Hosts, users and keys are in the private workspace notes, never in this file.

## 0. Answer in short

- **No new base model beats star-fast in its speed class** (released 2026-10-14 to 10-18, <=4B active, GGUF, usable
  licence). The October open releases are either far too big for brain 1 (816B, 552B, 560B MoEs) or not coding models.
- **The real win is speculative decoding with the new DSpark draft head**, not a new model. star-fast's own weights +
  a 0.57 GB DSpark draft (Q4_K_M, n-max 2) + ngram-mod: **+29% generation** on the STAR specbench (9.3 vs 7.2 tok/s,
  replicated, CPU contended by another container), every prompt kind faster, prompt time unchanged, vision still works.
  Edit/fix turns that repeat code get far more (22 tok/s seen in the eval, ngram drafts 25 tokens long).
- Quality: speculative decoding keeps the target model's distribution; greedy text changes only through float rounding
  of batched verification. Eval: see section 3.

## 1. Scout (web, 2026-10-18)

| Candidate | Size / active | Why not (or why) | Source |
|---|---|---|---|
| Meta Muse Spark Open (Oct 15) | 816B / ~42B | far beyond 125 GB RAM at usable quality; star-deep class at best | HF unsloth/Muse-Spark-Open-816B-A42B-GGUF |
| DeepSeek-V4.1-Flash-1017 (Oct 17) | 552B / 8-16B | too big | local-ai-zone October tracker |
| Ling 3.1 Flash (Oct 16 materials) | 560B / 25B | too big, fp8 only | same |
| Liquid LFM2.5-24B-A2B (Oct 13) | 24B / 2B | faster, but vendor SWE-V 51.0 vs 66.2 for Qwen3.6-35B-A3B; LFM licence with revenue cap | developersdigest comparison, orcarouter |
| Tencent Hy-Memory-30B-A3B (Oct 15-16) | 30B / 3B | memory-writer model, not coding | orcarouter blog |
| Index-Translate-35B-A3B (Oct 2) | 35B / 3B | translation | digitalapplied tracker |
| Mellum2.1 Thinking (Oct 8) | 12B / 2.5B | already live as star-voice/star-quick | llm-releases.com |
| Ornith 1.6/2 | - | not released; 1.5 already tested (INCONCLUSIVE, -24% prompt speed) | benchlm |
| Luau fine-tunes (Qwen2.5-Coder 0.5-14B, CodeLlama-7B LoRA, Luau-coder-3B base) | small dense | weaker base models; Qwen2.5 tokenizer, so unusable as a draft for star-fast | HF cards |
| **DSpark draft for Qwen3.6-35B-A3B** | 0.95B head | **tested: section 2** | HF RedHatAI/Qwen3.6-35B-A3B-speculator.dspark (Apache-2.0), GGUF Anbeeld/Qwen3.6-35B-A3B-DSpark-GGUF rev c906bddc |
| DFlash / MTP drafts | - | measured slower here on 2026-10-13 (DFlash acceptance 25%) | docs/research/server-inference.md 2.3 |
| EAGLE3 draft for Qwen3.6-35B-A3B | - | only a captioning-tuned one, no GGUF | HF PatchyTisa/... |

## 2. Stage A: speed (brain 1, temp server, live build, star-fast placement, -t 24 -tb 24, 1 slot, greedy)

Another container (Roblox Studio) used 4-10 cores throughout, so absolute numbers are below the clean 11.5 tok/s;
compare adjacent rows. specbench = 4 STAR prompts (chat, new module, edit a script, debug fix).

| config | gen tok/s all | chat / code_new / code_edit / debug_fix | draft acceptance |
|---|---|---|---|
| baseline (no spec), run 1 / run 2 | 6.25 / 7.20 | 6.55/6.28/6.15/6.18 ; 7.22/7.28/7.16/7.19 | - |
| DSpark Q8_0, n-max 8 | 3.42 | 2.73/3.96/3.47/3.64 | 11-20% |
| DSpark Q4_K_M, n-max 4 | 6.64 | 5.36/7.17/7.05/6.86 | 27-44% |
| DSpark Q4_K_M, n-max 3 | 7.43 | 6.58/8.08/7.48/7.42 | 36-55% |
| DSpark Q4_K_M, n-max 2 | 8.00 | 7.61/8.17/7.63/11.3 | 52-74% |
| **DSpark Q4_K_M n-max 2 + ngram-mod**, run 1 / run 2 | **9.32 / 9.27** | 8.11/8.98/10.02/9.92 ; 8.16/8.85/9.96/9.93 | 52-74% (+ngram on code_edit) |

- Short drafts win on this CPU: verifying many tokens reads many different experts, so long drafts cost more than
  they save (same reason MTP/DFlash lost). n-max 2 is the sweet spot.
- Prompt processing is unchanged (2.8/1.8/9.8/2.7 s vs 2.8/1.8/9.7/2.7 s). RAM: +0.6 GB for the draft.
- Through the router (preset `star-fast-spec`): 9.75 tok/s on a short Luau answer; image chat answered correctly
  (spec + mmproj load together).

## 3. Stage B: quality

(filled in below)
- Candidate arm only (time and usage limits): golden v2, 34 tasks, `--model star-fast-spec --pin-model --mode auto
  --packs off`, 2026-10-18 08:40-10:44Z: **14/34**.
- Baseline: star-fast golden v2 from 2026-10-14 (same runner commit, same flags): 15/34. The v1.0 release run: 13/34.
- `gate --paired-session --allow-model-change --max-session-hours 200`: **INCONCLUSIVE**, 3 wins (LUA-02, LUA-04,
  NET-04) / 4 losses (UI-14, NET-09, ANI-05, PERF-03, none confirmed) / 27 ties, p(worse)=0.50, MDE +11 of 34.
  This is NOT a valid one-session paired gate (baseline is 4 days old; the 36 h limit was overridden on purpose).
  It shows no large loss, which is all a speculative-decoding change can be expected to show.
- In the eval, fix/repair turns ran at up to 22 tok/s (ngram drafts accepted 94%, mean length 25); fresh long answers
  6.2-7.7 tok/s under the Studio contention.

## 4. Not measured

- Two concurrent streams (live star-fast has 2 slots; night school uses one): spec decoding may gain less, or lose,
  when both slots generate. Measure before a switch (temp server -np 2, two specbench clients at once).
- A clean box (no Studio): expected gain is similar or larger, not measured.

## 5. Recommendation: needs owner OK (not switched)

Switch star-fast to speculative decoding (same weights, no model change) after the two-stream check, or accept the risk.
Switch (inside the container, from a branch of server/brain/models.ini, apply with `bash server/brain/apply.sh`, or
on the live file): add to `[star-fast]`

    spec-type = draft-dspark,ngram-mod
    model-draft = /opt/star/models/qwen3.6-35b-a3b-dspark/Qwen3.6-35B-A3B-DSpark-Q4_K_M.gguf
    spec-draft-n-max = 2

then `GET /models?reload=1` with the API key (reloads star-fast only, ~2.5 min, chat waits meanwhile), then validate.py
and one image chat. Undo: delete the three lines (or copy back the backup taken just before) and reload again.
The draft file is already on brain 1 (sha256 16b60f4f...a8). Test preset `[star-fast-spec]` is left in the live
models.ini (load-on-startup = false, unloaded, costs nothing); remove it in the switch commit.
