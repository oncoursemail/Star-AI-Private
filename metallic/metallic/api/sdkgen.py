"""Generate the thin SDKs (Python, JavaScript, Luau) and the static docs page from openapi.json.

    python -m metallic.api.sdkgen            # rewrite metallic/sdk/* and metallic/metallic/api/docs/index.html
    python -m metallic.api.sdkgen --check    # exit 1 when a generated file is out of date (the tests run this)

Only the method tables are generated; the small hand-written transport around them lives in the templates below.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
import re
import sys

from .spec import Spec

ROOT = Path(__file__).resolve().parents[2]          # metallic/
SDK = ROOT / "sdk"
DOCS = Path(__file__).with_name("docs") / "index.html"
HEADER = "GENERATED from metallic/metallic/api/openapi.json by `python -m metallic.api.sdkgen`. Do not edit by hand."


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _ops(spec: Spec, luau: bool = False):
    for op in spec.ops:
        kinds = {k for alt in op.security for k in alt}
        if luau and kinds and "serverKey" not in kinds:
            continue                    # Roblox servers hold server keys, never a player's sign-in
        path_params = [p["name"] for p in op.params if p["in"] == "path"]
        query = [p["name"] for p in op.params if p["in"] == "query"]
        yield op, path_params, query, op.body_schema is not None


# ---------------------------------------------------------------- Python
PY_HEAD = '''"""Metallic API v1 client for Python (standard library only, one file).

    from metallic_api import MetallicAPI, verify_webhook
    api = MetallicAPI("https://metallic-api.local:8476", token=sign_in_token_or_server_key, fingerprint="AB:CD:...")
    api.list_games(); api.list_friends(); api.server_heartbeat({{"game": "RC", "server_id": "eu-1", "players": 12}})

Errors raise MetallicAPIError(status, code, text, retry_after). Server keys belong on servers only.
''' + HEADER + '''
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import ssl
import time
import urllib.parse

__version__ = "{version}"


class MetallicAPIError(Exception):
    def __init__(self, status: int, code: str, text: str, retry_after: float | None = None):
        super().__init__(f"{{status}} {{code}}: {{text}}")
        self.status, self.code, self.text, self.retry_after = status, code, text, retry_after


def verify_webhook(secret: str, signature_header: str, body: bytes, tolerance: int = 300, now: float | None = None) -> bool:
    """True when `Metallic-Signature` matches the raw body and is at most `tolerance` seconds old."""
    try:
        parts = dict(p.split("=", 1) for p in signature_header.split(","))
        t = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs((time.time() if now is None else now) - t) > tolerance:
        return False
    mac = hmac.new(secret.encode(), str(t).encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, parts.get("v1", ""))


class MetallicAPI:
    def __init__(self, base_url: str, token: str | None = None, *, fingerprint: str | None = None,
                 cafile: str | None = None, timeout: float = 10.0, user_agent: str = "metallic-api-python"):
        u = urllib.parse.urlsplit(base_url)
        if u.scheme not in ("https", "http"):
            raise ValueError("base_url must be http(s)://host:port")
        self.scheme, self.host, self.port = u.scheme, u.hostname, u.port
        self.prefix = u.path.rstrip("/")
        self.token, self.timeout, self.user_agent = token, timeout, f"{{user_agent}}/{{__version__}}"
        self.fingerprint = fingerprint.replace(":", "").lower() if fingerprint else None
        self.cafile = cafile

    def _conn(self) -> http.client.HTTPConnection:
        if self.scheme == "http":
            return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        if self.fingerprint:
            ctx = ssl.create_default_context()
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE   # identity = pinned fingerprint below
        else:
            ctx = ssl.create_default_context(cafile=self.cafile)
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=ctx)
        if self.fingerprint:
            conn.connect()
            if hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest() != self.fingerprint:
                conn.close()
                raise MetallicAPIError(0, "bad_certificate", "The server certificate does not match the pinned one.")
        return conn

    def request(self, method: str, path: str, body: dict | None = None, query: dict | None = None) -> dict:
        q = {{k: v for k, v in (query or {{}}).items() if v is not None}}
        url = self.prefix + path + (("?" + urllib.parse.urlencode(q)) if q else "")
        headers = {{"Accept": "application/json", "User-Agent": self.user_agent}}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        try:
            conn = self._conn()
            try:
                conn.request(method, url, data, headers)
                resp = conn.getresponse()
                raw = resp.read()
            finally:
                conn.close()
        except (OSError, http.client.HTTPException) as exc:
            raise MetallicAPIError(0, "unreachable", f"Cannot reach the Metallic API ({{type(exc).__name__}}).") from exc
        try:
            obj = json.loads(raw) if raw else {{}}
        except ValueError:
            obj = {{}}
        if resp.status >= 400:
            ra = resp.getheader("Retry-After")
            raise MetallicAPIError(resp.status, obj.get("error", "error"), obj.get("text", "Request failed."),
                                   float(ra) if ra else None)
        return obj
