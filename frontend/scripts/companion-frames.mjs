#!/usr/bin/env node
/**
 * Design review captures for the rigged companions (src/companions): frame-exact sequences of every
 * animation in two themes. The page clock is frozen and stepped in fixed frames through the preview
 * hook, so every frame is the exact pose (no timer jitter). Needs a running `vite` dev server and an
 * existing playwright-core install (no new dependency):
 *
 *   node scripts/companion-frames.mjs --url http://127.0.0.1:5281 --playwright <dir with playwright-core> --out <folder>
 *     [--only walk,hug] [--themes obsidian,pearl] [--zoom 2]
 *
 * Writes <out>/<theme>/<scene>/NN.png and captures.json. Uses Edge with the GPU on (WebGL2 like the app).
 */
import {createRequire} from 'node:module'
import {mkdir, writeFile} from 'node:fs/promises'
import path from 'node:path'

const args = process.argv.slice(2)
const opt = (flag, fallback) => { const i = args.indexOf('--' + flag); return i >= 0 && args[i + 1] ? args[i + 1] : fallback }
const base = opt('url', 'http://127.0.0.1:5281')
const out = path.resolve(opt('out', 'companion-frames'))
const only = opt('only', '')
const themes = opt('themes', 'obsidian,pearl').split(',')
const zoom = Number(opt('zoom', '2'))
const require = createRequire(path.join(path.resolve(opt('playwright', '.')), 'noop.js'))
const {chromium} = require('playwright-core')

const THEMES = {
  obsidian: {},
  pearl: {'star.studio.layout': 'on', 'star.appearance.v1': JSON.stringify({version: 1, theme: 'pearl', accent: null, density: 'comfortable'})},
}

/**
 * Each scene: a page function that sets the cast up (gets the preview hook `S`, the floor platform and a
 * helper) and returns {frames, step, focus: [x0, x1] or null}; then `frames` captures `step` s apart.
 * Optional `during(S, i)` runs before frame i (pointer drags, mode switches).
 */
