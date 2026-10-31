// Number and time formatting. Units always shown; a missing value is an en-space-free "n/a", never a zero.

export const NA = "n/a";

export function bytes(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return NA;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let x = Math.abs(v);
  let i = 0;
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i++; }
  return `${v < 0 ? "-" : ""}${x.toFixed(i === 0 ? 0 : x >= 100 ? 0 : digits)} ${units[i]}`;
}

export function rate(v: number | null | undefined): string {
  return v == null ? NA : `${bytes(v)}/s`;
}

export function pct(v: number | null | undefined, digits = 0): string {
  return v == null || !Number.isFinite(v) ? NA : `${v.toFixed(digits)} %`;
}

export function num(v: number | null | undefined, digits = 1, unit = ""): string {
  if (v == null || !Number.isFinite(v)) return NA;
  return `${v.toFixed(digits)}${unit ? " " + unit : ""}`;
}

export function ms(v: number | null | undefined): string {
  if (v == null) return NA;
  return v >= 10_000 ? `${(v / 1000).toFixed(1)} s` : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;
}

/** "12 s ago", "4 min ago", "3 h ago", "2 d ago" from a unix time (s) or ISO string. */
export function ago(t: number | string | null | undefined, now = Date.now() / 1000): string {
  const s = toUnix(t);
  if (s == null) return NA;
  const d = Math.max(0, now - s);
  if (d < 60) return `${Math.round(d)} s ago`;
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86400 * 2) return `${(d / 3600).toFixed(d < 36000 ? 1 : 0)} h ago`;
  return `${Math.round(d / 86400)} d ago`;
}

export function toUnix(t: number | string | null | undefined): number | null {
  if (t == null || t === "") return null;
  if (typeof t === "number") return t;
  const v = Date.parse(t);
  return Number.isNaN(v) ? null : v / 1000;
}

const two = (n: number) => String(n).padStart(2, "0");

/** Local clock time for an axis or a table: "14:05", or "Tue 14:00" when the span is more than a day. */
export function clock(t: number, withDay = false): string {
  const d = new Date(t * 1000);
  const hm = `${two(d.getHours())}:${two(d.getMinutes())}`;
  return withDay ? `${d.toLocaleDateString(undefined, { weekday: "short" })} ${hm}` : hm;
}

export function stamp(t: number | string | null | undefined): string {
  const s = toUnix(t);
  if (s == null) return NA;
  const d = new Date(s * 1000);
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
}

/** Health of a 0-100 share: ok below warn, warn below crit. */
export function level(v: number | null | undefined, warn: number, crit: number): "ok" | "warn" | "crit" | "none" {
  if (v == null) return "none";
  return v >= crit ? "crit" : v >= warn ? "warn" : "ok";
}

/** Nice axis ticks covering [lo, hi]: 3-6 round steps (1, 2, 2.5, 5 x 10^n). */
export function ticks(lo: number, hi: number, target = 4): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (hi <= lo) hi = lo + 1;
  const raw = (hi - lo) / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.floor(lo / step) * step; out.length < 20; v += step) {    // the last tick is the first >= hi
    out.push(Number(v.toFixed(10)));
    if (v >= hi - step * 1e-9) break;
  }
  return out;
}

/** Time ticks aligned to round local minutes/hours for a span in seconds. */
export function timeTicks(from: number, to: number): number[] {
  const span = to - from;
  const steps = [300, 600, 900, 1800, 3600, 7200, 3 * 3600, 6 * 3600, 12 * 3600, 86400];
  const step = steps.find((s) => span / s <= 7) ?? 86400;
  const offset = new Date(from * 1000).getTimezoneOffset() * 60;   // align to local, not UTC, hours
  const out: number[] = [];
  for (let t = Math.ceil((from - offset) / step) * step + offset; t <= to; t += step) out.push(t);
  return out;
}
