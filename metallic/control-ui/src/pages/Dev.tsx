import { Meter } from "../Chart";
import { ago, stamp } from "../format";
import type { State } from "../types";
import { Dot, Empty, type Health } from "../ui";

const PROJECTS: [string, string][] = [["Metallic-RC", "RC"], ["Metallic-MC", "MC"], ["Metallic-RB", "RB"],
  ["Metallic-PX", "PX"], ["Star-AI-Private", "STAR"]];

function runHealth(status: string, conclusion?: string): Health {
  const s = (conclusion || status || "").toLowerCase();
  if (["success", "completed"].includes(s)) return "ok";
  if (["failure", "failed", "cancelled", "timed_out", "startup_failure"].includes(s)) return "crit";
  if (["running", "in_progress", "queued", "waiting", "pending", "blocked"].includes(s)) return "warn";
  return "none";
}

export function Dev({ state }: { state: State }) {
  const dev = state.dev ?? {};
  const pc = state.dev_pc;
  const now = state.generated;
  return (
    <div className="page">
      <header className="page-head">
        <h1>Metallic dev</h1>
        <p className="muted">GitHub is still the source of truth (open PRs and Actions come from the owner's PC every 5 minutes,
          {pc ? ` last ${ago(pc.at, now)}` : " not received yet"}); the forge holds the imported copy and its own CI
          ({dev.at ? `read ${ago(dev.at, now)}` : "not read yet"}).</p>
      </header>

      <section className="block">
        <h2>Projects</h2>
        <div className="projects">
          {PROJECTS.map(([repo, short]) => {
            const r = dev.repos?.find((x) => x.name === repo);
            const ms = (dev.milestones ?? []).filter((m) => m.repo === repo);
            const open = ms.reduce((a, m) => a + (m.open ?? 0), 0);
            const closed = ms.reduce((a, m) => a + (m.closed ?? 0), 0);
            const local = pc?.projects?.find((p) => p.name === repo || p.name === short || (short === "STAR" && p.name === "STAR"));
            return (
              <article key={repo} className="project">
                <header><span className="badge-short">{short}</span><h3>{repo}</h3></header>
                {r ? <p className="kv"><span>Open issues</span><strong>{r.open_issues}</strong><span>Open PRs (forge)</span>
                  <strong>{r.open_prs}</strong><span>Forge copy updated</span><strong>{ago(r.updated, now)}</strong></p>
                  : <Empty>Not on the forge yet.</Empty>}
                {ms.length > 0 ? (
                  <div className="ms">
                    <Meter value={closed} max={open + closed} levelOf={() => "ok"} />
                    <span>{closed} of {open + closed} milestone issues closed</span>
                    <ul>{ms.slice(0, 3).map((m) => <li key={m.title} className="small muted">{m.title}: {m.closed}/{m.open + m.closed}{m.state === "closed" ? " (closed)" : ""}</li>)}</ul>
                  </div>
                ) : r ? <p className="muted small">No milestones set, so no progress share to show.</p> : null}
                {local && (
                  <p className="muted small">{local.connected
                    ? `Local clone on ${local.branch ?? "?"} @ ${local.head ?? "?"}${local.release ? `, release ${local.release.tag}` : ""}`
                    : local.note}</p>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <section className="block">
        <h2>Merge queue</h2>
        {!pc?.projects ? <Empty>Waiting for the PC agent (it reads the queue from the local clones).</Empty> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Project</th><th>Waiting in queue</th><th>Last queue run</th><th>Result</th><th>Last check</th></tr></thead>
              <tbody>
                {pc.projects.filter((p) => p.connected).map((p) => {
                  const q = p.queue_runs[0];
                  const c = p.checks[0];
                  return (
                    <tr key={p.name}>
                      <td>{p.name}</td>
                      <td>{p.pending?.length ? p.pending.join(", ") : <span className="muted">empty</span>}</td>
                      <td>{q ? `${stamp(q.started)} (${Math.round(q.seconds)} s)` : <span className="muted">none yet</span>}</td>
                      <td>{q ? `${q.merged?.length ?? 0} landed${q.entries.some((e) => e.status === "rejected") ? `, ${q.entries.filter((e) => e.status === "rejected").length} rejected` : ""}${q.applied ? "" : " (not applied)"}` : " "}</td>
                      <td>{c ? <Dot h={c.verdict === "green" ? "ok" : "crit"} word={`${c.verdict} ${ago(c.started, now)}`} /> : <span className="muted">none yet</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="block two">
        <div>
          <h2>Open PRs on GitHub{pc?.prs ? ` (${pc.prs.length})` : ""}</h2>
          {!pc?.prs ? <Empty>No PR list from the PC agent yet (it needs the owner's gh login on the PC).</Empty> : (
            <ul className="prs">
              {pc.prs.slice(0, 14).map((p) => (
                <li key={p.number}>
                  <a href={p.url} target="_blank" rel="noreferrer">#{p.number}</a>
                  <span className="pr-title">{p.title}</span>
                  <span className="muted small">{p.draft ? "draft · " : ""}{p.author} · {ago(p.updated, now)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h2>CI runners</h2>
          <ul className="svc">
            {(pc?.runners ?? []).map((r) => (
              <li key={"gh" + r.name}><Dot h={r.status === "online" ? (r.busy ? "warn" : "ok") : "off"}
                word={`${r.name}: ${r.status}${r.busy ? ", busy" : ""}`} /><span className="muted small">GitHub</span></li>
            ))}
            {(dev.runners ?? []).map((r) => (
              <li key={"fg" + r.name}><Dot h={r.status === "offline" ? "off" : r.status === "active" ? "warn" : "ok"}
                word={`${r.name}: ${r.status}`} /><span className="muted small">forge {r.version}</span></li>
            ))}
            {state.runners.map((r) => (
              <li key={"u" + r.runner}><Dot h={r.state === "active" ? "ok" : "off"} word={`${r.runner} service: ${r.state}`} />
                <span className="muted small">systemd on {r.machine}</span></li>
            ))}
            {!pc?.runners && !dev.runners && !state.runners.length && <li><Empty>No runner data yet.</Empty></li>}
          </ul>
        </div>
      </section>

      <section className="block two">
        <div>
          <h2>Recent GitHub Actions runs</h2>
          {!pc?.runs ? <Empty>Waiting for the PC agent.</Empty> : (
            <ul className="runs">
              {pc.runs.slice(0, 10).map((r) => (
                <li key={r.id}>
                  <Dot h={runHealth(r.status, r.conclusion)} word={r.conclusion || r.status} />
                  <a href={r.url} target="_blank" rel="noreferrer">{r.workflow}</a>
                  <span className="muted small">{r.branch} · {ago(r.updated, now)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h2>Recent forge runs</h2>
          {!(dev.runs ?? []).length ? <Empty>No forge Actions runs recorded.</Empty> : (
            <ul className="runs">
              {dev.runs!.slice(0, 10).map((r, i) => (
                <li key={i}>
                  <Dot h={runHealth(r.status)} word={r.status} />
                  <a href={r.url} target="_blank" rel="noreferrer">{r.name}</a>
                  <span className="muted small">{r.repo} · {r.branch} · {ago(r.updated, now)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="block">
        <h2>Releases</h2>
        {!(dev.releases ?? []).length ? <Empty>No releases on the forge.</Empty> : (
          <table>
            <thead><tr><th>Project</th><th>Tag</th><th>Name</th><th>Published</th></tr></thead>
            <tbody>
              {dev.releases!.map((r) => (
                <tr key={r.repo + r.tag}><td>{r.repo}</td><td className="mono"><a href={r.url} target="_blank" rel="noreferrer">{r.tag}</a></td>
                  <td>{r.name}</td><td>{stamp(r.published)}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
