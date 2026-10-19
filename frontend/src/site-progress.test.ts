import {afterEach,describe,expect,it,vi} from 'vitest'
import committed from './progress.json'
import {
 CACHE_KEY,ENDPOINTS,FRESH_MS,LATEST_RELEASE_ENDPOINT,RateLimitError,REPO_SLUG,REPO_URL,availability,buildBoard,compareVersions,
 fetchLatestStableRelease,fetchLiveProgress,isFresh,latestStable,newest,normalizeProgress,parseStoredProgress,pullStage,
 readCachedProgress,readRetryAt,repoUrl,writeCachedProgress,writeRetryAt
} from './githubPublic'
import type {ProgressSnapshot} from './githubPublic'
import {releaseFiles} from './siteContent'
import * as generator from '../scripts/build-progress.mjs'
import pkg from '../package.json'
import {createElement} from 'react'
import {renderToString} from 'react-dom/server'
import {Landing} from './Landing'
import * as prerender from '../scripts/prerender-site.mjs'

afterEach(()=>vi.unstubAllGlobals())

const API='https://api.github.com/repos/'+REPO_SLUG
const release=(tag:string,published:string,extra:Record<string,unknown>={})=>({
 tag_name:tag,name:'STAR '+tag,html_url:REPO_URL+'/releases/tag/'+tag,published_at:published,prerelease:false,draft:false,
 assets:[
  {name:'STAR-Setup-'+tag+'.exe',size:226619305,digest:'sha256:'+'d5'.repeat(32),
   browser_download_url:REPO_URL+'/releases/download/'+tag+'/STAR-Setup-'+tag+'.exe'},
  {name:'STAR-Genesis-Windows-x64.zip',size:344663240,digest:'sha256:'+'1f'.repeat(32),
   browser_download_url:REPO_URL+'/releases/download/'+tag+'/STAR-Genesis-Windows-x64.zip'},
  {name:'SHA256SUMS.txt',size:183,digest:null,browser_download_url:REPO_URL+'/releases/download/'+tag+'/SHA256SUMS.txt'}
 ],...extra
})
const pull=(number:number,fields:Record<string,unknown>={})=>({
 number,title:'Pull '+number,html_url:REPO_URL+'/pull/'+number,state:'open',draft:false,merged_at:null,
 created_at:'2026-10-09T10:00:00Z',updated_at:'2026-10-10T10:00:00Z',user:{login:'oncoursemail',type:'User'},labels:[],...fields
})
const sample={
 releases:[release('v0.8.0','2026-10-10T02:11:48Z'),release('v0.8.1','2026-10-10T02:34:23Z')],
 pulls:[
  pull(39,{draft:true,title:'Integration'}),
  pull(40,{title:'Ready for review'}),
  pull(32,{state:'closed',merged_at:'2026-10-10T03:19:17Z',title:'Website'}),
  pull(25,{state:'closed',merged_at:'2026-10-10T02:43:55Z',user:{login:'dependabot[bot]',type:'Bot'}}),
  pull(17,{state:'closed',merged_at:'2026-10-10T02:23:51Z',title:'Maintenance'}),
  pull(28,{state:'closed',draft:true,title:'Superseded'}),
  pull(41,{user:{login:'dependabot[bot]',type:'Bot'}})
 ],
 issues:[
  {number:15,title:'Windows acceptance',html_url:REPO_URL+'/issues/15',state:'open',created_at:'2026-10-09T22:48:36Z',updated_at:'2026-10-09T22:48:36Z',comments:0,labels:[]},
  {number:44,title:'Dark mode for diagrams',html_url:REPO_URL+'/issues/44',state:'open',created_at:'2026-10-10T08:00:00Z',updated_at:'2026-10-10T09:00:00Z',comments:2,labels:[{name:'enhancement'}]},
  {number:39,title:'Integration',html_url:REPO_URL+'/pull/39',state:'open',pull_request:{url:'x'},labels:[]}
 ],
 commits:[{sha:'abcdef0123456789',html_url:REPO_URL+'/commit/abcdef0',commit:{message:'Safe release\nDetails',committer:{date:'2026-10-09T21:00:00Z'}}}],
 milestones:[]
}
const stubGitHub=(overrides:Record<string,()=>Response>={})=>vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
 const part=(Object.keys(ENDPOINTS) as Array<keyof typeof ENDPOINTS>).find(key=>url===API+ENDPOINTS[key])
 if(!part)throw new Error('Unexpected request '+url)
 if(overrides[part])return overrides[part]()
 return new Response(JSON.stringify(sample[part]),{status:200})
}))
const memoryStore=()=>{
 const data=new Map<string,string>()
 return {getItem:(key:string)=>data.get(key)??null,setItem:(key:string,value:string)=>{data.set(key,value)},removeItem:(key:string)=>{data.delete(key)},data}
}

