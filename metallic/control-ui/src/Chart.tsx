import { useEffect, useId, useMemo, useRef, useState } from "react";
import { clock, ticks, timeTicks } from "./format";
import type { Point } from "./types";

export interface Line { key: string; label: string; color: string; points: Point[] }

interface ChartProps {
  title: string;
  lines: Line[];
  from: number;
  to: number;
  step: number;
  fmt: (v: number) => string;
  yMax?: number;               // fixed top (e.g. 100 for a percentage)
  base2?: boolean;             // byte values: ticks at round KB/MB/GB steps instead of round decimals
  height?: number;
  empty?: string;              // why there is no data, shown instead of an empty plot
}

const PAD = { l: 64, r: 14, t: 10, b: 26 };

/** Split a series where samples are missing for more than three steps, so a gap reads as a gap, not a ramp. */
export function segments(points: Point[], step: number): Point[][] {
  const out: Point[][] = [];
  let cur: Point[] = [];
  let last = -Infinity;
  for (const p of points) {
    if (p[1] == null) continue;
    if (p[0] - last > step * 3 && cur.length) { out.push(cur); cur = []; }
    cur.push(p);
    last = p[0];
  }
  if (cur.length) out.push(cur);
  return out;
}

/** Index of the sample nearest to time t (points sorted by time). */
export function nearest(points: Point[], t: number): number {
  let lo = 0, hi = points.length - 1;
  if (hi < 0) return -1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid][0] < t) lo = mid + 1; else hi = mid;
  }
  if (lo > 0 && Math.abs(points[lo - 1][0] - t) < Math.abs(points[lo][0] - t)) lo--;
  return lo;
}

