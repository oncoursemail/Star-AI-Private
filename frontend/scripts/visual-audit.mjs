#!/usr/bin/env node
/**
 * Manual, read-only visual QA for STAR's real browser preview.
 *
 * Build frontend first; provide an existing playwright-core install directory:
 *   node scripts/visual-audit.mjs --tools ../.local/tools
 * Optional: --channel chrome  --out /private/qa/folder  --strict
 *
 * Launches only the local production Vite output as a static loopback site.
 * No user chats, credentials, model, Studio access, screenshot editing or
 * repository files are changed. Screenshots + JSON are saved to the output dir.
 * The Qt WebEngine Windows installer must still be checked independently.
 */
import {createServer} from 'node:http'
import {readFile, mkdir, writeFile} from 'node:fs/promises'
import {mkdtemp} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {createRequire} from 'node:module'
import {fileURLToPath, pathToFileURL} from 'node:url'
import path from 'node:path'
import {auditLayoutSnapshot} from './visual-contract.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const frontend = path.resolve(here, '..')
const dist = path.join(frontend, 'dist')
const args = process.argv.slice(2)
const opt = (flag, fallback) => {
  const i = args.indexOf('--' + flag)
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback
}
const toolsDir = path.resolve(opt('tools', path.join(frontend, '..', '.local', 'tools')))
const channel = opt('channel', 'msedge')
const strict = args.includes('--strict')
const outputDir = opt('out', null)
  ? path.resolve(opt('out', ''))
  : await mkdtemp(path.join(tmpdir(), 'star-visual-audit-'))
const TYPES = {'.html':'text/html; charset=utf-8', '.js':'text/javascript',
  '.css':'text/css', '.svg':'image/svg+xml', '.json':'application/json',
  '.png':'image/png', '.woff':'font/woff', '.woff2':'font/woff2'}

function createPreviewServer() {
  const server = createServer(async (request, response) => {
    try {
      const url = new URL(request.url || '/', 'http://127.0.0.1')
      const relative = decodeURIComponent(url.pathname).replace(/^\/+/, '') || 'index.html'
      const file = path.resolve(dist, relative)
      if (file !== dist && !file.startsWith(dist + path.sep)) throw Error('outside')
      const bytes = await readFile(file)
      response.writeHead(200, {'content-type': TYPES[path.extname(file)] ||
        'application/octet-stream', 'cache-control': 'no-store'})
      response.end(bytes)
    } catch {
      response.writeHead(404)
      response.end('Not found')
    }
  })
  return new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server)))
}

async function snapshot(page) {
  return page.evaluate(() => {
    const clips = value => ['hidden', 'clip', 'auto', 'scroll'].includes(value)
    const visibleBox = node => {
      const box = node.getBoundingClientRect()
      let left = box.left, top = box.top, right = box.right, bottom = box.bottom
      // A scrolled-out row still has a DOM rectangle behind the sidebar
      // footer. Measure only the part inside each ancestor's clipping box.
      for (let parent = node.parentElement; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent)
        if (!clips(style.overflowX) && !clips(style.overflowY)) continue
        const bounds = parent.getBoundingClientRect()
        const x = bounds.left + parent.clientLeft
        const y = bounds.top + parent.clientTop
        if (clips(style.overflowX)) {
          left = Math.max(left, x)
          right = Math.min(right, x + parent.clientWidth)
        }
        if (clips(style.overflowY)) {
          top = Math.max(top, y)
          bottom = Math.min(bottom, y + parent.clientHeight)
        }
      }
      return {x:left, y:top, width:Math.max(0, right-left), height:Math.max(0, bottom-top)}
    }
    const candidates = [...document.querySelectorAll(
      'button, a[href], input, select, textarea, [role="button"]'
    )].filter(node => {
      const style = getComputedStyle(node)
      const box = visibleBox(node)
      return (style.display !== 'none' && style.visibility !== 'hidden' &&
        style.opacity !== '0' && style.pointerEvents !== 'none' &&
        box.width > 0 && box.height > 0 &&
        !node.closest('[inert], [aria-hidden="true"]') && !node.disabled)
    })
    const controlsOmitted = Math.max(0, candidates.length - 800)
    const measured = candidates.slice(0, 800)
    const ids = new Map(measured.map((node, index) => [node, 'control-' + index]))
    const round = number => Math.round(number * 10) / 10
    return {
      viewport: {width: window.innerWidth, height: window.innerHeight},
      documentWidth: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth),
      controlsOmitted,
      controls: measured.map(node => {
        const box = visibleBox(node)
        const style = getComputedStyle(node)
        const labelledBy = (node.getAttribute('aria-labelledby') || '').split(/\s+/)
          .map(id => document.getElementById(id)?.textContent || '').join(' ')
        const label = (node.getAttribute('aria-label') || labelledBy ||
          node.getAttribute('title') || node.innerText || node.textContent || '').trim()
        const textClipped = style.textOverflow !== 'ellipsis' &&
          style.overflowX !== 'visible' && style.overflowX !== 'auto' &&
          ((node.scrollWidth > node.clientWidth + 3) ||
           (node.scrollHeight > node.clientHeight + 3))
        return {
          id: ids.get(node),
          label: label.slice(0, 100),
          role: node.tagName === 'BUTTON' || node.getAttribute('role') === 'button'
            ? 'button' : 'other',
          rect: {x:round(box.x), y:round(box.y),
                 width:round(box.width), height:round(box.height)},
          ancestors: measured.filter(other => other !== node && other.contains(node))
            .map(other => ids.get(other)),
          textClipped,
          visible: true,
        }
      })
    }
  })
}

