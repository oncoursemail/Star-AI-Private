// Shape of `metallic status` (metallic/metallic/status.py) and pure helpers the page uses.

export type Severity = "fail" | "warn" | "info" | "pass" | "skip";

export interface Finding { file: string; line: number; rule: string; message: string; severity: Severity }

export interface Check {
  name: string; status: Severity; summary: string; findings: Finding[]; seconds: number; cached: boolean;
  blocking: boolean;
}

export interface CheckRun {
  kind: "check"; project: string; runner: string; branch: string; base: string; tree: string; started: string;
  changed: number; verdict: "green" | "red"; red: string[];
  timings: { snapshot?: number; first_signal?: number; first_test?: number; near_done?: number; graph?: number;
    tests_done?: number; total: number };
  tests: { selected: number; total_files: number; cached: number; ran: number; near?: number; full_reason: string;
    failed: { file: string; status: string; failures: string[] }[]; tests_run?: number; not_run?: number };
  checks: Check[];
  cache: { hits: number; misses: number; hit_rate: number };
}

export interface QueueEntry {
  branch: string; head: string; status: "merged" | "rejected" | "conflict"; reason: string; seconds?: number;
  check?: { verdict: string; tree: string; failed: string[]; timings: { total: number } };
}

export interface QueueRun {
  kind: "queue"; project: string; target: string; started: string; target_before: string; result: string;
  entries: QueueEntry[]; merged: string[]; applied: boolean; apply_error?: string; seconds: number;
  batch: { branches: string[]; verdict: string; red: string[]; seconds: number } | null;
}

export interface Project {
  name: string; lang?: string; repo?: string; connected: boolean; note?: string; target?: string; branch?: string;
  configured?: boolean; head?: string; pending?: string[]; release?: { tag: string; date: string };
  checks?: CheckRun[]; queue_runs?: QueueRun[];
}

export interface Runner { name: string; role?: string; policy?: string; status: string; cores?: number; load?: number }

export interface Status { generated: string; projects: Project[]; runners: Runner[] }

export type Health = "red" | "warn" | "green" | "none" | "offline";

/** Decode a location.hash project selection; a damaged link uses the default project. */
export function projectFromHash(hash: string): string | null {
  try {
    return decodeURIComponent(hash.slice(1)) || null;
  } catch {
    return null;
  }
}

export function health(p: Project): Health {
  if (!p.connected) return "offline";
  const last = p.checks?.[0];
  if (!last) return "none";
  if (last.verdict === "red") return "red";
  return last.checks.some((c) => c.status === "warn") ? "warn" : "green";
}

const ORDER: Record<Health, number> = { red: 0, warn: 1, green: 2, none: 3, offline: 4 };

/** Projects that need a person first; otherwise the order the owner configured. */
export function byAttention(projects: Project[]): Project[] {
  return projects.map((p, i) => ({ p, i })).sort((a, b) => ORDER[health(a.p)] - ORDER[health(b.p)] || a.i - b.i)
    .map((x) => x.p);
}

export function ago(iso: string, now: Date): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "unknown age";
  const s = Math.max(0, Math.round((now.getTime() - t) / 1000));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function seconds(s: number | undefined): string {
  if (s === undefined) return "not reached";
  return s < 10 ? `${s.toFixed(1)} s` : s < 120 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

export const short = (sha: string | undefined) => (sha ?? "").slice(0, 8);
