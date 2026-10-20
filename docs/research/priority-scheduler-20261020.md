# Priority scheduler: owner first, background paused and resumed (2026-10-20)

Owner (2026-10-20): "do as many background tasks as possible ... but it prioritizes the task ... pause the other task
if it needs to for a second, but then go right back to it". Notes and run log: docs/agents/priority-scheduler-20261020.md.

## 1. What other systems do (sources)

| System | Priority | Preemption | Resume |
|---|---|---|---|
| vLLM | `--scheduling-policy priority`, per-request `priority`, lower value first, ties by arrival [1] | when KV cache runs out it preempts requests; V1 default is RECOMPUTE, not SWAP [2] | recompute: the preempted request's prompt + output is prefilled again when space returns [2]; PagedAttention paper: swap or recompute [3] |
| SGLang | `--enable-priority-scheduling`, `--schedule-low-priority-values-first` [4] | `--priority-scheduling-preemption-threshold` (min priority gap to preempt running requests, default 10), `--disable-priority-preemption`; `--retraction-policy priority` retracts low priority first when KV is full [4] | retracted requests are re-queued and their prefix comes back from the radix cache |
| FastServe | skip-join multi-level feedback queue | preempts at token granularity to cut head-of-line blocking [5] | KV kept/swapped per job |
| Hybrid real-time + best-effort serving | real-time vs best-effort classes | per-iteration preemption of best-effort work; FCFS causes head-of-line blocking [6] | |
| llama.cpp (our server) | none: any request takes any idle slot; `id_slot` pins a slot | none built in; a closed client connection cancels the task (checked live in the source on brain 1) | `cache_prompt` reuses the common prefix; `--cache-ram` keeps evicted prompts in RAM; `/slots/{id}?action=save|restore|erase` with `--slot-save-path` stores a slot's KV in a file [7]; `continue_final_message` (incl. `"reasoning_content"`) continues the last assistant message |
| Linux CPU | nice: each step is a factor ~1.25 in CFS weight; `SCHED_IDLE` runs below nice 19 [8] | cgroup v2 `cpu.weight` (1-10000), `cpu.idle` (SCHED_IDLE for a group), `cpu.max` (bandwidth cap), `cgroup.freeze` (stop a whole group) [9] | SIGSTOP/SIGCONT or unfreeze: the process continues exactly where it was |
| Agent frameworks | - | a run stops between steps | LangGraph checkpointers persist graph state per step and resume from the last checkpoint [10]; Temporal replays an event history to resume a workflow (durable execution) [11] |

What I verified in our llama.cpp build (/opt/star/src/llama.cpp-ramforge, router b1-b58ca6a), not just read in docs:
- `SLOT_SAVE` on a slot that is processing is deferred until the slot is idle, so "save the running slot" is not a
  preemption tool: the generation has to be stopped first.
