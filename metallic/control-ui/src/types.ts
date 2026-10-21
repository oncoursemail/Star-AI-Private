// Shapes of the collector's API (metallic/metallic/control). Every field can be missing: a source that has not
// reported yet is shown as missing, never filled in.

export type Level = "crit" | "warn" | "info";

export interface Alert { level: Level; where: string; text: string }

export interface Container {
  name: string;
  cores: number | null;
  mem: number | null;
  mem_max: number | null;
  limits?: Record<string, string>;
  status?: string;
}

export interface Proc { pid: number; comm: string; cpu_pct: number; rss: number | null; container: string }

export interface Fs { mount: string; total: number; used: number; pct: number | null }

export interface Gpu { name: string; util: number | null; mem_used: number | null; mem_total: number | null;
  temp: number | null; power: number | null }

export interface MachineState {
  id: string;
  name: string;
  role: string;
  kind: string;
  online: boolean;
  last_seen: number | null;
  pending?: string;
  ncpu?: number;
  cpu?: number | null;
  load?: number[];
  mem?: { total: number; used: number; pct: number; swap_total?: number; swap_used?: number };
  fs?: Fs[];
  net?: { rx: number; tx: number };
  disk_io?: { read: number; write: number };
  temps?: Record<string, number | null>;
  temp_cpu?: number | null;
  psi_cpu?: number | null;
  gpu?: Gpu | null;
  containers?: Container[];
  instances?: { name: string; status: string; type: string; limits: Record<string, string> }[];
  procs?: Proc[];
  services?: Record<string, string>;
}

export interface Service { unit: string; active: string; sub: string; since: string; restarts: number; result: string }

export interface BrainFacts {
  at: number;
  host?: string;
  services?: Service[];
  load?: { load1?: number; mem_available_gb?: number };
  night_school?: {
    paused: boolean;
    report?: { written: string; status: string; attempts_total: number | null; passed_first_total: number | null;
      examples_total: number | null; answers_per_active_hour: number | null; lessons_active_total: number | null };
    hours?: Record<string, Record<string, number>>;
    gates?: { ts: string; event: string; lesson: string; text: string }[];
  };
  conductor?: { night: string; written: string; cycles: number | null; created: number | null; accepted: number | null;
    rejected: number | null; off: boolean };
  knowledge_watchdog?: { ok: boolean; checked_at: string; failures: number;
    restarts: { at: string; done: boolean; reason: string }[] };
  studio_lab?: { run: string; ok: boolean; passed?: number; specs?: number; running?: boolean };
  ok?: boolean;
  error?: string;
}

export interface ModelRow {
  id: string;
  status: string;
  port: string | null;
  parallel: number | null;
  ctx: number | null;
  cache_ram_mib: number | null;
  spec: string | null;
  helper: boolean;
  slots?: { total: number; busy: number; ctx: number };
  live?: { processing?: number; deferred?: number; draft_accept_total?: number; cache_share_total?: number };
  error?: string;
}

export interface Gen { machine: string; model: string; slot: number; tps: number | null; n_gen: number | null;
  t: number }

export interface Req { t: number; machine: string; model: string; slot: number; prompt_ms: number | null;
  prompt_tokens: number | null; eval_ms: number | null; eval_tokens: number | null }

export interface BackupRow {
  set: string;
  where: string;
  schedule: string;
  machine: string;
  max_repository_bytes: number | null;
  last_attempt_utc?: string;
  last_success_utc?: string;
  latest_complete?: boolean;
  in_progress?: boolean;
  data_added?: number;
  data_added_packed?: number;
  repository_bytes?: number;
  last_snapshot_id?: string;
  last_error?: { at: string; action: string; message: string } | null;
  last_restore_verification?: { verified_utc: string; files: number; sqlite_databases: number; source_bytes: number };
  baseline_verification?: { verified_utc: string; files: number };
  last_ingest_validation?: { verified_utc: string; files: number };
  error?: string;
}

export interface DevState {
  at?: number;
  repos?: { name: string; open_issues: number; open_prs: number; releases: number; size_kb: number; updated: string;
    branch: string; url: string }[];
  prs?: { repo: string; number: number; title: string; draft: boolean; updated: string; author: string; url: string }[];
  releases?: { repo: string; tag: string; name: string; published: string; url: string }[];
  milestones?: { repo: string; title: string; open: number; closed: number; state: string; due: string | null }[];
  runs?: { repo: string; name: string; status: string; branch: string; started: string; updated: string; url: string }[];
  runners?: { name: string; status: string; version: string; labels: string[] }[];
}

export interface DevPc {
  at: number;
  repo: string;
  prs?: { number: number; title: string; draft: boolean; updated: string; author: string; head: string; base: string;
    url: string }[] | null;
  runs?: { id: number; title: string; workflow: string; status: string; conclusion: string; branch: string;
    created: string; updated: string; url: string }[] | null;
  runners?: { name: string; status: string; busy: boolean; labels: string[] }[] | null;
  projects?: { name: string; lang: string; connected: boolean; note?: string; target?: string; branch?: string;
    head?: string; pending?: string[]; release?: { tag: string; date: string };
    checks: { verdict: string; started: string; red: string[]; branch: string; seconds: number | null;
      cache_hit_rate: number | null }[];
    queue_runs: { started: string; target: string; seconds: number; applied: boolean; merged: string[];
      entries: { branch: string; status: string }[] }[] }[];
}

export interface State {
  generated: number;
  machines: MachineState[];
  star: { brains: Record<string, BrainFacts>; models: ModelRow[]; models_at: number | null; requests: Req[];
    generating?: Gen[] };
  dev: DevState;
  dev_pc: DevPc | null;
  runners: { runner: string; kind: string; state: string; machine: string }[];
  backups: BackupRow[];
  backup_pc: { last_success_utc: string; last_attempt_utc: string; error: string | null; snapshot: string } | null;
  forge_backups: { ok: boolean; files: { t: number; bytes: number; name: string }[]; count: number;
    total_bytes: number } | null;
  timers: Record<string, { unit: string; next: string; last: string }[]>;
  sources: { name: string; last_ok: number | null; error: string }[];
  alerts: Alert[];
}

export type Point = [number, number | null, number | null, number | null];   // ts, avg, min, max

export interface SeriesResponse { range: Range; step: number; from: number; to: number;
  series: Record<string, Point[]> }

export type Range = "hour" | "day" | "week";

export interface Action { id: string; machine: string; machine_name: string; verb: string; group: string;
  label: string; detail: string; danger: "high" | "normal" }

export interface AuditRow { id: number; ts: number; action: string; label: string; machine: string; actor: string;
  client: string; state: "pending" | "ok" | "failed" | "refused"; exit: number | null; text: string | null;
  finished: number | null }

export interface SpeedHour { t: number; machine: string; model: string; n: number; tps_median: number;
  prompt_ms_median: number }
