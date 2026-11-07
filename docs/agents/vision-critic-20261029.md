# vision-critic-20261029 (board #360, wave VISUAL, lead: Claude main session)

Goal: a vision critic with its own reliable compute that agrees with the blind Opus judges far above chance.
Branch star/vision-critic-20261029 (worktrees/vision-critic) from origin/star/next.

## RESULT (clear-preference pairs = >= 2 blind Opus judges agree, none disagree; test split never used for choices)
| critic | design | dev (33) | TEST (55) | test 95% CI | consistent | s/pair |
|---|---|---|---|---|---|---|
| none | pixel stats (more content) | 13/22 | 27/41 (UI blanks only) | - | - | 0 |
| Qwen3-VL-4B | absolute 1-9, EV over digit logprobs | 31/33 | 34/55 = 62% | 49-73% | - | 14 |
| Qwen3-VL-4B | pairwise + swap + checklist | 28/33 | 40/55 = 73% | 60-83% | 69% | 14 |
| Qwen3-VL-4B | + pixel facts | 25/33 | 41/55 = 75% | 62-84% | 65% | 14 |
| Qwen3-VL-4B | plain prompt (no checklist) + swap | 28/33 | 39/55 = 71% | 58-81% | 67% | 14 |
| **Qwen3-VL-8B** | **pairwise + swap + checklist (LIVE)** | 28/33 | **46/55 = 84%** | **72-91%** | 75% | 27 (part GPU) / 47 (CPU, live) |
| Qwen3-VL-8B | same, consistent verdicts only | 22/27 | 34/41 = 83% | 69-91% | cov 75% | |
Per domain, 8B test: 3d-assets 22/24, blockbench 5/8, roblox-build 5/6, ui 6/7, lighting 4/4, vfx 4/6.
One presentation order only (no swap) is position-biased and not a valid design (4B 23/33 dev).
Reference: today's star-fast critic picked the judge-better blockbench round 8/15 (chance).
Not run: gemma-4-E4B, gemma-4-12B (+ ggml-org mmproj; files are on the laptop), Qwen3-VL-2B (downloaded, sha256
1e8db192 / f9a68fab = HF oids): 8B met the target first and each run costs ~1 h of laptop CPU. Weakest domain:
blockbench (subtle round-0 vs round-1 differences; the judges' own scores were close).

## Live service (for shapes-templates, roblox-scenes and every visual pipeline)
- Host: the laptop (ssh `laptop`), port 8093, OpenAI-compatible llama.cpp server, model alias `critic` =
  Qwen3-VL-8B-Instruct Q4_K_M + mmproj Q8_0 (official Qwen GGUF, sha256 above), CPU only, below-normal priority on
  CPUs 4-11. Sleeps after 120 idle s (first call after that reloads, +5-10 s). The busy guard kills it while the owner
  games/streams and the supervisor waits for PAUSE to go: expect CriticUnavailable then, carry on without a critique.
- Key: ~/.star/vision_critic_key on the owner PC (the client reads it); same value in the laptop's
  vision-critic\api_keys. Copy that file to another machine's ~/.star/ to call from there. Never print it.
- Client (repo, branch star/vision-critic-20261029): `star/vision_critic.py`, stdlib + Pillow.
  ```python
  import os; os.environ["STAR_VISION_CRITIC_URL"] = "http://<laptop LAN address>:8093"   # see ssh config 'laptop'
  from star import vision_critic as vc
  r = vc.prefer(["a_front.png", "a_side.png"], ["b_front.png", "b_side.png"], brief, "3d-assets",
                facts=("2 floating parts", ""))          # optional measured facts per arm
  r["winner"]      # "A" / "B";  r["p_a"] 0..1;  r["consistent"]: both presentation orders agreed
  vc.issues(["front.png", "side.png"], brief, "roblox-scenes")   # {"issues": [{part, problem, fix, severity 1-3}]}
  ```
  Domains with their own checklist: blockbench (alias minecraft), 3d-assets (aliases shapes, shapes-templates, props),
  roblox-build (aliases roblox-scenes, roblox, map), ui, lighting, vfx; anything else = generic.
  All views of one candidate are tiled into one sheet (<= 768 px). Exceptions: CriticUnavailable (host off/busy/503,
  fails fast), RuntimeError (other HTTP errors).
- How to use it in a loop: generate N candidates, run prefer() knockout (N-1 calls of ~47 s each), keep the winner;
  when you need certainty use only `consistent` verdicts (83% agreement on those, 75% of pairs). Do not use `score()`
  for picks (62% on the test split). Throughput: one request at a time (np 1): serialise your calls.

## Log
- 21:15Z start. Hosts checked: brain2 = no GPU (Intel UHD 630), 8 threads, 15 GB RAM with 3 GB free, load 12 -> no.
  Laptop = GTX 1650 4 GB (embed+rerank use ~3.2 GB when both loaded, 0.4 GB asleep), Ryzen 5 5600H 12 threads,
  16 GB RAM (10 GB free), llama.cpp b11583 CUDA already there (gpu-worker\engine, has mtmd). STAR's PC: forbidden
  (busy guard). Owner PC: owner's by day.
- Benchmark built from today's blind judging (scratchpad vc/build_bench.py): 113 pairs, 88 clear (>= 2 judges agree,
  none disagree), split by brief 40/60: dev 33 / test 55 clear pairs.
