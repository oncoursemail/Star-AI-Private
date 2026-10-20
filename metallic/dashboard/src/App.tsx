import { useEffect, useMemo, useState } from "react";
import {
  ago, byAttention, health, seconds, short,
  type Check, type CheckRun, type Health, type Project, type QueueRun, type Runner, type Severity, type Status,
} from "./model";

const REFRESH_MS = 30_000;
const STALE_S = 15 * 60;

type Load = { state: "loading" } | { state: "error"; message: string } | { state: "ok"; data: Status; at: Date };

const SEV_LABEL: Record<Severity, string> = { pass: "Pass", fail: "Fail", warn: "Warn", info: "Note", skip: "Skipped" };
const HEALTH_LABEL: Record<Health, string> = {
  red: "Red", warn: "Green, with warnings", green: "Green", none: "No runs yet", offline: "Not connected",
};

function Shape({ kind }: { kind: Severity | Health }) {
  // Shape and word always travel together; colour is never the only signal.
  const k = kind === "red" ? "fail" : kind === "green" ? "pass" : kind === "none" || kind === "offline" ? "skip" : kind;
  return (
    <svg className={`shape shape-${k}`} viewBox="0 0 10 10" aria-hidden="true">
      {k === "pass" && <circle cx="5" cy="5" r="4" />}
      {k === "fail" && <rect x="1" y="1" width="8" height="8" />}
      {k === "warn" && <path d="M5 0.8 9.4 9H0.6Z" />}
      {k === "info" && <path d="M5 0.6 9.4 5 5 9.4 0.6 5Z" />}
      {k === "skip" && <circle cx="5" cy="5" r="3.4" fill="none" strokeWidth="1.3" />}
    </svg>
  );
}

function Mark() {
  return <span className="mark" aria-hidden="true"><i /><i /><i /></span>;
}

export default function App() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [pick, setPick] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    let alive = true;
    const get = () =>
      fetch("./data.json", { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`data.json answered ${r.status}`))))
        .then((data: Status) => alive && setLoad({ state: "ok", data, at: new Date() }))
        .catch((e: Error) => alive && setLoad((prev) => (prev.state === "ok" ? prev : { state: "error", message: e.message })));
    get();
    const a = setInterval(get, REFRESH_MS);
    const b = setInterval(() => setNow(new Date()), 10_000);
    return () => { alive = false; clearInterval(a); clearInterval(b); };
  }, []);

  if (load.state !== "ok") {
    return (
      <div className="shell">
        <main className="empty-page">
          <div className="brand"><Mark /><span>METALLIC</span></div>
          {load.state === "loading" ? <p>Loading data.json</p> : (
            <>
              <h1>No dashboard data</h1>
              <p>{load.message}. Run <code>metallic serve</code> in a clone, or write the file with{" "}
                <code>metallic status --out dashboard/public/data.json</code>.</p>
            </>
          )}
        </main>
      </div>
    );
  }

  return <Dashboard data={load.data} fetchedAt={load.at} now={now} pick={pick} setPick={setPick} />;
}

