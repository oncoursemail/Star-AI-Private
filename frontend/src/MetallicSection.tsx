import {useCallback, useEffect, useRef, useState, type ReactNode} from 'react'
import {CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts'
import {CheckCircle2, CircleDashed, CircleX, Clock3, FolderGit2, HardDrive, LoaderCircle, RefreshCw, Server, WifiOff} from 'lucide-react'
import {LinkExternal, Panel} from './components'
import {EmptyState, ErrorState, LoadingState} from './states'
import {useStarReducedMotion} from './MotionPolicy'
import {usePageVisible} from './usePageVisible'
import {askHost, clockTime, metallicPreview, type DevPcProject, type DevState, type MachineState, type MetallicRange,
  type MetallicReply, type MetallicSession, type MetallicState, type SpeedHour} from './metallic'
import './metallic.css'

const REFRESH_MS = 30000
/** Charts use the validated six-slot categorical palette (metallic.css); more series than this fold into the table. */
const MAX_LINES = 6
const RANGES: [MetallicRange, string][] = [['hour', 'Last hour'], ['day', 'Last day'], ['week', 'Last week']]

/* ---------- formatting: units always shown, a missing value is "n/a", never a zero ---------- */
const NA = 'n/a'
const toUnix = (t: number | string | null | undefined): number | null => {
  if (t === null || t === undefined || t === '') return null
  if (typeof t === 'number') return t
  const v = Date.parse(t)
  return Number.isNaN(v) ? null : v / 1000
}
function ago(t: number | string | null | undefined, now: number): string {
  const s = toUnix(t)
  if (s === null) return NA
  const d = Math.max(0, now - s)
  if (d < 60) return `${Math.round(d)} s ago`
  if (d < 3600) return `${Math.round(d / 60)} min ago`
  if (d < 172800) return `${(d / 3600).toFixed(d < 36000 ? 1 : 0)} h ago`
  return `${Math.round(d / 86400)} d ago`
}
function bytes(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return NA
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let x = Math.abs(v)
  let i = 0
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i++ }
  return `${x.toFixed(i === 0 || x >= 100 ? 0 : 1)} ${units[i]}`
}
const pct = (v: number | null | undefined) => v === null || v === undefined || !Number.isFinite(v) ? NA : `${Math.round(v)} %`
const msText = (v: number) => v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)} s` : `${Math.round(v)} ms`

type Health = 'ok' | 'bad' | 'busy' | 'none'
function runHealth(status: string, conclusion?: string): Health {
  const s = (conclusion || status || '').toLowerCase()
  if (['success', 'completed', 'passed', 'green', 'ok', 'online', 'idle', 'active'].includes(s)) return 'ok'
  if (['failure', 'failed', 'cancelled', 'timed_out', 'startup_failure', 'red', 'offline', 'error'].includes(s)) return 'bad'
  if (['running', 'in_progress', 'queued', 'waiting', 'pending', 'blocked', 'busy'].includes(s)) return 'busy'
  return 'none'
}
/** "in_progress" reads "in progress". */
const words = (value: string) => value.replace(/_/g, ' ')
/** A state is always a word with an icon, never a color alone. */
function StateWord({health, children}: {health: Health; children: ReactNode}) {
  const Icon = health === 'ok' ? CheckCircle2 : health === 'bad' ? CircleX : health === 'busy' ? Clock3 : CircleDashed
  return <span className={`metallic-state is-${health}`}><Icon size={13} aria-hidden="true" />{children}</span>
}

/* ---------- time-series chart ---------- */
type ChartLine = {label: string; points: [number, number | null][]}
type TipProps = {active?: boolean; label?: number; payload?: ReadonlyArray<{dataKey?: unknown; value?: unknown}>}

function ChartTip({active, label, payload, lines, format, withDay}: TipProps & {lines: ChartLine[]; format: (v: number) => string; withDay: boolean}) {
  if (!active || !payload?.length || typeof label !== 'number') return null
  return (
    <div className="metallic-tip">
      <strong>{clockTime(label, withDay)}</strong>
      {payload.map(item => {
        const index = Number(String(item.dataKey).slice(1))
        return typeof item.value === 'number' ? (
          <span key={String(item.dataKey)}><i className={`metallic-swatch s${index + 1}`} aria-hidden="true" />{lines[index]?.label}: {format(item.value)}</span>
        ) : null
      })}
    </div>
  )
}

/** One question per chart (the title), the unit on the value axis, local time on the other, a legend for two or more
 *  lines, a hover read-out, and the same numbers as a table. */
export function TimeChart({title, unit, lines, from, to, format, yMax, empty, withDay = false}: {
  title: string
  /** The value axis label, with its unit: "% busy", "tokens per second". */
  unit: string
  lines: ChartLine[]
  from: number
  to: number
  format: (v: number) => string
  yMax?: number
  empty: string
  withDay?: boolean
}) {
  const reduced = useStarReducedMotion()
  const shown = lines.slice(0, MAX_LINES)
  const byTime = new Map<number, Record<string, number | null>>()
  shown.forEach((line, i) => line.points.forEach(([t, v]) => {
    const row = byTime.get(t) ?? {t}
    row[`s${i}`] = v
    byTime.set(t, row)
  }))
  const rows = [...byTime.values()].sort((a, b) => (a.t as number) - (b.t as number))
  // A series with many missing samples (an hour without requests) would draw as invisible fragments: mark its points.
  const sparse = shown.map((_, i) => rows.filter(row => typeof row[`s${i}`] === 'number').length < rows.length * 0.8)
  const stats = shown.map(line => {
    const values = line.points.map(p => p[1]).filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
    return {label: line.label, latest: values.at(-1), average: values.length ? values.reduce((a, b) => a + b, 0) / values.length : undefined, peak: values.length ? Math.max(...values) : undefined}
  })
  const hasData = stats.some(s => s.latest !== undefined)
  return (
    <figure className="metallic-chart">
      <figcaption>
        <strong>{title}</strong>
        {shown.length > 1 && hasData && (
          <span className="metallic-legend">{shown.map((line, i) => <span key={line.label}><i className={`metallic-swatch s${i + 1}`} aria-hidden="true" />{line.label}</span>)}</span>
        )}
      </figcaption>
      {!hasData ? <p className="metallic-chart-empty">{empty}</p> : <>
        <span className="metallic-axis-y">{unit}</span>
        <div className="metallic-plot" role="img" aria-label={`${title}. ${stats.filter(s => s.latest !== undefined).map(s => `${s.label}: latest ${format(s.latest!)}, peak ${format(s.peak!)}`).join('; ')}`}>
          <ResponsiveContainer width="100%" height={196} initialDimension={{width: 560, height: 196}}>
            <LineChart data={rows} margin={{top: 6, right: 14, bottom: 0, left: 2}}>
              <CartesianGrid vertical={false} stroke="var(--star-stroke-soft)" />
              <XAxis dataKey="t" type="number" scale="time" domain={[from, to]} allowDataOverflow tickFormatter={(t: number) => clockTime(t, withDay)}
                tickLine={false} axisLine={{stroke: 'var(--star-stroke)'}} minTickGap={40} tick={{fill: 'var(--star-faint)', fontSize: 11}} />
              <YAxis domain={[0, yMax ?? 'auto']} tickFormatter={(v: number) => format(v)} width={56} tickLine={false} axisLine={false}
                allowDecimals={false} tick={{fill: 'var(--star-faint)', fontSize: 11}} />
              <Tooltip cursor={{stroke: 'var(--star-stroke-strong)'}} isAnimationActive={false}
                content={props => <ChartTip {...(props as TipProps)} lines={shown} format={format} withDay={withDay} />} />
              {shown.map((line, i) => (
                <Line key={line.label} dataKey={`s${i}`} name={line.label} className={`metallic-line s${i + 1}`} stroke={`var(--metallic-series-${i + 1})`}
                  strokeWidth={2} connectNulls={false} isAnimationActive={!reduced}
                  dot={sparse[i] ? {r: 4, strokeWidth: 2, stroke: 'var(--star-surface-1)', fill: `var(--metallic-series-${i + 1})`} : false}
                  activeDot={{r: 4, strokeWidth: 2, stroke: 'var(--star-surface-1)', fill: `var(--metallic-series-${i + 1})`}} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <span className="metallic-axis-x">Local time</span>
        <details className="metallic-numbers">
          <summary>Show the numbers</summary>
          <table>
            <thead><tr><th scope="col">{shown.length > 1 ? 'Series' : 'Value'}</th><th scope="col">Latest</th><th scope="col">Average</th><th scope="col">Peak</th></tr></thead>
            <tbody>{stats.map(s => (
              <tr key={s.label}><th scope="row">{s.label}</th>
                {[s.latest, s.average, s.peak].map((v, i) => <td key={i}>{v === undefined ? NA : format(v)}</td>)}</tr>
            ))}</tbody>
          </table>
          {lines.length > MAX_LINES && <p>Charted: the first {MAX_LINES} of {lines.length}. The table above lists the charted ones.</p>}
        </details>
      </>}
    </figure>
  )
}

/* ---------- Projects ---------- */
/** Forge repository names and the dev PC's short project names for the same project. */
const ALIAS: Record<string, string> = {'metallic-rc': 'rc', 'metallic-mc': 'mc', 'metallic-rb': 'rb', 'metallic-px': 'px', 'star-ai-private': 'star', 'star-ai': 'star'}
const canonical = (name: string) => ALIAS[name.toLowerCase()] ?? name.toLowerCase()
type Repo = NonNullable<DevState['repos']>[number]
type ProjectRow = {key: string; name: string; local?: DevPcProject; repo?: Repo
  prs: {number: number; title: string; draft: boolean; url: string; where: string}[]
  runs: {name: string; status: string; conclusion?: string; branch: string; updated: string; url: string; where: string}[]
  release?: {tag: string; date: string; url?: string}}

function buildProjects(state: MetallicState): ProjectRow[] {
  const rows = new Map<string, ProjectRow>()
  const row = (name: string) => {
    const key = canonical(name)
    let found = rows.get(key)
    if (!found) { found = {key, name, prs: [], runs: []}; rows.set(key, found) }
    return found
  }
  for (const p of state.dev_pc?.projects ?? []) { const r = row(p.name); r.local = p; if (p.release) r.release = {tag: p.release.tag, date: p.release.date} }
  for (const repo of state.dev?.repos ?? []) { const r = row(repo.name); r.repo = repo; r.name = repo.name }
  for (const pr of state.dev?.prs ?? []) row(pr.repo).prs.push({...pr, where: 'forge'})
  for (const run of state.dev?.runs ?? []) row(run.repo).runs.push({...run, where: 'forge CI'})
  for (const rel of state.dev?.releases ?? []) {
    const r = row(rel.repo)
    if (!r.release || (toUnix(rel.published) ?? 0) > (toUnix(r.release.date) ?? 0)) r.release = {tag: rel.tag, date: rel.published, url: rel.url}
  }
  const pc = state.dev_pc
  if (pc?.repo) {
    const r = row(pc.repo.split('/').pop() || pc.repo)
    for (const pr of pc.prs ?? []) r.prs.push({...pr, where: 'GitHub'})
    for (const run of pc.runs ?? []) r.runs.push({name: run.workflow || run.title, status: run.status, conclusion: run.conclusion, branch: run.branch, updated: run.updated, url: run.url, where: 'GitHub Actions'})
  }
  for (const r of rows.values()) r.runs.sort((a, b) => (toUnix(b.updated) ?? 0) - (toUnix(a.updated) ?? 0))
  return [...rows.values()]
}

function ProjectItem({p, now}: {p: ProjectRow; now: number}) {
  const check = p.local?.checks?.[0]
  const queue = p.local?.queue_runs?.[0]
  const run = p.runs[0]
  const branch = p.local?.branch ?? p.repo?.branch
  const facts: [string, ReactNode][] = [
    ['Branch', branch ? <><span className="metallic-mono">{branch}</span>{p.local?.head ? <> at <span className="metallic-mono">{p.local.head}</span></> : null}</> : NA],
    ['Last change', p.repo?.updated ? ago(p.repo.updated, now) : check ? ago(check.started, now) : NA],
    ['Open pull requests', String(p.prs.length || p.repo?.open_prs || 0)],
    ['Open issues', p.repo ? String(p.repo.open_issues) : NA],
    ['Checks', check ? <StateWord health={runHealth(check.verdict)}>{words(check.verdict)}{check.red.length ? `, ${check.red.length} failing` : ''}, {ago(check.started, now)}</StateWord> : NA],
    ['CI', run ? <StateWord health={runHealth(run.status, run.conclusion)}>{words(run.conclusion || run.status)} on {run.where}, {ago(run.updated, now)}</StateWord> : NA],
    ['Queue', queue ? `${queue.merged.length} merged, ${queue.applied ? 'applied' : 'not applied'}, ${ago(queue.started, now)}` : NA],
    ['Release', p.release ? `${p.release.tag}, ${ago(p.release.date, now)}` : 'None yet'],
  ]
  return (
    <article className="metallic-project">
      <header>
        <h3 dir="auto">{p.name}</h3>
        {p.local?.lang && <span className="metallic-chip">{p.local.lang}</span>}
        {p.local && !p.local.connected && <span className="metallic-note">Not connected{p.local.note ? `: ${p.local.note}` : ''}</span>}
        {p.repo?.url && <span className="metallic-link"><LinkExternal href={p.repo.url}>Open</LinkExternal></span>}
      </header>
      <dl className="metallic-facts">{facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      {p.local?.pending?.length ? <p className="metallic-note">Waiting to merge: {p.local.pending.join(', ')}</p> : null}
      {check?.red.length ? <p className="metallic-note">Failing checks: {check.red.slice(0, 6).join(', ')}{check.red.length > 6 ? ` and ${check.red.length - 6} more` : ''}</p> : null}
      {p.prs.length > 0 && (
        <ul className="metallic-prs">{p.prs.slice(0, 4).map(pr => (
          <li key={`${pr.where}-${pr.number}`}><span className="metallic-mono">#{pr.number}</span> <span dir="auto">{pr.title}</span>{pr.draft ? <span className="metallic-chip">draft</span> : null} <span className="metallic-note">{pr.where}</span></li>
        ))}{p.prs.length > 4 && <li className="metallic-note">and {p.prs.length - 4} more</li>}</ul>
      )}
    </article>
  )
}

function ProjectsView({state}: {state: MetallicState}) {
  const projects = buildProjects(state)
  const now = state.generated
  if (!projects.length) return <EmptyState icon={<FolderGit2 size={18} />} title="No projects reported yet" description="Metallic Control has not received repository data from the forge or the dev PC. Projects appear here after its next read." />
  return (
    <div className="metallic-projects">
      <p className="metallic-sub">Forge data read {state.dev?.at ? ago(state.dev.at, now) : 'not yet'}; dev PC data {state.dev_pc ? ago(state.dev_pc.at, now) : 'not received yet'}.</p>
      {projects.map(p => <ProjectItem key={p.key} p={p} now={now} />)}
    </div>
  )
}

/* ---------- Stats ---------- */
function MachinesPanel({state, reply, range}: {state: MetallicState; reply: MetallicReply; range: MetallicRange}) {
  const machines = (state.machines ?? []).filter(m => !m.pending || m.online)
  const series = reply.series
  const lineFor = (m: MachineState, key: string): ChartLine => ({label: m.name, points: (series?.series[`${m.id}.${key}`] ?? []).map(p => [p[0], p[1]])})
  const charted = machines.filter(m => series?.series[`${m.id}.cpu`])
  const withDay = range === 'week'
  return (
    <Panel className="metallic-panel">
      <h2>Machines</h2>
      {!machines.length ? <EmptyState compact icon={<Server size={16} />} title="No machines reported" description="Metallic Control lists machines once their collectors send a first sample." /> : <>
        <div className="metallic-table-wrap" tabIndex={0} role="region" aria-label="Machines right now">
          <table className="metallic-table">
            <thead><tr><th scope="col">Machine</th><th scope="col">State</th><th scope="col">CPU</th><th scope="col">Memory</th><th scope="col">GPU</th><th scope="col">Fullest disk</th><th scope="col">Network in / out</th></tr></thead>
            <tbody>{(state.machines ?? []).map(m => {
              const disk = [...(m.fs ?? [])].sort((a, b) => (b.pct ?? 0) - (a.pct ?? 0))[0]
              return (
                <tr key={m.id}>
                  <th scope="row">{m.name}{m.role ? <small>{m.role}</small> : null}</th>
                  <td>{m.online ? <StateWord health="ok">Online</StateWord> : m.pending ? <StateWord health="busy">{m.pending}</StateWord>
                    : <StateWord health="bad">Offline{m.last_seen ? `, seen ${ago(m.last_seen, state.generated)}` : ''}</StateWord>}</td>
                  <td>{pct(m.cpu)}{m.ncpu ? <small>{m.ncpu} threads</small> : null}</td>
                  <td>{m.mem ? <>{pct(m.mem.pct)}<small>{bytes(m.mem.used)} of {bytes(m.mem.total)}</small></> : NA}</td>
                  <td>{m.gpu ? <>{pct(m.gpu.util)}<small>{m.gpu.mem_total ? `${bytes(m.gpu.mem_used)} of ${bytes(m.gpu.mem_total)}` : m.gpu.name}</small></> : 'None'}</td>
                  <td>{disk ? <>{pct(disk.pct)}<small>{disk.mount}, {bytes(disk.total)}</small></> : NA}</td>
                  <td>{m.net ? `${bytes(m.net.rx)}/s / ${bytes(m.net.tx)}/s` : NA}</td>
                </tr>
              )
            })}</tbody>
          </table>
        </div>
        {!series ? <p className="metallic-chart-empty">Metallic Control sent no history for this range, so only the current values are shown.</p> : (
          <div className="metallic-chart-grid">
            <TimeChart title="CPU busy by machine" unit="% of all threads" yMax={100} format={pct} from={series.from} to={series.to} withDay={withDay}
              lines={charted.map(m => lineFor(m, 'cpu'))} empty="No CPU samples in this range." />
            <TimeChart title="Memory used by machine" unit="% of RAM" yMax={100} format={pct} from={series.from} to={series.to} withDay={withDay}
              lines={charted.map(m => lineFor(m, 'mem_pct'))} empty="No memory samples in this range." />
          </div>
        )}
      </>}
    </Panel>
  )
}

function SpeedPanel({reply, range}: {reply: MetallicReply; range: MetallicRange}) {
  const hours = reply.speed?.hours ?? []
  const groups = new Map<string, SpeedHour[]>()
  for (const h of hours) { const key = `${h.machine} / ${h.model}`; groups.set(key, [...(groups.get(key) ?? []), h]) }
  // The busiest models, then a fixed name order so a model keeps its color between refreshes.
  const names = [...groups.entries()].sort((a, b) => b[1].reduce((s, h) => s + h.n, 0) - a[1].reduce((s, h) => s + h.n, 0))
    .slice(0, MAX_LINES).map(([name]) => name).sort()
  const lines = (pick: (h: SpeedHour) => number) => names.map(name => ({label: name, points: (groups.get(name) ?? []).sort((a, b) => a.t - b.t).map(h => [h.t, pick(h)] as [number, number])}))
  const from = hours.length ? Math.min(...hours.map(h => h.t)) : 0
  const to = hours.length ? Math.max(...hours.map(h => h.t)) : 0
  const busiest = [...groups.entries()].sort((a, b) => b[1].reduce((s, h) => s + h.n, 0) - a[1].reduce((s, h) => s + h.n, 0))[0]
  const latest = busiest ? [...busiest[1]].sort((a, b) => b.t - a.t)[0] : null
  const span = range === 'week' ? 'last 7 days' : 'last 24 hours'
  return (
    <Panel className="metallic-panel">
      <h2>Star speed</h2>
      {!reply.speed ? <p className="metallic-chart-empty">Metallic Control did not send speed data with this refresh.</p>
        : !hours.length ? <EmptyState compact icon={<Clock3 size={16} />} title="No finished requests" description={`No Star request finished in the ${span}, so there is no speed to show.`} /> : <>
          {latest && busiest && (
            <div className="metallic-tiles">
              <div className="metallic-tile"><span>Generation speed</span><strong>{latest.tps_median.toFixed(1)} tok/s</strong><small>{busiest[0]}, hour from {clockTime(latest.t)}, median of {latest.n} requests</small></div>
              <div className="metallic-tile"><span>Wait for the first token</span><strong>{msText(latest.prompt_ms_median)}</strong><small>Prompt processing, same hour, median</small></div>
              <div className="metallic-tile"><span>Requests finished</span><strong>{hours.reduce((s, h) => s + h.n, 0)}</strong><small>All models, {span}</small></div>
            </div>
          )}
          <div className="metallic-chart-grid">
            <TimeChart title={`Generation speed per hour, ${span}`} unit="tokens per second (median)" format={v => v.toFixed(0)} from={from} to={to + 3600} withDay={range === 'week'}
              lines={lines(h => h.tps_median)} empty="No requests in this range." />
            <TimeChart title={`Wait for the first token per hour, ${span}`} unit="milliseconds (median)" format={msText} from={from} to={to + 3600} withDay={range === 'week'}
              lines={lines(h => h.prompt_ms_median)} empty="No requests in this range." />
          </div>
        </>}
    </Panel>
  )
}

const hourTime = (key: string) => { const v = Date.parse(`${key.slice(0, 13)}:00:00Z`); return Number.isNaN(v) ? null : v / 1000 }
function NightSchoolPanel({state, range}: {state: MetallicState; range: MetallicRange}) {
  const brains = Object.entries(state.star?.brains ?? {})
  const nameOf = (id: string) => state.machines?.find(m => m.id === id)?.name ?? id
  const keep = range === 'week' ? 168 : 24
  const lines: ChartLine[] = brains.filter(([, f]) => f.night_school?.hours).map(([id, f]) => ({
    label: nameOf(id),
    points: Object.entries(f.night_school!.hours!).slice(-keep).flatMap(([key, h]) => {
      const t = hourTime(key)
      if (t === null) return []
      const tries = h.first ?? 0
      return [[t, tries > 0 ? ((h.first_pass ?? 0) / tries) * 100 : null] as [number, number | null]]
    }),
  }))
  const times = lines.flatMap(l => l.points.filter(p => p[1] !== null).map(p => p[0]))
  const today = new Date().toISOString().slice(0, 10)
  return (
    <Panel className="metallic-panel">
      <h2>Night school</h2>
      {!brains.length ? <EmptyState compact icon={<CircleDashed size={16} />} title="No brain reported night school facts" description="Each brain sends night school progress with its STAR facts. None arrived yet." /> : <>
        <div className="metallic-table-wrap" tabIndex={0} role="region" aria-label="Night school by brain">
          <table className="metallic-table">
            <thead><tr><th scope="col">Brain</th><th scope="col">State</th><th scope="col">Today (UTC)</th><th scope="col">First-try pass rate, all time</th><th scope="col">Verified examples</th><th scope="col">Speed</th></tr></thead>
            <tbody>{brains.map(([id, f]) => {
              const ns = f.night_school
              if (f.ok === false || !ns) return <tr key={id}><th scope="row">{nameOf(id)}</th><td colSpan={5}>{f.error ? `Facts unavailable: ${f.error}` : 'No night school on this brain.'}</td></tr>
              const day = Object.entries(ns.hours ?? {}).filter(([k]) => k.slice(0, 10) === today)
              const tries = day.reduce((a, [, h]) => a + (h.first ?? 0) + (h.lesson ?? 0) + (h.validation ?? 0), 0)
              const passed = day.reduce((a, [, h]) => a + (h.first_pass ?? 0) + (h.lesson_pass ?? 0) + (h.validation_pass ?? 0), 0)
              const r = ns.report
              return (
                <tr key={id}>
                  <th scope="row">{nameOf(id)}</th>
                  <td>{ns.paused ? <StateWord health="busy">Paused</StateWord> : <StateWord health="ok">Running</StateWord>}</td>
                  <td>{tries} tries, {passed} passed</td>
                  <td>{r?.attempts_total ? `${pct(((r.passed_first_total ?? 0) / r.attempts_total) * 100)} of ${r.attempts_total}` : NA}</td>
                  <td>{r?.examples_total ?? NA}</td>
                  <td>{typeof r?.answers_per_active_hour === 'number' ? `${r.answers_per_active_hour.toFixed(1)} answers per active hour` : NA}</td>
                </tr>
              )
            })}</tbody>
          </table>
        </div>
        {times.length
          ? <TimeChart title={`First-try pass rate per hour, ${range === 'week' ? 'last 7 days' : 'last 24 hours'}`} unit="% of first tries passed" yMax={100} format={pct}
              from={Math.min(...times)} to={Math.max(...times) + 3600} withDay={range === 'week'} lines={lines} empty="" />
          : <p className="metallic-chart-empty">No eval history is reported. Night school has not sent hourly pass results, so there is no pass-rate history to chart.</p>}
      </>}
    </Panel>
  )
}

function BackupsPanel({state}: {state: MetallicState}) {
  const now = state.generated
  const rows = state.backups ?? []
  const pc = state.backup_pc
  const forge = state.forge_backups
  if (!rows.length && !pc && !forge) return <Panel className="metallic-panel"><h2>Backups</h2><EmptyState compact icon={<HardDrive size={16} />} title="No backup reports" description="Metallic Control has not received a report from any backup job." /></Panel>
  return (
    <Panel className="metallic-panel">
      <h2>Backups</h2>
      <div className="metallic-table-wrap" tabIndex={0} role="region" aria-label="Backups">
        <table className="metallic-table">
          <thead><tr><th scope="col">Backup</th><th scope="col">Where</th><th scope="col">Last success</th><th scope="col">State</th><th scope="col">Size</th></tr></thead>
          <tbody>
            {rows.map(b => (
              <tr key={`${b.set}-${b.where}`}>
                <th scope="row">{b.set}{b.machine ? <small>{b.machine}</small> : null}</th>
                <td>{b.where}</td>
                <td>{b.last_success_utc ? ago(b.last_success_utc, now) : 'Never'}</td>
                <td>{b.error ? <StateWord health="bad">{b.error}</StateWord> : b.in_progress ? <StateWord health="busy">Running</StateWord>
                  : b.last_error ? <StateWord health="bad">Failed: {b.last_error.message}</StateWord>
                  : b.latest_complete ? <StateWord health="ok">Complete</StateWord> : <StateWord health="none">Not complete</StateWord>}</td>
                <td>{bytes(b.repository_bytes)}</td>
              </tr>
            ))}
            {pc && <tr><th scope="row">Owner PC{pc.snapshot ? <small>snapshot {pc.snapshot}</small> : null}</th><td>This PC</td><td>{pc.last_success_utc ? ago(pc.last_success_utc, now) : 'Never'}</td>
              <td>{pc.error ? <StateWord health="bad">{pc.error}</StateWord> : <StateWord health="ok">OK</StateWord>}</td><td>{NA}</td></tr>}
            {forge && <tr><th scope="row">Forge copies<small>{forge.count} files</small></th><td>Forge</td><td>{forge.files?.length ? ago(Math.max(...forge.files.map(f => f.t)), now) : NA}</td>
              <td>{forge.ok ? <StateWord health="ok">OK</StateWord> : <StateWord health="bad">Problem reported</StateWord>}</td><td>{bytes(forge.total_bytes)}</td></tr>}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

function RunnersPanel({state}: {state: MetallicState}) {
  const rows: {name: string; kind: string; where: string; state: string; health: Health}[] = [
    ...(state.dev?.runners ?? []).map(r => ({name: r.name, kind: 'Forge CI runner', where: r.version ? `forge, v${r.version}` : 'forge', state: r.status, health: runHealth(r.status)})),
    ...(state.dev_pc?.runners ?? []).map(r => ({name: r.name, kind: 'GitHub runner', where: 'dev PC', state: r.busy ? 'busy' : r.status, health: r.busy ? 'busy' as Health : runHealth(r.status)})),
    ...(state.runners ?? []).map(r => ({name: r.runner, kind: r.kind, where: r.machine, state: r.state, health: runHealth(r.state)})),
  ]
  const generating = (state.star?.generating ?? []).filter(g => state.generated - g.t < 15)
  return (
    <Panel className="metallic-panel">
      <h2>Agents and runners</h2>
      {!rows.length ? <EmptyState compact icon={<Server size={16} />} title="No runners reported" description="No CI runner or agent runner has reported to Metallic Control." /> : (
        <div className="metallic-table-wrap" tabIndex={0} role="region" aria-label="Agents and runners">
          <table className="metallic-table">
            <thead><tr><th scope="col">Name</th><th scope="col">Kind</th><th scope="col">Where</th><th scope="col">State</th></tr></thead>
            <tbody>{rows.map((r, i) => <tr key={`${r.kind}-${r.name}-${i}`}><th scope="row" className="metallic-mono">{r.name}</th><td>{r.kind}</td><td>{r.where}</td><td><StateWord health={r.health}>{words(r.state)}</StateWord></td></tr>)}</tbody>
          </table>
        </div>
      )}
      <p className="metallic-sub">{generating.length
        ? `Generating now: ${generating.map(g => `${g.machine} ${g.model} slot ${g.slot}${typeof g.tps === 'number' ? `, ${g.tps.toFixed(1)} tok/s` : ''}`).join('; ')}.`
        : 'No model slot is generating right now.'}</p>
    </Panel>
  )
}

/* ---------- the section ---------- */
type View = 'projects' | 'stats'

/** The Metallic page: read-only projects and stats from Metallic Control. Shows content only while signed in; a
 *  reply that says the sign-in ended hides it at once and tells the session. Refreshes every 30 s while visible. */
export function MetallicSection({session, active = true, onOpenSignIn}: {
  session: MetallicSession
  /** The Metallic tab is the one on screen. */
  active?: boolean
  /** Open the sign-in (Settings > Account & Metallic, or the SignIn screen). */
  onOpenSignIn?: () => void
}) {
  const [preview] = useState(metallicPreview)
  // Preview review can open Stats directly with ?view=stats.
  const [view, setView] = useState<View>(() => preview && new URLSearchParams(window.location.search).get('view') === 'stats' ? 'stats' : 'projects')
  const [range, setRange] = useState<MetallicRange>('hour')
  const [reply, setReply] = useState<MetallicReply | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [updated, setUpdated] = useState<number | null>(null)
  const seq = useRef(0)
  const visible = usePageVisible()
  const {signedIn, markSignedOut, status} = session
  const address = status?.control_url || ''

  const load = useCallback(async () => {
    const mine = ++seq.current
    setLoading(true)
    const result = preview
      ? {ok: true as const, data: (await import('./metallicFixtures')).metallicFixtureReply(preview, range)}
      : await askHost<MetallicReply>('metallicState', {range})
    if (mine !== seq.current) return
    setLoading(false)
    if (!result.ok) { setError(result.error); return }
    const data = result.data
    if (!data || typeof data !== 'object') { setError('Metallic Control sent a reply STAR could not read.'); return }
    // Signed out comes first: an ended sign-in hides everything, reachable or not.
    if (!data.signed_in) { setReply(null); markSignedOut(Boolean(data.expired)); return }
    setError('')
    setReply(data)
    setUpdated(Date.now() / 1000)
  }, [preview, range, markSignedOut])

  useEffect(() => {
    if (!signedIn) { seq.current++; setReply(null); setError(''); setLoading(false); return }
    if (!active || !visible) return
    void load()
    const timer = window.setInterval(() => void load(), REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [signedIn, active, visible, load])

  const header = (
    <div className="metallic-head">
      <div className="metallic-title">
        <svg className="metallic-mark" width="22" height="22" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5 20.5 7v10L12 21.5 3.5 17V7z M12 2.5v19 M3.5 7 12 12l8.5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" /></svg>
        <h1>Metallic</h1>
        {preview && <span className="metallic-chip">Preview data</span>}
      </div>
      <p>Your Metallic projects and machines, read-only from Metallic Control{address ? ` at ${address}` : ''}.</p>
    </div>
  )
  const retry = <button type="button" className="secondary-button" onClick={() => void load()} disabled={loading}>
    {loading ? <LoaderCircle className="spin" size={14} aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />} Try again</button>

  let body: ReactNode
  if (!signedIn) {
    body = <EmptyState icon={<WifiOff size={18} />} title={session.ended ? 'Your Metallic sign-in ended' : 'Signed out of Metallic'}
      description="Sign in with your Metallic access code to see projects and machines. The rest of STAR works the same."
      action={onOpenSignIn ? <button type="button" className="secondary-button" onClick={onOpenSignIn}>Sign in</button> : undefined} />
  } else if (reply && !reply.reachable) {
    body = (
      <Panel className="metallic-panel metallic-offline">
        <WifiOff size={18} aria-hidden="true" />
        <div>
          <h2>Not reachable from here</h2>
          <p>STAR could not reach Metallic Control{address ? <> at <span className="metallic-mono">{address}</span></> : ''}. This PC may be off the Metallic network. Chat and the rest of STAR keep working.</p>
          {reply.message && <p className="metallic-sub">{reply.message}</p>}
          {retry}
        </div>
      </Panel>
    )
  } else if (!reply) {
    body = error ? <ErrorState title="Metallic did not load" description={error} action={retry} /> : <LoadingState label="Loading Metallic" lines={4} />
  } else if (!reply.state) {
    body = <ErrorState title="Metallic Control sent no data" description={reply.message || 'The reply had no projects or stats in it.'} action={retry} />
  } else {
    const state = reply.state
    body = <>
      <div className="metallic-toolbar">
        <div className="metallic-switch" role="tablist" aria-label="Metallic view">
          {(['projects', 'stats'] as View[]).map(v => (
            <button key={v} type="button" role="tab" aria-selected={view === v} className={view === v ? 'is-on' : ''} onClick={() => setView(v)}>{v === 'projects' ? 'Projects' : 'Stats'}</button>
          ))}
        </div>
        {view === 'stats' && (
          <div className="metallic-switch" role="radiogroup" aria-label="Time range">
            {RANGES.map(([id, label]) => <button key={id} type="button" role="radio" aria-checked={range === id} className={range === id ? 'is-on' : ''} onClick={() => setRange(id)}>{label}</button>)}
          </div>
        )}
        <span className="metallic-updated" role="status">{loading ? 'Refreshing' : updated ? `Updated ${clockTime(updated)}` : ''}</span>
        <button type="button" className="secondary-button metallic-refresh" onClick={() => void load()} disabled={loading} aria-label="Refresh now">
          <RefreshCw size={14} aria-hidden="true" /> Refresh</button>
      </div>
      {error && <p className="metallic-refusal" role="alert">The last refresh failed: {error} Showing the data from {updated ? clockTime(updated) : 'before'}.</p>}
      <div className={loading ? 'metallic-body is-refreshing' : 'metallic-body'}>
        {view === 'projects' ? <ProjectsView state={state} /> : <>
          <MachinesPanel state={state} reply={reply} range={range} />
          <SpeedPanel reply={reply} range={range} />
          <NightSchoolPanel state={state} range={range} />
          <BackupsPanel state={state} />
          <RunnersPanel state={state} />
        </>}
      </div>
    </>
  }
  return (
    <div className="scroll-region" tabIndex={0} role="region" aria-label="Metallic">
      <div className="page-wrap metallic-page">{header}{body}</div>
    </div>
  )
}
