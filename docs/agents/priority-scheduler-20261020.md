# priority-scheduler-20261020 (Claude sub-agent, board #192)

Goal (owner 2026-10-20): run as much background work as the machines allow, but whatever the owner asks for comes
first; background is paused for a moment and resumed where it stopped. Branch star/priority-scheduler-20261020
(worktree worktrees/priority-scheduler-20261020, from origin/star/next 78bc1ebd). Research + design:
docs/research/priority-scheduler-20261020.md (in the branch).

## Built (in the branch)
- star/priority_proxy.py: stdlib proxy in front of the router, own port 8097. URL prefix /p0../p3 (or header
  X-Star-Priority) = class. Schedules chat + text completions of star-fast/star-voice; everything else passes through.
  P0/P1 pause the lowest-priority running request when no slot is free; solo_p0 (default) pauses ALL background while
  a P0 runs (+2 s grace). Pause = shut down the upstream socket (llama.cpp cancels at the next token). Resume = same
  request with the partial answer as assistant prefix + continue_final_message, max_tokens reduced. Status
  /priority/v1/status (p0_active, per class wait/first token/preemptions/resumes/resume tokens), JSONL log.
- star/task_checkpoint.py + night conductor: finished steps of a yielded cycle are not asked again (checkpoint.json,
  cleared when a cycle finishes).
- night school STAR_NS_GATE=priority: PriorityGate (works beside other clients when brain_url is the proxy; HOLD and
  quiet lock still stop it; proxy missing -> old idle gate).
- star/cpu_priority.py: P2 nice 10 / P3 nice 19 + SCHED_IDLE (Windows below-normal/idle class), optional SIGSTOP/
  SIGCONT of the job's process group while the proxy says p0_active.
- server/priority/bench.py: latency / throughput / seam measurements.

## Log
- 10:50Z start; claimed #192; msg #440 to chat-slot (#190). Read speed-20261020 (33.5 s -> 2.26 s), planner, night
  school gates, conductor, llama.cpp source on brain 1 (/opt/star/src/llama.cpp-ramforge): continue_final_message
  (incl. "reasoning_content") supported; SLOT_SAVE defers while a slot is processing (so save needs a cancel first);
  disconnect cancels the task (router pipes should_stop); no --slot-save-path on the live router.
- Order note: proxy code was written before its tests (tests then written against it); checkpoint, conductor resume,
  priority gate and cpu_priority were test-first (seen failing, then passing).
- 11:13Z hold 1 (temp star-fast np=3 spec on :8096, proxy :8097): seam test exposed a bug (closing the http.client
  connection from the scheduler thread raised AttributeError inside http.client; the paused stream ended at 67 of
  300 tokens with status ok). Fixed: abort() only shuts the socket down; regression test added. Direct np=3 P0 first
  token: k0 1.54-1.57 s, k1 2.07-2.12, k2 2.75-2.76, k3 71.3 s (queued).
- Live config changed meanwhile by chat-slot: [star-fast] parallel = 3, ctx 98304 (reloaded ~11:06Z).
- Holds 2-7 (11:2x-12:07Z, each <= 10 min, lock holder claude-prio): H2 still ran the old proxy (a stale process kept
  :8097; proxy.sh stop now uses pkill + port wait). H3: seam fixed (300/300 tokens, resume re-read 1 token, 55 from
  cache). Then fixed-workload batch pairs (6 x 250 tokens, 2 at a time, chats at 10/50/90 s): proxy/today 92.5%,
  90.6%, 85.0% (mean 89.2%); chats first token median 2.35 s (proxy) vs 4.30 s (today). Latency K=0..3 (bg_cap 2,
  solo): medians 1.72/1.87/2.56/2.61 s, worst 3.55 s; today K=3 = 71.3 s. bg_cap 0 (background on all 3 slots) gave
  4.92 s at K=3 -> bg_cap 2 is the setting.
- Resume overhead is bimodal (hybrid Qwen3.6: recurrent state cannot be rewound): exact (1-5 tokens re-read) when the
  server stopped at the proxy's last token, else the partial answer is re-read at prompt speed. Diagnosis script
  (/tmp/cut.py on brain 1): tokenization of prompt+partial matches the generated ids exactly; the slot keeps only
  the end-of-prompt checkpoint. Slot affinity added (pin to a free slot, keep a paused answer's slot) - did not change
  the bimodality (the cause is the extra token, not the slot).
- 12:08Z temp server + proxy on brain 1 stopped (ports 8096/8097 free). Full pytest on the PC: 9939 passed, 315
  skipped, 0 failed (7.5 min). pyright (new modules) 0 errors; ruff on changed files clean.
- Targets: throughput >= 85% MET (89%); P0 first token < 3 s: 31/36 logged owner requests (median 2.3 s, worst 4.0 s)
  -> NOT met strictly, so NOT deployed live (brief: deploy only if targets are met). Nothing live changed by this
  item. Deploy when wanted: `STAR_SERVER_SSH=<brain1> bash server/priority/deploy.sh --start` (inert until a client
  moves to :8097/p<class>); undo `... deploy.sh --undo`; client undo = URL back to :8080.
- Next: (1) try `--ubatch-size` smaller for star-fast (cancel lands between smaller batches) to cut the 3.3-4.0 s
  tail; (2) deploy + switch Discord bot /p0 and night school /p3 (STAR_NS_GATE=priority) together; (3) wire
  StepCheckpoint into agent_fleet/conductor_fleet runs; (4) Studio/test jobs under star.cpu_priority.
