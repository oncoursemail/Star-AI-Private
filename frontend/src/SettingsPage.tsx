import {createContext,useContext,useEffect,useId,useLayoutEffect,useMemo,useRef,useState} from 'react'
import type {KeyboardEvent,ReactNode} from 'react'
import {BookOpen,BrainCircuit,Check,ChevronDown,ChevronRight,Download,ExternalLink,FolderOpen,ImagePlus,KeyRound,LoaderCircle,Mic,Palette,RefreshCcw,Search,ShieldCheck,SlidersHorizontal,Smile,Sparkles,Undo2,UserRound,Wrench,X,Zap,Info} from 'lucide-react'
import {Panel,Tag} from './components'
import {WEBSITE_RELEASES} from './constants'
import type {AppSettings,BootData} from './types'
import {ProviderPanel} from './IntegrationPanels'
import {onBackendEvent} from './bridge'
import {RobloxPanel} from './RobloxPanel'
import {BlenderPanel} from './BlenderPanel'
import {ImageAbPanel,MediaPlaces} from './MediaPanel'
import {VoiceSettings} from './VoiceSettings'
import {DiscordSettings} from './DiscordSettings'
import {StudioTargetSettings} from './StudioTargetSettings'
import {ModelFleetPanel,type ModelTeamReport} from './ModelFleetPanel'
import {GpuHelperSettings} from './GpuHelperSettings'
import './settings-page.css'

type Invoke=(action:string,payload?:Record<string,unknown>)=>Promise<unknown>
export type UpdateInfo={available:boolean;version:string;url:string;requires_browser?:boolean;explanation?:string}
export type SettingsSectionId='basics'|'appearance'|'models'|'voice'|'companions'|'account'|'advanced'

/** Everything the page needs from the desktop shell. The shell keeps the state; this page only lays it out. */
export type SettingsPageProps={
 appearance?:ReactNode
 /** Companion choices (CompanionControls); shown on the Companions section. */
 companions?:ReactNode
 /** Sign-in and Metallic block from the shell; a plain note shows when it is absent. */
 account?:ReactNode
 data:BootData
 draft:AppSettings
 setDraft:(update:AppSettings|((d:AppSettings)=>AppSettings))=>void
 act:Invoke
 sync:()=>void
 inactive:boolean
 busy:boolean
 nav:(tab:'tools')=>void
 serverDraft:boolean
 modelChecking:boolean
 modelCheck:{ok:boolean;model:string;sample:string}|null
 modelList:string[]
 testActualModel:()=>void
 routerBusy:boolean
 teamChecking:boolean
 teamResult:ModelTeamReport|null
 selectRouterFolder:()=>void
 startLocalRouter:()=>void
 stopLocalBrain:()=>void
 testSpecialists:()=>void
 imageMode:boolean
 chooseWorkflow:()=>void
 showStar:boolean
 setShowStar:(on:boolean)=>void
 newHome?:boolean
 studioLayout?:boolean
 setStudioLayout?:(on:boolean)=>void
 setNewHome?:(on:boolean)=>void
 clipsOn?:boolean
 setClipsOn?:(on:boolean)=>void
 setReducedMotion:(on:boolean)=>void
 update:UpdateInfo|null
 updateBusy:boolean
 updateProgress:{phase:string;downloaded:number;total:number}|null
 checkForUpdates:()=>void
 installVerifiedUpdate:()=>void
 saveSettings:()=>void
 /** Preview only: open on this section (`?section=`). */
 initialSection?:string
}

/** Seven plain sections. Basics holds what most people change; everything technical sits under Advanced.
 * Every original setting is still here; nothing was removed. */
export const SETTINGS_SECTIONS:{id:SettingsSectionId;label:string;description:string;icon:typeof Sparkles}[]=[
 {id:'basics',label:'Basics',description:'The few things most people change. The defaults suit everyone else.',icon:SlidersHorizontal},
 {id:'appearance',label:'Appearance',description:'Theme, accent color, spacing and layout. Changes apply right away.',icon:Palette},
 {id:'models',label:'Models & speed',description:'Where STAR thinks and how fast it answers.',icon:BrainCircuit},
 {id:'voice',label:'Voice',description:"Star's voice, read-aloud, calls and song recognition.",icon:Mic},
 {id:'companions',label:'Companions',description:'The Star mascot and the companions beside the chat.',icon:Smile},
 {id:'account',label:'Account & Metallic',description:'Your sign-in and Metallic account.',icon:UserRound},
 {id:'advanced',label:'Advanced',description:'Engines, Roblox and Studio, creative tools, knowledge, permissions and update details.',icon:Wrench},
]
/** Sub-headings inside Advanced, in page order; the jump row at its top links to each. */
const ADVANCED_GROUPS=[
 {id:'engine',title:'Model engine'},{id:'roblox',title:'Roblox & Studio'},{id:'creative',title:'Images, 3D & bots'},
 {id:'knowledge',title:'Knowledge & search'},{id:'permissions',title:'Permissions'},{id:'updates',title:'Update details'},
]
const SECTION_KEY='star.settings.section'
const isSection=(value:string):value is SettingsSectionId=>SETTINGS_SECTIONS.some(s=>s.id===value)
function readSection(initial?:string):SettingsSectionId {
 if(initial&&isSection(initial))return initial
 try{const saved=window.localStorage.getItem(SECTION_KEY)||'';if(isSection(saved))return saved}catch{/* storage unavailable */}
 return 'basics'
}
function writeSection(id:SettingsSectionId){try{window.localStorage.setItem(SECTION_KEY,id)}catch{/* preference simply does not persist */}}

/** Lower-case, accents folded, so "resume" finds "résumé" and "Wi-Fi" finds "wifi". */
export function normalizeSearch(text:string):string {
 return text.normalize('NFKD').replace(/[̀-ͯ]/g,'').toLowerCase().replace(/[-_]/g,' ').replace(/\s+/g,' ').trim()
}
/** Every word of the query must appear somewhere in the block's visible text or keywords. */
export function matchesSearch(haystack:string,query:string):boolean {
 const words=normalizeSearch(query).split(' ').filter(Boolean)
 if(!words.length)return true
 const text=normalizeSearch(haystack)
 return words.every(word=>text.includes(word))
}

