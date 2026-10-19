/**
 * Editorial content for the public website.
 *
 * Every feature carries an honest status (available, opt-in, coming soon) and, when it is in the source, the first
 * release that contains it (`since`). The page compares `since` with the latest *published* GitHub release at view
 * time, so a feature that is only in the source reads "Not in a published release yet" until a release catches up.
 * "Coming soon" items are open pull requests; they are never shown as available.
 */
import pkg from '../package.json'
import {REPO_URL,availability,compareVersions} from './githubPublic'
import type {ReleaseInfo} from './githubPublic'

/** Version of the source this site was built from. It can be ahead of the latest published release. */
export const SOURCE_VERSION:string=pkg.version
const doc=(path:string)=>REPO_URL+'/blob/main/'+path
export const LINKS={
 repo:REPO_URL,
 releases:REPO_URL+'/releases',
 latest:REPO_URL+'/releases/latest',
 issues:REPO_URL+'/issues',
 newIssue:REPO_URL+'/issues/new',
 pulls:REPO_URL+'/pulls',
 commits:REPO_URL+'/commits/main',
 docs:REPO_URL+'/tree/main/docs',
 readme:REPO_URL+'#readme',
 notes:doc('docs/release/v1.0/RELEASE_NOTES.md'),
 start:doc('START_HERE_WINDOWS11.md'),
 security:doc('docs/SECURITY_AND_AUTONOMY.md'),
 server:doc('docs/STAR_MODEL_ROUTER_WINDOWS.md'),
 robloxAccess:doc('docs/ROBLOX_ACCESS.md'),
 knowledge:doc('docs/ROBLOX_KNOWLEDGE.md'),
 evals:doc('docs/evals.md'),
 learning:doc('docs/SELF_LEARNING_LOOP.md'),
 discord:doc('docs/STAR_DISCORD_SETUP.md'),
 design:doc('docs/DESIGN_AND_MAP_TOOLS.md'),
 voice:doc('docs/STAR_VOICE_CALLS.md'),
 media:doc('docs/STAR_MEDIA.md'),
 acceptance:REPO_URL+'/issues/15',
} as const

/**
 * v1.0.0 was the last historically published release in the source repository,
 * which was renamed to Star-AI-Private. It is NOT available anonymously from the
 * new public Star-AI repository. A committed progress snapshot is historical,
 * not proof that a public installer exists.
 */
export const PUBLISHED_FLOOR='1.0.0'

/** Show only current releases verified by the live PUBLIC GitHub Releases API.
 * The prior snapshot is deliberately ignored after the private/public split.
 * Failing closed prevents offering inaccessible historic private binaries.
 */
export function currentRelease(live:ReleaseInfo|null,_snapshot:ReleaseInfo|null):ReleaseInfo|null{
 return live&&compareVersions(live.tag,PUBLISHED_FLOOR)>=0?live:null
}

/** Only label capabilities as shipped when a stable published release confirms them. */
export function modelLabelForRelease(latest:ReleaseInfo|null):string{
 const state=availability('0.9.0',latest)
 if(state==='released')return 'Local, LAN or opt-in hosted'
 if(state==='upcoming')return 'On-device model option'
 return 'Check GitHub'
}

export type FeatureStatus='available'|'opt-in'|'soon'
export const STATUS_LABEL:Record<FeatureStatus,string>={available:'Available','opt-in':'Opt-in',soon:'Coming soon'}
export type Feature={name:string;what:string;status:FeatureStatus;since?:string;doc?:string}
export type FeatureGroup={id:string;title:string;features:Feature[]}

/**
 * The feature index. Sources: docs/release/v1.0/RELEASE_NOTES.md and the merged pull requests it lists.
 * "Coming soon" means an open pull request on GitHub that is not part of the release.
 */