let requireTools
try {
  requireTools = createRequire(pathToFileURL(path.join(toolsDir, 'package.json')))
  requireTools.resolve('playwright-core')
} catch {
  throw Error('Install playwright-core in a reviewed tools folder and pass --tools <folder>. No automatic installation occurs.')
}
const {chromium} = requireTools('playwright-core')
const requireFrontend = createRequire(pathToFileURL(path.join(frontend, 'package.json')))
const axePath = requireFrontend.resolve('axe-core')
await readFile(path.join(dist, 'index.html')) // fail before creating any browser if not built
const server = await createPreviewServer()
let browser
const results = []
try {
  await mkdir(outputDir, {recursive: true})
  browser = await chromium.launch({channel, headless: true})
  const viewports = [
    {id:'desktop',width:1280,height:800},
    {id:'small',width:900,height:700},
    {id:'phone',width:390,height:844},
  ]
  for (const viewport of viewports) {
    for (const tab of ['chat','tools']) {
      const id = tab + '-' + viewport.id
      const context = await browser.newContext({
        viewport: {width:viewport.width,height:viewport.height},
        reducedMotion:'reduce', colorScheme:'dark', deviceScaleFactor:1,
      })
      try {
        const page = await context.newPage()
        const url = 'http://127.0.0.1:' + server.address().port +
          '/?preview=1&tab=' + tab + (tab === 'chat' ? '&fixture=chat' : '')
        await page.goto(url, {waitUntil:'networkidle'})
        await page.waitForSelector('[data-preview="true"]', {timeout:20_000})
        await page.evaluate(() => document.fonts.ready)
        const data = await snapshot(page)
        const audit = auditLayoutSnapshot(data)
        // axe's color-contrast check needs a real rendered browser; jsdom
        // tests deliberately cannot perform this measurement.
        await page.addScriptTag({path: axePath})
        const accessibility = await page.evaluate(async () => {
          const checks = await window.axe.run(document.body, {
            runOnly: {type:'rule', values:['color-contrast', 'button-name', 'link-name']},
          })
          return checks.violations.map(issue => ({
            id:issue.id, impact:issue.impact,
            targets:issue.nodes.slice(0, 8).map(node => node.target.join(' ')),
            omittedNodes:Math.max(0, issue.nodes.length - 8),
          }))
        })
        await page.screenshot({path: path.join(outputDir, id + '.png')})
        results.push({id, screenshot:id + '.png', controlsOmitted:data.controlsOmitted,
                      controls:data.controls.map(({id,label,role,rect}) => ({id,label,role,rect})),
                      accessibility, ...audit})
        console.log(id, (audit.issues.length + accessibility.length) +
                           ' geometry/a11y findings')
      } finally {
        await context.close()
      }
    }
  }
} finally {
  if (browser) await browser.close()
  server.close()
}
const report = {
  generatedAt: new Date().toISOString(),
  implementation: 'frontend/dist read-only browser preview',
  nativeWindowsVerified: false,
  robloxStudioVerified: false,
  artisticQualityVerified: false,
  pages: results,
}
await writeFile(path.join(outputDir, 'report.json'), JSON.stringify(report, null, 2) + '\n')
console.log('Evidence: ' + outputDir)
if (strict && results.some(row =>
  row.issues.some(issue => issue.severity === 'error') ||
  row.accessibility.length > 0 || row.controlsOmitted > 0)) {
  process.exitCode = 1
}
