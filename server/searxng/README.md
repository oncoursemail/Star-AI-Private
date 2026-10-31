# STAR search: self-hosted SearXNG (no paid search key)

STAR's web search (`star/web_search.py`) uses Brave or Tavily when the owner has a key. Without one it uses
this: the official SearXNG metasearch engine (github.com/searxng/searxng), installed inside the STAR Server's
`starai` LXD container, behind a small gateway.

```
STAR on the PC --(private network, Bearer <STAR Server key>)--> star-search-gateway :8093 (container)
                                                                  |  rate limit 30/min, burst 10, 4 at once
                                                                  v
                                                       SearXNG 127.0.0.1:8888 (container only)
```

| Piece | Where | Notes |
|---|---|---|
| SearXNG source | `/usr/local/searxng/searxng-src` (git clone, `VERSION` file next to it) | user `searxng`, venv `searx-pyenv`, served by granian |
| Settings | `/etc/searxng/settings.yml` (from `settings.yml`; random `secret_key` kept across installs) | JSON API on, limiter off (the gateway limits), safe search 1 |
| `searxng.service` | binds **127.0.0.1:8888** only | Nice 10, CPUWeight 20, MemoryMax 1G, hardened |
| Gateway | `/opt/star/search-gateway/gateway.py`, `star-search-gateway.service` on :8093 | stdlib only; same key file as the brain (`/opt/star/secrets/api_keys`); `GET /health` (no key), `GET /search?q=&n=&time_range=&categories=`, `GET /watched?since=` (watch-list snapshots from `/opt/star/research`, read-only; see server/research) |

The desktop app and the Discord bot find the gateway automatically: the STAR Server's address on port 8093
(`Settings.search_endpoint` overrides it; `off` disables it). The key is the STAR Server key the app already has.

## Install / update

From the PC (Git Bash), with the server's ssh login in an environment variable (it is not written in the repo):

```bash
STAR_SERVER_SSH=<user>@<server> bash server/searxng/deploy.sh                    # install or re-apply
STAR_SERVER_SSH=<user>@<server> SEARXNG_UPDATE=1 bash server/searxng/deploy.sh   # also pull a newer SearXNG
```

`install.sh` never touches star-brain, star-knowledge, `/opt/star/config` or the models. Safe to run while the
brain is busy (the installs run at nice 19).

## Check

Inside the container: `systemctl status searxng star-search-gateway`, `curl -s 127.0.0.1:8093/health`,
`curl -s '127.0.0.1:8888/search?q=roblox&format=json' | head -c 300`.

## Backup and rollback

- Every install keeps the previous `/etc/searxng/settings.yml.bak-<UTC stamp>` and
  `/opt/star/search-gateway/gateway.py.bak-<UTC stamp>`; an update records the previous SearXNG commit in
  `/usr/local/searxng/previous-commit.txt`.
- Roll back settings or gateway: copy the `.bak-<stamp>` file over the live one, then
  `systemctl restart searxng star-search-gateway`.
- Roll back SearXNG itself: `runuser -u searxng -- git -C /usr/local/searxng/searxng-src checkout <commit>`
  (from `previous-commit.txt`), then `systemctl restart searxng`.
- Remove everything: `systemctl disable --now searxng star-search-gateway`,
  `rm /etc/systemd/system/searxng.service /etc/systemd/system/star-search-gateway.service`,
  `rm -rf /usr/local/searxng /etc/searxng /opt/star/search-gateway`, `userdel searxng`. STAR then falls back to
  "web search needs STAR Server search or a Brave/Tavily key" (nothing else breaks).

## Behaviour notes (2026-10-13)

- Some upstream engines answer CAPTCHAs or 429 to a datacenter-like address (seen: DuckDuckGo CAPTCHA, Brave
  429); SearXNG skips them and the others answer (Google CSE, Bing News, Wikipedia...). `unresponsive_engines` in a
  direct SearXNG reply shows which.
- Questions about news/"latest"/today are sent with `categories=news&time_range=week` first, then without.
