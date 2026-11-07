import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api";
import { ago } from "./format";
import type { Range, State } from "./types";
import { Dot, usePoll } from "./ui";
import { Admin } from "./pages/Admin";
import { Backups } from "./pages/Backups";
import { Dev } from "./pages/Dev";
import { Overview } from "./pages/Overview";
import { Servers } from "./pages/Servers";
import { StarAI } from "./pages/StarAI";

export const PAGES = [
  ["overview", "Overview"], ["servers", "Servers"], ["star", "Star AI"], ["dev", "Metallic dev"],
  ["backups", "Backups"], ["admin", "Admin"],
] as const;
type Page = (typeof PAGES)[number][0];

function fromHash(): { page: Page; machine: string } {
  const [page, machine] = window.location.hash.replace(/^#\/?/, "").split("/");
  return { page: (PAGES.some(([p]) => p === page) ? page : "overview") as Page, machine: machine ?? "" };
}

export function App() {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  useEffect(() => {
    api.session().then(setSignedIn).catch(() => setSignedIn(false));
    const out = () => setSignedIn(false);
    window.addEventListener("mc-signed-out", out);
    return () => window.removeEventListener("mc-signed-out", out);
  }, []);
  if (signedIn === null) return <div className="boot" role="status">Checking your session…</div>;
  if (!signedIn) return <Login onDone={() => setSignedIn(true)} />;
  return <Shell onSignOut={() => api.logout().finally(() => setSignedIn(false))} />;
}

function Login({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim()) { setError("Paste the token first."); return; }
    setBusy(true);
    setError("");
    try {
      await api.login(token.trim());
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="login">
      <form onSubmit={submit} className="login-card">
        <h1 className="wordmark">Metallic Control</h1>
        <p className="muted">Owner sign-in. The token is in <code>%USERPROFILE%\.star\metallic-control-token</code> on the owner's PC.</p>
        <label htmlFor="tok">Login token</label>
        <input id="tok" type="password" autoComplete="off" spellCheck={false} value={token} autoFocus
               onChange={(e) => setToken(e.target.value)} aria-invalid={!!error} aria-describedby="tok-err" />
        <p id="tok-err" className="bad-text" role="alert">{error}</p>
        <button className="btn btn-primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}

function Shell({ onSignOut }: { onSignOut: () => void }) {
  const [{ page, machine }, setNav] = useState(fromHash);
  const [range, setRange] = useState<Range>("hour");
  const [help, setHelp] = useState(false);
  const { data: state, error } = usePoll<State>(api.state, 5_000);
  const [recorded, setRecorded] = useState<number | null>(null);
  useEffect(() => { api.sampleRecorded().then(setRecorded); }, []);
  const main = useRef<HTMLElement>(null);

  const go = useCallback((p: string, m?: string) => {
    window.location.hash = `/${p}${m ? "/" + m : ""}`;
  }, []);
  useEffect(() => {
    const on = () => { setNav(fromHash()); main.current?.focus({ preventScroll: true }); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const machines = state?.machines.filter((m) => !m.pending).map((m) => m.id) ?? [];
  const currentMachine = machines.includes(machine) ? machine : machines[0] ?? "";

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.ctrlKey || e.metaKey || e.altKey || t.closest("input, textarea, select, dialog")) return;
      const n = Number(e.key);
      if (n >= 1 && n <= PAGES.length) { go(PAGES[n - 1][0]); return; }
      if (e.key === "?") { setHelp(true); return; }
      if (["h", "d", "w"].includes(e.key) && (page === "servers" || page === "star"))
        setRange(({ h: "hour", d: "day", w: "week" } as const)[e.key as "h" | "d" | "w"]);
      if ((e.key === "[" || e.key === "]") && page === "servers" && machines.length) {
        const i = machines.indexOf(currentMachine);
        go("servers", machines[(i + (e.key === "]" ? 1 : machines.length - 1)) % machines.length]);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [go, page, machines, currentMachine]);

  const crit = state?.alerts.filter((a) => a.level === "crit").length ?? 0;
  const warn = state?.alerts.filter((a) => a.level === "warn").length ?? 0;
  const fresh = state ? Date.now() / 1000 - state.generated < 20 || recorded != null : false;
  return (
    <div className="shell">
      <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); main.current?.focus(); }}>Skip to content</a>
      <nav className="rail" aria-label="Pages">
        <div className="wordmark">Metallic<span>Control</span></div>
        <ul>
          {PAGES.map(([p, label], i) => (
            <li key={p}>
              <a href={`#/${p}`} aria-current={page === p ? "page" : undefined}>
                <span>{label}</span><kbd aria-hidden="true">{i + 1}</kbd>
                {p === "overview" && (crit + warn) > 0 && <span className={`count count-${crit ? "crit" : "warn"}`}
                  aria-label={`${crit + warn} alerts`}>{crit + warn}</span>}
              </a>
            </li>
          ))}
        </ul>
        <div className="rail-foot">
          <button className="link" onClick={() => setHelp(true)}>Keyboard keys (?)</button>
          {!api.SAMPLE && <button className="link" onClick={onSignOut}>Sign out</button>}
        </div>
      </nav>
      <div className="main-col">
        <div className="topbar">
          {recorded != null ? (
            <span className="sample-flag" role="note">Static preview with data recorded {new Date(recorded * 1000).toLocaleString()}. Actions are disabled.</span>
          ) : <span />}
          <span className={`fresh ${fresh ? "" : "stale"}`} role="status">
            {state ? <Dot h={fresh ? "ok" : "warn"} word={recorded != null ? "Recorded" : `Updated ${ago(state.generated)}`} />
              : error ? <Dot h="crit" word={`Collector unreachable: ${error}`} /> : "Loading…"}
          </span>
        </div>
        <main id="main" ref={main} tabIndex={-1}>
          {!state ? (error ? <p className="error-line">Could not load the state: {error}. Retrying every 5 s.</p>
            : <p className="muted boot">Loading the first state…</p>) : (
            <>
              {error && <p className="error-line">Could not refresh: {error}. Showing data from {ago(state.generated)}.</p>}
              {page === "overview" && <Overview state={state} go={go} />}
              {page === "servers" && <Servers state={state} machine={currentMachine} setMachine={(id) => go("servers", id)}
                                              range={range} setRange={setRange} />}
              {page === "star" && <StarAI state={state} range={range} setRange={setRange} />}
              {page === "dev" && <Dev state={state} />}
              {page === "backups" && <Backups state={state} />}
              {page === "admin" && <Admin state={state} />}
            </>
          )}
        </main>
      </div>
      {help && <Help onClose={() => setHelp(false)} />}
    </div>
  );
}

function Help({ onClose }: { onClose: () => void }) {
  const dlg = useRef<HTMLDialogElement>(null);
  useEffect(() => { const d = dlg.current; d?.showModal(); return () => d?.close(); }, []);
  return (
    <dialog ref={dlg} className="dialog" onClose={onClose} aria-labelledby="help-h">
      <h2 id="help-h">Keyboard keys</h2>
      <dl className="keys">
        <dt><kbd>1</kbd>…<kbd>6</kbd></dt><dd>Open a page</dd>
        <dt><kbd>h</kbd> <kbd>d</kbd> <kbd>w</kbd></dt><dd>Last hour, day, week (Servers, Star AI)</dd>
        <dt><kbd>[</kbd> <kbd>]</kbd></dt><dd>Previous / next machine (Servers)</dd>
        <dt><kbd>←</kbd> <kbd>→</kbd></dt><dd>Move along a focused chart</dd>
        <dt><kbd>Esc</kbd></dt><dd>Close a dialog</dd>
      </dl>
      <div className="dialog-actions"><button className="btn" onClick={onClose} autoFocus>Close</button></div>
    </dialog>
  );
}