describe('reading public repository data',()=>{
 it('counts only GitHub issues, never pull requests listed among them',()=>{
  const snapshot=normalizeProgress(sample,'2026-10-10T12:00:00Z','live')
  expect(snapshot.issues?.map(issue=>issue.number)).toEqual([15,44])
 })
 it('asks only the five public endpoints, without credentials or custom headers',async()=>{
  stubGitHub()
  const result=await fetchLiveProgress(undefined,Date.parse('2026-10-10T12:00:00Z'))
  const calls=vi.mocked(fetch).mock.calls
  expect(calls.map(call=>call[0]).sort()).toEqual(Object.values(ENDPOINTS).map(path=>API+path).sort())
  for(const [,init] of calls){
   expect(init?.credentials).toBe('omit')
   expect(Object.keys((init?.headers||{}) as Record<string,string>)).toEqual(['Accept'])
  }
  expect(result.partial).toBe(false)
  expect(result.snapshot.origin).toBe('live')
  expect(latestStable(result.snapshot)?.tag).toBe('v0.8.1')
  expect(result.snapshot.commits?.[0]).toMatchObject({sha:'abcdef0',title:'Safe release'})
 })
 it('marks missing parts as unavailable instead of inventing values',async()=>{
  stubGitHub({pulls:()=>new Response('nope',{status:500}),issues:()=>{throw new Error('offline')}})
  const result=await fetchLiveProgress()
  expect(result.partial).toBe(true)
  expect(result.snapshot.pulls).toBeNull()
  expect(result.snapshot.issues).toBeNull()
  expect(result.snapshot.releases).toHaveLength(2)
 })
 it('does not claim success when every request fails',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>{throw new Error('Offline')}))
  await expect(fetchLiveProgress()).rejects.toThrow('temporarily unavailable')
 })
 it('recognises the anonymous rate limit and says when to come back',async()=>{
  const now=Date.parse('2026-10-10T12:00:00Z')
  const reset=Math.round(now/1000)+1800
  stubGitHub({releases:()=>new Response('{}',{status:403,headers:{'x-ratelimit-remaining':'0','x-ratelimit-reset':String(reset)}})})
  const error=await fetchLiveProgress(undefined,now).catch((reason:unknown)=>reason)
  expect(error).toBeInstanceOf(RateLimitError)
  expect((error as RateLimitError).retryAt).toBe(reset*1000)
 })
 it('reads the latest stable published release from GitHub directly, without credentials',async()=>{
  const get=vi.fn(async(_url:string)=>new Response(JSON.stringify(release('v0.9.0','2026-10-11T17:00:00Z')),{status:200}))
  vi.stubGlobal('fetch',get)
  const result=await fetchLatestStableRelease()
  expect(get).toHaveBeenCalledWith(API+LATEST_RELEASE_ENDPOINT,expect.objectContaining({
   credentials:'omit',headers:{Accept:'application/vnd.github+json'}
  }))
  expect(result?.tag).toBe('v0.9.0')
  expect(releaseFiles(result).setup?.url).toBe(REPO_URL+'/releases/download/v0.9.0/STAR-Setup-v0.9.0.exe')
 })
 it('refuses unreleased, foreign or missing latest-release data instead of inventing assets',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(release('v0.9.0','2026-10-11T17:00:00Z',{prerelease:true})),{status:200})))
  expect(await fetchLatestStableRelease()).toBeNull()
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(release('v0.9.0','2026-10-11T17:00:00Z',{assets:[
   {name:'STAR-Setup-v0.9.0.exe',size:1,browser_download_url:'https://untrusted.invalid/setup.exe'}
  ]})),{status:200})))
  expect(releaseFiles(await fetchLatestStableRelease()).setup).toBeNull()
  vi.stubGlobal('fetch',vi.fn(async()=>new Response('{}',{status:502})))
  await expect(fetchLatestStableRelease()).rejects.toThrow('unavailable')
 })
 it('only follows links into this repository',()=>{
  expect(repoUrl(REPO_URL+'/pull/39')).toBe(REPO_URL+'/pull/39')
  expect(repoUrl('javascript:alert(1)')).toBe(REPO_URL)
  expect(repoUrl('https://github.com/someone-else/Star-AI/pull/1')).toBe(REPO_URL)
  expect(repoUrl(REPO_URL+'/pull/1"onmouseover="x')).toBe(REPO_URL)
  const forged=normalizeProgress({releases:[release('v9.9.9','2026-10-11T00:00:00Z',{assets:[
   {name:'STAR-Setup-v9.9.9.exe',size:1,browser_download_url:'https://evil.example/STAR-Setup-v9.9.9.exe',digest:'sha256:'+'a'.repeat(64)}
  ]})]},'2026-10-11T00:00:00Z','live')
  expect(forged.releases?.[0].assets).toEqual([])
 })
})