const SCENES = {
  idle: {setup: `place([0, 1, 2, 3], 'idle'); return {frames: 16, step: 0.12}`},
  walk: {setup: `place([0, 1, 2, 3], 'walk', {gap: 70}); S.advance(0.5, 60); return {frames: 16, step: 1 / 24}`},
  run: {setup: `place([0, 1, 2, 3], 'run', {gap: 70}); S.advance(0.5, 60); return {frames: 14, step: 1 / 30}`},
  turn: {setup: `place([3], 'walk'); S.advance(0.5, 60); const a = S.world.actors.find(a => a.id === 'gemini'); a.dir = -1; a.act = {kind: 'walk', tx: -2000, run: false}; a.path = [{type: 'walk', x: -2000}]; return {frames: 12, step: 1 / 30, follow: 'gemini'}`},
  hop: {setup: `place([1, 3], 'idle'); for (const a of S.world.actors.filter(a => window.__labIds.includes(a.id))) { a.act = {kind: 'hop', x0: a.x, y0: a.y, x1: a.x + 60, y1: a.y, to: a.platform, t: 0, dur: 0.75, height: 46} }; return {frames: 16, step: 1 / 20}`},
  sit: {setup: `place([0, 1, 2, 3], 'idle'); for (const a of S.world.actors.filter(a => window.__labIds.includes(a.id))) { a.act = a.id === 'astra' ? {kind: 'sleep', until: 1e9} : a.id === 'ember' ? {kind: 'sit', until: 1e9, tired: true} : {kind: 'sit', until: 1e9, tired: false} }; return {frames: 14, step: 0.1}`},
  talk: {setup: `place([3, 0], 'idle'); const a = S.world.actors.find(a => a.id === 'gemini'); a.act = {kind: 'talk', until: 1e9, to: null}; a.bubble = {text: 'Hello! I can really talk now, see?', until: 1e9}; return {frames: 16, step: 1 / 15, follow: 'gemini'}`},
  tag: {setup: `place([0, 1, 2, 3], 'idle', {gap: 80}); S.scene('tag'); S.advance(1.5, 60); return {frames: 16, step: 1 / 12}`},
  kiss: {setup: `pair('ember', 'gemini', 'kiss'); return {frames: 16, step: 0.12}`},
  hug: {setup: `pair('star', 'astra', 'hug'); return {frames: 18, step: 0.13}`},
  highfive: {setup: `pair('gemini', 'star', 'highfive'); return {frames: 14, step: 0.09}`},
  pickup: {setup: `place([3], 'idle'); const a = S.world.actors.find(a => a.id === 'gemini'); a.act = {kind: 'dragged'}; a.platform = null; a.y -= 70; return {frames: 18, step: 1 / 15, follow: 'gemini'}`,
    during: `const a = S.world.actors.find(a => a.id === 'gemini'); if (i < 11) { a.x += Math.sin(i * 0.9) * 14; a.vx = Math.sin(i * 0.9) * 14 } if (i === 11) a.act = {kind: 'fall', vx: 0, vy: 0}`},
  poke: {setup: `place([2], 'idle'); const a = S.world.actors.find(a => a.id === 'astra'); a.act = {kind: 'poked', until: S.world.now + 0.8}; return {frames: 12, step: 1 / 15, follow: 'astra'}`},
  cat: {setup: `place([0, 1, 3], 'idle'); S.advance(0.3, 60); S.setForm('all', 'cat'); return {frames: 16, step: 1 / 20}`},
  dog: {setup: `place([0, 1, 3], 'idle'); S.setForm('all', 'cat'); S.advance(1.5, 60); S.setForm('all', 'dog'); return {frames: 18, step: 1 / 20}`},
  dogwalk: {setup: `S.setForm('all', 'dog'); place([0, 1, 3], 'walk', {gap: 80}); S.advance(0.8, 60); return {frames: 16, step: 1 / 24}`},
  catback: {setup: `place([0, 3], 'idle'); S.setForm('all', 'cat'); S.advance(1.5, 60); S.setForm('all', 'normal'); return {frames: 14, step: 1 / 20}`},
  study: {setup: `place([0, 1, 3], 'idle'); S.advance(0.2, 60); for (const a of S.world.actors) if (window.__labIds.includes(a.id)) a.act = {kind: 'study', until: 1e9, nap: false}; return {frames: 18, step: 0.1}`},
  studyoff: {setup: `place([0, 1, 3], 'idle'); for (const a of S.world.actors) if (window.__labIds.includes(a.id)) a.act = {kind: 'study', until: 1e9, nap: false}; S.advance(2, 60); for (const a of S.world.actors) if (window.__labIds.includes(a.id)) a.act = {kind: 'idle', until: 1e9, look: 0}; return {frames: 12, step: 1 / 20}`},
  nap: {setup: `place([0, 3], 'idle'); for (const a of S.world.actors) if (window.__labIds.includes(a.id)) a.act = {kind: 'study', until: 1e9, nap: true}; S.advance(1.5, 60); return {frames: 10, step: 0.25}`},
  cheer: {setup: `place([0, 1, 2, 3], 'idle'); for (const a of S.world.actors.filter(a => window.__labIds.includes(a.id))) a.act = {kind: 'celebrate', until: 1e9}; return {frames: 12, step: 1 / 20}`},
}

