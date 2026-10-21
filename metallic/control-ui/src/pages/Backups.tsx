import { Meter } from "../Chart";
import { ago, bytes, stamp, toUnix } from "../format";
import type { BackupRow, State } from "../types";
import { Dot, Empty, type Health } from "../ui";

const LIMIT: Record<string, number> = { hourly: 2.5 * 3600, daily: 26 * 3600 };

export function backupHealth(b: BackupRow, now: number): Health {
  if (b.error) return "warn";
  const last = toUnix(b.last_success_utc);
  if (last == null) return "warn";
  const errAt = toUnix(b.last_error?.at);
  if (errAt != null && errAt > last) return "warn";
  return now - last > (LIMIT[b.schedule] ?? LIMIT.daily) ? "warn" : "ok";
}

const LABEL: Record<string, string> = { starai: "Brain 1 (STAR data)", kb: "Brain 1 knowledge base", "star-main": "PC (STAR state)" };

export function Backups({ state }: { state: State }) {
  const now = state.generated;
  const fb = state.forge_backups;
  const timers = Object.values(state.timers ?? {}).flat();
  return (
    <div className="page">
      <header className="page-head">
        <h1>Backups and recovery</h1>
        <p className="muted">Restic repositories on brain 2 (encrypted, deduplicated) plus the forge's nightly dumps on brain 1.
          Restore checks restore a snapshot into scratch and compare checksums.</p>
      </header>
      {!state.backups.length ? <Empty>No backup status yet: brain 2's gate reports it once a minute.</Empty> : (
        <div className="table-scroll">
          <table className="backups">
            <thead><tr><th>Set</th><th>State</th><th>Last snapshot</th><th>Added</th><th>Repository vs budget</th>
              <th>Restore check</th><th>Baseline</th></tr></thead>
            <tbody>
              {state.backups.map((b) => {
                const used = b.repository_bytes, max = b.max_repository_bytes;
                return (
                  <tr key={b.set}>
                    <td><strong>{LABEL[b.set] ?? b.set}</strong><div className="muted small">{b.where} · {b.schedule}</div></td>
                    <td><Dot h={backupHealth(b, now)} word={b.in_progress ? "Running now" : backupHealth(b, now) === "ok" ? "OK" : "Check"} />
                      {b.last_error && toUnix(b.last_error.at)! > (toUnix(b.last_success_utc) ?? 0) &&
                        <div className="small bad-text">{b.last_error.action} failed {ago(b.last_error.at, now)}: {b.last_error.message}</div>}
                      {b.error && <div className="small bad-text">{b.error}</div>}</td>
                    <td>{ago(b.last_success_utc, now)}<div className="muted small"><span className="mono">{b.last_snapshot_id || " "}</span> · {stamp(b.last_success_utc)}</div></td>
                    <td className="num">{bytes(b.data_added_packed)}<div className="muted small">{bytes(b.data_added)} before packing</div></td>
                    <td><Meter value={used} max={max} /><div className="small">{bytes(used)} of {max ? bytes(max, 0) : "no budget"}
                      {used && max ? ` (${Math.round((100 * used) / max)} %)` : ""}</div></td>
                    <td>{b.last_restore_verification ? <>
                      <Dot h={now - (toUnix(b.last_restore_verification.verified_utc) ?? 0) > 2 * 86400 ? "warn" : "ok"}
                           word={ago(b.last_restore_verification.verified_utc, now)} />
                      <div className="muted small">{b.last_restore_verification.files} files, {b.last_restore_verification.sqlite_databases} SQLite checked</div></>
                      : <span className="muted">none recorded</span>}
                      {b.last_ingest_validation && <div className="muted small">ingest check {ago(b.last_ingest_validation.verified_utc, now)}</div>}</td>
                    <td>{b.baseline_verification ? `verified ${ago(b.baseline_verification.verified_utc, now)}` : <span className="muted">none</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <section className="block two">
        <div>
          <h2>Forge dumps (brain 1)</h2>
          {!fb ? <Empty>No forge backup listing yet (read every 5 minutes).</Empty> : (
            <>
              <p className="kv"><span>Files kept</span><strong>{fb.count}</strong><span>Total</span><strong>{bytes(fb.total_bytes)}</strong>
                <span>Newest</span><strong>{fb.files.length ? ago(fb.files[fb.files.length - 1].t, now) : "n/a"}</strong></p>
              <ul className="files">
                {fb.files.slice().reverse().map((f) => (
                  <li key={f.name}><span className="mono small">{f.name}</span><span className="num">{bytes(f.bytes)}</span></li>
                ))}
              </ul>
              <p className="muted small">Daily at 03:30 UTC, kept 7 days. Restore procedure: docs/agents/metallic-forge-20261020.md.</p>
            </>
          )}
        </div>
        <div>
          <h2>Schedules on brain 2</h2>
          {!timers.length ? <Empty>No timer data yet.</Empty> : (
            <table>
              <thead><tr><th>Job</th><th>Next run</th></tr></thead>
              <tbody>
                {timers.map((t) => (
                  <tr key={t.unit}><td className="mono small">{t.unit.replace(".timer", "")}</td><td className="small">{t.next || "not scheduled"}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          {state.backup_pc && (
            <p className="muted small">PC export side: last success {ago(state.backup_pc.last_success_utc, now)}
              {state.backup_pc.error ? `, error: ${state.backup_pc.error}` : ""}.</p>
          )}
        </div>
      </section>
    </div>
  );
}
