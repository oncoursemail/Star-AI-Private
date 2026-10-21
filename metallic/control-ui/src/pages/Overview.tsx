import { Meter, Spark } from "../Chart";
import { ago, bytes, level, num, pct, rate } from "../format";
import type { MachineState, State } from "../types";
import { Dot, Empty, SERIES, pts, useSeries, worst, type Health } from "../ui";

export function machineHealth(m: MachineState, state: State): Health {
  if (m.pending) return "none";
  if (!m.online) return m.last_seen ? "off" : "none";
  const lv: Health[] = [];
  for (const a of state.alerts) if (a.where === m.id) lv.push(a.level === "crit" ? "crit" : "warn");
  lv.push("ok");
  return worst(lv);
}

export function Overview({ state, go }: { state: State; go: (page: string, machine?: string) => void }) {
  const live = state.machines.filter((m) => !m.pending);
  const keys = live.flatMap((m) => [`${m.id}.cpu`, `${m.id}.mem_pct`, `${m.id}.net_rx`]);
  const { data: s } = useSeries(keys, "hour");
  const recent = (key: string) => pts(s, key).filter((p) => p[0] >= state.generated - 900);
  return (
    <div className="page">
      <header className="page-head">
        <h1>Overview</h1>
        <p className="muted">Every machine and container, live. Numbers are the last 5-10 s; traces are the last 15 minutes.</p>
      </header>

      <section aria-labelledby="alerts-h" className="alerts">
        <h2 id="alerts-h" className="sr-only">Alerts</h2>
        {state.alerts.length === 0 ? <p className="all-clear"><Dot h="ok" word="No alerts" /></p> : (
          <ul>
            {state.alerts.map((a, i) => (
              <li key={i} className={`alert alert-${a.level}`}>
                <Dot h={a.level === "crit" ? "crit" : "warn"} word={a.level === "crit" ? "Problem" : "Check"} />
                <span>{a.text}</span>
                {state.machines.some((m) => m.id === a.where) &&
                  <button className="link" onClick={() => go("servers", a.where)}>
                    Open {state.machines.find((m) => m.id === a.where)?.name}</button>}
                {a.where === "backups" && <button className="link" onClick={() => go("backups")}>Open backups</button>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="plates" aria-label="Machines">
        {state.machines.map((m) => (
          <article key={m.id} className={`plate ${m.online ? "" : "plate-off"}`}>
            <header>
              <div>
                <h2>{m.name}</h2>
                <p className="muted">{m.role}</p>
              </div>
              <div className="plate-state">
                <Dot h={machineHealth(m, state)} word={m.pending ? "Not connected" : undefined} />
                <span className="muted small">{m.pending ? m.pending : m.last_seen ? `data ${ago(m.last_seen, state.generated)}` : "no data yet"}</span>
              </div>
            </header>
            {!m.pending && m.online && (
              <>
                <dl className="vitals">
                  <div>
                    <dt>CPU{m.ncpu ? ` (${m.ncpu} threads)` : ""}</dt>
                    <dd><span className={`v lv-${level(m.cpu, 85, 95)}`}>{pct(m.cpu)}</span>
                      <Spark points={recent(`${m.id}.cpu`)} color={SERIES[0]} max={100} /></dd>
                  </div>
                  <div>
                    <dt>Memory</dt>
                    <dd><span className="v">{m.mem ? `${bytes(m.mem.used)} of ${bytes(m.mem.total, 0)}` : "n/a"}</span>
                      <Spark points={recent(`${m.id}.mem_pct`)} color={SERIES[0]} max={100} /></dd>
                  </div>
                  <div>
                    <dt>Network in / out</dt>
                    <dd><span className="v">{m.net ? `${rate(m.net.rx)} / ${rate(m.net.tx)}` : "n/a"}</span>
                      <Spark points={recent(`${m.id}.net_rx`)} color={SERIES[0]} /></dd>
                  </div>
                  <div>
                    <dt>{m.gpu ? "GPU" : "CPU temperature"}</dt>
                    <dd><span className="v">{m.gpu ? `${pct(m.gpu.util)} · ${num(m.gpu.temp, 0, "°C")} · ${bytes(m.gpu.mem_used)}`
                      : num(m.temp_cpu, 0, "°C")}</span></dd>
                  </div>
                </dl>
                <ul className="disks">
                  {(m.fs ?? []).map((f) => (
                    <li key={f.mount}>
                      <span className="mono">{f.mount}</span>
                      <Meter value={f.pct} max={100} levelOf={(v) => level(v, 90, 95)} />
                      <span className={`lv-${level(f.pct, 90, 95)}`}>{pct(f.pct)}</span>
                      <span className="muted">{bytes(f.used, 0)} of {bytes(f.total, 0)}</span>
                    </li>
                  ))}
                </ul>
                {m.containers && m.containers.length > 0 && (
                  <table className="cts">
                    <caption className="sr-only">Containers on {m.name}</caption>
                    <thead><tr><th>Container</th><th>CPU now</th><th>Memory</th><th>Limit</th></tr></thead>
                    <tbody>
                      {m.containers.map((c) => (
                        <tr key={c.name}>
                          <td>{c.name}</td>
                          <td className="num">{c.cores == null ? "n/a" : `${c.cores.toFixed(2)} cores`}
                            {c.limits?.cpu ? <span className="muted"> of {c.limits.cpu}</span> : null}</td>
                          <td className="num">{bytes(c.mem)}</td>
                          <td><Meter value={c.mem} max={c.mem_max} />
                            <span className="muted small">{c.mem_max ? bytes(c.mem_max, 0) : "no memory limit"}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {m.services && (
                  <p className="muted small">Sunshine: {m.services.sunshine ?? "n/a"} · Windows runner: {m.services.pc_win_runner ?? "n/a"}</p>
                )}
                <button className="link" onClick={() => go("servers", m.id)}>Charts and processes for {m.name}</button>
              </>
            )}
            {!m.pending && !m.online && <Empty>{m.last_seen ? `No data for ${ago(m.last_seen, state.generated)}. The collector keeps retrying.` : "Waiting for the first sample."}</Empty>}
          </article>
        ))}
      </section>
    </div>
  );
}
