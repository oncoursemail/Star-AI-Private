# speed-queue-20261021 (Claude Opus sub-agent, board #215): queue items 1 (faster-packed model) and 2 (priority scheduler)

Brief: docs/agents/QUEUE-speed-20261021.md, docs/agents/WAVE-20261020-BRIEF.md. Branch star/speed-queue-20261021
(worktree worktrees/speed-queue-20261021, from origin/star/next 6ad9725f). Every timing step under
`./star.cmd lock run --owner claude --holder speed-q1|speed-q2 --server 1 --max-minutes 10` (<= 10 min, >= 5 min gaps).

## Item 1: Qwen3.6-35B-A3B Q4_K_M lmstudio-community ("cand3") with live spec decoding
Prior (docs/agents/model-eval-20261014.md): without spec, cand3 +2.7% gen / +6% prompt vs live; spot check luau_exec 0/8
(live 8/8). Live star-fast = /opt/star/models/qwen3.6-35b-a3b/Qwen3.6-35B-A3B-Q4_K_M.gguf (20.4 GB) + DSpark Q4_K_M
draft n-max 2 + ngram-mod, -np 2. Candidate = /opt/star/models/qwen3.6-35b-a3b-lms/Qwen3.6-35B-A3B-Q4_K_M.gguf (21.2 GB).
Method: side instance on :8094 (live binary /opt/star/bin-ramforge, A1 env, -t 24 -tb 24, -np 2, live spec flags) for
BOTH arms, so live star-fast is untouched; RAM 55 GB available at start, one temp server ~23-25 GB.
Scripts: brain 1 /opt/star/bench/speed20/q1hold.sh (start, quiet check, spec2.py, stop); results q1-<label>.json there.
PC wrapper: scratchpad q1run.sh (ssh + `timeout -k 10 540`).

## Status log
- 17:10Z start. Brain 1: lock free, load ~19 (night school back after the A/B), RAM 55 GB available.
- 17:13Z hold 0 wasted (Git Bash rewrote the /opt model path; server never started; 30 s). Script now takes keys live|lms.
- 17:18-17:25Z hold 1 (speed-q1) BASE = live weights + spec, -np 2, single stream: loaded 122 s, RSS 22.6 -> 24.5 GB;
  gen 10.28 tok/s all (chat 9.28/9.05, code_new 10.26/8.54, code_edit 11.43/11.63, debug 11.18/9.36), accept 54.8%,
  prompt median 36.7 tok/s, first token chat 2.54/1.57 s, code_edit 9.3/9.2 s. File q1-base.json.
- 17:30-17:36Z hold 2 CAND3 + same spec flags, single stream: loaded 117 s, RSS 23.3 -> 25.2 GB (+0.7 GB vs base);
  gen 10.68 tok/s all (+3.9%; chat 9.45/9.09, code_new 10.67/10.52, code_edit 11.37/11.82, debug 10.58/10.42),
  accept 51.5% (base 54.8%), prompt median 41.1 tok/s (+12%), first token chat 2.38/1.45 s, code_edit 8.1/8.1 s.
  Texts differ from base for all 8 (different weights). Next: two-stream, ABBA order (cand3 then base).
- 17:42-17:47Z hold 3 CAND3 two streams (fresh server, cold cache): per-stream 6.23/6.17 tok/s, aggregate over wall
  11.14 tok/s, accept 49.8%, first token chat 3.97/3.96 s, prompt median 28.9 tok/s.
- 17:52-17:58Z hold 4 BASE two streams (fresh server): per-stream 6.73/7.01 tok/s, aggregate over wall 11.11 tok/s
  (cand3 11.14), accept 56.6%, first token chat 4.18/4.18 s, prompt median 32.6 tok/s (cand3 28.9).

