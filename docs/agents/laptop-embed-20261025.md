# laptop-embed-20261025 (claude): the laptop GPU embeds pending knowledge chunks, automatically

Branch star/laptop-embed-20261025 (from origin/star/next), worktree worktrees/laptop-embed. Claim: board item
laptop-embed-20261025. Lead's brief: use the laptop's GTX 1650 (llama.cpp CUDA worker on :8090, `star-embed-ft1`) for the
pending knowledge embeds, push them into brain 1's index, make it automatic, verify.

## What was true at the start (differs from the brief)
- Pending was 0, not ~292,806. The PC GPU path (finish.cmd) finished on 10-20: `offload-import: read 292806, inserted
  280710` (finish.log, 16:27). Brain 1 now: 351,145 chunks, 351,145 with a star-embed-ft1 vector (`starkb stats`),
  `offload-export | wc -l` = 0. The nightly refresh since then added 209 / 24 / 28 new texts (10-23, 10-24, 10-25), which brain 1
  embedded itself in about 20 s each (1.2-2 chunks/s, under the 3000 cap).
- So there was no backlog to push. What was missing is the automatic path for the NEXT bulk change (a new corpus, a model
  or chunking change): the refresh caps its own embedding at 3000 and leaves the rest for a manual PC run that only
  happens when the PC is idle.
- The laptop's ssh (port 22) timed out from 13:30Z on (ping and 135/445/3389 are filtered too; :8090 answers 200). Nothing
  in this item needed a laptop shell, see the design.

## Design (no laptop scheduled task, on purpose)
The orchestration runs on brain 1, the laptop is only the GPU worker over HTTP (the container reaches the laptop directly).
- Nothing new has to be installed or authorised on the laptop (a laptop task would need a key to brain 1's host; that is an
  access grant I did not want to add), and the laptop's own priority/CPU 4-11 settings stay as they were.
- New `starkb offload-run` (server/knowledge/starkb/offload.py `run_on_worker`) driven by `star-knowledge-offload.timer`
  (hourly at :35 UTC). Per run: pending texts from the index; nothing pending = exit at once. More than 3000 pending (a bulk
  change) only starts 00:00-08:00 America/Chicago, so the laptop's owner is not disturbed; a small delta runs at any time.
  Takes the claim, embeds 24 stored texts on the worker and compares with the stored vectors (median >= 0.9997, each >=
  0.999, else exit 3 and nothing is stored), then embeds in groups of 2 x 8 texts in flight, each group written with
  INSERT OR IGNORE and committed (the index is the resume state: kill it anywhere, rerun, it continues). Waits for the quiet
  lock between groups, stops after `--max-seconds` (3300), on SIGTERM, if the claim is lost, the worker errors or returns a
  non-unit vector. A worker that is off or asleep = exit 0 with a log line, nothing lost.
- One claim file `data/offload-claim.json` ({owner, until}); the laptop run renews it every group (20 min TTL, so a dead run
  frees it); the PC's `gpu_embed.py pull` takes owner `pc` for 12 h and refuses (exit 75) while the laptop holds it; `push`
  releases it. Manual: `starkb offload-claim --owner X`, `starkb offload-release --owner X`.
- Unit runs as user star, Nice=19, idle IO class, CPUQuota 100 %, MemoryMax 2G; the embedding itself costs brain 1 no CPU.
- The unit has no address in it (private IP); it is `ConditionPathExists` on the key file and reads the URL from a drop-in.

## Live state on brain 1 (installed 10-25, see Undo)
- Code: starkb/offload.py and starkb/__main__.py replaced (backups in /opt/star/knowledge/backups/20261025-laptop-embed/).
  Only those two files; the live client.py/search code is untouched (live client.py is older than star/next).
- Key: /opt/star/secrets/laptop_gpu_embed_key (star, 0600), copied from the PC's laptop_gpu_api_key without printing it.
- Units: see "Automation status" below.

## Measurements (10-25, all run from brain 1 against the laptop worker, nothing stored in the live index)
Because the live index had nothing pending, the whole path was tested on a scratch copy of the live kb.sqlite3
(sqlite backup API, 2.1 GB, deleted afterwards): the star-embed-ft1 vectors of 5,590 texts (sha < "04", all sources) were
removed from the copy (originals kept in a side table), then `offload-run` re-embedded them on the laptop.