const SearchMatches=createContext<Set<string>|null>(null)

/** One searchable group of settings. Its own text (labels, help, options) is what search reads, plus a few
 * synonyms people type ("dark", "api key", "animation"). */
function Block({id,keywords='',children}:{id:string;keywords?:string;children:ReactNode}) {
 const matches=useContext(SearchMatches)
 return <div className="settings-block" data-settings-block={id} data-keywords={keywords} hidden={matches!==null&&!matches.has(id)}>{children}</div>
}

/** A titled group inside Advanced. CSS hides it while a search leaves none of its blocks visible. */
function Subgroup({id,title,hint,children}:{id:string;title:string;hint:string;children:ReactNode}) {
 return <section className="settings-subgroup" id={id} aria-labelledby={id+'-title'}>
   <header className="settings-subgroup-head"><h3 id={id+'-title'}>{title}</h3><p>{hint}</p></header>
   {children}
 </section>
}

/** A switch row: the label text is the accessible name, the small line is its description. */
function Switch({label,hint,checked,onChange,disabled,experimental}:{label:string;hint:string;checked:boolean;onChange:(on:boolean)=>void;disabled?:boolean;experimental?:boolean}) {
 const hintId=useId()
 return <label className="setting-switch"><span><strong>{label}{experimental&&<span className="settings-badge">Experimental</span>}</strong><small id={hintId}>{hint}</small></span><input type="checkbox" aria-label={label} aria-describedby={hintId} checked={checked} disabled={disabled} onChange={e=>onChange(e.target.checked)}/></label>
}

type StrataProbeResult={ok:boolean;model:string;sample:string;elapsed_ms:number}

function StrataProbe({draft,invoke,disabled}:{draft:AppSettings;invoke:Invoke;disabled:boolean}) {
 const [busy,setBusy]=useState(false)
 const [result,setResult]=useState<StrataProbeResult|null>(null)
 const [error,setError]=useState('')
 const pending=useRef('')
 useEffect(()=>onBackendEvent(event=>{
   if(!pending.current||event.requestId!==pending.current||event.kind==='progress')return
   pending.current='';setBusy(false)
   if(event.kind==='error'){setResult(null);setError(String(event.data||'Strata test failed').slice(0,260));return}
   const value=event.data as StrataProbeResult|null
   if(value?.ok){setResult(value);setError('')}else{setResult(null);setError('Strata returned no usable test result.')}
 }),[])
 const run=async()=>{
   if(disabled||busy)return
   setBusy(true);setResult(null);setError('')
   const reply=await invoke('testStrata',{endpoint:draft.strata_endpoint||'',model:draft.strata_model||''}) as
     ({pending?:boolean;requestId?:string}&Partial<StrataProbeResult>)|null
   if(reply?.pending&&reply.requestId){pending.current=reply.requestId;return}
   setBusy(false)
   if(reply?.ok){setResult(reply as StrataProbeResult);return}
   if(reply!==null)setError('Strata returned no usable test result.')
 }
 return <div className="settings-actions">
   <button type="button" className="secondary-button" disabled={disabled||busy||!draft.strata_model}
     onClick={()=>void run()}>{busy?<LoaderCircle className="spin" size={14} aria-hidden="true"/>:<Zap size={14} aria-hidden="true"/>} Test Strata</button>
   {result&&<span className="health-result" role="status"><Check size={14} aria-hidden="true"/> {result.sample} · {result.elapsed_ms} ms</span>}
   {error&&<span className="integrated-error" role="alert">{error}</span>}
 </div>
}

function StrataEngineRepair({invoke,disabled}:{invoke:Invoke;disabled:boolean}) {
 const [busy,setBusy]=useState(false)
 const [result,setResult]=useState('')
 const apply=async()=>{
   if(disabled||busy)return
   setBusy(true);setResult('')
   try {
     // Native Qt file picker decides the path; no file path is accepted from React.
     const reply=await invoke('repairStrataConfig') as
       {configured?:boolean;changed?:boolean;restart_required?:boolean;cancelled?:boolean}|null
     if(reply?.cancelled||!reply)return
     if(reply.configured)setResult(reply.changed
       ?'Recovery enabled in Strata config. Restart the Strata server to activate it; a local backup was kept.'
       :'Recovery was already enabled in this Strata config.')
   } finally {setBusy(false)}
 }
 return <div className="settings-actions">
   <button type="button" className="secondary-button" onClick={()=>void apply()}
     disabled={disabled||busy}>{busy?<LoaderCircle className="spin" size={14} aria-hidden="true"/>:<ShieldCheck size={14} aria-hidden="true"/>} Apply engine loop recovery…</button>
   {result&&<small role="status">{result}</small>}
 </div>
}

/** A service key (Brave or Tavily for web search, AudD or AcoustID for song recognition). The key goes to the OS
 * credential vault through saveProviderKey and is never shown again; the page only learns whether one is stored. */
