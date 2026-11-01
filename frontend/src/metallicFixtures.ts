/**
 * Browser preview data for the Metallic section (`?preview=1&metallic=signed|offline|empty|signin`). Loaded only by
 * a dynamic import when the page is a preview; the desktop never reads it. The numbers are made up for layout
 * screenshots and the page labels them "Preview data". Host names are placeholders, never real addresses.
 */
import type {MetallicPreview, MetallicRange, MetallicReply, MetallicState, Point, SpeedHour} from './metallic'

const STEP: Record<MetallicRange, [number, number]> = {hour: [3600, 30], day: [86400, 600], week: [7 * 86400, 3600]}
/** A smooth, repeatable wave, so screenshots do not change between runs. */
const wave = (i: number, base: number, swing: number, phase: number) =>
  Math.max(0, Math.min(100, base + swing * Math.sin(i / 9 + phase) + (swing / 3) * Math.sin(i / 2.3 + phase * 2)))

function series(range: MetallicRange, now: number) {
  const [span, step] = STEP[range]
  const from = now - span
  const make = (base: number, swing: number, phase: number, gapFrom = -1, gapTo = -1): Point[] => {
    const out: Point[] = []
    for (let t = from, i = 0; t <= now; t += step, i++) {
      const v = i >= gapFrom && i < gapTo ? null : Math.round(wave(i, base, swing, phase) * 10) / 10
      out.push([t, v, v, v])
    }
    return out
  }
  return {range, step, from, to: now, series: {
    'brain1.cpu': make(62, 18, 0), 'brain1.mem_pct': make(71, 4, 1),
    'brain2.cpu': make(34, 15, 2, 40, 52), 'brain2.mem_pct': make(48, 6, 3, 40, 52),
    'pc.cpu': make(18, 10, 4), 'pc.mem_pct': make(55, 5, 5),
  }}
}

function speed(range: MetallicRange, now: number): SpeedHour[] {
  const hours = range === 'week' ? 7 * 24 : 24
  const start = Math.floor(now / 3600) * 3600 - (hours - 1) * 3600
  const out: SpeedHour[] = []
  for (let i = 0; i < hours; i++) {
    const t = start + i * 3600
    if (i % 5 !== 3) out.push({t, machine: 'brain1', model: 'qwen3-coder-30b', n: 20 + (i % 7) * 4, tps_median: 38 + 6 * Math.sin(i / 4), prompt_ms_median: 420 + 160 * Math.sin(i / 3 + 1)})
    if (i % 3 === 0) out.push({t, machine: 'brain2', model: 'star-ns-brain', n: 6 + (i % 4), tps_median: 21 + 3 * Math.sin(i / 5), prompt_ms_median: 900 + 250 * Math.sin(i / 4)})
  }
  return out
}

function nightHours(now: number) {
  const out: Record<string, Record<string, number>> = {}
  const start = Math.floor(now / 3600) * 3600 - 47 * 3600
  for (let i = 0; i < 48; i++) {
    const key = new Date((start + i * 3600) * 1000).toISOString().slice(0, 13)
    const first = i % 6 === 5 ? 0 : 14 + (i % 5) * 3
    out[key] = {first, first_pass: Math.round(first * (0.55 + 0.2 * Math.sin(i / 6))), lesson: 4, lesson_pass: 3, validation: 2, validation_pass: 2}
  }
  return out
}

const iso = (now: number, ago: number) => new Date((now - ago) * 1000).toISOString()

