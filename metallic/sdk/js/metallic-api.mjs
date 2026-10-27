// Metallic API v1 client for JavaScript (browsers and Node 18+, no dependencies).
//   import { MetallicApi, verifyWebhook } from "./metallic-api.mjs";
//   const api = new MetallicApi({ baseUrl: "https://metallic-api.local:8476", token });
//   const { games } = await api.listGames();
// Errors throw MetallicApiError {status, code, text, retryAfter}. Never ship a server key (msk_...) to a browser.
// GENERATED from metallic/metallic/api/openapi.json by `python -m metallic.api.sdkgen`. Do not edit by hand.

export const VERSION = "1.0.0";

export class MetallicApiError extends Error {
  constructor(status, code, text, retryAfter) {
    super(`${status} ${code}: ${text}`);
    this.status = status; this.code = code; this.text = text; this.retryAfter = retryAfter;
  }
}

const enc = new TextEncoder();

/** True when the Metallic-Signature header matches the raw body (string or Uint8Array) and is fresh. */
export async function verifyWebhook(secret, signatureHeader, body, { tolerance = 300, now } = {}) {
  const parts = Object.fromEntries(String(signatureHeader).split(",").map((p) => p.split("=", 2)));
  const t = Number.parseInt(parts.t, 10);
  if (!Number.isFinite(t) || !parts.v1) return false;
  const nowS = now ?? Date.now() / 1000;
  if (Math.abs(nowS - t) > tolerance) return false;
  const raw = typeof body === "string" ? enc.encode(body) : body;
  const msg = new Uint8Array([...enc.encode(`${t}.`), ...raw]);
  const key = await globalThis.crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = Array.from(new Uint8Array(await globalThis.crypto.subtle.sign("HMAC", key, msg)),
    (b) => b.toString(16).padStart(2, "0")).join("");
  if (mac.length !== parts.v1.length) return false;
  let diff = 0;
  for (let i = 0; i < mac.length; i++) diff |= mac.charCodeAt(i) ^ parts.v1.charCodeAt(i);
  return diff === 0;
}