- Downloads (official repos, sha256 = HF LFS oid, checked after download) to the laptop
  C:\Users\<owner>\Documents\starai\vision-critic\models: Qwen3-VL-4B/8B-Instruct GGUF (Qwen org), gemma-4-E4B-it and
  gemma-4-12B mmproj (ggml-org).
- 21:35Z sha256 of all downloaded GGUFs = HF LFS oids (Qwen3VL-4B Q4_K_M 66358cb1..., mmproj-4B Q8_0 30ba2c7d...,
  Qwen3VL-8B Q4_K_M 67d1659b..., mmproj-8B Q8_0 c6ba8550..., gemma-4-E4B Q4_0 a555b900..., mmproj-E4B Q8_0 197f49a9...,
  mmproj-gemma-4-12B BF16 b9d4500e...; Qwen3VL-2B Q8_0 1e8db192... / mmproj f9a68fab... pending check).
- Pixel-only baseline (no model; prefer more content / detail): test 27/41 content (only UI blank detection works:
  7/7), detail 18/48, roblox 0-2/6 -> chance elsewhere.
- Bench server: laptop llama-server b11583 (existing build), localhost:8093 via ssh tunnel, --fit default (partial
  GPU: ~2.3 GB VRAM, rest CPU), -c 4096 q8 KV, --image-max-tokens 384 -> ~900 prompt tokens, ~7-10 s per call.
- 21:45Z DEV (33 clear pairs), Qwen3-VL-4B: sep_chk first-order only 23/33 (70%), sep_chk + position swap 28/33 (85%,
  consistent 73%), + pixel facts 25/33 (76%; facts hurt UI 2/5 first-order). PRE-REGISTERED primary design for the
  test split (chosen on dev before any test call): separate images + domain checklist + both orders averaged, no
  pixel facts.
- 21:54Z DEV more: plain prompt (no checklist) + swap 28/33 (85%); ABSOLUTE score per arm read as the expected value
  over the digit log-probabilities (1-9, checklist prompt, one call per arm) 31/33 (94%; 3d 12/13, blockbench 4/5,
  roblox 4/4, ui/lighting/vfx 11/11). abs+swap ensemble 28-30/33. The lanes' absolute critic failed because it read
  an integer from free text (coarse, ties, star-fast position/rounding noise); the EV over logprobs is continuous.
  REVISED primary (dev only, test results not looked at yet): abs-EV checklist score per arm, prefer = higher score.
  Pairwise swap stays the secondary design in the test table.
- 22:20Z TEST (55 clear pairs, never used for any choice), Qwen3-VL-4B: abs-EV 34/55 (62%, CI 49-73%; blockbench
  2/8) -> the dev 31/33 did not hold (small dev, luck). Pairwise + swap (the first pre-registered design) 40/55 (73%,
  CI 60-83%; 3d 16/24, blockbench 4/8, roblox 5/6, ui 6/7, lighting 4/4, vfx 5/6); consistent-only 31/38 (82%) at 69%
  coverage. +pixel facts 41/55, plain prompt 39/55. Not >= 75% with a CI clear of chance -> try bigger models.