### Item 1 verdict: NOT switched (no clear speed win); paired gate not run
| cand3 vs live weights, same spec flags, side server :8094, ABBA order | live | cand3 | change |
|---|---|---|---|
| single stream gen tok/s (8 greedy prompts) | 10.28 | 10.68 | +3.9% |
| single stream prompt tok/s (median) | 36.7 | 41.1 | +12% |
| single stream first token code_edit (393-token prompt) | 9.3 / 9.2 s | 8.1 / 8.1 s | -1.1 s |
| two streams aggregate tok/s over wall | 11.11 | 11.14 | same |
| two streams gen tok/s (gen-time weighted) | 6.89 | 6.20 | -10% |
| draft acceptance single / two | 54.8% / 56.6% | 51.5% / 49.8% | lower |
| RSS after runs | 24.5-24.9 GB | 25.2-25.3 GB | +0.4-0.7 GB |
The scout's +30% does not exist: with spec decoding on both, cand3 is +4% single-stream and level on two streams
(live runs two slots). Draft acceptance is lower with cand3 (51.5/49.8% vs 54.8/56.6%; probable cause, not checked:
its Q4_K/Q6_K dense layers sit further from the model the DSpark head was trained on), which eats the bandwidth gain. Switch rule = PROMOTE or clear speed win with
zero pass loss. No clear speed win, so only PROMOTE could switch; at k=1 the paired gate's MDE is about +11/34 and a
lower-precision quant of the same weights cannot plausibly gain that (2026-10-14 spot check: cand3 luau_exec 0/8 vs
8/8). The gate (two arms x 57 tasks, ~6-7 h of brain 1 background slot, night school starved meanwhile) was therefore
NOT run; same stop rule as model-eval-20261014. To run it anyway: model star-fast-cand3 preset is still in models.ini
(load-on-startup=false); arms `star.evals run --pin-model --model star-fast|star-fast-cand3` on golden-tasks-v2 and
golden-tasks-creation-v1, then `star.evals gate --paired-session --allow-model-change`.
Live state after item 1: unchanged. star-fast = bin-ramforge, live weights + DSpark + ngram-mod (checked 18:12Z:
answers "OK."); temp server on :8094 stopped (no process); lock free.

## Item 2: priority scheduler, one clean live trial (PR #524 head 68ae2dcc + patch 0003 binary /opt/star/bin-prio)
Config = branch server/priority/priority.json: unlabelled = P2, owner = label or STAR app/bot/voice body fingerprint
(chat_template_kwargs) = P0, night school / conductor / knowledge refresh on :8083 = P3 (+ STAR_PRIORITY=P3 header),
solo_p0 + solo_keep 1, mark_low_priority (64-token prompt chunks), star-fast 3 slots / ctx 98304 / bg_cap 2.
Differences from round 3 (why this one is cleaner): the quality A/B eval (STAR code, fingerprinted, unlabelled = counted
as owner in round 3) has finished; no other star-fast server on brain 1 (round-3 suspect for the 313 s stall: none
running now, checked 18:00Z); default batch size (the batch-size 128 assert is not in this config); every remote step
has `timeout -k 10 540` inside the container so a killed lock run cannot leave a step running.
Bench (brain 1 /opt/star/bench/prio, results q2.jsonl): q2-base.sh, q2-m1.sh (batch x2 + latency), q2-m2.sh (300 s, 2 P3
streams, owner chat every 10 s), q2-m3.sh (3,000-token P3 prompt + owner chats, class check). PC wrapper scratchpad
q2/run.sh. Pre-change file hashes in scratchpad q2/pre-state.txt (models.ini 39ecf3b1..., ramforge.conf 0a67cc32...,
learning/env e2bbf768..., ns __main__ 3697e4d2, conductor b0e566f0, config 44a7c8ce, idle 8daa2265, real d4696c39).
- 18:03-18:08Z hold Q2-BASE (router direct, 2 slots, live binary): batch (6 x 250 tokens, 2 at a time, chats at
  10/50/90 s) bg 12.34 tok/s (cold) and 15.26 (warm prompt cache), chats first token 24.4/21.9/23.9 s and 10.4/12.1/1.5 s;
  latency k0 1.59/1.59 s, k1 1.89/2.04 s.
