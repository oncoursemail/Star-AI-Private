# Image quality, phase 2 (Claude, branch star/image-quality-2-20261026, board #268)

Builds on docs/agents/image-quality-20261023.md (phase 1). Same settings (`image_quality`, `image_drafts` = most drafts, `image_engine`),
no new setting. Samples and the full benchmark JSON: docs/design/assets/image-quality-2-20261026/.

## Result (fixed prompt set, 12 prompts, request words through the whole pipeline, cold rewriter cache)
| | phase 1 (`legacy=True`) | phase 2 |
|---|---|---|
| pictures | 12 (seed 1111) | 24 (seeds 1111, 2222) |
| seconds per picture, mean / median / max | **184 / 179 / 231** | **83 / 76 / 183** (seed 1111 only: 77) |
| anatomy pass (final picture, one fixed blind judge at 768 px) | 8/8 | 16/16 |
| prompt-match checks yes | 24/24 | 47/48 |
| exact text, read back from the FINAL picture at 1024 px | 4/4 | 8/8 |
| early stop used | 0 | 23 of 24 |
| pictures drawn per request (mean) | 3 | 2 (one is the look-ahead draft) |
Honest reading: 2.2x faster end to end (2.4x on the same seed), quality at the judge's ceiling in both (it was already at ceiling in phase 1;
the judge cannot rank two good pictures). Where phase 2 is visibly better is text: in phase 1 the blank-area prompt let the model write its
own "PIZZA" on the neon sign AND Pillow drew a second "PIZZA" on top (see phase1-vs-phase2.jpg). Timings were taken on a PC that was
at 97-100 % CPU from other sessions (and, for phase 1, a full pytest run beside it), so absolute seconds are pessimistic for both;
the ratio is the usable number. 1 in 24 phase-2 pictures needed more than one draft (open/2222: two drafts misread the sign, the third matched).
No picture needed a repair or the Pillow fallback in the benchmark: Z-Image Turbo is that good on these prompts. 12 extra hard
prompts I tried at 4 steps (hands on piano, handshake, baby and cat, rider, knitting, ...) all passed the judge; to my eye only the elephant calf looked like a cow calf.

## What changed
1. **Speed** (`star/image_quality.py`, `star/comfy.py`)
   - Early stop: a draft whose verdict is `clear` (anatomy ok, no soft count, words exact, all yes/no checks yes, one "no" allowed of 3)
     is taken; the draft being drawn is cancelled in ComfyUI, queued judge jobs are skipped. Never more than `LOOKAHEAD`=2 pictures drawn
     ahead of the judge (the judge, not the card, is the slow part: judge 12-40 s, a 1024 draft 13-20 s).
   - Steps: Z-Image 5 steps for drafts (8 for pictures with in-scene words and for the phase-1 baseline). Measured warm, 1024x1024:
     4 steps 11.4 s, 5 steps 13.3 s, 6 steps 15.9 s, 8 steps about 19 s; 768 px 6.0 / 8.6 / 12.2 s for 4 / 6 / 8. I looked at 4/6/8 on
     cow, hands, mug, dogcat, spider, retro text, shop sign (zimage-steps-*.jpg): same quality, exact text even at 4. 5 = one step of margin.
   - Models resident: one engine does drafts AND repairs (Z-Image masked repaint), so the 8 GB card never swaps models; a tiny 512 px
     picture is drawn while the rewriter thinks (cold start 35 s hidden). ComfyUI also fails fast now (status check before the rewrite).
   - Judge: 640 px blind look (was 768), 448 px for the yes/no questions, both asked at the same time (the brain answers two requests at
     once: 13 s instead of 25 s). Measured per picture: 768 px 65 s -> about 40 s -> 13-25 s depending on brain load.
   - Not done: rewriter is still 15-28 s (output tokens on the CPU brain), the biggest remaining piece.