function SearchKey({provider,label,stored,invoke,disabled,onSaved}:{provider:'brave'|'tavily'|'audd'|'acoustid';label:string;stored:boolean;invoke:Invoke;disabled:boolean;onSaved:()=>void}) {
 const field=useRef<HTMLInputElement>(null)
 const [typed,setTyped]=useState(false)
 const [busy,setBusy]=useState(false)
 const [present,setPresent]=useState<boolean|null>(null)
 const [note,setNote]=useState('')
 const has=present??stored
 const inputId=useId(),noteId=useId()
 const save=async()=>{
   const input=field.current
   if(disabled||busy||!input||!input.value.trim())return
   setBusy(true);setNote('')
   try{const ok=await invoke('saveProviderKey',{provider,key:input.value.trim()});if(ok){setPresent(true);setNote(`${label} key saved in Windows Credential Manager.`);onSaved()}}
   finally{input.value='';setTyped(false);setBusy(false)}
 }
 const forget=async()=>{
   if(disabled||busy)return
   setBusy(true);setNote('')
   try{const ok=await invoke('clearProviderKey',{provider});if(ok){setPresent(false);setNote(`${label} key removed.`);onSaved()}}
   finally{setBusy(false)}
 }
 return <div className="settings-key-row">
   <label htmlFor={inputId}>{label} key</label>
   <div className="settings-key-controls">
     <input id={inputId} ref={field} type="password" autoComplete="off" spellCheck={false} disabled={disabled||busy} aria-describedby={note?noteId:undefined}
       placeholder={has?'A key is saved. Paste a new one to replace it.':`Paste a ${label} API key`} onInput={e=>setTyped(Boolean(e.currentTarget.value.trim()))}
       onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();void save()}}}/>
     <button type="button" className="secondary-button" disabled={disabled||busy||!typed} onClick={()=>void save()}>{busy?<LoaderCircle size={14} className="spin" aria-hidden="true"/>:<Check size={14} aria-hidden="true"/>} Save</button>
     <button type="button" className="secondary-button" disabled={disabled||busy||!has} onClick={()=>void forget()} aria-label={`Forget ${label} key`}><X size={14} aria-hidden="true"/> Forget</button>
   </div>
   <span className={'settings-key-state'+(has?' is-on':'')}>{has?<><ShieldCheck size={13} aria-hidden="true"/> Stored in the OS vault</>:'No key stored'}</span>
   {note&&<small id={noteId} role="status">{note}</small>}
 </div>
}

const SETTINGS_KEYS_IGNORED_FOR_DIRTY=new Set(['reduced_motion','use_my_gpu'])  // both save themselves
/** True when the form differs from what was last saved. Reduced motion saves itself, so it never counts. */
export function settingsDirty(draft:AppSettings,saved:AppSettings):boolean {
 const a=draft as unknown as Record<string,unknown>,b=saved as unknown as Record<string,unknown>
 for(const key of new Set([...Object.keys(a),...Object.keys(b)])){
   if(SETTINGS_KEYS_IGNORED_FOR_DIRTY.has(key))continue
   const x=a[key],y=b[key]
   if(x===y||(x==null&&y==null))continue
   if(typeof x==='object'||typeof y==='object'){if(JSON.stringify(x)===JSON.stringify(y))continue}
   return true
 }
 return false
}