- 18:13-18:16Z hold GO-LIVE (`STAR_SERVER_SSH=... bash server/priority/deploy.sh --start` from worktrees/priority-scheduler-20261020
  @ 68ae2dcc): backup /opt/star/config/backups/priority-20261021-181322, warm-up star-fast via 8083 200 in 129 s.
  Checked 18:16Z: star-fast = bin-prio, --parallel 3, --ctx-size 98304; star-priority/star-brain/star-night-school
  active; night school already sending P3 through the proxy. UNDO (one command, as root in the container):
  `ssh <brain 1> "lxc exec starai -- bash /opt/star/priority/undo.sh"` (or `bash server/priority/deploy.sh --undo`).
- 18:21-18:27Z hold M1 (proxy live): batch bg 7.53 tok/s (first run after the restart; 61% of base run 1) and 13.13
  (86% of base run 2); mean 10.33 vs 13.80 = 75%. Owner chats first token: batch 2.43/3.23/2.51, 3.17/2.99/1.70 s;
  latency k0 1.75/1.55, k1 1.86/2.12, k2 3.93/3.01 s.
- 18:33-18:38Z hold M2 (proxy live): 2 P3 streams for 300 s + owner chat (60 tokens, /p0) every 10 s = 30 owner
  requests: first token median 2.35 s, best 1.54, worst 5.14 s; 3 of 30 over 5 s (5.04, 5.09, 5.14), 9 over 3 s.
  Background made 128 tokens in 300 s (0.42 tok/s): with an owner answer running 7-12 s out of every 10 s, solo mode
  keeps background paused almost all the time (by design, but it means a busy owner starves background completely).
- VERDICT (18:39Z): FAIL -> undo. Worst first token 5.14 s (> 5 s rule; 3/30 over), background in the batch test 75%
  of baseline (< 85%: 61% on the first run after the restart, 86% on the second). Medians pass (2.35 s M2; all 42
  owner requests M1+M2 median ~2.3 s). M3 (long background prompt) not run: the decision was already made.
- 18:43-18:46Z hold UNDO (`lxc exec starai -- bash /opt/star/priority/undo.sh`): "undo done: router on 8080 again (200)".
  Verified 18:47Z: models.ini, ramforge.conf, learning/env and the 5 night-school files hash-identical to before the
  trial; refresh drop-in gone; no task_checkpoint.py; star-priority inactive; star-brain + star-night-school active;
  only the router listens on 0.0.0.0:8080; star-fast = bin-ramforge, spec on, --parallel 2, --ctx-size 65536; chat
  "Say OK." answered "OK" (101 s incl. star-fast reload). bin-prio and the patched tree stay on disk (unused).
- What would be needed for a keep: (1) the worst case: 3/30 owner chats at 5.0-5.1 s when the chat lands while a
  P3 answer is being paused (pause + 64-token chunk cadence + spec decode on 3 slots); (2) background share: solo
  mode pauses all background during every owner answer, so background falls to ~0 under steady owner traffic and to
  61-86% with three chats in two minutes. A budget (e.g. background keeps one slot after N seconds of owner activity)
  would trade (2) against (1); not tried here (one trial only).

