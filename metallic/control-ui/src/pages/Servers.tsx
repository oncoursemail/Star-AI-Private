import { LineChart } from "../Chart";
import { bytes, num, pct } from "../format";
import type { MachineState, Range, State } from "../types";
import { Dot, Empty, ErrorLine, RangePicker, SERIES, pts, useSeries } from "../ui";
import { machineHealth } from "./Overview";

const fmtPct = (v: number) => `${Math.round(v)} %`;
const fmtGB = (v: number) => bytes(v, v >= 10 * 2 ** 30 ? 0 : 1);
const fmtRate = (v: number) => `${bytes(v, 0)}/s`;

export function Servers({ state, machine, setMachine, range, setRange }: {
  state: State; machine: string; setMachine: (id: string) => void; range: Range; setRange: (r: Range) => void;
}) {
  const machines = state.machines.filter((m) => !m.pending);
  const m = machines.find((x) => x.id === machine) ?? machines[0];
  return (
    <div className="page">
      <header className="page-head">
        <h1>Servers</h1>
        <p className="muted">Per machine: history with units and local times, containers with their limits, the busiest processes.
          Keys: [ and ] switch machine, h d w pick the range.</p>
      </header>
      <div className="toolbar">
        <div className="tabs" role="tablist" aria-label="Machine">
          {machines.map((x) => (
            <button key={x.id} role="tab" aria-selected={x.id === m?.id} className={x.id === m?.id ? "on" : ""}
                    onClick={() => setMachine(x.id)}>
              <Dot h={machineHealth(x, state)} word={x.name} />
            </button>
          ))}
        </div>
        <RangePicker value={range} onChange={setRange} />
      </div>
      {m ? <MachineCharts key={m.id + range} m={m} range={range} /> : <Empty>No machines configured.</Empty>}
      {state.machines.filter((x) => x.pending).map((x) => (
        <p key={x.id} className="muted small">{x.name}: {x.pending}</p>
      ))}
    </div>
  );
}