| check | result |
|---|---|
| parity, 1,000 stored texts, laptop vs brain 1 (PC, batch 16) | min 0.999512, median 0.999819, 0 below 0.999 (24 inputs shortened like on the brain) |
| the 5,590 re-embedded texts vs the brain's original vectors | min 0.999513, p1 0.999694, median 0.999819, 4 below 0.9996, 0 below 0.999, 0 below 0.99 |
| pending / embeddings in the scratch copy | 5,590 pending -> 0; star-embed-ft1 vectors 345,786 -> 351,376 |
| rate, 5,590 simplewiki/OpenStax/docs mix, batch 32 x 2 in flight | 437.5 s = 12.8 chunks/s (brain 1: 1.2-2 chunks/s, about 8x) |
| tuning, 60 s runs, same texts | batch 8 x 2: 11.6/s; 16 x 3: 11.7; 8 x 4: 11.7; 32 x 1: 10.5; 32 x 2: 10.5 -> compute-bound, default batch 8 x 2 |
| brain 1 cost of the run | 9 CPU-seconds in 4.5 min (3.5 % of one core, nice 19) |
| eval30 / heldout / golden, vector mode, hits@5 | live before 30/37/18 (recall@5 1.0 / 0.925 / 0.72, mrr 0.8667 / 0.8217 / 0.5027); scratch with the 5,590 vectors missing 30/36/18; scratch after re-embedding on the laptop 30/37/18 with identical recall and mrr to the live before |
| brain 1 chat (star-fast, 24-token reply), informal, not under the quiet lock, load average 18-21 from other work | median 0.97 s before, 1.02 s during an embedding run, 0.50-0.89 s after: no slowdown beyond the noise |

Not measured: a real bulk change end to end through the timer at night (nothing pending to run it on); the 00:00-08:00
window is covered by a unit test and by the refusal seen live at 08:5x local ("5590 pending is a bulk change: waits for
00:00-08:00 America/Chicago").

## Verified live (10-25 14:0x-14:25Z)
- Claim: `pc` holds it -> `offload-run` says "pc holds the claim" and embeds nothing; `offload-claim --owner laptop` exits 1;
  after `offload-release --owner pc` the run proceeds. PC `gpu_embed.py pull` took the claim, found 0 texts and released it.
- SIGTERM during a run: stops after the group in flight ("stop requested"), exit 0, claim file removed.
- Unit started by hand with nothing pending: "offload-run: nothing pending", unit inactive (success).
- Tests: `test_offload.py` 15 passed (8 old + 7 new: store/keep/resume, time budget and stop, bulk window, window wrap,
  wrong or down worker, worker failing midway and non-unit vector, claim). Knowledge suite 155 passed, 1 skipped, 3 failed
  (test_private_corpus: PyYAML missing in the PC venv, unrelated, same as PR #542's note).

## Automation status
- `star-knowledge-offload.timer` enabled on brain 1 (hourly at :35 UTC), first fire 14:35Z. Unit
  `/etc/systemd/system/star-knowledge-offload.service`, drop-in `.service.d/laptop.conf` (worker URL).
- Behaviour per hour: nothing pending -> a one-second no-op. Small delta -> embedded on the laptop at any time. Bulk (more
  than 3000) -> only 00:00-08:00 Chicago, in 55-minute runs. Laptop off or asleep -> logged, exit 0, tried again next hour.
- The nightly refresh still embeds up to 3000 new texts itself on brain 1's CPU (1.5/s, about 33 min at the cap); with the
  laptop up, lowering STAR_KB_REFRESH_EMBED_LIMIT (drop-in embed-limit.conf) to about 300 would send everything bigger than
  the usual daily delta (about 25 texts) to the laptop instead. Not done: if the laptop is off, nothing would be embedded for
  that day, and the vector search would miss those chunks until it is back.
- The laptop's own models unload after 300 s idle (sleep-idle-seconds), so the GPU is free again soon after a run.

## Undo
`lxc exec starai -- systemctl disable --now star-knowledge-offload.timer` (then `rm /etc/systemd/system/star-knowledge-offload.*
and -offload.service.d/laptop.conf`, `daemon-reload`, `rm /opt/star/secrets/laptop_gpu_embed_key`). Code: copy
/opt/star/knowledge/backups/20261025-laptop-embed/{offload.py,__main__.py} back over /opt/star/knowledge/app/starkb/. Nothing was
changed on the laptop. The index was not modified by this item.

## Open
- Laptop ssh (port 22) was unreachable from the PC all afternoon while :8090 answered; not needed here, but
  `laptop-ctl.cmd` (ssh) does not work until it is back. Probably the laptop's network profile or sshd; owner's machine.
- Deploy: after this PR is merged into star/next, a full deploy.sh run brings the repo copy of the two units (identical files)
  and the same code; it must not overwrite anything with an older client.py (the live one is older than star/next's).