describe('what counts as shipped',()=>{
 const snapshot=normalizeProgress(sample,'2026-10-10T12:00:00Z','live')
 const board=buildBoard(snapshot)
 it('labels a draft as in progress and never as shipped',()=>{
  expect(pullStage({state:'open',draft:true,mergedAt:null})).toBe('draft')
  expect(pullStage({state:'open',draft:false,mergedAt:null})).toBe('review')
  expect(pullStage({state:'closed',draft:false,mergedAt:'2026-10-10T03:19:17Z'})).toBe('merged')
  expect(pullStage({state:'closed',draft:true,mergedAt:null})).toBe('closed')
  expect(board.active.map(item=>item.number)).toEqual([39,40])
  expect(board.draftCount).toBe(1)
  expect(board.reviewCount).toBe(1)
  expect(board.unreleased.map(item=>item.number)).not.toContain(39)
 })
 it('separates work merged after the latest release from work already in it',()=>{
  expect(board.latest?.tag).toBe('v0.8.1')
  expect(board.unreleased.map(item=>item.number)).toEqual([32])
  expect(board.unreleasedMaintenance).toBe(1)
  expect(board.activeMaintenance).toBe(1)
 })
 it('lists labelled issues as ideas and the rest as tasks',()=>{
  expect(board.tasks.map(item=>item.number)).toEqual([15])
  expect(board.ideas.map(item=>item.number)).toEqual([44])
 })
 it('calls a capability released only when a published release contains it',()=>{
  const latest=board.latest
  expect(availability('0.8.0',latest)).toBe('released')
  expect(availability('0.8.1',latest)).toBe('released')
  expect(availability('0.9.0',latest)).toBe('upcoming')
  expect(availability('0.9.0',null)).toBe('unknown')
  expect(compareVersions('v0.10.0','0.9.9')).toBeGreaterThan(0)
  expect(compareVersions('not a version','0.9.0')).toBe(0)
 })
 it('ignores prereleases when choosing the stable download',()=>{
  const withPre=normalizeProgress({releases:[...sample.releases,release('v0.9.0','2026-10-12T00:00:00Z',{prerelease:true})]},'2026-10-12T01:00:00Z','live')
  expect(withPre.releases?.[0].tag).toBe('v0.9.0')
  expect(latestStable(withPre)?.tag).toBe('v0.8.1')
 })
 it('offers only the real release assets',()=>{
  const files=releaseFiles(board.latest)
  expect(files.setup?.name).toBe('STAR-Setup-v0.8.1.exe')
  expect(files.setup?.url.startsWith(REPO_URL+'/releases/download/v0.8.1/')).toBe(true)
  expect(files.setup?.sha256).toBe('d5'.repeat(32))
  expect(files.zip?.name).toBe('STAR-Genesis-Windows-x64.zip')
  expect(files.sums?.sha256).toBeNull()
  expect(releaseFiles(null)).toEqual({setup:null,zip:null,sums:null})
 })
})

