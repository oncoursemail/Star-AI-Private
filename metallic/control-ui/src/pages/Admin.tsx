import { useEffect, useRef, useState } from "react";
import * as api from "../api";
import { ago, stamp } from "../format";
import type { Action, AuditRow, State } from "../types";
import { Dot, Empty, ErrorLine, usePoll, type Health } from "../ui";

export function buttonWord(verb: string): string {
  const head = verb.split(":")[0];
  return ({ restart: "Restart", "ns-pause": "Pause", "ns-resume": "Resume", "runner-start": "Start",
    "runner-stop": "Stop", "backup-now": "Back up", "sunshine-start": "Start", "sunshine-stop": "Stop" } as
    Record<string, string>)[head] ?? "Run";
}

const STATE_H: Record<AuditRow["state"], Health> = { ok: "ok", failed: "crit", refused: "crit", pending: "warn" };

/** What the owner should know before confirming, from live data (busy slots, a running backup, a busy runner). */
export function warnings(a: Action, state: State): string[] {
  const out: string[] = [];
  const fast = state.star.models.find((m) => m.id === "star-fast");
  if (a.verb === "restart:star-brain" && fast?.slots && fast.slots.busy > 0)
    out.push(`star-fast is answering right now (${fast.slots.busy} of ${fast.slots.total} slots busy): those answers are cut off.`);
  if (a.verb.startsWith("backup-now:")) {
    const set = a.verb.slice(11);
    const b = state.backups.find((x) => x.set === set);
    if (b?.in_progress) out.push("This backup is already running; a second start waits for it or does nothing.");
  }
  if (a.verb === "runner-stop:github" && state.dev_pc?.runners?.some((r) => r.busy))
    out.push("A GitHub runner is busy with a job right now.");
  const m = state.machines.find((x) => x.id === a.machine);
  if (m && !m.online && !m.pending) out.push(`${m.name} is not reporting; the action may not reach it.`);
  return out;
}

export function Admin({ state }: { state: State }) {
  const acts = usePoll(api.actions, 600_000);
  const audit = usePoll(api.audit, 4_000);
  const [pick, setPick] = useState<Action | null>(null);
  const groups = new Map<string, Action[]>();
  for (const a of acts.data ?? []) groups.set(a.group, [...(groups.get(a.group) ?? []), a]);
  return (
    <div className="page">
      <header className="page-head">
        <h1>Admin</h1>
        <p className="muted">Only these allow-listed actions exist. Each one asks for confirmation and lands in the audit log below.
          No shell, no passwords, nothing that needs sudo.</p>
      </header>
      <ErrorLine error={acts.error} />
      {acts.loading && !acts.data ? <p className="muted">Loading the allow-list…</p> : !(acts.data ?? []).length ? <Empty>This deployment offers no actions.</Empty> : (
        <div className="action-groups">
          {[...groups.entries()].map(([group, list]) => (
            <section key={group} className="action-group">
              <h2>{group}</h2>
              <ul>
                {list.map((a) => (
                  <li key={a.id}>
                    <div>
                      <strong>{a.label}</strong> <span className="muted">on {a.machine_name}</span>
                      <p className="muted small">{a.detail}</p>
                    </div>
                    <button className={a.danger === "high" ? "btn btn-danger" : "btn"} onClick={() => setPick(a)}>
                      {buttonWord(a.verb)}…
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      <section className="block">
        <h2>Audit log</h2>
        <ErrorLine error={audit.error} />
        {!(audit.data ?? []).length ? <Empty>No admin actions yet.</Empty> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>When</th><th>Action</th><th>Who</th><th>Result</th><th>Output</th></tr></thead>
              <tbody>
                {audit.data!.map((r) => (
                  <tr key={r.id}>
                    <td>{stamp(r.ts)}<div className="muted small">{ago(r.ts)}</div></td>
                    <td>{r.label}<div className="muted small mono">{r.action}</div></td>
                    <td className="small">{r.actor}<div className="muted">{r.client}</div></td>
                    <td><Dot h={STATE_H[r.state]} word={r.state + (r.exit != null ? ` (exit ${r.exit})` : "")} /></td>
                    <td className="small">{r.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {pick && <Confirm action={pick} state={state} onClose={() => setPick(null)} />}
    </div>
  );
}

function Confirm({ action, state, onClose }: { action: Action; state: State; onClose: () => void }) {
  const dlg = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    const d = dlg.current;
    d?.showModal();
    return () => d?.close();
  }, []);
  const warn = warnings(action, state);
  const run = async () => {
    setBusy(true);
    try {
      const r = await api.runAction(action.id);
      setResult({ ok: r.ok, text: `Started (audit #${r.audit}): ${r.text}. The result appears in the audit log.` });
    } catch (e) {
      setResult({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <dialog ref={dlg} className="dialog" onClose={onClose} aria-labelledby="confirm-h">
      <h2 id="confirm-h">{action.label} on {action.machine_name}?</h2>
      <p>{action.detail}</p>
      {warn.map((w) => <p key={w} className="warn-text"><Dot h="warn" word="Note" /> {w}</p>)}
      <p className="muted small mono">{action.id}</p>
      {result && <p className={result.ok ? "ok-text" : "bad-text"} role="status">{result.text}</p>}
      <div className="dialog-actions">
        <button className="btn" onClick={onClose} autoFocus={action.danger === "high"}>{result ? "Close" : "Cancel"}</button>
        {!result && (
          <button className={action.danger === "high" ? "btn btn-danger" : "btn btn-primary"} onClick={run} disabled={busy}
                  autoFocus={action.danger !== "high"}>
            {busy ? "Starting…" : `Yes, ${action.label.toLowerCase()}`}
          </button>
        )}
      </div>
    </dialog>
  );
}
