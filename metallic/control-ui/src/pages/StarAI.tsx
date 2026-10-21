import { LineChart } from "../Chart";
import { ago, clock, ms, num, pct } from "../format";
import * as api from "../api";
import type { BrainFacts, Point, Range, State } from "../types";
import { Dot, Empty, ErrorLine, RangePicker, SERIES, pts, usePoll, useSeries, type Health } from "../ui";

function svcHealth(active: string): Health {
  return active === "active" ? "ok" : active === "failed" ? "crit" : active === "activating" || active === "reloading" ? "warn" : "off";
}

export function StarAI({ state, range, setRange }: { state: State; range: Range; setRange: (r: Range) => void }) {
  const star = state.star;
  const chat = star.models.filter((m) => !m.helper);
  const loaded = chat.filter((m) => m.status === "loaded");
  const brainMachine = Object.keys(star.brains)[0] ?? "brain1";
  const keys = loaded.flatMap((m) => [`llm.brain1.${m.id}.tps`, `llm.brain1.${m.id}.prompt_ms`, `llm.brain1.${m.id}.busy`,
    `llm.brain1.${m.id}.deferred`]).concat(["llm.brain2.star-ns-brain.tps"]);
  const { data: s, error } = useSeries(keys, range);
  const speed = usePoll(api.speed, 300_000);
  const base = { from: s?.from ?? 0, to: s?.to ?? 0, step: s?.step ?? 5 };
  const weekFrom = state.generated - 7 * 86400;
  const speedLines = Array.from(new Set((speed.data ?? []).map((h) => `${h.machine}/${h.model}`))).slice(0, 3)
    .map((name, i) => ({ key: name, label: name.replace("/", ": "), color: SERIES[i],
      points: (speed.data ?? []).filter((h) => `${h.machine}/${h.model}` === name)
        .map((h) => [h.t, h.tps_median, h.tps_median, h.tps_median] as Point) }));
  return (
    <div className="page">
      <header className="page-head">
        <h1>Star AI</h1>
        <p className="muted">Models and their live speed, night school, the conductor, knowledge search and the Discord bot.
          Router data {star.models_at ? ago(star.models_at, state.generated) : "not received yet"}.</p>
      </header>

      <section className="block">
        <h2>Models on brain 1</h2>
        {!star.models.length ? <Empty>No answer from the brain router yet (it is polled every 10 s; models that are not loaded are never asked anything, so they stay unloaded).</Empty> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Model</th><th>State</th><th>Slots busy</th><th>Waiting</th><th>Decode now</th>
                <th>Output now</th><th>Prompt speed</th><th>Draft accepted</th><th>Prompt cache share</th><th>Context</th></tr></thead>
              <tbody>
                {star.models.map((m) => (
                  <tr key={m.id} className={m.status === "loaded" ? "" : "dim"}>
                    <td className="mono">{m.id}{m.helper ? <span className="muted"> (helper)</span> : null}</td>
                    <td><Dot h={m.status === "loaded" ? "ok" : "none"} word={m.status} /></td>
                    <td className="num">{m.slots ? `${m.slots.busy} of ${m.slots.total}` : m.parallel ? `${m.parallel} slots` : " "}</td>
                    <td className="num">{m.live?.deferred ?? (m.status === "loaded" && !m.helper ? "n/a" : " ")}</td>
                    <td className="num">{m.live?.decode_tps != null ? num(m.live.decode_tps, 1, "tok/s") : m.status === "loaded" && !m.helper ? "idle" : " "}</td>
                    <td className="num">{m.live?.output_tps != null ? num(m.live.output_tps, 1, "tok/s") : " "}</td>
                    <td className="num">{m.live?.prompt_tps != null ? num(m.live.prompt_tps, 0, "tok/s") : " "}</td>
                    <td className="num">{m.live?.draft_accept != null ? pct(m.live.draft_accept * 100) : m.spec ? <span className="muted">{m.spec}</span> : " "}</td>
                    <td className="num">{m.live?.cache_share_total != null ? pct(m.live.cache_share_total * 100) : " "}
                      {m.cache_ram_mib ? <span className="muted"> ({(m.cache_ram_mib / 1024).toFixed(0)} GB cache)</span> : null}</td>
                    <td className="num">{m.ctx ? `${Math.round(m.ctx / 1024)}k` : " "}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted small">Decode now = tokens per second while a slot generates, between the last two polls. Output now = tokens
          produced per wall-clock second. Prompt cache share = cached prompt tokens over all prompt tokens since the model loaded.</p>
      </section>

      <div className="toolbar"><h2 className="inline">Request speed</h2><RangePicker value={range} onChange={setRange} /></div>
      <ErrorLine error={error} />
      <div className="charts">
        <LineChart title="Decode speed per finished request, tokens per second" {...base} fmt={(v) => v.toFixed(0)}
                   empty="No request finished in this range."
                   lines={[...loaded.map((m, i) => ({ key: m.id, label: m.id, color: SERIES[i % 3], points: pts(s, `llm.brain1.${m.id}.tps`) })),
                     { key: "b2", label: "brain 2 model", color: SERIES[2], points: pts(s, "llm.brain2.star-ns-brain.tps") }]
                     .filter((l) => l.points.length).slice(0, 3)} />
        <LineChart title="Prompt time per request (time to first token, without queueing)" {...base} fmt={(v) => ms(v)}
                   empty="No request finished in this range."
                   lines={loaded.map((m, i) => ({ key: m.id, label: m.id, color: SERIES[i % 3], points: pts(s, `llm.brain1.${m.id}.prompt_ms`) }))
                     .filter((l) => l.points.length).slice(0, 3)} />
        <LineChart title="Slots busy and requests waiting (star-fast)" {...base} fmt={(v) => v.toFixed(0)}
                   lines={[{ key: "busy", label: "Busy slots", color: SERIES[0], points: pts(s, "llm.brain1.star-fast.busy") },
                           { key: "wait", label: "Waiting", color: SERIES[1], points: pts(s, "llm.brain1.star-fast.deferred") }]} />
        <LineChart title="Speed history: hourly median decode speed, last week" from={weekFrom} to={state.generated} step={3600}
                   fmt={(v) => v.toFixed(0)} lines={speedLines}
                   empty={speed.error ? `Could not load: ${speed.error}` : "History builds up from the collector's start (kept 8 days)."} />
      </div>

      <section className="block">
        <h2>Recent requests</h2>
        {!star.requests.length ? <Empty>No request finished in the last hour.</Empty> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Finished</th><th>Machine</th><th>Model</th><th>Slot</th><th>Prompt tokens</th><th>Prompt time</th>
                <th>Output tokens</th><th>Decode</th></tr></thead>
              <tbody>
                {star.requests.slice(0, 15).map((r, i) => (
                  <tr key={i}>
                    <td>{clock(r.t)}</td><td>{r.machine}</td><td className="mono">{r.model}</td><td className="num">{r.slot}</td>
                    <td className="num">{r.prompt_tokens ?? "n/a"}</td><td className="num">{ms(r.prompt_ms)}</td>
                    <td className="num">{r.eval_tokens ?? "n/a"}</td>
                    <td className="num">{r.eval_ms && r.eval_tokens ? num((r.eval_tokens * 1000) / r.eval_ms, 1, "tok/s") : "n/a"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="brains">
        {Object.entries(star.brains).length === 0 && <Empty>No STAR facts yet (they arrive once a minute from each brain's gate).</Empty>}
        {Object.entries(star.brains).map(([id, f]) => <BrainCard key={id} id={id} f={f} state={state} />)}
      </div>
      <p className="muted small">Facts come from STAR's own allow-listed gate (the Discord bot's `facts` verb) once a minute. Main brain: {brainMachine}.</p>
    </div>
  );
}

function BrainCard({ id, f, state }: { id: string; f: BrainFacts; state: State }) {
  const name = state.machines.find((m) => m.id === id)?.name ?? id;
  if (f.ok === false) return <article className="brain"><h2>{name}</h2><Empty>STAR facts unavailable: {f.error}</Empty></article>;
  const ns = f.night_school;
  const hours = Object.entries(ns?.hours ?? {}).slice(-24);
  const maxH = Math.max(1, ...hours.map(([, h]) => (h.first ?? 0) + (h.lesson ?? 0) + (h.validation ?? 0)));
  const today = hours.filter(([k]) => k.slice(0, 10) === new Date().toISOString().slice(0, 10));
  const tries = today.reduce((a, [, h]) => a + (h.first ?? 0) + (h.lesson ?? 0) + (h.validation ?? 0), 0);
  const passed = today.reduce((a, [, h]) => a + (h.first_pass ?? 0) + (h.lesson_pass ?? 0) + (h.validation_pass ?? 0), 0);
  const wd = f.knowledge_watchdog;
  const discord = f.services?.find((s) => s.unit === "star-discord.service");
  return (
    <article className="brain">
      <header><h2>{name}</h2><span className="muted small">facts {ago(f.at, state.generated)}</span></header>
      {ns && (
        <section>
          <h3>Night school <Dot h={ns.paused ? "warn" : "ok"} word={ns.paused ? "Paused (HOLD)" : "Running"} /></h3>
          <p className="kv"><span>Today (UTC)</span><strong>{tries} tries, {passed} passed</strong>
            <span>Speed</span><strong>{num(ns.report?.answers_per_active_hour, 1, "answers per active hour")}</strong>
            <span>Verified examples</span><strong>{ns.report?.examples_total ?? "n/a"}</strong></p>
          {hours.length > 0 && (
            <div className="bars" role="img" aria-label={`Night school attempts per hour, last ${hours.length} hours`}>
              {hours.map(([k, h]) => {
                const total = (h.first ?? 0) + (h.lesson ?? 0) + (h.validation ?? 0);
                const ok = (h.first_pass ?? 0) + (h.lesson_pass ?? 0) + (h.validation_pass ?? 0);
                return (
                  <span key={k} className="bar" title={`${k.slice(11, 13)}:00 UTC: ${total} tries, ${ok} passed`}>
                    <i className="bar-try" style={{ height: `${(total / maxH) * 100}%` }} />
                    <i className="bar-pass" style={{ height: `${(ok / maxH) * 100}%` }} />
                  </span>
                );
              })}
            </div>
          )}
          {hours.length > 0 && <p className="legend small"><span><i style={{ background: SERIES[0] }} />tries</span>
            <span><i style={{ background: SERIES[2] }} />passed</span><span className="muted">per hour, last {hours.length} h (hover a bar for its numbers)</span></p>}
          {ns.report?.status && <p className="muted small">{ns.report.status}</p>}
        </section>
      )}
      {f.conductor && (
        <section>
          <h3>Night conductor {f.conductor.off ? <Dot h="warn" word="Off" /> : null}</h3>
          <p className="kv"><span>Night</span><strong>{f.conductor.night}</strong>
            <span>Tasks created</span><strong>{f.conductor.created ?? "n/a"}</strong>
            <span>Accepted / rejected</span><strong>{f.conductor.accepted ?? "n/a"} / {f.conductor.rejected ?? "n/a"}</strong></p>
        </section>
      )}
      {wd && (
        <section>
          <h3>Knowledge service <Dot h={wd.ok ? "ok" : "warn"} word={wd.ok ? "Watchdog OK" : `Watchdog: ${wd.failures} failures`} /></h3>
          <p className="muted small">Checked {ago(wd.checked_at, state.generated)}.{wd.restarts.length
            ? ` Last watchdog restart ${ago(wd.restarts[wd.restarts.length - 1].at, state.generated)}: ${wd.restarts[wd.restarts.length - 1].reason}.` : " No watchdog restarts on record."}</p>
        </section>
      )}
      {discord && (
        <section>
          <h3>Discord bot <Dot h={svcHealth(discord.active)} word={discord.active === "active" ? "Online" : discord.active} /></h3>
          <p className="muted small">Up since {discord.since || "n/a"}, {discord.restarts} automatic restarts.</p>
        </section>
      )}
      {(ns?.gates ?? []).length > 0 && (
        <section>
          <h3>Latest lesson gate results</h3>
          <ul className="gates">
            {ns!.gates!.slice(-5).reverse().map((g, i) => (
              <li key={i}><span className="muted">{clock(Date.parse(g.ts) / 1000)}</span> <strong>{g.event}</strong> {g.text}</li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h3>Services</h3>
        <ul className="svc">
          {(f.services ?? []).filter((s) => s.unit.endsWith(".service")).map((s) => (
            <li key={s.unit}><Dot h={svcHealth(s.active)} word={s.unit.replace(".service", "")} />
              <span className="muted small">{s.active === "active" ? s.sub : `${s.active} (${s.result})`}</span></li>
          ))}
        </ul>
      </section>
    </article>
  );
}