/** Width of the figure (always rendered, unlike the plot), so the SVG never draws wider than its card. */
function useWidth(ref: React.RefObject<HTMLElement | null>): number {
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setW(Math.max(200, Math.floor(el.clientWidth - 28)));     // minus the card's padding
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

export function LineChart({ title, lines, from, to, step, fmt, yMax, base2, height = 180, empty }: ChartProps) {
  const box = useRef<HTMLDivElement>(null);
  const fig = useRef<HTMLElement>(null);
  const width = useWidth(fig) || 560;
  const [hover, setHover] = useState<number | null>(null);      // a time on the x axis
  const [table, setTable] = useState(false);
  const id = useId();
  const has = lines.some((l) => l.points.some((p) => p[1] != null));
  const { yTicks, top } = useMemo(() => {
    let hi = yMax ?? 0;
    for (const l of lines) for (const p of l.points) if (p[1] != null && p[1] > hi) hi = p[1];
    const span = yMax ?? (hi > 0 ? hi * 1.1 : 1);
    const unit = base2 && span >= 1024 ? 1024 ** Math.floor(Math.log(span) / Math.log(1024)) : 1;
    const t = ticks(0, span / unit).map((v) => v * unit).filter((v) => yMax == null || v <= yMax * 1.0001);
    return { yTicks: t, top: yMax ?? t[t.length - 1] };
  }, [lines, yMax, base2]);
  const iw = width - PAD.l - PAD.r;
  const ih = height - PAD.t - PAD.b;
  const x = (t: number) => PAD.l + ((t - from) / Math.max(1, to - from)) * iw;
  const y = (v: number) => PAD.t + ih - (v / (top || 1)) * ih;
  const xt = timeTicks(from, to);
  const withDay = to - from > 86400 * 1.5;
  const ref = lines.find((l) => l.points.length)?.points ?? [];
  const hi = hover != null ? nearest(ref, hover) : -1;
  const ht = hi >= 0 ? ref[hi][0] : null;

  const move = (clientX: number) => {
    const r = box.current?.getBoundingClientRect();
    if (!r) return;
    const t = from + ((clientX - r.left - PAD.l) / iw) * (to - from);
    setHover(Math.min(to, Math.max(from, t)));
  };
  const key = (e: React.KeyboardEvent) => {
    if (!ref.length) return;
    const i = hi >= 0 ? hi : ref.length - 1;
    if (e.key === "ArrowLeft") { setHover(ref[Math.max(0, i - 1)][0]); e.preventDefault(); }
    if (e.key === "ArrowRight") { setHover(ref[Math.min(ref.length - 1, i + 1)][0]); e.preventDefault(); }
    if (e.key === "Escape") setHover(null);
  };

  return (
    <figure className="chart" ref={fig}>
      <figcaption>
        <span className="chart-title" id={id}>{title}</span>
        {lines.length > 1 && (
          <span className="legend">
            {lines.map((l) => <span key={l.key}><i style={{ background: l.color }} />{l.label}</span>)}
          </span>
        )}
        {has && <button className="link" onClick={() => setTable(!table)} aria-expanded={table}>
          {table ? "Hide values" : "Values"}</button>}
      </figcaption>
      {!has ? <p className="chart-empty" style={{ height }}>{empty ?? "No samples in this range yet."}</p> : (
        <div className="plot" ref={box} tabIndex={0} aria-labelledby={id} role="img"
             onPointerMove={(e) => move(e.clientX)} onPointerLeave={() => setHover(null)} onKeyDown={key}
             onFocus={() => setHover(ref.length ? ref[ref.length - 1][0] : null)} onBlur={() => setHover(null)}>
          <svg width={width} height={height} aria-hidden="true">
            {yTicks.map((v) => (
              <g key={v}>
                <line x1={PAD.l} x2={width - PAD.r} y1={y(v)} y2={y(v)} className={v === 0 ? "axis" : "grid"} />
                <text x={PAD.l - 8} y={y(v) + 4} textAnchor="end" className="tick">{fmt(v)}</text>
              </g>
            ))}
            {xt.map((t) => (
              <text key={t} x={x(t)} y={height - 6} textAnchor="middle" className="tick">{clock(t, withDay)}</text>
            ))}
            {lines.map((l) => segments(l.points, step).map((seg, i) => (
              <polyline key={l.key + i} fill="none" stroke={l.color} strokeWidth={2} strokeLinejoin="round"
                        strokeLinecap="round"
                        points={seg.map((p) => `${x(p[0]).toFixed(1)},${y(p[1] as number).toFixed(1)}`).join(" ")} />
            )))}
            {ht != null && <line className="crosshair" x1={x(ht)} x2={x(ht)} y1={PAD.t} y2={PAD.t + ih} />}
            {ht != null && lines.map((l) => {
              const p = l.points[nearest(l.points, ht)];
              return p && p[1] != null && Math.abs(p[0] - ht) <= step * 2 ?
                <circle key={l.key} cx={x(p[0])} cy={y(p[1])} r={4} fill={l.color} className="dot" /> : null;
            })}
          </svg>
          {ht != null && (
            <div className="tip" style={{ left: Math.min(width - 190, Math.max(0, x(ht) + 12)) }}>
              <div className="tip-time">{clock(ht, withDay)}</div>
              {lines.map((l) => {
                const p = l.points[nearest(l.points, ht)];
                const ok = p && p[1] != null && Math.abs(p[0] - ht) <= step * 2;
                return (
                  <div key={l.key} className="tip-row">
                    <i style={{ background: l.color }} />
                    <strong>{ok ? fmt(p[1] as number) : "no sample"}</strong>
                    <span>{l.label}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
      {table && has && <ValuesTable lines={lines} fmt={fmt} withDay={withDay} />}
    </figure>
  );
}

function ValuesTable({ lines, fmt, withDay }: { lines: Line[]; fmt: (v: number) => string; withDay: boolean }) {
  const ref = lines.find((l) => l.points.length)?.points ?? [];
  const every = Math.max(1, Math.ceil(ref.length / 24));
  const rows = ref.filter((_, i) => i % every === 0 || i === ref.length - 1);
  return (
    <div className="table-scroll">
      <table className="values">
        <thead><tr><th>Time</th>{lines.map((l) => <th key={l.key}>{l.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p[0]}>
              <td>{clock(p[0], withDay)}</td>
              {lines.map((l) => {
                const q = l.points[nearest(l.points, p[0])];
                return <td key={l.key}>{q && q[1] != null && q[0] === p[0] ? fmt(q[1]) : "n/a"}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A 15-minute trace beside a live number: shape only, the number next to it carries the value. */
export function Spark({ points, color, max }: { points: Point[]; color: string; max?: number }) {
  const vals = points.filter((p) => p[1] != null);
  if (vals.length < 2) return <span className="spark spark-empty" aria-hidden="true" />;
  const t0 = vals[0][0], t1 = vals[vals.length - 1][0];
  const hi = max ?? Math.max(...vals.map((p) => p[1] as number), 1e-9);
  const pts = vals.map((p) => `${(((p[0] - t0) / Math.max(1, t1 - t0)) * 78 + 1).toFixed(1)},`
    + `${(23 - ((p[1] as number) / hi) * 21).toFixed(1)}`).join(" ");
  return (
    <svg className="spark" viewBox="0 0 80 24" aria-hidden="true">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}

/** Used vs limit as a thin bar; the text beside it says the numbers. */
export function Meter({ value, max, levelOf }: { value: number | null | undefined; max: number | null | undefined;
  levelOf?: (share: number) => string }) {
  if (value == null || !max) return <span className="meter meter-none" aria-hidden="true" />;
  const share = Math.min(1, value / max);
  const lv = levelOf ? levelOf(share * 100) : share >= 0.95 ? "crit" : share >= 0.85 ? "warn" : "ok";
  return <span className={`meter meter-${lv}`} aria-hidden="true"><i style={{ width: `${(share * 100).toFixed(1)}%` }} /></span>;
}
