// The collector's API. In the static preview build (VITE_SAMPLE=1) the same calls read a recorded snapshot instead,
// and admin actions explain that they do nothing there.
import type { Action, AuditRow, Range, SeriesResponse, SpeedHour, State } from "./types";

export class SignedOut extends Error {}

let csrf = "";
export const SAMPLE = import.meta.env.VITE_SAMPLE === "1";

type Sample = { state: State; series: Record<Range, SeriesResponse>; speed: SpeedHour[]; actions: Action[];
  audit: AuditRow[]; recorded: number };
let sample: Sample | null = null;

// The recorded snapshot exists only for the preview build (src/sample/ is not in git: it holds live data). Eager, so the
// preview is one file; in the normal build the folder is absent and this is an empty object.
const sampleFiles = import.meta.glob("./sample/sample.json", { eager: true, import: "default" });

async function loadSample(): Promise<Sample> {
  const data = SAMPLE ? sampleFiles["./sample/sample.json"] : undefined;
  if (!data) throw new Error("no recorded sample in src/sample/ (preview build only)");
  sample ??= data as Sample;
  return sample;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin", ...init,
    headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...(init?.headers ?? {}) } });
  if (res.status === 401) throw new SignedOut();
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.text || `HTTP ${res.status}`);
  return body as T;
}

export async function session(): Promise<boolean> {
  if (SAMPLE) return true;
  try {
    csrf = (await call<{ csrf: string }>("/api/session")).csrf;
    return true;
  } catch (e) {
    if (e instanceof SignedOut) return false;
    throw e;
  }
}

export async function login(token: string): Promise<void> {
  const res = await fetch("/api/login", { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.text || `HTTP ${res.status}`);
  csrf = body.csrf;
}

export async function logout(): Promise<void> {
  if (SAMPLE) return;
  await call("/api/logout", { method: "POST", body: "{}" });
  csrf = "";
}

export async function state(): Promise<State> {
  if (SAMPLE) return (await loadSample()).state;
  return call<State>("/api/state");
}

export async function series(keys: string[], range: Range): Promise<SeriesResponse> {
  if (SAMPLE) {
    const s = (await loadSample()).series[range];
    return { ...s, series: Object.fromEntries(keys.map((k) => [k, s.series[k] ?? []])) };
  }
  return call<SeriesResponse>(`/api/series?keys=${encodeURIComponent(keys.join(","))}&range=${range}`);
}

export async function speed(): Promise<SpeedHour[]> {
  if (SAMPLE) return (await loadSample()).speed;
  return (await call<{ hours: SpeedHour[] }>("/api/speed?days=7")).hours;
}

export async function actions(): Promise<Action[]> {
  if (SAMPLE) return (await loadSample()).actions;
  return (await call<{ actions: Action[] }>("/api/actions")).actions;
}

export async function audit(): Promise<AuditRow[]> {
  if (SAMPLE) return (await loadSample()).audit;
  return (await call<{ audit: AuditRow[] }>("/api/audit")).audit;
}

export async function runAction(id: string): Promise<{ ok: boolean; audit: number; text: string }> {
  if (SAMPLE) throw new Error("This is the static preview with recorded data: actions run only on the live collector.");
  return call("/api/actions/run", { method: "POST", body: JSON.stringify({ action: id, confirm: id }) });
}

export async function sampleRecorded(): Promise<number | null> {
  return SAMPLE ? (await loadSample()).recorded : null;
}