'''


def gen_python(spec: Spec) -> str:
    out = [PY_HEAD.format(version=spec.doc["info"]["version"])]
    for op, pp, query, has_body in _ops(spec):
        args = ["self", *pp] + (["body: dict"] if has_body else []) + (["*"] + [f"{q}=None" for q in query] if query else [])
        path = op.path
        for p in pp:
            path = path.replace("{" + p + "}", "{urllib.parse.quote(str(" + p + "), safe='')}")
        call = f'self.request("{op.method}", {"f" if pp else ""}"{path}"' + (", body" if has_body else ", None") + \
            (", {" + ", ".join(f'"{q}": {q}' for q in query) + "}" if query else "") + ")"
        doc = op.raw.get("summary", "")
        scopes = _scopes_text(op)
        out.append(f"\n    def {snake(op.op_id)}({', '.join(args)}) -> dict:\n"
                   f'        """{doc}. {scopes}"""\n        return {call}\n')
    return "".join(out)


def _scopes_text(op) -> str:
    if not op.security:
        return "Public."
    alts = [f"{'server key' if s == 'serverKey' else 'sign-in'} [{' '.join(sc)}]" for a in op.security for s, sc in a.items()]
    return "Needs " + " or ".join(alts) + "."


# ---------------------------------------------------------------- JavaScript
JS_HEAD = '''// Metallic API v1 client for JavaScript (browsers and Node 18+, no dependencies).
//   import {{ MetallicApi, verifyWebhook }} from "./metallic-api.mjs";
//   const api = new MetallicApi({{ baseUrl: "https://metallic-api.local:8476", token }});
//   const {{ games }} = await api.listGames();
// Errors throw MetallicApiError {{status, code, text, retryAfter}}. Never ship a server key (msk_...) to a browser.
// ''' + HEADER + '''

export const VERSION = "{version}";

export class MetallicApiError extends Error {{
  constructor(status, code, text, retryAfter) {{
    super(`${{status}} ${{code}}: ${{text}}`);
    this.status = status; this.code = code; this.text = text; this.retryAfter = retryAfter;
  }}
}}

const enc = new TextEncoder();

/** True when the Metallic-Signature header matches the raw body (string or Uint8Array) and is fresh. */
export async function verifyWebhook(secret, signatureHeader, body, {{ tolerance = 300, now }} = {{}}) {{
  const parts = Object.fromEntries(String(signatureHeader).split(",").map((p) => p.split("=", 2)));
  const t = Number.parseInt(parts.t, 10);
  if (!Number.isFinite(t) || !parts.v1) return false;
  const nowS = now ?? Date.now() / 1000;
  if (Math.abs(nowS - t) > tolerance) return false;
  const raw = typeof body === "string" ? enc.encode(body) : body;
  const msg = new Uint8Array([...enc.encode(`${{t}}.`), ...raw]);
  const key = await globalThis.crypto.subtle.importKey("raw", enc.encode(secret), {{ name: "HMAC", hash: "SHA-256" }}, false, ["sign"]);
  const mac = Array.from(new Uint8Array(await globalThis.crypto.subtle.sign("HMAC", key, msg)),
    (b) => b.toString(16).padStart(2, "0")).join("");
  if (mac.length !== parts.v1.length) return false;
  let diff = 0;
  for (let i = 0; i < mac.length; i++) diff |= mac.charCodeAt(i) ^ parts.v1.charCodeAt(i);
  return diff === 0;
}}

export class MetallicApi {{
  constructor({{ baseUrl, token = null, fetch: fetchImpl = globalThis.fetch.bind(globalThis) }}) {{
    this.baseUrl = baseUrl.replace(/\\/$/, "");
    this.token = token;
    this.fetch = fetchImpl;
  }}

