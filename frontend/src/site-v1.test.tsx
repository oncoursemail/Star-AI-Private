// @vitest-environment jsdom
import {afterEach,describe,expect,it} from 'vitest'
import {cleanup,render,screen} from '@testing-library/react'
import {existsSync,readFileSync,readdirSync} from 'node:fs'
import {resolve} from 'node:path'
import {renderToString} from 'react-dom/server'
import {Landing} from './Landing'
import {SiteDownload} from './SiteDownload'
import {SiteFeatures} from './SiteFeatures'
import media from './siteMedia.json'
import {LINKS,PUBLISHED_FLOOR,brainCounts,currentRelease,evaluation,featureGroups,learnSteps,limits,releaseFiles} from './siteContent'
import {compareVersions,latestStable} from './githubPublic'
import {builtSnapshot} from './siteHooks'
import type {ReleaseInfo} from './githubPublic'

afterEach(()=>cleanup())
const html=renderToString(<Landing/>)
const page=new DOMParser().parseFromString(html,'text/html')
const release=(tag:string):ReleaseInfo=>({tag,name:'STAR',publishedAt:'2026-10-13T00:00:00Z',url:LINKS.latest,prerelease:false,assets:[]})

describe('website v1.0 claims',()=>{
 it('reports the measured v0.9.0 and v1.0.0 results as they are, without a combined or best-of score',()=>{
  expect(evaluation.rows.map(row=>[row.suite,row.before,row.after])).toEqual([
   ['Roblox scripting, development set','13 / 34','16 / 34'],
   ['Creation tasks','11 / 23','10 / 23'],
   ['Blind holdout, never used for tuning','8 / 24','9 / 24'],
  ])
  for(const text of ['13 / 34','16 / 34','11 / 23','10 / 23','8 / 24','About the same','inconclusive','not a game-quality score'])
   expect(page.body.textContent?.replace(/\s+/g,' '),text).toContain(text)
  expect(html).not.toMatch(/smarter than|best[- ]in[- ]class|state[- ]of[- ]the[- ]art|29 \/ 57/i)
 })
 it('labels every feature with one honest status, and never shows an open pull request as available',()=>{
  const features=featureGroups.flatMap(group=>group.features)
  expect(features.length).toBeGreaterThanOrEqual(15)
  const soon=features.filter(feature=>feature.status==='soon').map(feature=>feature.name)
  expect(soon).toEqual(['Studio Lab','Blender on a server','Voice'])
  for(const feature of features){
   expect(['available','opt-in','soon']).toContain(feature.status)
   // Anything in the source names the release it first shipped in; coming-soon items name none.
   expect(Boolean(feature.since),feature.name).toBe(feature.status!=='soon')
  }
  const prefix=LINKS.repo+'/blob/main/'
  for(const feature of features)if(feature.doc){
   expect(feature.doc.startsWith(prefix),feature.name).toBe(true)
   expect(existsSync(resolve(process.cwd(),'..',feature.doc.slice(prefix.length))),feature.doc).toBe(true)
  }
  expect(existsSync(resolve(process.cwd(),'..',LINKS.notes.slice(prefix.length)))).toBe(true)
 })
 it('says when a feature is newer than the latest published release',()=>{
  render(<SiteFeatures latest={release('v0.9.0')}/>)
  expect(screen.getAllByText(/In v1\.0\.0, not in a published release yet/).length).toBeGreaterThan(5)
  cleanup()
  render(<SiteFeatures latest={release('v1.0.0')}/>)
  expect(screen.queryByText(/not in a published release yet/)).toBeNull()
 })
 it('describes the learning loop the code implements, including what it has not done yet',()=>{
  expect(learnSteps.map(step=>step.title)).toEqual(['Practise','Check','Propose','Gate','You decide'])
  const text=page.body.textContent||''
  for(const fact of ['300 practice tasks','14-day trial','inconclusive means no','The lesson file bundled with 1.0 is empty','model itself never changes'])
   expect(text,fact).toContain(fact)
  expect(page.querySelectorAll('svg.sw-loop[role="img"] title')).toHaveLength(2)
 })
 it('keeps the known limits on the page',()=>{
  expect(limits.length).toBeGreaterThanOrEqual(5)
  const text=page.body.textContent||''
  for(const fact of ['not code-signed','installing over v0.9.0','not a frontier model','no licence file','Windows 10 is untested'])
   expect(text.toLowerCase(),fact).toContain(fact.toLowerCase())
 })
})

