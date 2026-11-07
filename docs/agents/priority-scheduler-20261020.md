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
- 12:2xZ LEAD: go live (proxy as front door on 8080, router internal, star-fast 3 slots, background labelled P3/P2).
  Built: class ports (8080 P0 / 8082 P2 / 8083 P3; night school's app refuses URL paths), all verbs passed through,
  logprobs unscheduled, listen backlog 256, golive.sh (writes /opt/star/priority/undo.sh), deploy.sh --start/--undo.
- 12:28Z L1 live baseline (router direct, 2 slots). 12:35Z go-live (backup /opt/star/config/backups/priority-
  20261020-123520). 12:39-13:15Z L3-L9 (table in docs/research/priority-scheduler-20261020.md section 5). Medians
  < 3 s everywhere; worst 5.99 / 6.58 / 44.3 / 31 s when star-fast is reading a long background prompt (night
  school's 3,113-token prompt: cancel landed ~29 s later); ubatch 128 and batch-size 128 did not fix it.
- ~13:25Z an owner request hung in the proxy ~10 min, star-fast did not answer /slots; lock run's 10-min limit did
  not end the hold (ssh kept running; lock went stale). 13:3xZ UNDO run (undo.sh): router 0.0.0.0:8080 direct,
  star-priority inactive, star-fast parallel 2 / ctx 65536, no batch lines, learning env + night school code back
  (live MAX_REPAIRS_PER_CYCLE = 0 kept), refresh drop-in removed; brain 2 playtest brain.env restored from
  .bak-20261020-priority. Chat via 8080 answered (110 s: star-fast reload). Nothing of this item is live now.
- After: solo_max_s (120 s) so a stuck owner request cannot starve background (test added).
- ROUND 2 (lead: offline first, patch llama.cpp). Root cause in update_slots: one batch per iteration, prompts added
  greedily in slot order; router keeps the child connection while the child reads a prompt. Patch 0003 (low_priority
  prompt chunks of 64 tokens, deferred while a normal slot works; router cli->stop()) in /opt/star/src/llama.cpp-prio
  (copy of the live tree; build_prio.sh). Live tree and binary untouched.
- Hang reproduced (hold HH, 15:01-15:09Z): live binary + batch-size 128 + spec + 3 slots -> GGML_ASSERT batch too
  small (server-context.cpp:576), star-fast dies, requests wait to timeout. My round-1 batch-size experiment caused
  the 10-minute hang.
- Offline holds HA-HL (13:52-15:01Z, temp router 127.0.0.1:8096 + temp proxy 8097): final config passes: 3,000-token
  background prompt -> owner 1.74-2.77 s (today 104.5 s); 30 owner requests median 2.30 s, worst 3.86 s; background
  102% of today. Table in docs/research section 6.
- 15:10Z go-live (deploy.sh --start; backup /opt/star/config/backups/priority-20261020-151025). Live checks LIVE-2/3:
  owner fine except 2 samples beside another P0 answer; background 82% then 58% because an unlabelled eval on the PC
  (scripts/brain_vault_eval.py) ran as P0. 15:4xZ UNDONE (undo.sh, after waiting for claude-fastdraft's lock).
  Verified restored. bin-prio and llama.cpp-prio left on disk (not used).
- ROUND 3 (board #203): unlabelled = P2, owner = body has chat_template_kwargs (v1.0 app/bot/voice; v1.0 sends no
  header, UA AsyncOpenAI/Python), STAR_PRIORITY header from providers.open_client, night school P3. Tests first
  (seen failing), 259 related tests pass. Go-live 16:04Z (backup priority-20261020-160413). Live owner samples 24:
  median 2.28 s, but 33-37 s beside an outside 668-token owner request and 313 s at 17:35Z (outside star-voice
  stream classified owner by fingerprint; cause of the 313 s not proven). Background 81% / 105%. Undone ~17:5xZ
  (undo.sh; waited for the lock queue). Restored and checked. Details docs/research section 7.