- 22:55Z Qwen3-VL-8B (Q4_K_M + mmproj Q8_0, same pairwise+swap+checklist design): TEST 46/55 (84%, CI 72-91%,
  one-sided p vs chance ~1e-6): 3d 22/24, blockbench 5/8, roblox 5/6, ui 6/7, lighting 4/4, vfx 4/6; consistent 75%
  (consistent-only 34/41 = 83%). DEV 28/33 (85%). Robustness: test without the 3d judge-round-1 near-duplicates 34/42
  (81%), without UI blank-render pairs 40/48 (83%), dev+test 74/88 (84%, CI 75-90%). 13.5 s per call, 27 s per pair
  (laptop, --fit partial GPU). Caveat: two models were run on test (4B 73%, 8B 84%); 8B was picked because 4B missed
  the target; with that 2-way choice the 8B result is still far above chance.
- 23:05Z latency of the deploy config: Qwen3-VL-8B fully on CPU (-dev none, no projector offload) 23.6 s per call
  (47 s per prefer), same verdicts on 10 dev pairs (9/10) as the partial-GPU run; projector on GPU 13 s/call but holds
  1.2 GB VRAM (the knowledge workers need that when both are loaded). Chose CPU only = zero VRAM.
- INCIDENT (mine): 22:28Z the laptop busy guard paused the knowledge workers for 2 min ("other programs use the GPU
  57%"): my ssh-launched bench server (partial GPU) is not recognised as "ours" (the guard cannot read the path of a
  process started from the ssh session). Knowledge calls fell back to brain1 for those 2 min. The installed service runs
  in the logon session (path readable = ours) and uses no GPU, so it cannot trigger this.
- 23:11Z DEPLOYED on the laptop (see "Live service" below): task "STAR laptop vision critic" (logon, hidden), firewall
  rule TCP 8093 Private/LocalSubnet, busy_guard.json overlay {kill_ports 8090+8093, watch_ports 8090+8092+8093}, guard
  task restarted (status serving). /health ok over the LAN, 401 without the key.
- 23:14Z end-to-end from the owner PC over the LAN with the client: prefer on rb-P03 -> B (judges: B), consistent,
  77.7 s including the cold model load; issues() returned 4 sensible issues (incl. "camera shots inside walls").
- 23:17Z FOUND + FIXED: after my `schtasks /end` + `/run` the busy guard had NOT come back (the new copy exited, the old
  one still held the single-instance lock) -> guard was off ~6 min (23:11-23:17Z). Re-ran the task: running, status
  fresh, log "guard started". Verified with FAKE_BUSY: guard killed 8090 + 8093 within a second, critic supervisor
  logged "PAUSE file found, waiting".
  23:21Z PAUSE removed after 120 s free; both the knowledge router (8090) and the critic (8093) listening again.

## Reproduce
tools/vision_critic/bench/: build_bench.py (VC_DOCS = docs/agents with the judging files, VC_WORK = work dir with
src/eval1 = blockbench eval1_outputs.tgz unpacked, VC_UIVFX = the ui-vfx lane scratch with judging/ and keys/),
run_bench.py --url --model --split dev|test|all --variants sep_chk,abs,... (cached per call), score.py test
--by-domain, ens.py, pixel_baseline.py. pairs.json = the manifest (labels, briefs, split); results_20261029.jsonl =
every call made today.

## Cleanup / leftovers
- Laptop: vision-critic\models also holds Qwen3VL-4B, Qwen3VL-2B, gemma-4-E4B, gemma-4-12b (copy of litha) and
  mmproj-gemma-4-12B (~17 GB unused); delete when no longer wanted. bench-server.log, %USERPROFILE%\vc-*.cmd/.ps1 =
  bench helpers (safe to delete).
- Undo the service: see tools/vision_critic/laptop/install-vision-critic.cmd header.