- A closed client connection stops the generation (HTTP layer `should_stop`, also through the router's pipe).
- `continue_final_message: true` + `add_generation_prompt: false` continues an assistant prefix; for star-fast's
  template the rendered continuation is byte-for-byte the generation prompt + the text (checked with /apply-template).
- star-fast (Qwen3.6-35B-A3B) is a hybrid model with recurrent layers. Its state "cannot be rewound"
  (server-context.cpp); llama.cpp only keeps context checkpoints made during prompt processing. Consequence measured
  below: a resumed answer reuses its slot exactly when the server stopped at the same token the proxy last received;
  if the server had produced one more token, it falls back to the end-of-prompt checkpoint and reads the partial
  answer again (at prompt speed, ~4x faster than generating it).

Why not slot save/restore: it needs a cancel first anyway, writes 200-360 MiB per slot to disk (entry sizes seen on
brain 1, 2026-10-13), and its checkpoints have the same rewind limit. The RAM prompt cache (`cache-ram 24576`) and the
slot's own KV already give the cheap path. Why not vLLM/SGLang: brain 1 is CPU-only and llama.cpp is what runs there;
the policy ideas carry over (priority classes, preempt the lowest, recompute on resume, threshold so equal
priorities never preempt each other).

## 2. Design (as built, opt-in)

```
 owner chat / voice / Discord ──► :8097/p0 ┐
 owner tasks                  ──► :8097/p1 ├─► priority proxy ─► llama.cpp router :8080 ─► star-fast (3 slots), star-voice
 conductor / agents / games   ──► :8097/p2 │   (star/priority_proxy.py)
 night school / evals / index ──► :8097/p3 ┘   status: /priority/v1/status   log: /opt/star/logs/priority.jsonl
```

- **Classes** P0 owner chat/voice/Discord, P1 owner tasks, P2 conductor/agent/game work, P3 night school/evals/
  indexing; chosen by URL prefix (a client changes only its URL) or the `X-Star-Priority` header.
- **Admission** per model: a request starts when a slot is free; P2/P3 together use at most `bg_cap` slots
  (star-fast: 2 of 3, the same cap as chat-slot-20261020's convention) so an owner request always finds a slot.
- **Preemption**: a P0/P1 request that finds no slot pauses the lowest-priority running request (P3 before P2,
  newest first; equal or higher priority is never paused). `solo_p0` (on): while any P0 runs, every P2/P3
  generation on star-fast and star-voice is paused, plus 2 s grace for a follow-up, because brain 1 is CPU-bound and
  three streams share the same memory bandwidth (chat measured at 4.1 tok/s beside two background streams vs ~11
  alone, speed-20261020).
- **Pause** = shut down the upstream socket: llama.cpp cancels at the next token and frees the slot.
- **Resume** = the same request with the text so far as an assistant prefix (`continue_final_message`) or, for text
  completions, appended to the prompt; `max_tokens` reduced by what was made. The client sees one answer with a
  pause in it: same id, one role line, usage summed over segments. Non-streaming clients get one JSON answer.
  Not continuable (tool-call output, grammar/JSON-schema, n > 1, non-text prompt): non-streaming ones start over
  (nothing was sent yet; counted as a restart), streaming ones are not paused once such output was sent.
- **Slot affinity**: each scheduled request is pinned to a slot that the proxy and the server's /slots both show
  free; a paused answer gets its own slot back; P0 takes a slot no paused answer is waiting for.
- **Auth**: chat requests need a key from /opt/star/secrets/api_keys before they are scheduled (a stranger cannot
  pause background work); status is free from loopback.
- **Task level**: star/task_checkpoint.py (atomic per-step JSON); the night conductor stores each finished step, so a
  cycle that yields (owner chat, restart) does not ask those steps again and still counts their tasks. Night school
  `STAR_NS_GATE=priority` stops yielding to other clients when its brain URL is the proxy (HOLD and the quiet lock
  still stop it; no proxy -> old idle gate). Agents/fleet code can use the same StepCheckpoint (not wired yet).
- **CPU work**: `python -m star.cpu_priority --class P3 [--pause-url http://127.0.0.1:8097] -- <cmd>`: P2 nice 10,
  P3 nice 19 + SCHED_IDLE (Windows: below-normal / idle priority class), optional SIGSTOP/SIGCONT of the job's
  process group while the proxy reports `p0_active`. Night school's own jobs already run under `nice -n 19`.

## 3. Measured (brain 1, under the quiet lock, 2026-10-20 11:13-12:07Z)

Setup: temporary star-fast server on :8096 with the live binary and live flags (DSpark + ngram-mod speculative
decoding, `cache-ram 24576`, 24/24 threads, **3 slots** = live since 11:06Z), proxy on :8097 with star-fast 3 slots,
bg_cap 2, solo_p0, grace 2 s. "Today" = clients straight to the server (the 3-slot / 2-background convention).
Background streams: 250-400-token Roblox guides, greedy; chat: 60 tokens, 52-token uncached prompt. Studio in the
pb-studio container shared the host CPU (load average ~13 of 48 threads), so rows are compared within the session.
Script: server/priority/bench.py; raw rows /opt/star/bench/prio/results.jsonl and proxy-*.jsonl on brain 1.

**P0 first token, K background streams wanting to run** (seconds; proxy rows = holds 4, 6, 7)

| K | today (direct, 3 slots) | proxy | proxy samples |
|---|---|---|---|
| 0 | 1.54, 1.57 | median 1.72 | 1.88, 1.55 |
| 1 | 2.07, 2.12 | median 1.87, max 2.70 | 7 |
| 2 | 2.75, 2.76 | median 2.56, max 2.73 | 7 |
| 3 | **71.3** (queued behind a 400-token answer) | median 2.61, max **3.55** | 7: 2.00 2.61 1.74 3.55 3.44 3.27 2.46 |

With bg_cap 0 (background may take all 3 slots) K=3 gave 4.92 and 2.09 s: the owner then waits for a cancel to land,
so bg_cap 2 is the setting.

**Fixed workload with owner chats** (6 background answers x 250 tokens, 2 at a time, chats at 10/50/90 s)

| pair | today: makespan, bg tok/s | proxy: makespan, bg tok/s | proxy / today |
|---|---|---|---|
| hold 5 (direct first) | 120.8 s, 12.42 | 130.5 s, 11.49 | 92.5% |
| hold 6 (proxy first) | 98.0 s, 15.30 | 108.2 s, 13.86 | 90.6% |
| hold 7 (slot affinity) | 96.6 s, 15.52 | 113.7 s, 13.19 | 85.0% |
| mean | 14.41 | 12.85 | **89.2%** |

Chats in those runs: today first token median 4.30 s (1.68-6.50), whole answer median 13.5 s (max 36.9 s); proxy
first token median 2.35 s (1.52-3.25), whole answer median 7.6 s (max 10.0 s). Three chats in two minutes is a heavy
owner rate; the background loss scales with chat time (each chat pauses background for its length + 2 s).

**Resume overhead** (20 resumes of 17 answers that finished): tokens read again per resume median ~106, mean ~111,
bimodal: 5 resumes read 1-5 tokens (the slot still matched), the rest re-read the partial answer (the server had made
a token past the cut; hybrid model, see section 1). Seam test: a 300-token answer cut after 55 tokens resumed with 1
token re-read and 55 from cache; the text reads straight through and ends at exactly 300 tokens. Nothing was lost or
duplicated in any resumed answer (unit tests check the exact text; live answers ended at their max_tokens).

**Against the targets**: background throughput 89% of today's (target >= 85%: met, worst pair 85.0%). P0 first token
under 3 s: median 2.3 s over the 36 owner requests in the proxy logs (bg_cap 2 runs), 31/36 under 3 s, worst 4.0 s
(seam run) and 3.25-3.55 s (K=3 and one batch chat);
today's comparable figures are 4.3 s median and 71 s worst. Strictly "under 3 s with any load" is not met in every
sample.

## 4. Expected effect live and what is next
- Discord/desktop message during night school + an eval (K=2-3): first token ~2-2.7 s instead of 33-71 s, full answer
  at ~11 tok/s instead of ~4-6.
- Background loses roughly (chat seconds + 2 s) per owner message plus the re-read (~2.5 s per paused stream).
- The remaining tail (3.3-4.0 s) comes when a cancel has to wait for a big prompt batch (a resumed answer re-reading
  its text, or a new background prompt). Two ways to cut it, both measurable: a smaller `--ubatch-size` for star-fast
  (cancels land between smaller batches), or making resumes exact (the server would have to stop at the proxy's last
  received token; llama.cpp has no graceful-stop call today).
- Rollout: (1) `bash server/priority/deploy.sh --start` (inert until a client moves), (2) Discord bot and desktop to
  `/p0`, night school to `/p3` with `STAR_NS_GATE=priority`, (3) evals/agents/conductor to `/p2`/`/p3`, (4) Studio
  jobs and test runs under `star.cpu_priority`. Undo at any step: the client's URL back to :8080;
  `deploy.sh --undo` stops the proxy.

## Sources
1. vLLM SchedulerConfig `policy`: https://docs.vllm.ai/en/latest/api/vllm/config/scheduler.html
2. vLLM optimization guide, preemption: https://docs.vllm.ai/en/latest/configuration/optimization.html
3. Kwon et al., Efficient Memory Management for LLM Serving with PagedAttention (SOSP 2023): https://arxiv.org/abs/2309.06180
4. SGLang server arguments: https://docs.sglang.io/advanced_features/server_arguments.html
5. Wu et al., Fast Distributed Inference Serving for LLMs (FastServe): https://arxiv.org/abs/2305.05920
6. Efficient LLM Serving on Hybrid Real-time and Best-effort Requests: https://arxiv.org/abs/2504.09590
7. llama.cpp server README (slots save/restore/erase, cache_prompt, cache-ram, id_slot): https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
8. sched(7), SCHED_IDLE and nice weights: https://man7.org/linux/man-pages/man7/sched.7.html
9. Linux cgroup v2 (cpu.weight, cpu.idle, cpu.max, cgroup.freeze): https://docs.kernel.org/admin-guide/cgroup-v2.html
10. LangGraph persistence / checkpointers: https://langchain-ai.github.io/langgraph/concepts/persistence/
11. Temporal, durable execution: https://docs.temporal.io/workflows

## 5. Live trial on brain 1 (2026-10-20 12:28-13:3xZ) - undone

Lead decision: go live with every client behind the proxy. Deployed with `server/priority/deploy.sh --start`
(golive.sh): router moved to 127.0.0.1:8081, proxy on 8080 (unlabelled = P0) + 8082 (P2) + 8083 (P3), star-fast
3 slots / ctx 98304, night school + conductor on 8083 with STAR_NS_GATE=priority, knowledge refresh on 8083,
brain 2 playtest learning on 8083. Discord bot, desktop app and voice stayed on 8080 (P0). Every step and measurement
ran under `star lock run`. Same bench as section 3 (chat 60 tokens; batch = 6 x 250 tokens, 2 at a time, chats at
10/50/90 s).

| live run | owner first token (s) | whole chat (s) | background tok/s (vs 12.01 today) |
|---|---|---|---|
| today: router direct, 2 slots | K0 1.99 1.61 · K1 2.01 2.01 · K2 **48.13** 2.27 · batch 18.64 18.61 23.45 | 26.7-33.5 | 12.01 |
| proxy, solo, grace 2 s | K0 2.93 1.95 · K1 2.06 2.07 · K2 1.81 2.06 · batch 2.03 3.28 2.00 | 7.4-8.6 | 9.57 (80%) |
| + solo_keep 1 | K1 2.00 2.04 · K2 **5.99** 2.22 · batch 3.27 3.51 2.35 | 6.0-23.9 | 12.32 (103%) |
| solo_keep 0, grace 1 s | K1 2.30 1.83 · K2 2.61 3.03 · batch **6.58** 4.24 3.54 | 8.4-12.1 | 12.64 (105%) |
| + ubatch-size 128 | K0 1.71 1.56 · K1 1.80 1.87 · K2 2.03 2.05 3.46 2.26 · batch **44.32** 1.85 2.07 / 3.91 3.99 3.34 | 8.4-46.3 | 7.84 / 12.25 |
| + batch-size 128 | long background prompt then chat: **30.96, 30.71** · batch 2.26 3.16 2.08 | 6.9-38.2 | 9.98 (83%) |

Long-prompt speed did not suffer from the small batches (1,950-token cold prompt 36.2 tok/s at the default, 43.1
with ubatch 128, 43.0 with batch 128; single samples).

What failed: the owner waits whenever star-fast is reading a long background prompt. In the 44 s case night school
(correctly labelled P3) had just sent a 3,113-token prompt; the router log shows the cancel of the paused requests
landing ~29 s later. Smaller `ubatch-size` and `batch-size` did not remove it (31 s in the dedicated test). Then an
owner request hung in the proxy for ~10 minutes while star-fast stopped answering `/slots` (> 2 min), and solo mode
held all background off behind it. Lead's rule (median < 3 s, worst < 5 s, background >= 85%): medians passed in
every configuration; the worst case did not -> **undone** with /opt/star/priority/undo.sh (router back on
0.0.0.0:8080, proxy off, star-fast 2 slots / 65536, night school env and code, refresh drop-in and brain 2 playtest
URL restored; checked: chat through 8080 answers).

Fixed in the code after the trial: `solo_max_s` (120 s): an owner request running longer no longer holds background
off. Open: (1) why star-fast stopped answering (not reproduced; it began after a P0 was pinned while two paused
P3 cancels and a long P3 prompt were in flight), (2) the long-prompt wait: next is reading llama.cpp's
update_slots to see whether a new task and cancels wait for a whole slot prompt, and either a server patch (check
cancels between prompt batches) or a proxy rule that holds background prompts above N tokens while an owner request
is likely (e.g. within 60 s of the last one).

## 6. Round 2: server patch 0003 (2026-10-20 13:45-15:50Z)

Root cause, from llama.cpp's update_slots: each iteration builds ONE batch (up to `batch-size`, default 2048 tokens);
generating slots add their tokens first, then pending prompts are added greedily in slot order. A long background
prompt in an earlier slot fills every batch, so the owner's prompt starts only when it is done. Second cause: in
router mode a request that is still reading its prompt is not cancelled when its client leaves; the router's
connection to the child stays open until the child sends its first byte.

Patch `server/ramforge/patches/0003-server-low-priority-slots.patch` (built by `server/ramforge/build_prio.sh` into
/opt/star/src/llama.cpp-prio, next to the live tree): a request with `"low_priority": true` reads its prompt in
chunks of at most 64 tokens per iteration (`LLAMA_LOW_PRIO_CHUNK`), and not at all while a normal slot has work
(prompt or generation). The router calls `cli->stop()` when the client goes away, so the child cancels mid-prompt.
Proxy: `mark_low_priority` adds the field to P2/P3 requests; `solo_keep` streams resume only after every owner
request has its first token.

The 10-minute hang, reproduced offline: the live binary with `batch-size 128` + speculative drafts (ngram-mod) +
3 slots under 3 streams of repetitive code hits `GGML_ASSERT(add_ok && "batch must be large enough to hold the
sampled and draft tokens")` (server-context.cpp:576; the batch holds max(batch-size, parallel) = 128 tokens, three
slots' sampled + draft tokens overflow it), star-fast dies and the router leaves its requests waiting until they time
out. Cause: my round-1 `batch-size 128` experiment. The patch keeps the default batch size.

Offline, temporary router on 127.0.0.1:8096 (same model, live flags, router mode), quiet lock for every run:

| configuration | owner first token behind a 3,000-token background prompt | owner, all scenarios | background tok/s (batch test) |
|---|---|---|---|
| today: live binary, 2 slots, no proxy | **104.5 s** (chat at 3 s) | batch chats 22.8-24.9 s | 12.44 |
| patch, chunk 256, proxy solo | 2.14-5.90 s (median ~4.1) | - | - |
| patch, chunk 64, proxy solo (pause all) | 1.56-2.63 s (8) | latency 1.55-2.02, batch 1.82-2.02 | 9.76 (78%) |
| patch 64, proxy solo_keep 1 | 1.64-2.78 s (12) | batch first chats 3.33-5.30 | 14.31-15.63 |
| patch 64, proxy without solo | - | batch 1.66-5.89 | 15.37 |
| **final: patch 64, solo_keep 1 after the owner's first token** | **1.74-2.77 s (8/8 < 3 s)** | **30 requests: median 2.30 s, worst 3.86 s** (6 over 3 s) | **12.34-13.32, mean 12.73 (102%)** |

Live trial 2 (15:10-15:42Z, the final configuration via golive.sh: patched binary /opt/star/bin-prio, proxy front
door, star-fast 3 slots): my owner requests 1.56-3.55 s in 20 of 22 samples; the two exceptions (7.41, 6.04 s) ran
beside another client's 440-token unlabelled (= P0) answer. Background in the batch test 9.84 tok/s (82%) and then
6.91 (58%): during that run an eval on the PC (`scripts/brain_vault_eval.py`, another session) sent star-voice and
star-fast requests back to back without a label, so as P0 it held background off for minutes (P3 waits of
105-204 s in the proxy log). Background >= 85% failed live -> **undone again** with /opt/star/priority/undo.sh
(checked: router on 8080 with the live binary, proxy off, star-fast 2 slots, night school env restored, brain 2
playtest URL restored).

What is needed before the next go-live: every background client labelled, especially evals (`STAR_EVAL_SERVER=
http://<brain 1>:8083/v1`) and any script session; or make the unlabelled default P2 and label only the owner's
clients (Discord bot, desktop app, voice) P0. Then `deploy.sh --start` and the same live check.
