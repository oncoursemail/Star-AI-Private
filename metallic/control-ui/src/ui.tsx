import { useEffect, useRef, useState } from "react";
import * as api from "./api";
import type { Point, Range, SeriesResponse } from "./types";

export type Health = "ok" | "warn" | "crit" | "off" | "none";

const WORD: Record<Health, string> = { ok: "OK", warn: "Check", crit: "Problem", off: "Not reporting", none: "No data" };

/** Health as shape + word, never colour alone: circle ok, triangle check, square problem, ring off. */
export function Dot({ h, word }: { h: Health; word?: string }) {
  return (
    <span className={`health health-${h}`}>
      <svg viewBox="0 0 10 10" aria-hidden="true">
        {h === "ok" && <circle cx="5" cy="5" r="4" />}
        {h === "warn" && <path d="M5 1 9.2 9H.8Z" />}
        {h === "crit" && <rect x="1.2" y="1.2" width="7.6" height="7.6" />}
        {(h === "off" || h === "none") && <circle cx="5" cy="5" r="3.4" fill="none" strokeWidth="1.4" />}
      </svg>
      <span>{word ?? WORD[h]}</span>
    </span>
  );
}

export function worst(levels: Health[]): Health {
  for (const h of ["crit", "off", "warn", "ok"] as Health[]) if (levels.includes(h)) return h;
  return "none";
}

/** Poll an async source; keeps the last good value while refetching (no flash) and remembers the last error. */
export function usePoll<T>(load: () => Promise<T>, every: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    let timer: number | undefined;
    const tick = async () => {
      setLoading(true);
      try {
        const v = await load();
        if (live.current) { setData(v); setError(""); }
      } catch (e) {
        if (e instanceof api.SignedOut) { window.dispatchEvent(new Event("mc-signed-out")); return; }
        if (live.current) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (live.current) setLoading(false);
      }
      if (live.current) timer = window.setTimeout(tick, every);
    };
    tick();
    return () => { live.current = false; window.clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading };
}

/** Series for a set of keys over a range: refresh every 10 s for the hour view, every minute for day/week. */
export function useSeries(keys: string[], range: Range) {
  const joined = keys.join(",");
  return usePoll<SeriesResponse>(() => api.series(keys, range), range === "hour" ? 10_000 : 60_000, [joined, range]);
}

export function pts(s: SeriesResponse | null, key: string): Point[] {
  return s?.series[key] ?? [];
}

export function RangePicker({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  const opts: [Range, string, string][] = [["hour", "Last hour", "h"], ["day", "Last day", "d"], ["week", "Last week", "w"]];
  return (
    <div className="seg" role="radiogroup" aria-label="Time range">
      {opts.map(([r, label, k]) => (
        <button key={r} role="radio" aria-checked={value === r} className={value === r ? "on" : ""}
                onClick={() => onChange(r)} title={`${label} (key ${k})`}>{label}</button>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function ErrorLine({ error }: { error: string }) {
  return error ? <p className="error-line" role="status">Could not refresh: {error}. Showing the last good data.</p> : null;
}

export const SERIES = ["#3987e5", "#d95926", "#199e70"];      // dataviz slots 1-3, validated on the dark surface