describe('STAR\'s brain map',()=>{
 const brainSource=readFileSync(resolve(process.cwd(),'src','SiteBrain.tsx'),'utf8')
 it('calls it code structure, not neurons, and dates the data',()=>{
  const text=page.body.textContent||''
  expect(text).toContain('It shows structure, not neurons')
  expect(text).toContain('a bigger map does not mean a smarter STAR')
  expect(text).toMatch(/Built with graphify extract \. --code-only on [A-Z][a-z]+ \d{1,2}, 20\d\d/)
  expect(text).toContain('Counted October 13, 2026')
 })
 it('prerenders the static map and growth numbers, and loads the interactive graph only on demand',()=>{
  expect(page.querySelector('#brain img.sw-brain-fallback')?.getAttribute('src')).toBe('./site/brain-graph.svg')
  expect(existsSync(resolve(process.cwd(),'public','site','brain-graph.svg'))).toBe(true)
  expect(page.querySelector('#brain canvas')).toBeNull()
  expect(brainSource).toContain("import('./brainGraph.json')")
  expect(brainSource).not.toMatch(/^import .*brainGraph\.json/m)
  const rows=[...page.querySelectorAll('.sw-growth tbody th')].map(node=>node.textContent)
  expect(rows).toEqual(['v0.6.0','v0.8.1','v0.9.0','v1.0'])
 })
 it('shows only counts that come from the repository or the project notes',()=>{
  const text=page.body.textContent||''
  for(const fact of ['300 with runnable checks','137 checked practice answers','64 pass','18,133 passages'])
   expect(text.replace(/\s+/g,' '),fact).toContain(fact)
  const packs=readdirSync(resolve(process.cwd(),'..','star','skill_packs'),{withFileTypes:true}).filter(entry=>entry.isDirectory()&&!entry.name.startsWith('_'))
  expect(brainCounts.items.find(item=>item.label==='Skill packs')?.value).toBe(String(packs.length))
  const bundled=JSON.parse(readFileSync(resolve(process.cwd(),'..','star','skill_packs','lessons_bundled.json'),'utf8'))
  expect(brainCounts.items.find(item=>item.label==='Lesson candidates')?.value).toBe(String(bundled.lessons.length))
  expect(text.replace(/\s+/g,' ')).toContain(`${bundled.lessons.length} waiting for review`)
 })
})

describe('site navigation, assets and accessibility',()=>{
 it('has one first-level heading and never skips a heading level',()=>{
  const headings=[...page.querySelectorAll('h1,h2,h3,h4,h5,h6')]
  expect(headings.length).toBeGreaterThan(10)
  const levels=headings.map(node=>Number(node.tagName.slice(1)))
  expect(levels[0]).toBe(1)
  expect(levels.filter(level=>level===1)).toHaveLength(1)
  for(let i=1;i<levels.length;i++)expect(levels[i],headings[i].textContent||'').toBeLessThanOrEqual(levels[i-1]+1)
 })
 it('resolves every internal link and keeps ids unique',()=>{
  const ids=[...page.querySelectorAll('[id]')].map(node=>node.id)
  expect(ids).toHaveLength(new Set(ids).size)
  for(const anchor of page.querySelectorAll('a[href^="#"]'))expect(ids,anchor.textContent||'internal link').toContain(anchor.getAttribute('href')?.slice(1))
  expect(page.querySelector('a.sw-skip')?.getAttribute('href')).toBe('#main')
  for(const anchor of page.querySelectorAll('a[target="_blank"]'))expect(anchor.getAttribute('rel')).toContain('noopener')
 })
 it('gives every image alt text and real dimensions, and ships every capture in the manifest',()=>{
  const images=[...page.querySelectorAll('img')]
  expect(images.length).toBeGreaterThanOrEqual(6)
  for(const image of images){
   expect(image.getAttribute('alt'),image.getAttribute('src')||'').toBeTruthy()
   expect(Number(image.getAttribute('width'))).toBeGreaterThan(0)
  }
  for(const files of Object.values(media.images))for(const asset of files)
   expect(existsSync(resolve(process.cwd(),'public','site',asset.file)),asset.file).toBe(true)
  expect(media.sourceVersion).toBe('1.0.0')
 })
 it('keeps visible focus, skip navigation and reduced-motion rules',()=>{
  const css=readFileSync(resolve(process.cwd(),'src','site.css'),'utf8')
  expect(css).toContain('.sw :focus-visible')
  expect(css).toContain('.sw-skip:focus')
  expect(css).toContain('@media (prefers-reduced-motion:reduce)')
  expect(html).toContain('aria-label="Main"')
 })
})

