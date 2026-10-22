#!/usr/bin/env node
/**
 * Design review captures for the living companions (src/companions): screenshots and short frame
 * sequences from the browser preview, in two themes. Read-only; needs a running `vite` dev server and
 * an existing playwright-core install (no new dependency):
 *
 *   node scripts/companion-frames.mjs --url http://127.0.0.1:5281 --playwright <dir with playwright-core> --out <folder>
 *
 * Uses the Edge channel with the GPU on, so WebGL2 runs on the graphics card like the desktop app.
 */
import {createRequire} from 'node:module'
import {mkdir, writeFile} from 'node:fs/promises'
import path from 'node:path'

const args = process.argv.slice(2)
const opt = (flag, fallback) => { const i = args.indexOf('--' + flag); return i >= 0 && args[i + 1] ? args[i + 1] : fallback }
const base = opt('url', 'http://127.0.0.1:5281')
const out = path.resolve(opt('out', 'companion-frames'))
const only = opt('only', '')
const themes = opt('themes', '')
const require = createRequire(path.join(path.resolve(opt('playwright', '.')), 'noop.js'))
const {chromium} = require('playwright-core')

const THEMES = {
  obsidian: {},
  pearl: {'star.studio.layout': 'on', 'star.appearance.v1': JSON.stringify({version: 1, theme: 'pearl', accent: null, density: 'comfortable'})},
}
// name: [query flags, scene to trigger, frames, interval ms, settle ms, fixture]
const SHOTS = {
  idle: ['', null, 10, 160, 2500, 'chat'],
  walk: ['', 'walk', 12, 90, 1200, 'chat'],
  banter: ['', 'banter', 10, 260, 600, 'chat'],
  tag: ['', 'tag', 12, 110, 1800, 'chat'],
  kiss: ['', 'kiss', 14, 150, 2600, 'chat'],
  hug: ['', 'hug', 14, 150, 2600, 'chat'],
  cat: ['cat', null, 10, 160, 2500, 'chat'],
  dog: ['dog', 'tag', 12, 110, 1800, 'chat'],
  study: ['study', null, 10, 220, 3500, 'chat'],
  studynight: ['study,night', null, 10, 300, 3500, 'chat'],
  working: ['', null, 10, 200, 2600, 'streaming'],
  done: ['', null, 10, 120, 5200, 'streaming'],
  error: ['', null, 10, 120, 1500, 'error'],
  empty: ['', null, 6, 250, 2500, ''],
  drag: ['', 'drag', 14, 90, 300, 'chat'],
  poke: ['', 'poke', 8, 100, 300, 'chat'],
}

const browser = await chromium.launch({channel: 'msedge', headless: true, args: ['--enable-gpu', '--ignore-gpu-blocklist', '--use-angle=d3d11']})
const report = []
for (const [theme, storage] of Object.entries(THEMES)) {
  if (themes && !themes.split(',').includes(theme)) continue
  for (const [name, [flags, scene, frames, interval, settle, fixture]] of Object.entries(SHOTS)) {
    if (only && !only.split(',').includes(name)) continue
    const context = await browser.newContext({viewport: {width: 1280, height: 800}, deviceScaleFactor: 2})
    await context.addInitScript(values => { for (const [k, v] of Object.entries(values)) localStorage.setItem(k, v) }, storage)
    const page = await context.newPage()
    const query = new URLSearchParams({preview: '1', ...(fixture ? {fixture} : {}), ...(flags ? {companions: flags} : {})})
    await page.goto(`${base}/?${query}`)
    await page.waitForFunction(() => !!window.__starCompanions, null, {timeout: 20000})
    // The chat fixture loads after the stage; let the layout settle before scripting a scene.
    await page.waitForTimeout(1800)
    if (scene === 'walk') await page.evaluate(() => {
      const {world} = window.__starCompanions
      world.next.banter = world.next.tag = world.next.affection = Infinity
      for (const a of world.actors) if (a.platform) { a.act = {kind: 'idle', until: 0, look: 0} }
    })
    else if (scene) await page.evaluate(kind => window.__starCompanions.scene(kind), scene)
    await page.waitForTimeout(settle)
    const dir = path.join(out, theme, name)
    await mkdir(dir, {recursive: true})
    const stage = await page.evaluate(() => {
      const t = document.querySelector('.thread').getBoundingClientRect()
      const c = document.querySelector('.companion-stage__canvas').getBoundingClientRect()
      return {x: t.left, y: Math.max(t.top, c.top - 40), width: t.width, height: t.bottom - Math.max(t.top, c.top - 40)}
    })
    // Drag: press on Gemini, lift her and swing left and right, then let go over the composer.
    const hit = scene === 'drag' || scene === 'poke' ? await page.locator('.companion-stage__hit[data-companion="gemini"]').boundingBox() : null
    if (hit && scene === 'poke') await page.mouse.click(hit.x + hit.width / 2, hit.y + hit.height / 2)
    if (hit && scene === 'drag') { await page.mouse.move(hit.x + hit.width / 2, hit.y + hit.height * 0.25); await page.mouse.down() }
    for (let i = 0; i < frames; i++) {
      if (hit && scene === 'drag') {
        if (i < 10) await page.mouse.move(hit.x - 120 - Math.sin(i * 0.9) * 90, hit.y - 60 - i * 6, {steps: 3})
        else if (i === 10) await page.mouse.up()
      }
      await page.screenshot({path: path.join(dir, `${String(i).padStart(2, '0')}.png`), clip: stage})
      await page.waitForTimeout(interval)
    }
    await page.screenshot({path: path.join(out, theme, `${name}-full.png`)})
    report.push({theme, name, frames, interval})
    await context.close()
  }
}
await browser.close()
await writeFile(path.join(out, 'captures.json'), JSON.stringify({base, report}, null, 2))
console.log('saved', report.length, 'sequences to', out)