function MachineCharts({ m, range }: { m: MachineState; range: Range }) {
  const pc = m.kind === "pc";
  const cts = (m.containers ?? []).slice().sort((a, b) => (b.cores ?? 0) - (a.cores ?? 0));
  const ctKeys = cts.slice(0, 3).map((c) => `${m.id}.ct:${c.name}:cores`);
  const rootFs = (m.fs ?? [])[0]?.mount ?? "/";
  const keys = [`${m.id}.cpu`, `${m.id}.mem_used`, `${m.id}.net_rx`, `${m.id}.net_tx`, `${m.id}.disk_r`,
    `${m.id}.disk_w`, `${m.id}.temp_cpu`, `${m.id}.load1`, `${m.id}.fs_pct:${rootFs}`,
    "pc.gpu_util", "pc.gpu_temp", "pc.gpu_mem", ...ctKeys];
  const { data: s, error, loading } = useSeries(keys, range);
  const base = { from: s?.from ?? 0, to: s?.to ?? 0, step: s?.step ?? 5 };
  const p = (k: string) => pts(s, k);
  return (
    <>
      <ErrorLine error={error} />
      <div className={`charts ${loading && s ? "refreshing" : ""}`}>
        <LineChart title="CPU busy, % of all threads" {...base} fmt={fmtPct} yMax={100}
                   lines={[{ key: "cpu", label: "CPU", color: SERIES[0], points: p(`${m.id}.cpu`) }]} />
        <LineChart title={`Memory used${m.mem ? `, of ${bytes(m.mem.total, 0)}` : ""}`} {...base} fmt={fmtGB} base2
                   yMax={m.mem?.total}
                   lines={[{ key: "mem", label: "Used", color: SERIES[0], points: p(`${m.id}.mem_used`) }]} />
        <LineChart title="Network, bytes per second" {...base} fmt={fmtRate} base2
                   lines={[{ key: "rx", label: "In", color: SERIES[0], points: p(`${m.id}.net_rx`) },
                           { key: "tx", label: "Out", color: SERIES[1], points: p(`${m.id}.net_tx`) }]} />
        {pc ? (
          <LineChart title="GPU busy, %" {...base} fmt={fmtPct} yMax={100}
                     lines={[{ key: "gpu", label: "GPU", color: SERIES[0], points: p("pc.gpu_util") }]} />
        ) : (
          <LineChart title="Disk I/O, bytes per second" {...base} fmt={fmtRate} base2
                     lines={[{ key: "r", label: "Read", color: SERIES[0], points: p(`${m.id}.disk_r`) },
                             { key: "w", label: "Write", color: SERIES[1], points: p(`${m.id}.disk_w`) }]} />
        )}
        <LineChart title={pc ? "GPU temperature, °C" : "CPU temperature (hottest sensor), °C"} {...base}
                   fmt={(v) => `${Math.round(v)} °C`}
                   empty={pc ? "No GPU readings yet." : "This machine exposes no CPU temperature sensor."}
                   lines={[{ key: "t", label: "Temperature", color: SERIES[0], points: p(pc ? "pc.gpu_temp" : `${m.id}.temp_cpu`) }]} />
        {pc ? (
          <LineChart title="GPU memory used" {...base} fmt={fmtGB} base2 yMax={m.gpu?.mem_total ?? undefined}
                     lines={[{ key: "gm", label: "VRAM", color: SERIES[0], points: p("pc.gpu_mem") }]} />
        ) : (
          <LineChart title={`Load average (1 min), ${m.ncpu ?? "?"} threads`} {...base} fmt={(v) => v.toFixed(v < 10 ? 1 : 0)}
                     lines={[{ key: "l", label: "Load", color: SERIES[0], points: p(`${m.id}.load1`) }]} />
        )}
        {ctKeys.length > 0 && (
          <LineChart title="Busiest containers, CPU cores in use" {...base} fmt={(v) => v.toFixed(v < 1 ? 2 : 1)}
                     lines={cts.slice(0, 3).map((c, i) => ({ key: c.name, label: c.name, color: SERIES[i],
                       points: p(`${m.id}.ct:${c.name}:cores`) }))} />
        )}
        <LineChart title={`Disk ${rootFs} used, %`} {...base} fmt={fmtPct} yMax={100}
                   lines={[{ key: "fs", label: rootFs, color: SERIES[0], points: p(`${m.id}.fs_pct:${rootFs}`) }]} />
      </div>

      {(m.instances ?? m.containers ?? []).length > 0 && (
        <section className="block">
          <h2>LXD instances and limits</h2>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Name</th><th>State</th><th>CPU now</th><th>CPU limit</th><th>Priority</th><th>Memory</th>
                <th>Memory limit</th><th>Other limits</th></tr></thead>
              <tbody>
                {(m.instances ?? m.containers!.map((c) => ({ name: c.name, status: "Running", type: "container", limits: c.limits ?? {} })))
                  .map((i) => {
                    const c = (m.containers ?? []).find((x) => x.name === i.name);
                    const other = Object.entries(i.limits).filter(([k]) => !["cpu", "memory", "cpu.priority"].includes(k));
                    return (
                      <tr key={i.name}>
                        <td>{i.name}{i.type === "virtual-machine" ? <span className="muted"> (VM)</span> : null}</td>
                        <td>{i.status}</td>
                        <td className="num">{c?.cores == null ? "n/a" : `${c.cores.toFixed(2)} cores`}</td>
                        <td className="num">{i.limits.cpu ?? "none"}</td>
                        <td className="num">{i.limits["cpu.priority"] ?? "default"}</td>
                        <td className="num">{bytes(c?.mem)}</td>
                        <td className="num">{i.limits.memory ?? "none"}</td>
                        <td className="mono small">{other.map(([k, v]) => `${k}=${v}`).join(" ") || " "}</td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="block">
        <h2>Busiest processes, last minute</h2>
        {pc ? <Empty>Per-process numbers are not collected on the PC (the agent reads only system totals).</Empty>
          : !(m.procs ?? []).length ? <Empty>The first process sample arrives a minute after the collector connects.</Empty> : (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Process</th><th>Container</th><th>CPU</th><th>Memory</th><th>PID</th></tr></thead>
                <tbody>
                  {m.procs!.map((p) => (
                    <tr key={p.pid}>
                      <td className="mono">{p.comm}</td>
                      <td>{p.container || <span className="muted">host</span>}</td>
                      <td className="num">{pct(p.cpu_pct, 1)} <span className="muted">of one thread</span></td>
                      <td className="num">{bytes(p.rss)}</td>
                      <td className="num muted">{p.pid}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </section>
      {m.temps && Object.keys(m.temps).length > 0 && (
        <p className="muted small">Sensors now: {Object.entries(m.temps).map(([k, v]) => `${k} ${num(v, 0, "°C")}`).join(" · ")}</p>
      )}
    </>
  );
}