2. **Repair loop** (`star/image_repair.py`): judge finds a hard flaw -> `locate` asks the vision model for a box (0-1000 coordinates) and a
   plain description of what the region should show -> crop around it (+45 % context, multiples of 16, upscaled to ~768) -> masked repaint
   with the same engine (`zimage_inpaint`, denoise 0.78, mask = the box +12 %) -> feathered paste-back (pixels outside stay the original)
   -> judged again. Max 2 repairs; unboxable flaw -> the old reroll (half the drafts). `decide()` and `better()` are pure and tested.
   Live proof (repair-flawed-boxed-fixed.jpg): a cow with two pasted ghost legs; the model boxed exactly the pasted rectangle, the repaint
   made one natural leg, seams invisible. Lessons: (a) the repaint prompt must not contain the scene's subject (first try grew a cow head
   in the box), so it is the region description plus only the last style phrases of the scene prompt; instructions ("remove the leg")
   are replaced by a generic continuation. (b) **The blind judge did NOT notice the six-legged cow** (counted 4 at 640 and at 1024); I
   drove locate and repaint with the issue text instead. The VLM is weak at spotting defects (known: FineGRAIN); the loop only helps for
   flaws it reports. A better detector (per-region counting probes, MediaPipe hands) is the next lever. Klein masked repaint path
   (`klein_edit` with mask, used when pinned references force Klein) is unit-tested, not run live.
3. **Text in scenes**: the rewriter marks `scene: true` for words ON an object (<= 4 words, <= 30 characters). With Z-Image those words go
   into the prompt in quotes (8 steps), the judge reads the picture at 1024 px and `exact_text()` (whole words, case and punctuation aside)
   must match; else more drafts, then one repair of the sign region, then the fallback: a blank-area scene and Pillow draws every word. A
   dead judge also takes the fallback (words cannot be trusted unchecked). Klein never draws words itself. HUD/score/captions stay Pillow.
4. **Discord /draw** (`star/discord_bot/draw.py: make_picture`): same function as the chat (pipeline when `image_quality` is on and no own
   workflow, else single shot). Default timeout 240 -> 420 s (setup doc updated). The GPU worker (server bot) uses the same Drawer.
5. **Blind A/B page** (Settings > Creative > "Picture quality: blind test"; `star/image_ab.py`, `ImageAbPanel` in MediaPanel.tsx,
   host actions imageAbNext / imageAbPick / imageAbSummary / imageAbMake): two pictures of one prompt, sides drawn at random when the pair
   is stored (never leaked to the page), pick left/right/same, one pick per pair, append-only `<STAR data>/image-ab/picks.jsonl`, summary
   with an exact sign test (verdict only from 6 decided pairs, p < 0.05). "Draw a new pair" makes old (`legacy=True`) and new live (~5 min).
   `python -m star.image_ab --results R --pictures P --home <STAR data folder>` imports a benchmark run as pairs. 12 ready pairs from this
   benchmark are on the PC at media/bench-iq2/ab-home/image-ab (not committed, 2 MB each, not copied into %APPDATA%\STAR on purpose):
   to use them copy that `image-ab` folder into the STAR data folder.
6. **Benchmark** `scripts/media/bench_pipeline.py --phase 1|2` (resumable; one fixed judge over all finals).

## Tests
tests/test_image_quality2.py (37: early stop incl. in-flight cancel and skipped judge jobs, look-ahead, repair decisions, flaw parsing, crop
geometry, paste-back leaves outside pixels untouched, in-scene text read-back / fallback / dead judge / Klein, legacy mode, Discord),
tests/test_image_ab.py (random sides, no leak, one pick, sign test, damaged files, host actions, benchmark import), frontend
src/imageAb.test.tsx (5). Updated: test_image_quality.py (early stop changes draft counts), test_discord_draw.py (timeout 420).
Full pytest run on this branch: everything passed except one real finding I fixed (test_windows_package_data wants `__file__` anchors listed:
image_ab no longer uses one), and the rest re-ran green. tsc clean.

## Resume / next
- Rewriter speed (15-28 s): shorter JSON, or skip it for requests that are already long.
- A stronger defect detector so the repair loop fires on real flaws (see 2b); then measure repair rate on a set of known-bad pictures.
- Owner: do the 12 blind pairs; the verdict is the real decision whether phase 2 is better.
- Voice lane asked for GPU quiet 00:02-00:49Z on 2026-10-27; I paused and resumed after "GPU free". ComfyUI is stopped again.