## Item 2b (owner priority, added 18:40Z): CCX-aware thread pinning + huge pages for star-fast
Host facts (read 18:38Z): EPYC 7451, 24 cores / 48 threads, 4 NUMA nodes, 8 L3 (CCX) of 3 cores; CPUs 0-23 are
the physical cores, 24-47 their SMT siblings (cpu N+24 = sibling of N); node k = CPUs k, k+4, ... CCX pairs per node,
e.g. node 0: CCX {0,8,16} and {4,12,20}. `sudo -n star-host-tune status`: numa_balancing 0, swappiness 10 (applied,
persistent via /etc/sysctl.d/90-star-host-tuning.conf), THP enabled=madvise defrag=madvise (tool leaves them),
no cpufreq governor exposed, irqbalance inactive; HugePages_Total 0 (no hugetlbfs pool); AnonHugePages 0.
Why --cpu-mask/--cpu-strict cannot do it here: with --numa distribute ggml calls set_numa_thread_affinity() at the
start of every graph, which pins each thread to ALL 12 CPUs of its node (6 cores + 6 SMT siblings) and overrides any
cpumask; and without --numa the RAMForge node-local row split is lost. Observed in the baseline: busy compute threads
on cpu0+cpu24, 9+33, 20+44, 21+45 (two threads sharing one physical core) while other cores idle.
Patch (brain 1 /opt/star/bench/q2b/apply_pin.py, tree /opt/star/src/llama.cpp-pin, never the live tree): env
GGML_RF_PIN=1 pins thread j of node k to ONE cpu: node k's physical cores sorted by (L3 id, cpu), then their SMT
siblings. Off unless the env var is set. Built 18:5xZ (build_pin.sh, nice 19, -j 8).
Bench: /opt/star/bench/q2b/q2bhold.sh (temp server :8094, live weights, A1 env, live spec flags, -np 2, -tb 24,
spec2.py single = same 8 greedy prompts as item 1, thread->CPU sample, AnonHugePages). PC wrapper scratchpad q2b/run.sh.
- 18:51-19:00Z hold b1 BASE (bin-ramforge, -t 24): gen 10.14 tok/s, prompt median 37.3, first token chat 2.47/1.50 s,
  accept 54.8%. (Script hung in `wait` on the server after the run, killed by the 540 s timeout; result complete,
  temp server gone; fixed.)
- 19:06-19:12Z hold b2 PIN -t 24 (GGML_RF_PIN=1): busy threads exactly on cpu0..cpu23 (one per physical core, no
  SMT sharing); gen 10.01 tok/s (-1%, noise), prompt median 41.2 tok/s (+10%), first token chat 2.47/1.33 s.
- 19:18-19:24Z hold b3 PIN -t 20 (-tb 24): gen 9.99 tok/s (same as -t 24 pinned 10.01), prompt 41.3, first token
  chat 2.22/1.52 s. Generation does not move with -t 20/24 or pinning: it is memory-bandwidth bound (4 of 8 channels,
  2400 MT/s). (The thread sample uses ps lifetime %CPU, so the prompt-phase threads also show.)
- Per prompt (b1 base vs b2 pin24): code_edit (393-token prompt) first token 9.21/8.94 s -> 7.64/7.56 s (-17%), its
  prompt speed 43.6/44.9 -> 52.9/53.3 tok/s (+20%); short prompts 1.3-2.7 s both. Generation per prompt within noise.