describe('last known state',()=>{
 it('keeps a complete live answer and reuses it while it is fresh',async()=>{
  stubGitHub()
  const store=memoryStore()
  const now=Date.parse('2026-10-10T12:00:00Z')
  const result=await fetchLiveProgress(undefined,now)
  writeCachedProgress(result,store)
  const cached=readCachedProgress(store)
  expect(cached?.generatedAt).toBe('2026-10-10T12:00:00.000Z')
  expect(isFresh(cached,now+FRESH_MS-1)).toBe(true)
  expect(isFresh(cached,now+FRESH_MS+1)).toBe(false)
  expect(store.data.get(CACHE_KEY)).not.toMatch(/"(token|authorization|email)"/i)
 })
 it('never lets a partial answer overwrite the last complete one',async()=>{
  stubGitHub({pulls:()=>new Response('nope',{status:502})})
  const store=memoryStore()
  writeCachedProgress(await fetchLiveProgress(),store)
  expect(store.data.has(CACHE_KEY)).toBe(false)
 })
 it('survives a broken or foreign cache entry',()=>{
  const store=memoryStore()
  store.setItem(CACHE_KEY,'{not json')
  expect(readCachedProgress(store)).toBeNull()
  store.setItem(CACHE_KEY,JSON.stringify({schema:1,repo:'someone/else',generatedAt:'2026-10-10T12:00:00Z',raw:{}}))
  expect(readCachedProgress(store)).toBeNull()
  expect(readCachedProgress(null)).toBeNull()
 })
 it('remembers a rate limit until it has passed',()=>{
  const store=memoryStore()
  writeRetryAt(2_000,store)
  expect(readRetryAt(1_000,store)).toBe(2_000)
  expect(readRetryAt(3_000,store)).toBeNull()
 })
 it('prefers whichever snapshot was read from GitHub most recently',()=>{
  const older=normalizeProgress(sample,'2026-10-10T10:00:00Z','build')
  const newer=normalizeProgress(sample,'2026-10-10T11:00:00Z','live')
  expect(newest(older,newer)).toBe(newer)
  expect(newest(newer,older)).toBe(newer)
  expect(newest(null,older)).toBe(older)
  expect(isFresh(older,Date.parse('2026-10-10T10:01:00Z'))).toBe(false) // a build snapshot is never "live"
 })
})