  async request(method, path, {{ body, query }} = {{}}) {{
    const qs = new URLSearchParams(Object.entries(query || {{}}).filter(([, v]) => v !== undefined && v !== null));
    const headers = {{ Accept: "application/json" }};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (this.token) headers.Authorization = `Bearer ${{this.token}}`;
    let res;
    try {{
      res = await this.fetch(this.baseUrl + path + (qs.toString() ? `?${{qs}}` : ""), {{
        method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      }});
    }} catch (err) {{
      throw new MetallicApiError(0, "unreachable", `Cannot reach the Metallic API (${{err?.name || "error"}}).`);
    }}
    const text = await res.text();
    let obj = {{}};
    try {{ obj = text ? JSON.parse(text) : {{}}; }} catch {{ obj = {{}}; }}
    if (!res.ok) {{
      const ra = res.headers.get("Retry-After");
      throw new MetallicApiError(res.status, obj.error || "error", obj.text || "Request failed.", ra ? Number(ra) : null);
    }}
    return obj;
  }}
'''


def gen_js(spec: Spec) -> str:
    out = [JS_HEAD.format(version=spec.doc["info"]["version"])]
    for op, pp, query, has_body in _ops(spec):
        args = [*pp] + (["body"] if has_body else []) + (["{ " + ", ".join(query) + " } = {}"] if query else [])
        path = op.path
        for p in pp:
            path = path.replace("{" + p + "}", "${encodeURIComponent(" + p + ")}")
        opts = []
        if has_body:
            opts.append("body")
        if query:
            opts.append("query: { " + ", ".join(query) + " }")
        out.append(f"\n  /** {op.raw.get('summary', '')}. {_scopes_text(op)} */\n"
                   f"  {op.op_id}({', '.join(args)}) {{\n"
                   f"    return this.request(\"{op.method}\", `{path}`" + (", { " + ", ".join(opts) + " }" if opts else "") +
                   ");\n  }\n")
    out.append("}\n")
    return "".join(out)


# ---------------------------------------------------------------- Luau
LUAU_HEAD = '''--!strict
-- Metallic API v1 client for Roblox game servers (HttpService). SERVER ONLY.
--
--   local MetallicApi = require(game:GetService("ServerScriptService").MetallicApi)
--   local api = MetallicApi.new({{ baseUrl = "https://metallic-api.example:8476", secretName = "metallic_api_key" }})
--   local ok, res = api:serverHeartbeat({{ game = "RB", server_id = game.JobId, players = #game.Players:GetPlayers() }})
--
-- Key handling: store the server key (msk_...) in the experience's secrets (Creator Hub > Secrets) and name it
-- here; HttpService:GetSecret returns a Secret that can only be sent in a request header, never read or printed.
-- Put this module in ServerScriptService or ServerStorage (clients cannot see those); it refuses to run on a client.
-- Every method returns (ok: boolean, result: table). On failure result = {{ status, error, text, retryAfter }}.
-- ''' + HEADER + '''

local HttpService = game:GetService("HttpService")
local RunService = game:GetService("RunService")

local MetallicApi = {{}}
MetallicApi.__index = MetallicApi
MetallicApi.VERSION = "{version}"

export type Config = {{ baseUrl: string, secretName: string?, key: any? }}

function MetallicApi.new(config: Config)
	assert(RunService:IsServer(), "MetallicApi is server-only: never give a server key to a client")
	assert(type(config.baseUrl) == "string", "baseUrl is required")
	local key = config.key
	if key == nil and config.secretName then
		key = HttpService:GetSecret(config.secretName)
	end
	local self = setmetatable({{}}, MetallicApi)
	self._base = string.gsub(config.baseUrl, "/$", "")
	self._auth = nil
	if typeof(key) == "string" then
		self._auth = "Bearer " .. key -- plain strings only for Studio tests; use secretName in live games
	elseif key ~= nil then
		self._auth = key:AddPrefix("Bearer ")
	end
	return self
end

local function encode(s: string): string
	return HttpService:UrlEncode(s)
end

function MetallicApi:request(method: string, path: string, body: any?, query: {{ [string]: any }}?): (boolean, any)
	local url = self._base .. path
	if query then
		local parts = {{}}
		for k, v in query do
			if v ~= nil then
				table.insert(parts, encode(k) .. "=" .. encode(tostring(v)))
			end
		end
		table.sort(parts)
		if #parts > 0 then
			url ..= "?" .. table.concat(parts, "&")
		end
	end
	local headers: {{ [string]: any }} = {{ Accept = "application/json" }}
	if self._auth ~= nil then
		headers.Authorization = self._auth
	end
	local req: {{ [string]: any }} = {{ Url = url, Method = method, Headers = headers }}
	if body ~= nil then
		headers["Content-Type"] = "application/json"
		req.Body = HttpService:JSONEncode(body)
	end
	local sent, res = pcall(function()
		return HttpService:RequestAsync(req)
	end)
	if not sent then
		return false, {{ status = 0, error = "unreachable", text = tostring(res) }}
	end
	local data = {{}}
	if res.Body and #res.Body > 0 then
		local parsed, obj = pcall(function()
			return HttpService:JSONDecode(res.Body)
		end)
		if parsed then
			data = obj
		end
	end
	if res.StatusCode >= 400 then
		local ra = res.Headers and (res.Headers["retry-after"] or res.Headers["Retry-After"])
		return false, {{ status = res.StatusCode, error = data.error or "error", text = data.text or "Request failed.",
			retryAfter = ra and tonumber(ra) or nil }}
	end
	return true, data
end
'''


def gen_luau(spec: Spec) -> str:
    out = [LUAU_HEAD.format(version=spec.doc["info"]["version"])]
    for op, pp, query, has_body in _ops(spec, luau=True):
        args = ["self", *[f"{p}: string" for p in pp]] + (["body: { [string]: any }"] if has_body else []) + \
            (["query: { [string]: any }?"] if query else [])
        path = '"' + op.path + '"'
        for p in pp:
            path = path.replace("{" + p + "}", '" .. encode(' + p + ') .. "')
        path = path.replace(' .. ""', "")
        out.append(f"\n-- {op.raw.get('summary', '')}. {_scopes_text(op)}\n"
                   f"function MetallicApi:{op.op_id}({', '.join(args[1:]) if len(args) > 1 else ''}): (boolean, any)\n"
                   f"\treturn self:request(\"{op.method}\", {path}, {'body' if has_body else 'nil'}"
                   f"{', query' if query else ''})\nend\n")
    out.append("\nreturn MetallicApi\n")
    return "".join(out)


# ---------------------------------------------------------------- docs page
CSS = """
:root{--bg:#121216;--panel:#1a1a20;--line:#2c2c35;--ink:#e6e6ea;--ink2:#a9a9b4;--ink3:#7c7c88;--acc:#a58bff;
--get:#7fb4a2;--post:#a58bff;--del:#e08a8a;--put:#d6b46a;--code:#0e0e12}
@media (prefers-color-scheme: light){:root{--bg:#f4f4f7;--panel:#fff;--line:#dcdce3;--ink:#18181d;--ink2:#4a4a55;
--ink3:#6d6d78;--acc:#5b3fd1;--get:#2c6e5a;--post:#5b3fd1;--del:#a33a3a;--put:#7d5d12;--code:#f0f0f4}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,
"Segoe UI",sans-serif}a{color:var(--acc)}code,pre{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
font-size:13px}pre{background:var(--code);border:1px solid var(--line);border-radius:6px;padding:10px 12px;
overflow-x:auto}.wrap{display:grid;grid-template-columns:240px minmax(0,1fr);max-width:1180px;margin:0 auto}
nav{position:sticky;top:0;align-self:start;height:100vh;overflow-y:auto;padding:28px 16px;border-right:1px solid
var(--line)}nav a{display:block;color:var(--ink2);text-decoration:none;padding:3px 0;font-size:13px}nav a:hover,
nav a:focus-visible{color:var(--ink)}nav h4{margin:18px 0 6px;font-size:11px;letter-spacing:.08em;text-transform:
uppercase;color:var(--ink3)}nav h4 a{color:inherit;display:inline;padding:0;font-size:inherit}main{padding:28px 32px 80px;min-width:0}h1{font-size:28px;margin:0 0 4px}h2{font-size:20px;
margin:44px 0 12px;padding-top:12px;border-top:1px solid var(--line)}h3{font-size:16px;margin:0}.op{border:1px solid
var(--line);background:var(--panel);border-radius:8px;padding:16px 18px;margin:14px 0}.sig{display:flex;gap:10px;
align-items:baseline;flex-wrap:wrap}.m{font:600 12px ui-monospace,Consolas,monospace;padding:2px 7px;border-radius:4px;
border:1px solid currentColor}.GET{color:var(--get)}.POST{color:var(--post)}.DELETE{color:var(--del)}.PUT,.PATCH{color:
var(--put)}.path{font:600 14px ui-monospace,Consolas,monospace}.auth{font-size:12px;color:var(--ink2)}.muted{color:
var(--ink2)}table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}th,td{text-align:left;padding:5px 8px;
border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--ink3);font-weight:600}td:first-child code{white-space:nowrap}
td code{overflow-wrap:anywhere}
.req{color:var(--acc);font-size:11px}@media (max-width:760px){.wrap{grid-template-columns:1fr}nav{position:static;
height:auto;border-right:0;border-bottom:1px solid var(--line)}main{padding:20px 16px 60px}table{display:block;overflow-x:auto}nav a.o{display:none}nav{padding:16px}}
"""


def _type(spec: Spec, s: dict) -> str:
    s = spec.resolve(s)
    if "$ref" in s:
        return s["$ref"].rsplit("/", 1)[1]
    if "const" in s:
        return json.dumps(s["const"])
    if "enum" in s:
        return " | ".join(json.dumps(e) for e in s["enum"] if e not in ("",))
    t = s.get("type", "object")
    t = " | ".join(t) if isinstance(t, list) else t
    if t == "array" and "items" in s:
        it = s["items"]
        return (it["$ref"].rsplit("/", 1)[1] if "$ref" in it else _type(spec, it)) + "[]"
    return t


def _fields(spec: Spec, schema: dict) -> list[tuple[str, str, bool, str]]:
    s = spec.resolve(schema)
    props, req = {}, set(s.get("required", []))
    for sub in s.get("allOf", []):
        sub = spec.resolve(sub)
        props.update(sub.get("properties", {}))
        req |= set(sub.get("required", []))
    props.update(s.get("properties", {}))
    rows = []
    for name, p in props.items():
        notes = []
        rp = spec.resolve(p)
        for k in ("minLength", "maxLength", "minimum", "maximum", "pattern", "maxItems"):
            if k in rp:
                notes.append(f"{k} {rp[k]}")
        if rp.get("description"):
            notes.insert(0, rp["description"])
        rows.append((name, _type(spec, p), name in req, "; ".join(notes)))
    return rows


def _table(rows, head=("Field", "Type", "Notes")) -> str:
    if not rows:
        return ""
    body = "".join(f"<tr><td><code>{html.escape(n)}</code>{' <span class=req>required</span>' if r else ''}</td>"
                   f"<td><code>{html.escape(t)}</code></td><td>{_inline(x)}</td></tr>" for n, t, r, x in rows)
    return f"<table><thead><tr>{''.join(f'<th>{h}</th>' for h in head)}</tr></thead><tbody>{body}</tbody></table>"


def _inline(text: str) -> str:
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text))


def _md(text: str) -> str:
    return "".join(f"<p>{para}</p>" for para in _inline(text).split("\n\n"))


def gen_docs(spec: Spec) -> str:
    d = spec.doc
    tags = [t["name"] for t in d["tags"]]
    by_tag = {t: [o for o in spec.ops if (o.raw.get("tags") or ["content"])[0] == t] for t in tags}
    nav = ["<h4>Start</h4><a href='#auth'>Authentication</a><a href='#scopes'>Scopes</a><a href='#limits'>Rate limits</a>"
           "<a href='#minors'>Minors' privacy</a><a href='#errors'>Errors</a><a href='#webhooks'>Webhooks</a>"
           "<a href='#sdks'>SDKs</a>"]
    body = []
    for t in d["tags"]:
        nav.append(f"<h4><a href='#tag-{t['name']}'>{html.escape(t['name'])}</a></h4>" + "".join(
            f"<a class=o href='#{o.op_id}'>{html.escape(o.raw.get('summary', o.op_id))}</a>" for o in by_tag[t["name"]]))
    scopes = "".join(f"<tr><td><code>{html.escape(k)}</code></td><td>{html.escape(v['kind'])}</td>"
                     f"<td>{'yes' if v['minors'] else 'no'}</td><td>{html.escape(v['description'])}</td></tr>"
                     for k, v in spec.scopes.items())
    limits = "".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v['per_minute']))}</td>"
                     f"<td>{html.escape(str(v['burst']))}</td><td>{html.escape(v['key'])}</td></tr>"
                     for k, v in d["x-metallic-rate-limits"].items())
    schemes = d["components"]["securitySchemes"]
    body.append(f"""
<h1>{html.escape(d['info']['title'])} <span class=muted>v{html.escape(d['info']['version'])}</span></h1>
<p class=muted>{html.escape(d['info']['summary'])} Internal preview: outside developer access comes later.
The machine-readable document is <a href="/v1/openapi.json"><code>/v1/openapi.json</code></a> (OpenAPI 3.1).</p>
{_md(d['info']['description'])}
<h2 id=auth>Authentication</h2>
<p>Send <code>Authorization: Bearer &lt;token&gt;</code>. Three kinds of token:</p>
<table><thead><tr><th>Token</th><th>Who holds it</th><th>Scopes</th></tr></thead><tbody>
<tr><td>Metallic sign-in token (JWT)</td><td>The launcher and other first-party apps</td><td>{_inline(schemes['metallicUser']['description'])}</td></tr>
<tr><td>Scoped token <code>mtk_…</code></td><td>Apps acting for a player</td><td>Only what was granted at <a href="#exchangeToken">POST /v1/oauth/token</a>; at most 15 minutes.</td></tr>
<tr><td>Server key <code>msk_…</code></td><td>Game servers and backends</td><td>{_inline(schemes['serverKey']['description'])}</td></tr>
</tbody></table>
<pre>curl -X POST https://HOST:8476/v1/oauth/token -H "Content-Type: application/json" \\
  -d '{{"subject_token": "&lt;sign-in token&gt;", "scope": "friends:read presence:read"}}'</pre>
<h2 id=scopes>Scopes</h2>
<table><thead><tr><th>Scope</th><th>Kind</th><th>Minors may grant</th><th>Allows</th></tr></thead><tbody>{scopes}</tbody></table>
<h2 id=limits>Rate limits</h2>
<table><thead><tr><th>Caller</th><th>Per minute</th><th>Burst</th><th>Counted per</th></tr></thead><tbody>{limits}</tbody></table>
<p>Some endpoints have their own tighter bucket (token exchange: 10 per minute per IP). Over the limit: <code>429</code> with
<code>Retry-After</code>. Every response carries <code>RateLimit-Limit</code> and <code>RateLimit-Remaining</code>.</p>
<h2 id=minors>Minors' privacy</h2>
<p>Players under 18 are private by default. Accounts already limits who sees their presence and who may send them requests;
on top of that the API never hands a minor's username or display name to a server key or webhook (only an opaque account id
with <code>minor: true</code>), and scoped tokens for minors can only hold <code>profile:read</code>.</p>
<h2 id=errors>Errors</h2>
<pre>{{"ok": false, "error": "insufficient_scope", "text": "This token lacks the scope presence:write.", "scope": "presence:write"}}</pre>
<p><code>401</code> no or bad token, <code>403</code> wrong credential kind, missing scope or a privacy rule, <code>404</code>
unknown thing, <code>429</code> slow down, <code>502</code> accounts unreachable, <code>503</code> a release channel failed verification.</p>
<h2 id=webhooks>Webhooks</h2>
<p>Create one with <a href="#createWebhook">POST /v1/webhooks</a>; the <code>whsec_…</code> secret is shown once. Each delivery is a
POST with a JSON envelope <code>{{"id", "type", "created", "data"}}</code> and these headers:</p>
<pre>Metallic-Event: player.joined
Metallic-Delivery: dlv_…
Metallic-Signature: t=1793000000,v1=&lt;hex HMAC-SHA256(secret, "1793000000." + raw body)&gt;</pre>
<p>Check the signature on the raw body, refuse ones older than 5 minutes, answer any 2xx quickly, and de-duplicate on
<code>id</code>: failed deliveries are retried after 10 s, 1 min, 5 min, 30 min and 2 h, then marked failed. The delivery log is at
<a href="#listDeliveries">GET /v1/webhooks/{{id}}/deliveries</a>. Events: {', '.join(f'<code>{html.escape(e)}</code>' for e in d['webhooks'])}.</p>
<pre># Python
from metallic_api import verify_webhook
ok = verify_webhook(secret, request.headers["Metallic-Signature"], raw_body)</pre>
<h2 id=sdks>SDKs</h2>
<p>Thin clients generated from this document live in <code>metallic/sdk/</code>: <code>python/metallic_api.py</code> (standard library),
<code>js/metallic-api.mjs</code> (browsers and Node 18+), <code>luau/MetallicApi.luau</code> (Roblox servers; the key comes from
<code>HttpService:GetSecret</code> and the module refuses to run on a client). Each folder has examples.</p>""")
    for t in d["tags"]:
        body.append(f"<h2 id='tag-{t['name']}'>{html.escape(t['name'].title())}</h2><p class=muted>{html.escape(t['description'])}</p>")
        for o in by_tag[t["name"]]:
            params = [(p["name"], _type(spec, p["schema"]), bool(p.get("required")), p["in"]) for p in o.params]
            req = _fields(spec, o.body_schema) if o.body_schema else []
            resp = o.raw["responses"].get(str(o.success), {})
            rs = resp.get("content", {}).get("application/json", {}).get("schema")
            errors = [c for c in o.raw["responses"] if not c.startswith("2")]
            body.append(
                f"<section class=op id='{o.op_id}'><div class=sig><span class='m {o.method}'>{o.method}</span>"
                f"<span class=path>{html.escape(o.path)}</span><h3>{html.escape(o.raw.get('summary', ''))}</h3></div>"
                f"<p class=auth>{html.escape(_scopes_text(o))}"
                f"{' Rate: ' + str(o.rate['per_minute']) + '/min.' if o.rate else ''}</p>"
                f"{_md(o.raw['description']) if o.raw.get('description') else ''}"
                f"{'<h4>Parameters</h4>' + _table(params, ('Name', 'Type', 'In')) if params else ''}"
                f"{'<h4>Request body</h4>' + _table(req) if req else ''}"
                f"<h4>Response {o.success}</h4>{_table(_fields(spec, rs)) if rs else '<p class=muted>Empty.</p>'}"
                f"{'<p class=muted>Errors: ' + ', '.join(errors) + '</p>' if errors else ''}"
                f"<pre>{html.escape(_curl(o, spec))}</pre></section>")
    return ("<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
            "initial-scale=1'><title>Metallic API v1</title><meta name=generator content='metallic.api.sdkgen'>"
            f"<style>{CSS}</style></head><body><!-- {HEADER} --><div class=wrap><nav aria-label='API sections'>"
            f"{''.join(nav)}</nav><main>{''.join(body)}</main></div></body></html>\n")


def _curl(o, spec: Spec) -> str:
    path = re.sub(r"\{(\w+)\}", lambda m: m.group(1).upper(), o.path)
    line = f"curl -X {o.method} https://HOST:8476{path}"
    if o.security:
        kinds = {k for a in o.security for k in a}
        line += ' -H "Authorization: Bearer ' + ("$SERVER_KEY" if kinds == {"serverKey"} else "$TOKEN") + '"'
    if o.body_schema:
        sample = {n: _sample(spec, spec.resolve(o.body_schema), n) for n, _, r, _ in _fields(spec, o.body_schema) if r}
        line += " -H \"Content-Type: application/json\" -d '" + json.dumps(sample) + "'"
    return line


def _sample(spec: Spec, schema: dict, name: str):
    p = spec.resolve(schema.get("properties", {}).get(name, {}))
    for sub in schema.get("allOf", []):
        p = p or spec.resolve(spec.resolve(sub).get("properties", {}).get(name, {}))
    if "const" in p:
        return p["const"]
    if "enum" in p:
        return next(e for e in p["enum"] if e not in ("", None))
    t = p.get("type")
    t = t[0] if isinstance(t, list) else t
    if t == "integer":
        return p.get("minimum", 1) or 1
    if t == "array":
        it = spec.resolve(p.get("items", {}))
        return [next((e for e in it.get("enum", []) if e), "...")]
    return {"username": "sam", "server_id": "eu-1", "url": "https://example.com/hooks/metallic", "to": "sam",
            "target": "room-123", "name": "rc-server", "display_name": "Sam"}.get(name, "...")


def outputs(spec: Spec | None = None) -> dict[Path, str]:
    spec = spec or Spec()
    py = gen_python(spec)
    return {SDK / "python" / "metallic_api.py": py, ROOT.parent / "launcher" / "metallic_api.py": py,
            SDK / "js" / "metallic-api.mjs": gen_js(spec),
            SDK / "luau" / "MetallicApi.luau": gen_luau(spec), DOCS: gen_docs(spec)}


def main(argv: list[str]) -> int:
    stale = []
    for path, text in outputs().items():
        if "--check" in argv:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(str(path))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path}")
    if stale:
        print("out of date (run python -m metallic.api.sdkgen):\n  " + "\n  ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