- 19:30Z lock held by another session (claude-g0); b4 waited for it.
- 19:38-19:46Z hold b4 PIN -t 24 + 2 MB huge pages (GLIBC_TUNABLES=glibc.malloc.hugetlb=1: glibc madvises its
  mmap'd chunks MADV_HUGEPAGE; THP is madvise system-wide, so no system change): AnonHugePages 4.1 GB after load,
  6.0 GB after the run (khugepaged keeps collapsing); load 167 s (+45 s); gen 8.08 tok/s (-19%), prompt 36.1 (-12%).
  REJECTED. Cause (consistent with the numbers, not traced): RAMForge places weights per node in ~150 KB row ranges
  (124,044 mbind calls for 18.7 GiB); a 2 MB page can live on one node only, so huge pages undo the node-local placement.
  1 GB pages (hugetlbfs) were not tried: they need a reserved pool (root, kernel setting = owner's call) and would be
  even coarser than 2 MB against the same ~150 KB placement, so they cannot help with RAMForge on; without RAMForge
  placement the 2026-10-13 measurements were slower than with it.
- 19:53-20:03Z hold b5 CONCURRENCY BASE (bin-ramforge: temp star-fast :8094 + temp star-voice :8095, same flags as
  live, voice answering 200 tokens back to back): star-fast gen 5.75 tok/s (8 prompts; variant 0: 5.88), prompt 21.7,
  first token chat 3.87/3.00 s, code_edit 11.8 s; voice 28 answers, median 14.2 tok/s. The script was killed at its
  560 s limit after spec2 finished, and the voice temp server survived the kill (found 20:05Z, killed; scripts now
  trap TERM, test shortened to variant 0).
- 20:12-20:19Z hold b6 CONCURRENCY PIN (both temp servers GGML_RF_PIN=1, variant 0 only): star-fast gen 4.03 tok/s
  (b5 variant 0: 5.88, -31%), first token chat 4.38 s (3.87), voice 9 answers median 6.4 tok/s (b5: 14.2, -55%).
  Two pinned 24-thread processes land on the same 24 cores and cannot move to the idle SMT siblings.

### Item 2b verdict: nothing changed live
| star-fast temp server, live flags (spec, -np 2) | gen tok/s | prompt tok/s | first token 393-token prompt | with star-voice busy: fast / voice tok/s |
|---|---|---|---|---|
| live today (bin-ramforge, -t 24, node-wide affinity) | 10.14 | 37.3 | 9.2 / 8.9 s | 5.88 / 14.2 |
| per-core pin, CCX-grouped, -t 24 | 10.01 | 41.2 | 7.6 / 7.6 s | **4.03 / 6.4** |
| per-core pin, -t 20 | 9.99 | 41.3 | 7.7 / 8.5 s | - |
| per-core pin + 2 MB huge pages | **8.08** | 36.1 | - | - |
- Pinning: +10-20% prompt speed and -1.4 s first token on a 393-token prompt when star-fast runs ALONE, no
  generation gain, and a large regression when a second model works at the same time (-31% star-fast, -55% voice).
  The router gives every model the same environment, so it cannot be enabled for star-fast only without more code;
  brain 1 runs star-fast beside star-voice, embeddings and night school all day -> NOT kept.
  -t 20 vs 24: same generation (bandwidth-bound). Huge pages: -19% generation -> NOT kept. 1 GB pages: not tried
  (owner-level kernel setting, and coarser than RAMForge's ~150 KB per-node placement).
- Possible follow-up (not done): pin only the process whose thread count equals a given value, or give star-fast
  cores 0-23 and other models the SMT siblings 24-47 (needs per-model env in the router).
- Live state after 2b: unchanged (star-fast bin-ramforge, node-wide affinity, THP madvise untouched). Patch and
  binary stay on brain 1 at /opt/star/src/llama.cpp-pin (unused); repo copy server/ramforge/patches/0004-ggml-rf-pin-per-core.patch
  + server/ramforge/build_pin.sh. Temp servers on :8094/:8095 stopped (checked 20:20Z).

## Brain 1 state at the end (checked 20:21Z)
Router llama-server (bin-ramforge, /opt/star/config/models.ini sha 39ecf3b1..., unchanged since before item 2)
directly on 0.0.0.0:8080; star-priority inactive (proxy off); star-fast = live Qwen3.6-35B-A3B Q4_K_M + DSpark
Q4_K_M draft n-max 2 + ngram-mod, --parallel 2, --ctx-size 65536, node-wide thread affinity (no GGML_RF_PIN);
THP madvise (untouched); star-brain, star-night-school, star-knowledge active; star-fast and star-voice answer;
no temp servers on :8094-8097; quiet lock free. Left on disk, unused: /opt/star/bin-prio, /opt/star/src/llama.cpp-prio,
/opt/star/src/llama.cpp-pin, preset [star-fast-cand3] (load-on-startup=false), bench files under /opt/star/bench/.