// Runs in the page: freezes the stage and offers `place` and `pair` to the scene setup.
const PRELUDE = `
  const S = window.__starCompanions; S.freeze()
  const w = S.world, floor = S.env().platforms.reduce((a, b) => (b.x1 - b.x0 > a.x1 - a.x0 ? b : a))
  w.next.banter = w.next.tag = w.next.affection = w.next.nightLine = w.next.studyBanter = w.next.studyNap = Infinity
  const ids = ['star', 'ember', 'astra', 'gemini']
  const place = (which, kind, o = {}) => {
    const gap = o.gap ?? 95
    // Everyone else sits quietly at the far end, out of the picture.
    window.__labIds = which.map(k => ids[k])
    w.actors.forEach((a, n) => { a.bubble = null; a.platform = floor.id; a.y = floor.y; a.x = floor.x1 - 40 - n * 60; a.path = []; a.act = {kind: 'sit', until: 1e9, tired: false} })
    which.forEach((k, n) => {
      const a = w.actors.find(a => a.id === ids[k]); if (!a) return
      a.away = false; a.platform = floor.id; a.y = floor.y; a.x = floor.x0 + 90 + n * gap; a.dir = 1; a.path = []; a.bubble = null
      if (kind === 'walk' || kind === 'run') { a.act = {kind: 'walk', tx: 4000, run: kind === 'run'}; a.path = [{type: 'walk', x: 4000}]; a.running = kind === 'run' }
      else a.act = {kind: 'idle', until: 1e9, look: 0}
    })
  }
  const pair = (x, y, type) => {
    place([ids.indexOf(x), ids.indexOf(y)], 'idle', {gap: 100})
    w.scene = {kind: 'affection', a: x, b: y, type, phase: 'approach', until: w.now + 9}
    for (let i = 0; i < 400 && w.scene && w.scene.phase === 'approach'; i++) S.advance(1 / 60, 60)
  }
`

const browser = await chromium.launch({channel: 'msedge', headless: true, args: ['--enable-gpu', '--ignore-gpu-blocklist', '--use-angle=d3d11']})
const report = []
for (const theme of themes) {
  for (const [name, scene] of Object.entries(SCENES)) {
    if (only && !only.split(',').includes(name)) continue
    const context = await browser.newContext({viewport: {width: 1000, height: 640}, deviceScaleFactor: zoom})
    await context.addInitScript(values => { for (const [k, v] of Object.entries(values)) localStorage.setItem(k, v) }, THEMES[theme])
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', e => errors.push(e.message))
    await page.goto(`${base}/?preview=1`)
    await page.waitForFunction(() => !!window.__starCompanions, null, {timeout: 30000})
    await page.waitForTimeout(1200)
    const plan = await page.evaluate(`(() => { ${PRELUDE}; ${scene.setup} })()`)
    const dir = path.join(out, theme, name)
    await mkdir(dir, {recursive: true})
    let clip = null
    for (let i = 0; i < plan.frames; i++) {
      if (scene.during) await page.evaluate(`(() => { const S = window.__starCompanions; const i = ${i}; ${scene.during} })()`)
      await page.evaluate(s => window.__starCompanions.advance(s, 60), i ? plan.step : 1 / 60)
      if (!clip || plan.follow) clip = await page.evaluate(follow => {
        const S = window.__starCompanions, t = document.querySelector('.thread').getBoundingClientRect()
        const shown = S.world.actors.filter(a => (window.__labIds || []).includes(a.id) && (!follow || a.id === follow))
        const size = S.env().size
        const x0 = Math.min(...shown.map(a => a.x)) - size * 0.55, x1 = Math.max(...shown.map(a => a.x)) + size * 0.55
        const yb = Math.max(...S.env().platforms.map(p => p.y)) + 8
        return {x: t.left + Math.max(0, x0), y: t.top + yb - size * 1.45, width: Math.min(t.width, x1 - x0), height: size * 1.45}
      }, plan.follow ?? null)
      await page.screenshot({path: path.join(dir, `${String(i).padStart(2, '0')}.png`), clip})
    }
    report.push({theme, name, frames: plan.frames, step: plan.step, errors})
    if (errors.length) console.log(theme, name, 'page errors:', errors.join(' | '))
    await context.close()
  }
}
await browser.close()
await mkdir(out, {recursive: true})
await writeFile(path.join(out, 'captures.json'), JSON.stringify({base, report}, null, 2))
console.log('saved', report.length, 'sequences to', out)