function Dashboard({ data, fetchedAt, now, pick, setPick }: {
  data: Status; fetchedAt: Date; now: Date; pick: string | null; setPick: (n: string) => void;
}) {
  const projects = useMemo(() => byAttention(data.projects), [data.projects]);
  const project = projects.find((p) => p.name === pick) ?? projects[0];
  const ageS = (now.getTime() - Date.parse(data.generated)) / 1000;
  const stale = ageS > STALE_S;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><Mark /><span>METALLIC<small>Forge layer</small></span></div>
        <nav aria-label="Projects" className="projects">
          <h2 className="side-label">Projects</h2>
          {projects.map((p) => {
            const h = health(p);
            return (
              <button key={p.name} className="project-link" aria-current={p === project ? "page" : undefined}
                onClick={() => setPick(p.name)}>
                <Shape kind={h} />
                <span className="project-name">{p.name}</span>
                <span className="project-state">{h === "offline" ? "not connected" : h === "none" ? "no runs" : h}</span>
              </button>
            );
          })}
        </nav>
        <section className="side-runners" aria-label="Runners">
          <h2 className="side-label">Runners</h2>
          {data.runners.map((r) => <RunnerLine key={r.name} r={r} />)}
        </section>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="crumb"><span>Projects</span><span className="slash">/</span><strong>{project?.name}</strong></div>
          <label className="mobile-pick">
            <span className="sr-only">Project</span>
            <select value={project?.name} onChange={(e) => setPick(e.target.value)}>
              {projects.map((p) => <option key={p.name} value={p.name}>{p.name}: {HEALTH_LABEL[health(p)]}</option>)}
            </select>
          </label>
          <div className={`freshness ${stale ? "is-stale" : ""}`} role="status">
            <span className="dot" aria-hidden="true" />
            {stale ? "Stale data" : "Live"}: <span className="tnum">{ago(data.generated, now)}</span>
            <span className="fresh-detail">, fetched {fetchedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
          </div>
        </header>

        <Attention projects={projects} onPick={setPick} />

        {project && <ProjectView key={project.name} p={project} now={now} />}
      </div>

      <aside className="inspector" aria-label="Fleet">
        <section className="panel">
          <h2>Runners</h2>
          <ul className="runner-list">
            {data.runners.map((r) => (
              <li key={r.name}>
                <RunnerLine r={r} />
                {r.role && <p className="muted">{r.role}</p>}
                {r.policy && <p className="policy">{r.policy}</p>}
              </li>
            ))}
          </ul>
        </section>
        <section className="panel">
          <h2>Releases</h2>
          <table className="dense">
            <thead><tr><th>Project</th><th>Latest tag</th><th>Date</th></tr></thead>
            <tbody>
              {data.projects.map((p) => (
                <tr key={p.name}>
                  <td>{p.name}</td>
                  <td className="mono">{p.release?.tag ?? <span className="muted">none</span>}</td>
                  <td className="tnum">{p.release ? p.release.date.slice(0, 10) : <span className="muted">-</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </aside>
    </div>
  );
}

function RunnerLine({ r }: { r: Runner }) {
  const online = r.status.startsWith("online");
  return (
    <div className="runner-line">
      <Shape kind={online ? "pass" : "skip"} />
      <span className="runner-name">{r.name}</span>
      <span className="runner-meta tnum">
        {online ? [r.cores && `${r.cores} threads`, r.load !== undefined && `load ${r.load.toFixed(2)}`]
          .filter(Boolean).join(", ") || "online" : r.status}
      </span>
    </div>
  );
}

function Attention({ projects, onPick }: { projects: Project[]; onPick: (n: string) => void }) {
  // The phone view opens on this list (the emergency panel): what is red right now, across projects.
  const red = projects.filter((p) => health(p) === "red");
  return (
    <section className="attention" aria-label="Needs attention">
      {red.length === 0 ? <p className="all-clear"><Shape kind="pass" /> No project is red.</p> : red.map((p) => (
        <button key={p.name} className="attention-item" onClick={() => onPick(p.name)}>
          <Shape kind="fail" /><strong>{p.name}</strong>
          <span>{p.checks?.[0]?.red.join(", ")} failed on {p.checks?.[0]?.branch}</span>
        </button>
      ))}
    </section>
  );
}

function ProjectView({ p, now }: { p: Project; now: Date }) {
  if (!p.connected) {
    return (
      <main className="content">
        <ProjectHead p={p} />
        <div className="notice">
          <p><strong>{p.note ?? "Not connected"}.</strong> Add a clone path for {p.name} to
            <code> ~/.metallic/projects.toml</code>, then run <code>metallic check</code> in it.</p>
        </div>
      </main>
    );
  }
  const last = p.checks?.[0];
  return (
    <main className="content">
      <ProjectHead p={p} />
      {last ? <Timing run={last} now={now} /> : (
        <div className="notice"><p>No check runs in this clone yet. Run <code>metallic check</code> here.</p></div>
      )}
      <Queue runs={p.queue_runs ?? []} pending={p.pending ?? []} now={now} />
      {last && <Checks run={last} />}
      {(p.checks?.length ?? 0) > 1 && <History runs={p.checks!} now={now} />}
    </main>
  );
}

function ProjectHead({ p }: { p: Project }) {
  const h = health(p);
  return (
    <div className="project-head">
      <div>
        <h1>{p.name}</h1>
        <p className="muted">
          {[p.lang, p.branch && `on ${p.branch}`, p.target && `target ${p.target}`].filter(Boolean).join(", ")}
          {p.connected && !p.configured && ", no metallic.toml yet (built-in checks only)"}
        </p>
      </div>
      <div className={`verdict verdict-${h}`}><Shape kind={h} /> {HEALTH_LABEL[h]}</div>
    </div>
  );
}

function Timing({ run, now }: { run: CheckRun; now: Date }) {
  const t = run.timings;
  const cacheTotal = run.cache.hits + run.cache.misses;
  return (
    <section className="timing" aria-label="Latest check timing">
      <dl>
        <div><dt>First verdict</dt><dd className="tnum">{seconds(t.first_signal)}</dd></div>
        <div><dt>Nearest tests done</dt><dd className="tnum">{seconds(t.near_done)}</dd></div>
        <div><dt>All selected tests</dt><dd className="tnum">{seconds(t.tests_done)}</dd></div>
        <div><dt>Cache hits</dt>
          <dd className="tnum">{cacheTotal ? `${Math.round(run.cache.hit_rate * 100)} %` : "-"}
            <small> {run.cache.hits}/{cacheTotal}</small></dd></div>
      </dl>
      <p className="provenance">
        Check of <span className="mono">{short(run.tree)}</span> on {run.branch} against{" "}
        <span className="mono">{short(run.base)}</span>, {run.changed} changed file(s), runner {run.runner},{" "}
        {ago(run.started, now)}. Tests: {run.tests.selected} of {run.tests.total_files} files selected
        {run.tests.full_reason && ` (${run.tests.full_reason})`}, {run.tests.cached} from cache, {run.tests.ran} ran.
      </p>
    </section>
  );
}

function Queue({ runs, pending, now }: { runs: QueueRun[]; pending: string[]; now: Date }) {
  const run = runs[0];
  return (
    <section className="panel queue" aria-label="Merge queue">
      <div className="panel-head">
        <h2>Merge queue</h2>
        <p className="muted">Each branch is tested merged onto everything ahead of it; only a green combined tree lands.</p>
      </div>
      {pending.length > 0 && (
        <div className="pending">
          <h3>Waiting</h3>
          <ol>{pending.map((b) => <li key={b} className="mono">{b}</li>)}</ol>
        </div>
      )}
      {!run ? <p className="empty">No queue runs yet. <code>metallic queue run BRANCH...</code> tests branches on the combined tree.</p> : (
        <div className="rail">
          <div className="rail-stop">
            <span className="rail-node" aria-hidden="true" />
            <span><strong>{run.target}</strong> at <span className="mono">{short(run.target_before)}</span></span>
            <span className="muted">{ago(run.started, now)}</span>
          </div>
          {run.batch && (
            <p className="batch">
              Batch of {run.batch.branches.length} tested together first: {run.batch.verdict}
              {run.batch.verdict === "red" ? `, ${run.batch.red.join(", ")} failed; retried one by one.` : "."}
            </p>
          )}
          <ol className="entries">
            {run.entries.map((e) => (
              <li key={e.branch} className={`entry entry-${e.status}`}>
                <span className="rail-node" aria-hidden="true" />
                <div className="entry-main">
                  <span className="mono branch">{e.branch}</span>
                  <span className={`entry-status`}><Shape kind={e.status === "merged" ? "pass" : "fail"} />{" "}
                    {e.status === "merged" ? "Merged" : e.status === "conflict" ? "Conflict" : "Rejected"}</span>
                </div>
                <p className="entry-reason">{e.reason}</p>
                {e.check && (
                  <p className="entry-meta">
                    Combined tree <span className="mono">{short(e.check.tree)}</span>
                    {e.check.failed.length > 0 && <>, failing: <span className="mono">{e.check.failed.join(", ")}</span></>}
                    {e.seconds !== undefined && <>, {seconds(e.seconds)}</>}
                  </p>
                )}
              </li>
            ))}
          </ol>
          <div className="rail-stop result">
            <span className="rail-node" aria-hidden="true" />
            <span>Result <span className="mono">{short(run.result)}</span>: {run.merged.length} of {run.entries.length} landed</span>
            <span className="muted">{run.applied ? `fast-forwarded ${run.target}` : run.apply_error ?? "dry run, target unchanged"}</span>
          </div>
        </div>
      )}
    </section>
  );
}

function Checks({ run }: { run: CheckRun }) {
  const [showPassing, setShowPassing] = useState(false);
  const rank: Record<Severity, number> = { fail: 0, warn: 1, info: 2, pass: 3, skip: 4 };
  const sorted = [...run.checks].sort((a, b) => rank[a.status] - rank[b.status]);
  const quiet = sorted.filter((c) => c.status === "pass" || c.status === "skip");
  const loud = sorted.filter((c) => !quiet.includes(c));
  return (
    <section className="panel" aria-label="Checks">
      <div className="panel-head"><h2>Checks</h2>
        <p className="muted">{loud.length} need a look, {quiet.length} passed or skipped</p></div>
      <table className="dense checks">
        <thead><tr><th>Result</th><th>Check</th><th>Detail</th><th className="num">Time</th></tr></thead>
        <tbody>
          {loud.map((c) => <CheckRow key={c.name} c={c} />)}
          {showPassing && quiet.map((c) => <CheckRow key={c.name} c={c} />)}
        </tbody>
      </table>
      {quiet.length > 0 && (
        <button className="text-button" aria-expanded={showPassing} onClick={() => setShowPassing(!showPassing)}>
          {showPassing ? "Hide" : "Show"} {quiet.length} passing and skipped checks
        </button>
      )}
      {run.tests.failed.length > 0 && (
        <div className="failures">
          <h3>Failing test files</h3>
          <ul>{run.tests.failed.map((f) => (
            <li key={f.file}><span className="mono">{f.file}</span>
              {f.failures.slice(0, 3).map((m) => <pre key={m}>{m}</pre>)}</li>
          ))}</ul>
        </div>
      )}
    </section>
  );
}

function CheckRow({ c }: { c: Check }) {
  return (
    <>
      <tr className={`row-${c.status}`}>
        <td className="result"><Shape kind={c.status} /> {SEV_LABEL[c.status]}</td>
        <td><strong>{c.name}</strong>{!c.blocking && <span className="muted"> (comments only)</span>}</td>
        <td className="detail">{c.summary}</td>
        <td className="num tnum">{c.cached ? "cached" : seconds(c.seconds)}</td>
      </tr>
      {c.findings.slice(0, 6).map((f, i) => (
        <tr key={i} className="finding">
          <td />
          <td className="mono">{f.rule}</td>
          <td colSpan={2}><span className="mono">{f.file}{f.line ? `:${f.line}` : ""}</span> {f.message}</td>
        </tr>
      ))}
    </>
  );
}

function History({ runs, now }: { runs: CheckRun[]; now: Date }) {
  return (
    <section className="panel" aria-label="Recent checks">
      <div className="panel-head"><h2>Recent checks</h2></div>
      <table className="dense">
        <thead><tr><th>Verdict</th><th>Branch</th><th>When</th><th className="num">Selected</th><th className="num">Total</th></tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.started + r.tree}>
              <td className="result"><Shape kind={r.verdict === "green" ? "pass" : "fail"} /> {r.verdict === "green" ? "Green" : "Red"}</td>
              <td className="mono">{r.branch}</td>
              <td className="tnum">{ago(r.started, now)}</td>
              <td className="num tnum">{r.tests.selected}/{r.tests.total_files}</td>
              <td className="num tnum">{seconds(r.timings.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
