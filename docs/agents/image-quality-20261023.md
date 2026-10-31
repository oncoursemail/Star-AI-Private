# Image quality, phase 1 (Claude, branch star/image-quality-20261023, board #230)

Implements the pipeline-first items of docs/research/image-gen-upgrade-20261023.md. Settings (all default ON, Settings page > Media):
`image_quality` (bool), `image_drafts` (1-5, default 3), `image_engine` (`auto` | `klein` | `zimage`).
Edits and inpaints, the Discord `/draw` path and an owner-supplied ComfyUI workflow keep the old single-shot path.

## What runs for a text-to-image chat request (`star/image_quality.generate_best`)
1. **Rewriter** (`star/image_prompt.py`): star-fast turns the request into a 45-80 word model prompt (subject, anatomy-correct
   pose, composition, light, style, positive wording), an aspect, 3 yes/no checks and an exact-text list. Cached per request in
   memory; on any failure the owner's own words are used (quoted words are drawn by STAR, not asked of the model).
   Measured: about 40-55 s per rewrite on the brain (CPU, about 7 tokens/s), so the timeout is 100 s.
2. **N drafts** at the chosen size and engine (Z-Image Turbo or Klein; pinned project references force Klein).
3. **Blind judge** (`star/image_judge.py`): star-fast with its vision projector sees each draft at 768 px WITHOUT the prompt and
   returns JSON: creatures, visible legs/arms/heads/tails/ears, fingers per hand, whether limbs attach, all readable text.
   Code compares the counts with what the species allows (quadruped legs 2-4 visible, 1 head, humans 2 arms and 5 fingers, spider
   6-8 legs, and so on; a count above the limit is a hard fail, fewer may be hidden). Counts are totals over `count` individuals;
   made-up creatures, sprites and robots are never a hard failure. Only drafts that pass anatomy get the second call, the 3
   prompt-match questions. Judging overlaps with drawing the next draft (VLM on the server, ComfyUI on the PC); a judge that is
   unreachable never blocks a picture (first draft kept, the answer says so).
4. **Pick**: passing drafts first, then score. If all drafts fail: ONE repair round, new seeds, the judge's complaints turned into
   positive wording, half as many drafts (cost).
5. **Exact text** (`star/image_post.py`): the art is drawn with the text area left blank; Pillow draws the real words with bundled
   fonts, `star/data/fonts`: Press Start 2P (retro, HUD) and Anton (titles, signs), both SIL OFL 1.1, licence files beside them.
   Texts of one style share one size.
6. The chat answer reports the judge: "3 drafts judged blind, #2 picked (anatomy ok, prompt match 3/3) ... text drawn by STAR".
   The JSON note beside the image keeps the rewritten prompt, per-draft verdicts, seeds and rounds.

## Z-Image Turbo
Source and licence checked on Hugging Face (2026-10-23): Comfy-Org/z_image_turbo (revision 6fc90a3b), card licence apache-2.0,
base Tongyi-MAI/Z-Image-Turbo (apache-2.0). Files (sizes and SHA-256 match the repo's LFS ids; pinned in `scripts/media/setup_comfyui.sh`):
`z_image_turbo_bf16.safetensors` 12.31 GB, `qwen_3_4b_fp4_mixed.safetensors` 3.48 GB, `ae.safetensors` 0.34 GB.
It loads in the installed ComfyUI 0.39.0 with core nodes only (UNETLoader, CLIPLoader type `lumina2`, ModelSamplingAuraFlow shift 3,
KSampler res_multistep/simple, 8 steps, CFG 1). The bf16 file streams through the 8 GB card (dynamic VRAM loading): warm-up 59 s,
then 30-46 s per 1024x1024 image. The 6.2 GB `int8_convrot` file was not tried.

## Benchmark (`scripts/media/bench_images.py`, `evals/image_quality/`, results-20261023.json)
12 prompts (6 anatomy, 4 text, 2 scene), 2 seeds, 1024x1024, both engines get the SAME rewritten prompt (text prompts carry the
exact words inline, so this measures the model's own text, not STAR's overlay). Judge: the blind judge above; text is read at 1024 px.

| | Klein 4B distilled | Z-Image Turbo bf16 |
|---|---|---|
| anatomy pass (16 non-text images) | 16/16 | 16/16 |
| exact text (8 images, judge reads the string) | 0.94 (retro seed 1111: "LIV6 3") | 1.00 |
| prompt-match checks yes (anatomy + scene) | 48/48 | 48/48 |
| seconds per image (mean, 1024 px) | 6.9 | 38.4 |

Honest reading: the judge is at ceiling on both engines (it is lenient with the strong prompts), so the numbers separate the
engines only on text. Looking at the saved pictures myself (cow, retro screenshot, horse, hands): Z-Image has cleaner text, more
natural hands and legs, better photo detail; Klein is fine on easy subjects and wins only on speed (5.6x). The plan's own bar
("not more than about 3x the time") would keep Klein; the owner's complaint is quality, so `DEFAULT_ENGINE = 'zimage'` when its files
are installed (fallback Klein), both selectable. To make it faster: Settings > Picture model > klein, fewer drafts, or the Draft size.
The first rewrite-only benchmark run used raw prompts by mistake (the 25 s rewriter timeout was too short) and was discarded.

## Cost, measured (sample run, 1280x720 wide, Z-Image, 3 drafts): about 3 min for the cow (rewrite 45 s, 3 drafts, judge tail).
A request that fails the judge adds the half-size repair round. The retro-screenshot sample took 310 s because a bug counted 2 of 3 yes answers as a fail (0.667 < 0.67) and forced a needless repair round; fixed afterwards (integer compare), so those two sample answers still show "all drafts failed". `image_drafts: 1` plus `klein` is about 1 min including the rewrite.

## Not done / open
- Judge calibration against owner labels (the plan's section 5.4), the owner's blind A/B page, hires pass, Real-ESRGAN, the masked
  fix loop, SeedVR2, anime: later phases.
- Discord `/draw` still uses the single-shot Klein path.
- The rewriter's yes/no checks about "an empty area for the text" can be answered no by the judge and trigger a needless repair
  round (seen once, retro screenshot); worth dropping layout questions from the checks.
- int8_convrot (6.2 GB) might be faster than bf16 on this card; untested.
