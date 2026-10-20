# obsidian-graphify-20261020 (Claude sub-agent, board #202): do Obsidian and Graphify help STAR?

Owner question 2026-10-20: does STAR have Obsidian and Graphify, and would they help? Branch
`star/obsidian-graphify-20261020` (worktree `worktrees/obsidian-graphify`, from origin/star/next e2371e83), PR into star/next.

## Verdict (short)

- **Yes, useful, but the useful part is the team's notes in a searchable form, not a graph picture.** STAR's
  knowledge index (Roblox docs, Luau, textbooks) did not contain a single note of ours: 0 of 30 questions about our own
  work were answered by it (live service, measured). With the brain vault reachable, 29 of 30 are in the top 5.
- Cost is small: about 430 tokens of tool schema only when a team question is asked, 500-1,600 tokens per tool result,
  0.2 s per vault search (2-3 s once after a change), 3.5-7 ms per private-corpus search plus the query embedding
  (about 0.1 s). RAM: 31 MB for the note index, 52 MB for the code graph. Build: 40 s notes + code map (2.5 min with a
  fresh Graphify run, low priority, nightly).
- **Install Obsidian? Optional, yes if you like to read the notes yourself.** It is free, only a viewer: STAR does not
  need it (the bridge reads plain Markdown files). It gives you a graph view, backlinks and full-text search over
  `vault\STAR-brain` (open that folder as a vault) and over `vault\STAR-brain-graph` (Graphify's own export, one note
  per code symbol, for exploring). Do not let it sync or publish the folder: it is private.
- Not worth doing: feeding Graphify's raw `export obsidian` (22,286 notes, 60 MB) to retrieval. It is noise (one note per
  docstring sentence); the vault uses a file-level map instead.

## What works today on star/next (measured 2026-10-20)

| piece | state |
|---|---|
| `star/obsidian_bridge.py` (read-only vault: search, read, list, links) | wired into `star/intelligence.py`, **opt-in** (`obsidian_enabled` false by default, vault path in Settings). Tests pass. Inert before today: no vault existed and Obsidian is not installed (the bridge does not need it). |
| `star/graphify_bridge.py` (graph.json: query, explain, path, stats) | wired, needs `graphify-out/graph.json` inside the selected workspace and `graphify_enabled`. **Broken on STAR's own repo**: the fresh graph (1,563 files, 21,503 nodes, 54,336 edges) is 29 MB and the adapter refused anything over 20 MB (`available() == False`). Fixed here (64 MB / 100k nodes / 300k edges). |
| Graphify CLI launcher `~/.local/bin/graphify.exe` | **was broken** (uv trampoline pointing at the deleted voice-lab Python). Fixed: `graphifyy==0.9.69` pinned in `~/.star/graphify-venv` (uv-managed Python 3.14.0), launchers copied to `~/.local/bin` (old ones kept as `*.broken-20261020`). Every run prints a harmless "skill is from 0.9.92" warning from the installed skill. |
| Knowledge service (`server/knowledge`) | indexes only open-licensed sources; team notes are not in it (needs the new private corpus below). |
| Tests run | `tests/test_intelligence.py`, `test_shared_brain_store.py`, `test_shared_brain_variants.py`, `test_data_knowledge_quality.py`: 81 passed, 5 skipped (before my changes). |
| `graphify extract . --code-only` | 2 min 16 s, 39 files with Luau syntax warnings (benchmark Luau files), no LLM, no network. Adapter on the real graph: load 0.4 s, query 40-80 ms. |

## What I built

