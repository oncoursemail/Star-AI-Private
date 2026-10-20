# Free API control center (#407) - slice 1

Branch `star/free-api-center-20261020`, PR to `star/next`, "Refs #407".

Done: `star/free_api_center.py`, a pure library (no network, no key reads, no settings change):
- `CATALOG`: source-linked rows (Groq, OpenRouter, Gemini, Cerebras, Cloudflare Workers AI, HF Inference Providers,
  Brave, Tavily) with `free` kind, `privacy` label, notes and a `withdrawn` flag that fails closed. Values are what the
  linked pages said when the row was written, not verified live by code; the live headers are the truth for quotas.
- `parse_rate_headers()`: Groq/OpenAI `x-ratelimit-*-requests/tokens` (durations like `2m59.56s`), OpenRouter
  `X-RateLimit-Limit/Remaining/Reset` (epoch ms), `Retry-After` (seconds or HTTP date). Unparsable -> None.
- `QuotaBook`: per-provider state from real responses only: 429 blocks for Retry-After/reset (exponential 2..300 s
  without a header, reset by the next success), 5xx blocks 5 s and shows the status, `remaining == 0` = exhausted
  until reset. No key or account cycling exists.
- `route()`: local by default; a cloud provider only when opted in + key configured + free-tier offer (else needs an
  explicit `allow_spend` entry) + quota ok; `private=True` always local; a blocked provider falls back to local, never
  to another cloud. `status()` rows for a UI, no key material. `redact()` for key shapes in errors.
- Tests: `tests/test_free_api_center.py` (12, fake headers only).

Left of #407: wire `note_response`/`route` into the real client path (`star/providers.py` + chat), a Settings
section and React view for `status()`, hosted-output classification, live verification of each catalog row by a
human (dates in the row), packaged Windows acceptance.
