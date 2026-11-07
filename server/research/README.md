# STAR research watch list (server side)

A nightly job in the `starai` container on STAR Server 1 that keeps STAR's research memory current before anyone asks:

```
star-research-watch.timer (08:20 UTC) -> python -m star.research_store poll    (watched pages -> snapshots)
                                      -> python -m star.research_store recheck (stored facts: quote still on the page?)
/opt/star/research/research-store.sqlite3 <- read-only -- star-search-gateway GET /watched (STAR Server key)
                                                           -> desktop Team research mirrors it every 6 h
```

| Piece | Where |
|---|---|
| Code | `/opt/star/research/current` -> `releases/<git sha>` (`star/` from git HEAD), `previous` kept for rollback |
| venv | `/opt/star/research/venv` (httpx only) |
| Store | `/opt/star/research/research-store.sqlite3` (owner `star`; facts + page snapshots) |
| Units | `star-research-watch.service` (oneshot, user `star`, Nice 15, 512 MB) + `.timer` |

Watch list: `star/research_store.py` `DEFAULT_WATCH` (Roblox release notes, advancing to the next number by itself;
DevForum release notes; Godot, Blender, Python, Rust, Go, Node, Luau releases; Minecraft changelogs and Mojang's
Java/Bedrock patch-note feeds). Polite by construction: one page at a time with a 2 s pause, robots.txt obeyed
(RFC 9309), a 429 stops that host for the run, and a page that answers 401/403 or is disallowed is left alone for 30
days. No sign-ins, no CAPTCHA or paywall work-arounds. Page text is untrusted data; it only ever reaches a model inside
the defanged research evidence frame.

```bash
STAR_SERVER_SSH=<user>@<server> bash server/research/deploy.sh install    # code + venv + timer (no poll)
STAR_SERVER_SSH=<user>@<server> bash server/research/deploy.sh run        # one poll now
STAR_SERVER_SSH=<user>@<server> bash server/research/deploy.sh status
STAR_SERVER_SSH=<user>@<server> bash server/research/deploy.sh rollback   # current <-> previous
STAR_SERVER_SSH=<user>@<server> bash server/research/deploy.sh remove     # units off; the store is kept
```