export const featureGroups:FeatureGroup[]=[
 {id:'chat',title:'Chat',features:[
  {name:'Chats you can manage',status:'available',since:'1.0.0',
   what:'Saved chats grouped by day, search, rename, and delete with six seconds to undo. An answer keeps streaming when you switch chats.'},
  {name:'Look at my screen',status:'available',since:'1.0.0',
   what:'STAR asks first, every time, then takes one screenshot that waits in your message until you send or remove it.'},
  {name:'Create image',status:'available',since:'1.0.0',doc:LINKS.media,
   what:'Ask for a picture in the same box. Needs a picture engine (ComfyUI) on this PC or on your STAR Server.'},
  {name:'Web search with sources',status:'opt-in',since:'1.0.0',
   what:'Through the self-hosted SearXNG search on your STAR Server (no paid key), or your own Brave or Tavily key. Answers link their sources.'},
  {name:'Knows the date and time',status:'available',since:'1.0.0',
   what:'Answers get the current local date and time, so “today” and “this week” mean what you think.'},
 ]},
 {id:'make',title:'Making things',features:[
  {name:'Roblox help with sources',status:'available',since:'0.9.0',doc:LINKS.knowledge,
   what:'Answers cite the official Roblox and Luau documentation, retrieved by STAR Knowledge on your server.'},
  {name:'Roblox map plans',status:'available',since:'1.0.0',doc:LINKS.design,
   what:'Blockout and level-layout plans as a dry run, offline and read-only.'},
  {name:'Luau checkers',status:'opt-in',since:'1.0.0',doc:LINKS.robloxAccess,
   what:'An API name check against the full API dump, StyLua, the official Luau analyzer, and server/client trust checks on generated code.'},
  {name:'Roblox Studio, read-only first',status:'opt-in',since:'0.8.0',doc:LINKS.robloxAccess,
   what:'Connect a test place through the official Studio MCP. Inspection is read-only; editing needs a separate switch.'},
  {name:'Design tools',status:'available',since:'1.0.0',doc:LINKS.design,
   what:'A searchable style database (88 UI styles, 192 palettes, 74 font pairings) and a DESIGN.md checker with WCAG contrast.'},
  {name:'Studio Lab',status:'soon',
   what:'STAR builds in a test place, playtests it, looks at the result and fixes it, with several Studios in parallel.'},
  {name:'Blender on a server',status:'soon',
   what:'STAR drives Blender on a second server. The first models, a dragon among them, are first attempts, not finished art.'},
 ]},
 {id:'where',title:'Where STAR runs',features:[
  {name:'STAR Server',status:'opt-in',since:'0.9.0',doc:LINKS.server,
   what:'Your own Linux server runs the brain on its processor, no graphics card needed. The key stays in Windows Credential Manager.'},
  {name:'This PC',status:'available',since:'0.8.0',
   what:'A 4B model on your graphics card (Vulkan, about 8 GB of video memory), downloaded and checked in one step.'},
  {name:'Discord bot',status:'opt-in',since:'1.0.0',doc:LINKS.discord,
   what:'A separate program that answers only you, in DMs: /ask, /image, /status, and /screen, which stays off until you allow it and asks each time.'},
  {name:'Hosted providers',status:'opt-in',since:'0.9.0',
   what:'Groq, OpenRouter, Gemini or Cerebras with your own key. Never a silent fallback.'},
  {name:'Voice',status:'soon',doc:LINKS.voice,
   what:'A warmer “Star” voice, read-aloud and push-to-talk calls. Basic optional voice calls have existed since v0.9.0.'},
 ]},
]

/** "How STAR learns": the loop drawn in SiteLearning. Source: docs/SELF_LEARNING_LOOP.md. */
export const learnSteps=[
 {id:'practise',title:'Practise',body:'While your server is idle, night school works through 300 practice tasks, each with a runnable check.'},
 {id:'check',title:'Check',body:'Answers are scored by the same scorer the evaluation uses.'},
 {id:'propose',title:'Propose',body:'A repeated mistake becomes a lesson: plain text, with its evidence attached.'},
 {id:'gate',title:'Gate',body:'A paired statistical test on held-out tasks. A lesson stays only if it wins; inconclusive means no.'},
 {id:'decide',title:'You decide',body:'“What STAR learned this week” puts a lesson on a 14-day trial, with Undo and Keep.'},
] as const
export const learnCorrections={title:'Your corrections',body:'Mark an answer “Not helpful” and say why. You can turn it into a test STAR has to pass.'} as const

/**
 * Measured on STAR Server (model star-fast, mode auto, skill packs off), one run per task, October 2026.
 * Source: docs/release/v1.0/RELEASE_NOTES.md and docs/agents/release-v1.0.md. Never replace a result with a
 * better-looking one from another run.
 */
export const evaluation={
 rows:[
  {suite:'Roblox scripting, development set',before:'13 / 34',after:'16 / 34',note:''},
  {suite:'Creation tasks',before:'11 / 23',after:'10 / 23',note:''},
  {suite:'Blind holdout, never used for tuning',before:'8 / 24',after:'9 / 24',
   note:'3 tasks stopped by server timeouts on the first pass were run once more on a quiet server.'},
 ],
 setup:'STAR Server, model star-fast, auto mode, skill packs off. One run per task, v0.9.0 and v1.0.0 measured a day apart in October 2026.',
} as const