describe('the release the page names',()=>{
 const snapshot=latestStable(builtSnapshot)
 it('never names a release older than the newest one known to be published',()=>{
  // The last v1.0.0 release was published in the OLD source repo,
  // now private. A snapshot can document history but not authorize downloads.
  const historical=readFileSync(resolve(process.cwd(),'..','docs','release','v1.0','RELEASE_NOTES.md'),'utf8')
  expect(historical).toContain('v1.0.0')
  expect(PUBLISHED_FLOOR).toBe('1.0.0')
  expect(snapshot,'historic committed snapshot').not.toBeNull()
  expect(compareVersions(snapshot!.tag,PUBLISHED_FLOOR)).toBeGreaterThanOrEqual(0)
  const readme=readFileSync(resolve(process.cwd(),'..','README.md'),'utf8')
  expect(readme).toContain('**private source repository**')
  expect(readme).toContain('currently has no installer')
 })
 it('drops a stale snapshot instead of naming it, and prefers GitHub\'s live answer',()=>{
  expect(currentRelease(null,release('v0.8.1'))).toBeNull()
  expect(currentRelease(null,release('v'+PUBLISHED_FLOOR))).toBeNull()
  expect(currentRelease(release('v1.0.1'),release('v0.8.1'))?.tag).toBe('v1.0.1')
 })
 it('never prerenders inaccessible private-release downloads as public',()=>{
  const hero=page.querySelector('.sw-hero-meta')?.textContent||''
  expect(hero).toContain('Release details are unavailable')
  expect(hero).not.toContain('v1.0.0')
  const download=page.querySelector('#download')?.textContent||''
  expect(download).toContain('Open the latest release')
  expect(download).not.toContain('Download Setup v1.0.0')
 })
})

describe('download section',()=>{
 it('offers the official release page, not fabricated ZIP or checksum URLs, when release data is missing',()=>{
  render(<SiteDownload latest={null} files={releaseFiles(null)} releaseLive={false} snapshotAt={null}/>)
  expect(screen.getByRole('link',{name:/Open the latest release/i}).getAttribute('href')).toBe(LINKS.latest)
  expect(screen.getByRole('link',{name:/View release assets/i}).getAttribute('href')).toBe(LINKS.latest)
  expect(screen.getByRole('link',{name:/Checksums on GitHub Releases/i}).getAttribute('href')).toBe(LINKS.latest)
  expect(screen.getByText(/Live release details unavailable/)).toBeTruthy()
  expect(screen.getByText(/If a release provides SHA256SUMS.txt/)).toBeTruthy()
 })
 it('lists the requirements, including the optional server',()=>{
  render(<SiteDownload latest={null} files={releaseFiles(null)} releaseLive={false} snapshotAt={null}/>)
  expect(screen.getByText('Or STAR Server')).toBeTruthy()
  expect(screen.getByText(/No graphics card needed/)).toBeTruthy()
 })
})