1. `star/brain_vault.py` (`python -m star.brain_vault build|status`): generates the vault.
   - `notes/<group>/` from docs/agents, docs/research, docs/*.md, docs/release/**, STATE.md, OWNER-TODO.md, AGENTS.md,
     CLAUDE.md (414 notes); `daily/<date>.md` ("what changed on that day": notes by git commit date, plus commit
     subjects; 12 days); `code/<dir>/<file>_<ext>.md` (671 source files: docstring, definitions with line numbers, imports,
     imported-by, tested-by as wiki-links) and `_overview.md` per folder; `Home.md`; `.brain-vault.json` manifest.
   - Redaction of every note: private network addresses (10/8, 172.16/12, 192.168/16, 100.64/10, link-local), server user
     names and the OS account, keys and tokens (same patterns as `star commit`), e-mail addresses, home-folder paths. Placeholders
     are `[private-ip]`, `[user]`, `[email]`, `[redacted-key]` (square brackets, so Obsidian does not hide them as HTML).
     Today's build: 82 addresses, 184 user names, 20 e-mails replaced; `tools/star.py scan_line` finds nothing in the vault.
   - Safe regeneration: builds into `<vault>.building`, replaces only `notes/ daily/ code/ Home.md`, never touches
     `.obsidian` or the owner's own folders; refuses a non-empty folder without the marker and any folder inside a Git
     checkout.
   - `--extract` runs Graphify first; `--raw-graph-dir` also runs `graphify export obsidian` into its own folder
     (22,286 notes, also redacted: 19 replacements).
2. `brain-vault.cmd` (workspace root, outside git): `brain-vault.cmd` full rebuild at low priority, `--no-graph` notes
   only. Reads from the detached worktree `worktrees/brain-vault-src` (fetches origin, uses origin/star/next, or this
   branch until the generator is merged). Scheduled task **"STAR brain vault"**, daily 04:30 local, log `vault\build.log`.
   Undo: `schtasks /delete /tn "STAR brain vault" /f`.
3. Obsidian bridge: opt-in as before (Settings > Obsidian vault > `C:\Users\alexi\Documents\starai\vault\STAR-brain`,
   tick the box; I did not touch the STAR profile). Changes: BM25-style ranking (stop words, inverse document frequency,
   name/title/heading boost, light stemming, underscore split, a cached term index that follows file changes) and one
   folder resolve per folder instead of per note (search 950 ms -> 220-290 ms). Brain vault only (marker file): team
   words such as night school, conductor, forge, metallic, priority proxy, "what did we change", "yesterday" switch the
   vault tools on without the word "notes" in the question; ordinary Roblox questions do not.
4. Graphify bridge: size limits raised for STAR's own graph; labels such as `priority_proxy.py` answer "priority proxy".
5. Private corpus in the knowledge service: `server/knowledge/starkb/private_corpus.py`, `python -m starkb --db <private.sqlite3>
   build-private --vault <vault>` (a second SQLite file, same schema, source `star-brain`, group `team`, licence PRIVATE,
   `public_bundle: false`), `serve.py`: `POST /search {"corpus": "private"}` answers from it when `STAR_KB_PRIVATE_DB` names the
   file (404 otherwise, 400 for any other value); a request without `corpus` never sees it. `KnowledgeClient.search(..., corpus="private")`.
   The nightly refresh rebuilds only the public file, so nothing of this can leak into a public bundle or be wiped by it.
6. Eval: `server/knowledge/eval/vault-questions.jsonl` (30 questions) and `scripts/brain_vault_eval.py`.

## Eval: recall@5 on 30 questions about our own notes

Questions were written on 2026-10-20 from the notes' opening sections before any search ran; each lists the notes that
contain the answer (checked by a text match on a fact string, not by a search engine). A hit on any listed note in the
top 5 counts. Vault of 414 notes + 671 code files (6,523 chunks, all embedded with star-embed-ft1).

| arm | recall@5 | recall@1 | MRR | median latency |
|---|---|---|---|---|
| live public knowledge index (no vault) | **0/30** | 0 | 0 | 16 ms (answers came from Roblox docs, Godot, Wikipedia) |
| Obsidian bridge, old ranking | 13/30 (43%) | 30% | 0.346 | 950 ms |
| Obsidian bridge, new ranking | 28/30 (93%) | 73% | 0.822 | 220 ms |
| private corpus, bm25 | 29/30 (97%) | 73% | 0.825 | 3.5 ms |
| private corpus, vector | 26/30 (87%) | 70% | 0.782 | 89 ms (query embedding 109 ms) |
| private corpus, hybrid | 29/30 (97%), 30/30 at 10 | 73% | 0.849 | 7 ms + the query embedding |

Misses: v28 ("what does the quality a b test compare": the note says "A/B" and the answer words are in a table) in every arm;
the bridge also misses v04. Caveats, honestly: 30 questions, written by the author of the vault, no held-out set and no
tuning on them (the ranker was written once, then measured once); plain BM25 is already near the ceiling, so the vector
and hybrid modes add a model call for no measured gain on this set (their value is paraphrased questions, which this
set has few of). Latencies of the knowledge service were measured on the PC against local files, not on brain 1.

## Cost

- Context: `star_obsidian_*` tool schemas 426 tokens, `star_graphify_*` 327 tokens (only when the prompt matches).
  One search result is about 500 tokens (5 hits with 260-character snippets), reading a note page about 1,600 tokens
  (cap 10,000 characters), a graph query about 740 tokens. The private corpus returns 4 passages of about 800 characters.
- Time: see the table; first vault search after a change 2-3 s (index rebuild), Graphify extract 2-2.5 min (cached
  afterwards), vault build 40 s, embedding of a first full private index 8.5 min on the shared PC GPU (12.8 chunks/s;
  on brain 1 it would be about 1.5 chunks/s = 72 min, so embed on the PC) and 19 changed chunks on the next day.
- RAM: 31 MB (note index), 52 MB (graph, peak 90 MB). Disk: 8.2 MB for the vault, 60 MB for the optional raw graph folder.

## Not done / next

- The private corpus is **not deployed** to brain 1 (a live server change; needs a quiet-lock window): copy the vault to the
  server, `starkb --db /opt/star/knowledge/data/private.sqlite3 build-private --vault <copy>`, `embed` with the PC GPU
  offload or accept bm25, then a systemd drop-in `STAR_KB_PRIVATE_DB=/opt/star/knowledge/data/private.sqlite3` for
  star-knowledge. Undo: remove the drop-in and the file.
- Nobody calls `corpus="private"` yet (the Discord Star agent, #199, is the natural first user: "what did we do today").
- The vault does not include `STAR_EXECUTION_LEDGER.md` (150 KB, mostly history) or `COLLAB/MESSAGES.md`.
- Dated notes only improve "what changed" questions when the notes themselves are dated; commit subjects fill the gap.