/**
 * Counts from STAR's learning systems, next to the code map. Sources (no server access needed):
 * skill packs = folders in star/skill_packs; practice tasks = PR #255 (300 tasks, 300/300 verified on the server
 * harness); worked examples = night school's outbox export of October 13, 2026 (docs/agents/self-learning-loop-20261013.md);
 * lessons = star/skill_packs/lessons_bundled.json; knowledge = docs/agents/knowledge-study.md.
 */
declare const __STAR_SKILL_PACKS__: string   // vite.config.ts: folders in star/skill_packs at build time
declare const __STAR_LESSONS__: string   // vite.config.ts: lessons in star/skill_packs/lessons_bundled.json at build time

export const brainCounts={
 asOf:'Counted October 13, 2026, from the repository and the project notes.',
 items:[
  {label:'Skill packs',value:__STAR_SKILL_PACKS__,note:' task-specific instruction packs; most are opt-in'},
  {label:'Practice tasks',value:'300',note:' with runnable checks, all 300 verified on the server'},
  {label:'Worked examples',value:'137',note:' checked practice answers in night school’s outbox; 64 pass the app’s import checks'},
  {label:'Lesson candidates',value:__STAR_LESSONS__,note:' waiting for review: none has passed the paired gate yet, so none is promoted'},
  {label:'Knowledge',value:'18,133',note:' passages of official Roblox documentation, indexed and embedded on the server'},
 ],
} as const

export const limits=[
 {title:'It is early software.',body:'Most testing happened on one Windows 11 PC. Other graphics cards and Windows setups are largely untested.',link:{href:LINKS.acceptance,label:'Acceptance issue #15'}},
 {title:'Not everything was tried for real.',body:'Installing over v0.9.0 with Setup was tried on one PC. Not yet tested end to end: the in-app Install & restart from v0.9.0, a real Look at my screen capture, pictures from the installed app, voice with sound, and the Discord bot on Discord.',link:{href:LINKS.notes,label:'What was and was not tested'}},
 {title:'The installer is not code-signed.',body:'Windows may show a publisher warning. Compare the SHA-256 checksum before you run it.'},
 {title:'It makes mistakes.',body:'The 4B model on a PC is not a frontier model, and neither are the server models. Check anything that matters.'},
 {title:'Roblox work needs your review.',body:'STAR helps inside your test place. It does not ship a finished game, and what it writes needs playtesting.'},
 {title:'Windows only, private development source.',body:'The application source is now private. No licence file has been published for the historical public sources.',link:{href:LINKS.releases,label:'Public release status'}},
] as const

export const requirements=[
 {term:'System',detail:'Windows 11, 64-bit. Windows 10 is untested.'},
 {term:'Model on this PC',detail:'A Vulkan graphics card with about 8 GB of video memory, and 4.3 GB free for the download.'},
 {term:'Or STAR Server',detail:'Your own Linux machine on your network, with plenty of memory. No graphics card needed.'},
 {term:'Account',detail:'None. No sign-in and no API key for a model you run yourself.'},
] as const

/* ---------- formatting ---------- */

/** Sizes the way Windows Explorer shows them (1 MB = 1,048,576 bytes), so the number matches the downloaded file. */
export function formatBytes(bytes:number|null|undefined):string{
 if(!bytes||bytes<=0)return 'size unavailable'
 const mb=bytes/1_048_576
 return mb>=1024?(mb/1024).toFixed(1)+' GB':Math.round(mb)+' MB'
}
export function formatDate(value:string|null|undefined,style:'short'|'long'='short'):string{
 if(!value)return 'date unavailable'
 const date=new Date(value)
 if(Number.isNaN(date.getTime()))return 'date unavailable'
 return date.toLocaleDateString('en',{month:style==='long'?'long':'short',day:'numeric',year:'numeric',timeZone:'UTC'})
}

export type ReleaseFiles={setup:ReleaseInfo['assets'][number]|null;zip:ReleaseInfo['assets'][number]|null;sums:ReleaseInfo['assets'][number]|null}
export function releaseFiles(release:ReleaseInfo|null):ReleaseFiles{
 const assets=release?.assets||[]
 return {
  setup:assets.find(asset=>/^STAR-Setup-v\d+\.\d+\.\d+\.exe$/.test(asset.name))||null,
  zip:assets.find(asset=>asset.name==='STAR-Genesis-Windows-x64.zip')||null,
  sums:assets.find(asset=>asset.name==='SHA256SUMS.txt')||null
 }
}