describe('the build-time snapshot',()=>{
 it('is a valid, dated snapshot of this repository with a downloadable release',()=>{
  const snapshot=parseStoredProgress(committed as unknown,'build') as ProgressSnapshot
  expect(snapshot).not.toBeNull()
  expect(Number.isNaN(Date.parse(snapshot.generatedAt))).toBe(false)
  const files=releaseFiles(latestStable(snapshot))
  expect(files.setup?.url).toMatch(/^https:\/\/github\.com\/oncoursemail\/Star-AI\/releases\/download\/v\d+\.\d+\.\d+\/STAR-Setup-v\d+\.\d+\.\d+\.exe$/)
  expect(files.setup?.sha256).toMatch(/^[0-9a-f]{64}$/)
 })
 it('contains no credentials, e-mail addresses or free-form bodies',()=>{
  const serialised=JSON.stringify(committed)
  expect(serialised).not.toMatch(/gh[pousr]_[A-Za-z0-9]{20}|github_pat_|PRIVATE KEY|authorization/i)
  expect(serialised).not.toMatch(/"(email|body|token)"/)
 })
 it('is written by a generator that reads the same endpoints as the page',()=>{
  expect(generator.ENDPOINTS).toEqual(ENDPOINTS)
  expect(generator.REPO_SLUG).toBe(REPO_SLUG)
 })
 it('is refreshed by the website deployment build and by nothing else',()=>{
  // `npm run build` is what .github/workflows/website-pages.yml runs, so the existing workflow produces the snapshot.
  expect(pkg.scripts.build.startsWith('node scripts/build-progress.mjs --pages-only && ')).toBe(true)
  expect(pkg.scripts.build.endsWith(' && node scripts/prerender-site.mjs --pages-only')).toBe(true)
  expect(generator.shouldRefresh({GITHUB_WORKFLOW_REF:'oncoursemail/Star-AI/.github/workflows/website-pages.yml@refs/heads/main'})).toBe(true)
  expect(generator.shouldRefresh({GITHUB_WORKFLOW_REF:'oncoursemail/Star-AI/.github/workflows/windows-desktop.yml@refs/heads/main'})).toBe(false)
  expect(generator.shouldRefresh({})).toBe(false)
  expect(generator.shouldRefresh({STAR_REFRESH_PROGRESS:'1'})).toBe(true)
 })
 it('lets only allowlisted fields through the generator',()=>{
  const noisy={
   releases:[{...release('v0.8.1','2026-10-10T02:34:23Z'),body:'notes',author:{login:'x',email:'x@example.com'},upload_url:'https://uploads.example'}],
   pulls:[{...pull(39,{draft:true}),body:'secret plan',head:{repo:{clone_url:'x'}},user:{login:'oncoursemail',type:'User',email:'x@example.com'}}],
   issues:[{...sample.issues[0],body:'details',assignee:{email:'x@example.com'}}],
   commits:[{...sample.commits[0],commit:{message:'Title\nBody',author:{email:'x@example.com'},committer:{date:'2026-10-09T21:00:00Z',email:'x@example.com'}},author:{login:'x'}}],
   milestones:[{number:1,title:'v1',html_url:REPO_URL+'/milestone/1',state:'open',due_on:null,open_issues:2,closed_issues:1,description:'long text',creator:{login:'x'}}]
  }
  const document=generator.pickProgress(noisy,'2026-10-10T12:00:00Z')
  const serialised=JSON.stringify(document)
  expect(serialised).not.toMatch(/example\.com|"email"|secret plan|notes|upload_url|clone_url|long text|"body"|Body/)
  const parsed=parseStoredProgress(document,'build')
  expect(parsed?.pulls?.[0]).toMatchObject({number:39,draft:true})
  expect(parsed?.milestones?.[0]).toMatchObject({title:'v1',open:2,closed:1})
  expect(parsed?.commits?.[0].title).toBe('Title')
 })
})