export class MetallicApi {
  constructor({ baseUrl, token = null, fetch: fetchImpl = globalThis.fetch.bind(globalThis) }) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = token;
    this.fetch = fetchImpl;
  }

  async request(method, path, { body, query } = {}) {
    const qs = new URLSearchParams(Object.entries(query || {}).filter(([, v]) => v !== undefined && v !== null));
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    let res;
    try {
      res = await this.fetch(this.baseUrl + path + (qs.toString() ? `?${qs}` : ""), {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (err) {
      throw new MetallicApiError(0, "unreachable", `Cannot reach the Metallic API (${err?.name || "error"}).`);
    }
    const text = await res.text();
    let obj = {};
    try { obj = text ? JSON.parse(text) : {}; } catch { obj = {}; }
    if (!res.ok) {
      const ra = res.headers.get("Retry-After");
      throw new MetallicApiError(res.status, obj.error || "error", obj.text || "Request failed.", ra ? Number(ra) : null);
    }
    return obj;
  }

  /** Service health. Public. */
  health() {
    return this.request("GET", `/health`);
  }

  /** This document. Public. */
  getOpenapi() {
    return this.request("GET", `/v1/openapi.json`);
  }

  /** Every scope and who may hold it. Public. */
  listScopes() {
    return this.request("GET", `/v1/scopes`);
  }

  /** Make a scoped token from a sign-in token. Public. */
  exchangeToken(body) {
    return this.request("POST", `/v1/oauth/token`, { body });
  }

  /** Revoke a scoped token. Public. */
  revokeToken(body) {
    return this.request("POST", `/v1/oauth/revoke`, { body });
  }

  /** Your profile. Needs sign-in [profile:read]. */
  getMe() {
    return this.request("GET", `/v1/me`);
  }

  /** Change your display name. Needs sign-in [profile:write]. */
  updateMe(body) {
    return this.request("PATCH", `/v1/me`, { body });
  }

  /** Friends and friend requests. Needs sign-in [friends:read]. */
  listFriends() {
    return this.request("GET", `/v1/friends`);
  }

  /** Ask a player to be friends. Needs sign-in [friends:write]. */
  sendFriendRequest(body) {
    return this.request("POST", `/v1/friends/requests`, { body });
  }

  /** Accept a friend request (sends friend.added). Needs sign-in [friends:write]. */
  acceptFriendRequest(username) {
    return this.request("POST", `/v1/friends/requests/${encodeURIComponent(username)}/accept`);
  }

  /** Decline an incoming or cancel an outgoing request. Needs sign-in [friends:write]. */
  declineFriendRequest(username) {
    return this.request("POST", `/v1/friends/requests/${encodeURIComponent(username)}/decline`);
  }

  /** Remove a friend. Needs sign-in [friends:write]. */
  removeFriend(username) {
    return this.request("DELETE", `/v1/friends/${encodeURIComponent(username)}`);
  }

  /** What your friends are doing. Needs sign-in [presence:read]. */
  listPresence() {
    return this.request("GET", `/v1/presence`);
  }

  /** Set your presence. Needs sign-in [presence:write]. */
  setPresence(body) {
    return this.request("PUT", `/v1/me/presence`, { body });
  }

  /** Your open game invites. Needs sign-in [invites:read]. */
  listInvites() {
    return this.request("GET", `/v1/invites`);
  }

  /** Invite a friend to a game. Needs sign-in [invites:write]. */
  sendInvite(body) {
    return this.request("POST", `/v1/invites`, { body });
  }

  /** Accept an invite. Needs sign-in [invites:write]. */
  acceptInvite(invite_id) {
    return this.request("POST", `/v1/invites/${encodeURIComponent(invite_id)}/accept`);
  }

  /** Decline an invite. Needs sign-in [invites:write]. */
  declineInvite(invite_id) {
    return this.request("POST", `/v1/invites/${encodeURIComponent(invite_id)}/decline`);
  }

  /** News posts. Public. */
  listNews({ game, limit } = {}) {
    return this.request("GET", `/v1/news`, { query: { game, limit } });
  }

  /** RC, MC, RB and PX status. Public. */
  listGames() {
    return this.request("GET", `/v1/games`);
  }

  /** One game's status. Public. */
  getGame(game) {
    return this.request("GET", `/v1/games/${encodeURIComponent(game)}`);
  }

  /** Release channels. Public. */
  listReleases() {
    return this.request("GET", `/v1/releases`);
  }

  /** A verified release channel. Public. */
  getRelease(channel) {
    return this.request("GET", `/v1/releases/${encodeURIComponent(channel)}`);
  }

  /** PX progress (public view). Public. */
  getProgress() {
    return this.request("GET", `/v1/progress`);
  }

  /** One project's progress. Public. */
  getProjectProgress(project) {
    return this.request("GET", `/v1/progress/${encodeURIComponent(project)}`);
  }

  /** Litha and STAR status (read-only). Public. */
  getProjectStatus() {
    return this.request("GET", `/v1/projects/status`);
  }

  /** Report a live game server. Needs server key [servers:write]. */
  serverHeartbeat(body) {
    return this.request("POST", `/v1/servers/heartbeat`, { body });
  }

  /** Report a player joining or leaving (sends player.joined / player.left). Needs server key [servers:write]. */
  serverEvent(body) {
    return this.request("POST", `/v1/servers/events`, { body });
  }

  /** Check a player's Metallic sign-in token. Needs server key [players:read]. */
  verifyPlayer(body) {
    return this.request("POST", `/v1/players/verify`, { body });
  }

  /** Your webhooks. Needs server key [webhooks:manage] or sign-in [webhooks:manage]. */
  listWebhooks() {
    return this.request("GET", `/v1/webhooks`);
  }

  /** Add a webhook (the secret is shown once). Needs server key [webhooks:manage] or sign-in [webhooks:manage]. */
  createWebhook(body) {
    return this.request("POST", `/v1/webhooks`, { body });
  }

  /** Delete a webhook. Needs server key [webhooks:manage] or sign-in [webhooks:manage]. */
  deleteWebhook(webhook_id) {
    return this.request("DELETE", `/v1/webhooks/${encodeURIComponent(webhook_id)}`);
  }

  /** Delivery log (newest first). Needs server key [webhooks:manage] or sign-in [webhooks:manage]. */
  listDeliveries(webhook_id, { limit } = {}) {
    return this.request("GET", `/v1/webhooks/${encodeURIComponent(webhook_id)}/deliveries`, { query: { limit } });
  }

  /** Send a signed `ping` event. Needs server key [webhooks:manage] or sign-in [webhooks:manage]. */
  pingWebhook(webhook_id) {
    return this.request("POST", `/v1/webhooks/${encodeURIComponent(webhook_id)}/ping`);
  }

  /** Server keys. Needs sign-in [keys:admin]. */
  listKeys() {
    return this.request("GET", `/v1/keys`);
  }

  /** Create a server key (the secret is shown once). Needs sign-in [keys:admin]. */
  createKey(body) {
    return this.request("POST", `/v1/keys`, { body });
  }

  /** Revoke a server key. Needs sign-in [keys:admin]. */
  revokeKey(key_id) {
    return this.request("DELETE", `/v1/keys/${encodeURIComponent(key_id)}`);
  }
}