function state(now: number): MetallicState {
  return {
    generated: now,
    machines: [
      {id: 'brain1', name: 'Brain 1', role: 'main models', online: true, ncpu: 32, cpu: 61, mem: {total: 128 * 2 ** 30, used: 91 * 2 ** 30, pct: 71}, fs: [{mount: '/', total: 2 * 2 ** 40, used: 1.3 * 2 ** 40, pct: 65}], net: {rx: 1.4 * 2 ** 20, tx: 320 * 2 ** 10}, gpu: null},
      {id: 'brain2', name: 'Brain 2', role: 'Studio and CPU work', online: true, ncpu: 16, cpu: 33, mem: {total: 64 * 2 ** 30, used: 31 * 2 ** 30, pct: 48}, fs: [{mount: '/', total: 2 ** 40, used: 0.82 * 2 ** 40, pct: 82}], net: {rx: 210 * 2 ** 10, tx: 95 * 2 ** 10}, gpu: null},
      {id: 'pc', name: 'Owner PC', role: 'GPU helper', online: true, ncpu: 24, cpu: 17, mem: {total: 64 * 2 ** 30, used: 35 * 2 ** 30, pct: 55}, fs: [{mount: 'C:', total: 2 ** 40, used: 0.6 * 2 ** 40, pct: 60}], net: {rx: 2.1 * 2 ** 20, tx: 640 * 2 ** 10}, gpu: {name: 'RTX 4090', util: 38, mem_used: 9 * 2 ** 30, mem_total: 24 * 2 ** 30}},
      {id: 'nas', name: 'Backup box', role: 'backups', online: false, last_seen: now - 5400},
    ],
    star: {
      brains: {
        brain1: {at: now - 40, night_school: {paused: false, report: {status: 'Lesson pass running', attempts_total: 4210, passed_first_total: 2690, examples_total: 1873, answers_per_active_hour: 61.4}, hours: nightHours(now)}},
        brain2: {at: now - 55, night_school: {paused: true, report: {status: 'Held by the owner', attempts_total: 950, passed_first_total: 512, examples_total: 402, answers_per_active_hour: 18.2}}},
      },
      generating: [{machine: 'brain1', model: 'qwen3-coder-30b', slot: 1, tps: 41.2, n_gen: 380, t: now - 3}],
    },
    dev: {
      at: now - 240,
      repos: [
        {name: 'Star-AI-Private', open_issues: 41, open_prs: 3, releases: 12, updated: iso(now, 1800), branch: 'star/next', url: 'https://forge.example/metallic/Star-AI-Private'},
        {name: 'Metallic-RC', open_issues: 9, open_prs: 1, releases: 2, updated: iso(now, 86400 * 2), branch: 'main', url: 'https://forge.example/metallic/Metallic-RC'},
        {name: 'Metallic-RB', open_issues: 4, open_prs: 0, releases: 0, updated: iso(now, 86400 * 6), branch: 'main', url: 'https://forge.example/metallic/Metallic-RB'},
      ],
      prs: [{repo: 'Metallic-RC', number: 18, title: 'Launcher: resume interrupted downloads', draft: true, updated: iso(now, 7200), author: 'claude', url: 'https://forge.example/metallic/Metallic-RC/pulls/18'}],
      releases: [{repo: 'Metallic-RC', tag: 'v0.4.1', name: 'v0.4.1', published: iso(now, 86400 * 9), url: 'https://forge.example/metallic/Metallic-RC/releases/v0.4.1'}],
      runs: [
        {repo: 'Star-AI-Private', name: 'tests', status: 'success', branch: 'star/next', started: iso(now, 2400), updated: iso(now, 1900), url: 'https://forge.example/metallic/Star-AI-Private/actions/1'},
        {repo: 'Metallic-RC', name: 'build', status: 'failure', branch: 'main', started: iso(now, 90000), updated: iso(now, 89000), url: 'https://forge.example/metallic/Metallic-RC/actions/7'},
      ],
      runners: [{name: 'forge-runner-1', status: 'idle', version: '6.3.1', labels: ['linux']}],
    },
    dev_pc: {
      at: now - 180, repo: 'oncoursemail/Star-AI-Private',
      prs: [
        {number: 612, title: 'Star 2.0 UI: Metallic sign-in and section', draft: false, updated: iso(now, 900), author: 'oncoursemail', head: 'star/ui-2-20261026', base: 'star/next', url: 'https://github.com/oncoursemail/Star-AI-Private/pull/612'},
        {number: 598, title: 'Night school: lesson gate retries', draft: false, updated: iso(now, 20000), author: 'oncoursemail', head: 'star/ns-gate', base: 'star/next', url: 'https://github.com/oncoursemail/Star-AI-Private/pull/598'},
      ],
      runs: [{id: 1, title: 'tests', workflow: 'tests', status: 'in_progress', conclusion: '', branch: 'star/ui-2-20261026', created: iso(now, 600), updated: iso(now, 120), url: 'https://github.com/oncoursemail/Star-AI-Private/actions/runs/1'}],
      runners: [{name: 'owner-pc-runner', status: 'online', busy: true, labels: ['windows']}],
      projects: [
        {name: 'STAR', lang: 'Python + TS', connected: true, branch: 'star/next', head: '0ee2701d', pending: ['star/ui-2-20261026'],
          checks: [{verdict: 'passed', started: iso(now, 3000), red: [], branch: 'star/next', seconds: 412}],
          queue_runs: [{started: iso(now, 5400), target: 'star/next', seconds: 900, applied: true, merged: ['star/ns-gate', 'star/voice-fix'], entries: []}]},
        {name: 'RC', lang: 'C#', connected: true, branch: 'main', head: 'a41c9e2', release: {tag: 'v0.4.1', date: iso(now, 86400 * 9)},
          checks: [{verdict: 'failed', started: iso(now, 90000), red: ['LauncherTests.ResumeDownload', 'UpdaterTests.Rollback'], branch: 'main', seconds: 188}], queue_runs: []},
        {name: 'Obby Builder', lang: 'Luau', connected: false, note: 'clone not found on the dev PC', checks: [], queue_runs: []},
      ],
    },
    runners: [{runner: 'claude-lane-d', kind: 'Agent runner', state: 'running', machine: 'Owner PC'}, {runner: 'codex-1', kind: 'Agent runner', state: 'idle', machine: 'Brain 2'}],
    backups: [
      {set: 'star-data', where: 'Backup box', machine: 'Brain 1', last_success_utc: iso(now, 3 * 3600), latest_complete: true, repository_bytes: 182 * 2 ** 30},
      {set: 'forge', where: 'Backup box', machine: 'Brain 2', last_success_utc: iso(now, 30 * 3600), last_error: {at: iso(now, 3600), action: 'backup', message: 'repository locked by another run'}, repository_bytes: 40 * 2 ** 30},
    ],
    backup_pc: {last_success_utc: iso(now, 6 * 3600), last_attempt_utc: iso(now, 6 * 3600), error: null, snapshot: 'daily'},
    forge_backups: {ok: true, count: 14, total_bytes: 9.4 * 2 ** 30, files: [{t: now - 7200, bytes: 2 ** 30, name: 'forge-latest.tar.zst'}]},
  }
}

function emptyState(now: number): MetallicState {
  return {generated: now, machines: [], star: {brains: {}, generating: []}, dev: {}, dev_pc: null, runners: [], backups: [], backup_pc: null, forge_backups: null}
}

export function metallicFixtureReply(kind: MetallicPreview, range: MetallicRange): MetallicReply {
  const now = Math.round(Date.now() / 1000)
  if (kind === 'offline') return {reachable: false, signed_in: true, message: 'Metallic Control did not answer. Showing nothing until it is back.'}
  if (kind === 'empty') return {reachable: true, signed_in: true, state: emptyState(now), series: {range, step: 30, from: now - 3600, to: now, series: {}}, speed: {hours: []}}
  return {reachable: true, signed_in: true, state: state(now), series: series(range, now), speed: {hours: speed(range, now)}}
}