describe('prerendering',()=>{
 // Vitest runs in Node here, so this is the same no-browser render the website build performs.
 const markup=renderToString(createElement(Landing))
 it('renders the whole page without a browser',()=>{
  // React hoists the hero image preload to the front; the prerender script moves it into <head>.
  expect(markup.replace(/^(?:<link [^>]*>)*/,'').startsWith('<div class="sw')).toBe(true)
  expect(markup).toContain('An AI that runs on machines you')
  for(const id of ['features','learning','honest','download'])expect(markup).toContain('id="'+id+'"')
  expect(markup).not.toMatch(/undefined|NaN|\[object Object\]/)
 })
 it('does not offer a historical private installer without a live public release',()=>{
  const snapshot=parseStoredProgress(committed as unknown,'build')
  const setup=releaseFiles(latestStable(snapshot)).setup
  expect(setup).not.toBeNull()
  // The repository was replaced: historical metadata cannot prove public availability.
  expect(markup).not.toContain('href="'+setup!.url+'"')
  expect(markup).toContain('Release details are unavailable')
  expect(markup).toContain('href="'+REPO_URL+'/releases/latest"')
  expect(markup).toContain('Open the latest release')
  expect(markup).not.toContain('STAR-Setup-v'+pkg.version+'.exe')
 })
 it('contains nothing that depends on the visitor clock or time zone',()=>{
  expect(markup).not.toMatch(/\d+ (min|hours?|days?) ago|just now/)
  expect(markup).not.toMatch(/\d{1,2}:\d{2} (AM|PM)/)
 })
 it('only touches a built document with an empty root',()=>{
  const page='<html><body><div id="root"></div></body></html>'
  expect(prerender.injectMarkup(page,'<div class="sw">x</div>')).toBe('<html><body><div id="root"><div class="sw">x</div></div></body></html>')
  expect(prerender.injectMarkup(page,'<p>not the page</p>')).toBeNull()
  expect(prerender.injectMarkup('<html><body><div id="root">already</div></body></html>','<div class="sw">x</div>')).toBeNull()
  expect(prerender.injectMarkup(page,'<div class="sw">$1 $& kept literally</div>')).toContain('$1 $& kept literally')
  const doc='<html><head><title>t</title></head><body><div id="root"></div></body></html>'
  expect(prerender.injectMarkup(doc,'<link rel="preload" as="image" href="a.webp"/><div class="sw">x</div>'))
   .toBe('<html><head><title>t</title><link rel="preload" as="image" href="a.webp"/></head><body><div id="root"><div class="sw">x</div></div></body></html>')
  expect(prerender.injectMarkup(page,'<link rel="preload" href="a"/><div class="sw">x</div>')).toBeNull()
 })
 it('runs for the website deployment and not for desktop builds',()=>{
  expect(prerender.isSiteBuild({GITHUB_WORKFLOW_REF:'oncoursemail/Star-AI/.github/workflows/website-pages.yml@refs/heads/main'})).toBe(true)
  expect(prerender.isSiteBuild({GITHUB_WORKFLOW_REF:'oncoursemail/Star-AI/.github/workflows/windows-desktop.yml@refs/tags/v0.9.0'})).toBe(false)
  expect(prerender.isSiteBuild({})).toBe(false)
 })
})

describe('the public page stays public',()=>{
 const sources=import.meta.glob(['./Landing.tsx','./Site*.tsx','./site*.ts','./githubPublic.ts'],{query:'?raw',import:'default',eager:true}) as Record<string,string>
 it('never imports the native desktop bridge or the desktop workspace',()=>{
  const names=Object.keys(sources).filter(name=>!name.endsWith('.test.ts'))
  expect(names.length).toBeGreaterThanOrEqual(8)
  for(const name of names){
   expect(sources[name],name).not.toMatch(/from '\.\/(bridge|Desktop|components|types)'/)
   expect(sources[name],name).not.toMatch(/window\.qt|webChannelTransport|starBridge|QWebChannel/)
  }
 })
 it('talks to no host other than the public GitHub API',()=>{
  const hosts=new Set<string>()
  for(const [name,code] of Object.entries(sources)){
   if(name.endsWith('.test.ts'))continue
   for(const match of code.matchAll(/fetch\(([^)]*)\)/g))hosts.add(match[1].split(',')[0].trim())
  }
  expect([...hosts]).toEqual(['API_ROOT+ENDPOINTS[part]','API_ROOT+LATEST_RELEASE_ENDPOINT'])
 })
})