export function SettingsPage(props:SettingsPageProps) {
 const {data,draft,setDraft,act,sync,inactive,busy,nav,serverDraft,modelChecking,modelCheck,modelList,update,updateBusy,updateProgress}=props
 const [section,setSection]=useState<SettingsSectionId>(()=>readSection(props.initialSection))
 const [query,setQuery]=useState('')
 const [matches,setMatches]=useState<Set<string>|null>(null)
 const root=useRef<HTMLDivElement>(null)
 const tabRefs=useRef<Record<string,HTMLButtonElement|null>>({})
 const searchRef=useRef<HTMLInputElement>(null)
 const baseId=useId()
 const searching=query.trim().length>0
 const dirty=useMemo(()=>settingsDirty(draft,data.settings),[draft,data.settings])
 const set=(patch:Partial<AppSettings>)=>setDraft(d=>({...d,...patch}))

 // Search reads the rendered text of every block (hidden tabs included), so it can never drift from the labels.
 useLayoutEffect(()=>{
   if(!searching||!root.current){setMatches(null);return}
   const found=new Set<string>()
   root.current.querySelectorAll<HTMLElement>('[data-settings-block]').forEach(el=>{
     const labels=[...el.querySelectorAll<HTMLElement>('[aria-label],[placeholder],option')].map(n=>(n.getAttribute('aria-label')||'')+' '+(n.getAttribute('placeholder')||'')+' '+(n.tagName==='OPTION'?n.textContent:'')).join(' ')
     if(matchesSearch((el.textContent||'')+' '+labels+' '+(el.dataset.keywords||''),query))found.add(el.dataset.settingsBlock||'')
   })
   setMatches(found)
 },[query,searching])
 useEffect(()=>{writeSection(section);tabRefs.current[section]?.scrollIntoView?.({block:'nearest',inline:'nearest'})},[section])

 const choose=(id:SettingsSectionId)=>{setSection(id);if(searching)setQuery('');root.current?.closest('.scroll-region')?.scrollTo?.({top:0})}
 const onTabKey=(e:KeyboardEvent<HTMLButtonElement>,index:number)=>{
   const keys:Record<string,number>={ArrowDown:index+1,ArrowRight:index+1,ArrowUp:index-1,ArrowLeft:index-1,Home:0,End:SETTINGS_SECTIONS.length-1}
   if(!(e.key in keys))return
   e.preventDefault()
   const next=SETTINGS_SECTIONS[(keys[e.key]+SETTINGS_SECTIONS.length)%SETTINGS_SECTIONS.length]
   setSection(next.id);tabRefs.current[next.id]?.focus()
 }
 const sectionHasMatch=(id:SettingsSectionId)=>{
   if(!matches||!root.current)return true
   return [...root.current.querySelectorAll<HTMLElement>(`[data-settings-section="${id}"] [data-settings-block]`)].some(el=>matches.has(el.dataset.settingsBlock||''))
 }
 const resultCount=matches?matches.size:0

 const panels:Record<SettingsSectionId,ReactNode>={
  basics:<>
   <Block id="answers" keywords="chat image picture web internet search news">
     <Panel className="settings-section"><h3 className="settings-group-title">Answers</h3>
       <Switch label="Search the web when a question needs it" hint="News, prices and weather questions are sent to your search provider without asking." checked={draft.web_auto_search!==false} onChange={on=>set({web_auto_search:on})}/>
       <Switch label="Create images straight from chat" hint="A message that clearly asks for a picture goes to your image tools instead of the text model." checked={draft.media_chat_auto!==false} onChange={on=>set({media_chat_auto:on})}/>
     </Panel>
   </Block>
   <Block id="motion" keywords="animation motion accessibility calm">
     <Panel className="settings-section"><h3 className="settings-group-title">Comfort</h3>
       <Switch label="Reduced motion" hint="Turns off animation everywhere in STAR and saves at once." checked={draft.reduced_motion} onChange={props.setReducedMotion}/>
     </Panel>
   </Block>
   <Block id="updates" keywords="version update upgrade release install about">
     <Panel className="settings-section updater-panel">
       <div className="section-heading"><div><h3 className="settings-group-title">Updates</h3></div><Tag kind={update?.available?'gold':'neutral'}>{update?.available?'Update ready':`v${data.version}`}</Tag></div>
       <div className="update-version-line"><span><strong>Installed</strong> v{data.version}</span><span><strong>Latest checked</strong> {update?`v${update.version}`:'Not checked yet'}</span></div>
       {update?.available&&<div className="update-found"><Download size={18} aria-hidden="true"/><div><strong>STAR v{update.version} is available</strong><small>Verify the installer, upgrade in place, and relaunch STAR.</small></div></div>}
       {update&&!update.available&&!update.requires_browser&&<div className="update-current"><Check size={16} aria-hidden="true"/> You have the latest published STAR release.</div>}
       <div className="update-actions"><button className="secondary-button" type="button" disabled={updateBusy} onClick={props.checkForUpdates}>{updateBusy&&!updateProgress?<LoaderCircle size={15} className="spin" aria-hidden="true"/>:<RefreshCcw size={15} aria-hidden="true"/>} {updateBusy&&!updateProgress?'Checking…':'Check for updates'}</button>
         {update?.available&&!update.requires_browser&&<button className="primary-button" type="button" disabled={updateBusy} onClick={props.installVerifiedUpdate}><Download size={16} aria-hidden="true"/> {updateBusy?'Preparing upgrade…':'Install & restart'}</button>}
         {update?.requires_browser&&<a className="secondary-button" href={WEBSITE_RELEASES} rel="noopener noreferrer" target="_blank"><ExternalLink size={15} aria-hidden="true"/> Open public releases</a>}
       </div>
       {updateProgress&&<div className="update-download" role="status" aria-live="polite"><div className="update-download-label"><span>{updateProgress.phase}</span><strong>{updateProgress.total?Math.round(updateProgress.downloaded/updateProgress.total*100)+'%':'Preparing…'}</strong></div><div className="progress-track" role="progressbar" aria-label="Update download" aria-valuemin={0} aria-valuemax={100} aria-valuenow={updateProgress.total?Math.min(100,Math.round(updateProgress.downloaded/updateProgress.total*100)):undefined}><div className={updateProgress.total?'':'progress-indeterminate'} style={updateProgress.total?{width:`${Math.min(100,Math.round(updateProgress.downloaded/updateProgress.total*100))}%`}:undefined}/></div></div>}
     </Panel>
   </Block>
  </>,
  appearance:<>
   <Block id="appearance" keywords="theme dark light colour color accent density spacing compact pearl obsidian dusk grove">
     {props.appearance}
   </Block>
   <Block id="layout" keywords="studio layout workbench home start canvas starter">
     <Panel className="settings-section"><h3 className="settings-group-title">Layout</h3>
       {props.setStudioLayout&&<Switch label="Studio layout" hint="Adds a workspace switch, an Appearance menu and a companion shelf beside the chat." checked={!!props.studioLayout} onChange={props.setStudioLayout}/>}
       {props.setNewHome&&<Switch label="Workbench home screen" hint="Shows a start canvas with starter tasks when a chat is empty." checked={!!props.newHome} onChange={props.setNewHome}/>}
     </Panel>
   </Block>
  </>,
  models:<>
   <Block id="model-id" keywords="local brain endpoint model id llm server test connection">
     <Panel className="settings-section"><div className="section-heading"><div><h3 className="settings-group-title">{serverDraft?'STAR Server model':'Local model'}</h3><p>{serverDraft?'The model your STAR Server runs. Its address, key and limits are under Model & provider below.':'STAR Brain configures these automatically after installation.'}</p></div><BrainCircuit size={20} aria-hidden="true"/></div>
       <div className="field-grid"><label>{serverDraft?'Server model ID':'Model ID'}<input list="star-model-ids" value={draft.model} onChange={e=>set({model:e.target.value})} placeholder={serverDraft?'Model on your STAR Server':'Installed model'}/></label>{!serverDraft&&<label>Local endpoint<input value={draft.endpoint} onChange={e=>set({endpoint:e.target.value})}/></label>}</div>
       <div className="settings-actions"><button className="secondary-button" type="button" onClick={()=>void act('listModels')}>List available models <RefreshCcw size={14} aria-hidden="true"/></button><button className="secondary-button" type="button" disabled={modelChecking||!draft.model} onClick={props.testActualModel}>{modelChecking?<LoaderCircle className="spin" size={14} aria-hidden="true"/>:<Zap size={14} aria-hidden="true"/>} Test actual response</button></div>
       {modelCheck&&<div className="health-result" role="status"><Check size={16} aria-hidden="true"/> <span>Live response: {modelCheck.sample}</span></div>}{modelList.length>0&&<small>Available: {modelList.join(', ')}</small>}
     </Panel>
   </Block>
   <Block id="provider" keywords="api key cloud groq openrouter gemini cerebras star server provider lan">
     <ProviderPanel draft={draft} onChange={setDraft} credentials={data.credentials||{}} invoke={act} refresh={sync} disabled={inactive}/>
   </Block>
   <Block id="speed" keywords="fast instant speed typing warm prefill">
     <Panel className="settings-section"><h3 className="settings-group-title">Speed</h3>
       <Switch label="Instant answers on this PC" hint="Simple Fast and Auto questions use a model already loaded on this PC; STAR never loads one for you." checked={draft.instant_route_enabled===true} onChange={on=>set({instant_route_enabled:on})}/>
       <Switch label="Start thinking while I type" hint="After a short pause in typing, the model reads your draft so the answer starts sooner." checked={draft.prefill_while_typing===true} onChange={on=>set({prefill_while_typing:on})}/>
     </Panel>
   </Block>
   <Block id="gpu-helper" keywords="use my gpu graphics card nvidia cuda speed faster local llama">
     <GpuHelperSettings draft={draft} set={set} disabled={inactive}/>
   </Block>
  </>,
  voice:<>
   <Block id="voice" keywords="voice speech speak tts read aloud sound audio">
     <VoiceSettings disabled={inactive}/>
   </Block>
   <Block id="song-recognition" keywords="song music recognition identify shazam audd acoustid chromaprint fpcalc">
     <Panel className="settings-section"><div className="section-heading"><div><h3 className="settings-group-title">Song recognition</h3><p>Identify a song from a WAV file or a short recording. Each lookup asks first. AudD receives the audio clip; AcoustID receives only a fingerprint made on this PC by Chromaprint fpcalc.</p></div><KeyRound size={20} aria-hidden="true"/></div>
       <Switch label="Song recognition" hint="Adds Identify a song to the composer and a lookup line for an attached WAV." checked={draft.music_recognition_enabled===true} onChange={on=>set({music_recognition_enabled:on})}/>
       {draft.music_recognition_enabled===true&&<>
         <SearchKey provider="audd" label="AudD" stored={!!data.credentials?.audd} invoke={act} disabled={inactive} onSaved={sync}/>
         <SearchKey provider="acoustid" label="AcoustID" stored={!!data.credentials?.acoustid} invoke={act} disabled={inactive} onSaved={sync}/>
         <div className="intelligence-folder-row"><label>Chromaprint fpcalc program<input aria-label="Chromaprint fpcalc program" value={draft.fpcalc_path??''} onChange={e=>set({fpcalc_path:e.target.value})} placeholder="Not set: fpcalc is looked up on PATH"/></label></div>
       </>}
     </Panel>
   </Block>
  </>,
  companions:<>
   <Block id="companions" keywords="mascot pet star companion character shelf">
     <Panel className="settings-section"><h3 className="settings-group-title">Star</h3>
       <Switch label="Show Star" hint="Shows the Star mascot over the chat; saved on this device." checked={props.showStar} onChange={props.setShowStar}/>
     </Panel>
     {props.companions&&<Panel className="settings-section"><h3 className="settings-group-title">Companion shelf</h3><p className="settings-panel-note">Companions sit on a shelf beside the chat when Studio layout is on.</p>{props.companions}</Panel>}
   </Block>
  </>,
  account:<>
   <Block id="account" keywords="account sign in login metallic profile">
     {props.account??<Panel className="settings-section"><h3 className="settings-group-title">Account</h3><p className="settings-panel-note">Nothing to set up here yet. Sign-in and Metallic options appear here when they are available.</p></Panel>}
   </Block>
  </>,
  advanced:<>
   {!searching&&<nav className="settings-jump" aria-label="Advanced groups">{ADVANCED_GROUPS.map(g=><button key={g.id} type="button" className="settings-jump-link" onClick={()=>document.getElementById(`${baseId}-adv-${g.id}`)?.scrollIntoView?.({block:'start'})}>{g.title}</button>)}</nav>}
   <Subgroup id={`${baseId}-adv-engine`} title="Model engine" hint="A second local engine, the model team and how much each task may use.">
   <Block id="strata" keywords="strata qwen qwen3.8 flash next large model reasoning coding roblox local second engine">
     <Panel className="settings-section"><div className="section-heading"><div><h3 className="settings-group-title">Strata + Qwen3.8 specialist</h3><p>Optional second local engine for harder code, Roblox, research and Agent tasks. Simple chat stays on your normal resident model.</p></div><Sparkles size={20} aria-hidden="true"/></div>
       <Switch label="Use Strata for hard local work" hint="With the Local provider, complex tasks go to the Strata endpoint and fall back to your resident model." checked={draft.strata_enabled===true} disabled={inactive||draft.provider!=='local'} onChange={on=>set({strata_enabled:on})}/>
       <div className="field-grid">
         <label>Strata endpoint<input value={draft.strata_endpoint??'http://127.0.0.1:8082/v1'} disabled={inactive||draft.strata_enabled!==true} onChange={e=>set({strata_endpoint:e.target.value})} placeholder="http://127.0.0.1:8082/v1"/></label>
         <label>Strata model ID<input value={draft.strata_model??'strata'} disabled={inactive||draft.strata_enabled!==true} onChange={e=>set({strata_model:e.target.value})} placeholder="strata"/></label>
         <label>Reasoning
           <select value={draft.strata_reasoning??'auto'} disabled={inactive||draft.strata_enabled!==true} onChange={e=>set({strata_reasoning:e.target.value as AppSettings['strata_reasoning']})}>
             <option value="auto">Automatic by task</option><option value="none">None</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
           </select>
         </label>
         <label>Context tokens<input type="number" min="4096" max="262144" step="1024" value={draft.strata_context_tokens??32768} disabled={inactive||draft.strata_enabled!==true} onChange={e=>set({strata_context_tokens:Number(e.target.value)})}/></label>
         <label>Request timeout (seconds)<input type="number" min="60" max="1800" step="30" value={draft.strata_timeout??900} disabled={inactive||draft.strata_enabled!==true} onChange={e=>set({strata_timeout:Number(e.target.value)})}/></label>
       </div>
       <Switch label="Let Strata inspect images" hint="Lets Strata read images when it debugs visual or Roblox problems." checked={draft.strata_vision_enabled!==false} disabled={inactive||draft.strata_enabled!==true} onChange={on=>set({strata_vision_enabled:on})}/>
       <Switch label="Stop runaway Strata repetition" hint="Stops a request that keeps repeating the same passage." checked={draft.strata_loop_guard_enabled!==false} disabled={inactive||draft.strata_enabled!==true} onChange={on=>set({strata_loop_guard_enabled:on})}/>
       <StrataProbe draft={draft} invoke={act} disabled={inactive||draft.strata_enabled!==true}/>
       <StrataEngineRepair invoke={act} disabled={inactive||draft.provider!=='local'}/>
       <small>Engine recovery requires Strata 0.1.40 or newer. Choose its installed strata-*.json file to enable recovery with an exact local backup; restart Strata afterwards.</small>
       <small>STAR never downloads or starts Strata automatically. Run Strata separately on this loopback endpoint; keeping it separate lets the small model stay fast for everyday chat.</small>
     </Panel>
   </Block>
   <Block id="fleet" keywords="router specialists team models gpu local">
     <ModelFleetPanel draft={draft} onChange={setDraft} models={modelList} routerRunning={!!data.model_router_running} brainRunning={data.brain_running} disabled={inactive} busy={busy} routerBusy={props.routerBusy} teamChecking={props.teamChecking} teamResult={props.teamResult} chooseFolder={props.selectRouterFolder} startRouter={props.startLocalRouter} stopBrain={props.stopLocalBrain} testTeam={props.testSpecialists}/>
   </Block>
   <Block id="limits" keywords="limits turns context budget tokens performance prompt">
     <Panel className="settings-section"><h3 className="settings-group-title">Limits</h3>
       <div className="field-grid"><label>Model turns per task<input type="number" min="1" max="30" value={draft.max_calls} onChange={e=>set({max_calls:Number(e.target.value)})}/></label><label>Context character budget<input type="number" min="6000" max="80000" value={draft.context_chars} onChange={e=>set({context_chars:Number(e.target.value)})}/></label></div>
       <Switch label="Describe session capabilities to the model" hint="Adds a short note about what this session can do; still being evaluated." experimental checked={draft.session_capabilities_prompt===true} onChange={on=>set({session_capabilities_prompt:on})}/>
     </Panel>
   </Block>
   </Subgroup>
   <Subgroup id={`${baseId}-adv-roblox`} title="Roblox & Studio" hint="Open Cloud, documentation, Luau help and the Studio place STAR works in.">
   <Block id="roblox" keywords="open cloud roblox research creator store api">
     <RobloxPanel status={data.roblox} draft={draft} onChange={setDraft} invoke={act} disabled={inactive}/>
   </Block>
   <Block id="roblox-docs" keywords="documentation docs live create.roblox.com engine reference internet skill packs guidance embedding">
     <Panel className="settings-section"><h3 className="settings-group-title">Roblox documentation</h3>
       <Switch label="Read the live Roblox documentation" hint="Looks up create.roblox.com pages while answering; only the search words leave this PC." checked={draft.roblox_docs_live_enabled===true} onChange={on=>set({roblox_docs_live_enabled:on})}/>
       <Switch label="Find guidance packs by meaning" hint="With STAR Server, picks the closest guidance pack by meaning and falls back to word matching." checked={draft.skill_pack_embeddings===true} onChange={on=>set({skill_pack_embeddings:on})}/>
     </Panel>
   </Block>
   <Block id="roblox-code" keywords="luau code studio tools examples retry fix thinking edit diff changed lines repair syntax">
     <Panel className="settings-section"><h3 className="settings-group-title">Roblox code help</h3>
       <Switch label="Show example Studio tool calls" hint="Adds one example call to each Studio tool so fewer calls are refused; permissions do not change." checked={draft.studio_tool_examples===true} onChange={on=>set({studio_tool_examples:on})}/>
       <Switch label="Retry a failed Luau fix with more thinking" hint="When a Luau fix still fails the check, tries once more with thinking on, so answers can take longer." checked={draft.luau_retry_ladder===true} onChange={on=>set({luau_retry_ladder:on})}/>
       <Switch label="Repair a failed tool step before going on" hint="When a tool step or saved file fails its check, holds other changes and makes at most two focused fixes." checked={draft.incremental_repair===true} onChange={on=>set({incremental_repair:on})}/>
       <Switch label="Write only the changed lines when I paste code" hint="For pasted code, asks the model for the changed lines only, applies them and checks the result." checked={draft.edit_diff===true} onChange={on=>set({edit_diff:on})}/>
     </Panel>
   </Block>
   <Block id="studio-target" keywords="studio place practice host this pc mcp">
     <StudioTargetSettings settings={data.settings} disabled={inactive} onSaved={sync} openTools={()=>nav('tools')}/>
   </Block>
   </Subgroup>
   <Subgroup id={`${baseId}-adv-creative`} title="Images, 3D & bots" hint="Where pictures run, ComfyUI, Blender, Discord and extra Tools panels.">
   <Block id="media" keywords="image picture voice video where generate comfyui gpu">
     <MediaPlaces settings={data.settings} invoke={act} disabled={inactive} refresh={sync}/>
   </Block>
   <Block id="image-ab" keywords="picture quality blind test compare old new pipeline image better">
     <ImageAbPanel invoke={act} disabled={inactive}/>
   </Block>
   <Block id="comfy" keywords="comfyui workflow image generation node port">
     <details className="settings-expander" open={props.imageMode||undefined}>
       <summary><span className="settings-expander-icon"><ImagePlus size={20} aria-hidden="true"/></span><span><strong>Image generation</strong><small>Use your own ComfyUI workflow</small></span><ChevronDown size={18} aria-hidden="true"/></summary>
       <div className="settings-expander-body">
         <p>Optional. Create image in the chat + menu works without this. If you choose your own API-format ComfyUI workflow here, STAR uses it for text-to-image instead; editing an attached picture always uses the built-in model.</p>
         <label className="image-workflow-label">Workflow file
           <button className="workflow-picker" type="button" onClick={props.chooseWorkflow}><FolderOpen size={17} aria-hidden="true"/><span>{draft.comfy_workflow?(draft.comfy_workflow.split(/[\\/]/).pop()||draft.comfy_workflow):'Choose a workflow (.json)'}</span><ChevronRight size={17} aria-hidden="true"/></button>
         </label>
         <div className="field-grid image-options"><label>Prompt node ID<input type="text" inputMode="numeric" value={draft.comfy_prompt_node} onChange={e=>set({comfy_prompt_node:e.target.value})}/></label><label>ComfyUI port<input type="number" min="1" max="65535" value={draft.comfy_port} onChange={e=>set({comfy_port:Number(e.target.value)})}/></label></div>
         <small>ComfyUI must already be running on this PC. Only approved core workflow nodes are allowed. Save settings before generating.</small>
       </div>
     </details>
   </Block>
   <Block id="blender" keywords="blender 3d model mesh">
     <BlenderPanel draft={draft} onChange={setDraft} status={data.blender} invoke={act} disabled={inactive||busy}/>
   </Block>
   <Block id="discord" keywords="discord bot autostart start stop supervisor">
     <DiscordSettings disabled={inactive}/>
   </Block>
   <Block id="clips" keywords="clips obs replay recording game lab tools">
     <Panel className="settings-section"><h3 className="settings-group-title">Tools page</h3>
       {props.setClipsOn&&<Switch label="STAR Clips and Game Lab" hint="Shows the OBS replay, clip and Game Lab panels on the Tools page; needs your own OBS Studio." checked={!!props.clipsOn} onChange={props.setClipsOn}/>}
     </Panel>
   </Block>
   </Subgroup>
   <Subgroup id={`${baseId}-adv-knowledge`} title="Knowledge & search" hint="Search keys, deep research and the read-only knowledge tools.">
   <Block id="web-search" keywords="internet brave tavily api key web search deep research sources">
     <Panel className="settings-section"><div className="section-heading"><div><h3 className="settings-group-title">Web search</h3><p>{serverDraft?'With STAR Server selected, STAR uses the server’s search. A Brave or Tavily key is used instead when you add one here.':'Add a Brave or Tavily key so STAR can search the web. Your search words go to that provider; nothing else does.'}</p></div><KeyRound size={20} aria-hidden="true"/></div>
       <SearchKey provider="brave" label="Brave Search" stored={!!data.credentials?.brave} invoke={act} disabled={inactive} onSaved={sync}/>
       <SearchKey provider="tavily" label="Tavily" stored={!!data.credentials?.tavily} invoke={act} disabled={inactive} onSaved={sync}/>
       <Switch label="Read source pages in deep research" hint="With Team and Research on, reads up to 12 public pages and shows where each claim came from." checked={draft.deep_research_enabled===true} onChange={on=>set({deep_research_enabled:on})}/>
       <Switch label="Add scholarly papers to deep research" hint="Also searches Crossref and OpenAlex; your research question is sent to both." checked={draft.scholarly_research_enabled===true} onChange={on=>set({scholarly_research_enabled:on})}/>
     </Panel>
   </Block>
   <Block id="knowledge-tools" keywords="skills graphify obsidian notes vault practice examples knowledge agents.md project rules">
     <Panel className="settings-section">
       <div className="section-heading"><div><h3 className="settings-group-title">Knowledge & expert tools</h3><p>New tools are strictly read-only. STAR discovers them on demand to avoid slowing ordinary conversations.</p></div><BookOpen size={20} aria-hidden="true"/></div>
       <Switch label="Enable Agent Skills" hint="Loads matching local SKILL.md instructions and never runs bundled code." checked={draft.skills_enabled??true} onChange={on=>set({skills_enabled:on})}/>
       <Switch label="Use checked practice examples" hint="Uses answers you imported by hand as untrusted local references, never training data." checked={draft.worked_examples_enabled===true} onChange={on=>set({worked_examples_enabled:on})}/>
       <Switch label="Pre-solve likely requests overnight" hint="Between 02:00 and 07:00, re-answers up to 6 recurring requests and keeps only answers that pass the Luau checks." checked={draft.presolve_enabled===true} onChange={on=>set({presolve_enabled:on})}/>
       <Switch label="Follow my workspace's project rules" hint="Adds AGENTS.md or CLAUDE.md from your workspace to each answer; conventions only, never permissions." checked={draft.project_rules_enabled===true} onChange={on=>set({project_rules_enabled:on})}/>
       <Switch label="Enable Graphify graph queries" hint="Reads graphify-out/graph.json in your selected workspace." checked={draft.graphify_enabled??true} onChange={on=>set({graphify_enabled:on})}/>
       <Switch label="Allow read-only Obsidian vault access" hint="STAR may search Markdown notes only in the folder you select." checked={draft.obsidian_enabled??false} onChange={on=>set({obsidian_enabled:on})}/>
       <div className="intelligence-folder-row"><label>Obsidian vault folder<input aria-label="Obsidian vault folder" value={draft.obsidian_vault??''} onChange={e=>set({obsidian_vault:e.target.value})} placeholder="Choose an Obsidian Markdown vault"/></label><button type="button" className="secondary-button" onClick={async()=>{const result=await act('selectFolder');if(result&&typeof result==='object'&&'path' in result&&typeof result.path==='string'&&result.path){const path=result.path;set({obsidian_vault:path})}}}><FolderOpen size={15} aria-hidden="true"/> Browse folder</button></div>
       <small>Note contents stay local, are not promoted into trusted memory without review, and cannot override tool permissions.</small>
     </Panel>
   </Block>
   </Subgroup>
   <Subgroup id={`${baseId}-adv-permissions`} title="Permissions" hint="What STAR may change on this PC. Everything starts read-only.">
   <Block id="permissions" keywords="permissions write edit folder workspace studio access security">
     <Panel className="settings-section"><h3 className="settings-group-title">Workspace & Studio</h3>
       <div className="field-grid"><label>Workspace folder<input value={draft.workspace} onChange={e=>set({workspace:e.target.value})} placeholder="Choose a project folder"/></label><div className="settings-field-static"><span>Selected Roblox Studio</span><small>{data.settings.studio_id||'Connect an open place in Tools first'}</small><button className="secondary-button" type="button" onClick={()=>nav('tools')}>Open Studio connections</button></div></div>
       <Switch label="Analyze debugger reports" hint="Reads test failures and debugger captures in your workspace and suggests focused checks." experimental checked={draft.debug_evidence_enabled===true} onChange={on=>set({debug_evidence_enabled:on})}/>
       <Switch label="Plan live-show episodes" hint="Checks an episode manifest in your workspace offline; nothing is rendered, posted or streamed." experimental checked={draft.live_show_enabled===true} onChange={on=>set({live_show_enabled:on})}/>
      <Switch label="Minecraft pack and server-folder tools" hint="Checks your own packs and server-folder details inside your workspace; nothing is downloaded, run or connected." experimental checked={draft.minecraft_tools_enabled===true} onChange={on=>set({minecraft_tools_enabled:on})}/>
      <Switch label="3D asset templates" hint="Builds 3D props, characters, creatures and buildings from parametric templates into your workspace (needs workspace editing); renders only with an operator-configured Blender builder." experimental checked={draft.asset3d_tools_enabled===true} onChange={on=>set({asset3d_tools_enabled:on})}/>
       <Switch label="Allow workspace writes" hint="Only inside your selected workspace." checked={draft.workspace_edit} onChange={on=>set({workspace_edit:on})}/>
       <Switch label="Allow Studio edits" hint="Use an unpublished disposable test place first." checked={draft.studio_edit} onChange={on=>set({studio_edit:on})}/>
     </Panel>
   </Block>
   </Subgroup>
   <Subgroup id={`${baseId}-adv-updates`} title="Update details" hint="How STAR checks and installs a new version.">
   <Block id="update-details" keywords="version update upgrade release checksum sha build github">
     <Panel className="settings-section"><h3 className="settings-group-title">How updates install</h3>
       <p>STAR downloads official Windows releases, checks the exact file size and SHA-256 checksum, and replaces application files. Your chats, projects, memories, settings, and downloaded models remain in your local profile.</p>
       {data.build?.stamped&&<small>Build source {data.build.head_commit.slice(0,12)} · <a href={data.build.run_url} target="_blank" rel="noopener noreferrer">View exact GitHub build</a></small>}
       <small>Upgrades start only after you choose Install & restart. Installing does not erase your local data.</small>
     </Panel>
   </Block>
   </Subgroup>
  </>,
 }

 return <div className="settings-layout" ref={root}>
   <div className="settings-head">
     <div className="page-intro"><h1>Settings</h1><p>Personalize STAR and connect the tools you need.</p></div>
     <div className="settings-search" role="search">
       <Search size={15} aria-hidden="true"/>
       <input ref={searchRef} type="search" aria-label="Search settings" placeholder="Search settings" value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Escape'&&query){e.preventDefault();setQuery('')}}}/>
       {searching&&<button type="button" className="settings-search-clear" aria-label="Clear search" onClick={()=>{setQuery('');searchRef.current?.focus()}}><X size={14} aria-hidden="true"/></button>}
     </div>
   </div>
   <div className="settings-body">
     <nav className="settings-nav" aria-label="Settings sections">
       <div role="tablist" aria-orientation="vertical" aria-label="Settings sections" className={searching?'is-searching':''}>
         {SETTINGS_SECTIONS.map((s,i)=>{const current=!searching&&s.id===section;const Icon=s.icon;return <button key={s.id} ref={el=>{tabRefs.current[s.id]=el}} type="button" role="tab" id={`${baseId}-tab-${s.id}`} aria-controls={`${baseId}-panel-${s.id}`} aria-selected={current} tabIndex={s.id===section?0:-1} className={'settings-tab'+(current?' is-current':'')} onClick={()=>choose(s.id)} onKeyDown={e=>onTabKey(e,i)}><Icon size={16} aria-hidden="true"/><span>{s.label}</span></button>})}
       </div>
     </nav>
     <SearchMatches.Provider value={matches}>
       <div className="settings-panels">
         {searching&&<p className="settings-search-summary" role="status">{resultCount?`${resultCount} ${resultCount===1?'group matches':'groups match'} “${query.trim()}”`:''}</p>}
         {searching&&matches&&resultCount===0&&<div className="settings-empty"><Search size={18} aria-hidden="true"/><strong>No settings match “{query.trim()}”</strong><span>Try a shorter word, such as “key”, “voice” or “Studio”.</span><button type="button" className="secondary-button" onClick={()=>{setQuery('');searchRef.current?.focus()}}>Clear search</button></div>}
         {SETTINGS_SECTIONS.map(s=>{
           const visible=searching?sectionHasMatch(s.id):s.id===section
           return <section key={s.id} data-settings-section={s.id} id={`${baseId}-panel-${s.id}`} role={searching?undefined:'tabpanel'} aria-labelledby={searching?`${baseId}-heading-${s.id}`:`${baseId}-tab-${s.id}`} hidden={!visible} className="settings-panel">
             <header className="settings-panel-head"><h2 id={`${baseId}-heading-${s.id}`}>{s.label}</h2><p>{s.description}</p></header>
             {panels[s.id]}
           </section>
         })}
       </div>
     </SearchMatches.Provider>
   </div>
   <div className={'settings-savebar'+(dirty?' is-dirty':'')}>
     <span className="settings-savebar-state" aria-live="polite">{dirty?<><Info size={14} aria-hidden="true"/> Unsaved changes</>:inactive?'Preview: changes are not saved':'All changes saved'}</span>
     <div className="settings-savebar-actions">
       {dirty&&<button type="button" className="secondary-button" onClick={()=>setDraft(data.settings)}><Undo2 size={14} aria-hidden="true"/> Discard</button>}
       <button type="button" className="primary-button save-button" aria-label="Save settings" onClick={props.saveSettings}><Check size={16} aria-hidden="true"/> <span>Save<span className="settings-save-word"> settings</span></span></button>
     </div>
   </div>
 </div>
}
