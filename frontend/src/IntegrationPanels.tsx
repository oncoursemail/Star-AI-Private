import {useEffect,useRef,useState} from 'react'
import type {ReactNode} from 'react'
import {Check,ChevronDown,KeyRound,LoaderCircle,Minus,RefreshCcw,Server,Settings2,ShieldCheck,Workflow,X} from 'lucide-react'
import {onBackendEvent} from './bridge'
import type {AppSettings,McpStatus,ServerReport,ServerRole,ServerStatus} from './types'
import './integrated-tools.css'

type Invoke=(action:string,params?:Record<string,unknown>)=>Promise<unknown|null>
const providers=['local','star_server','groq','openrouter','gemini','cerebras'] as const
type Provider=typeof providers[number]
type CloudProvider=Exclude<Provider,'local'|'star_server'>
const providerNames:Record<Provider,string>={local:'Local STAR Brain',star_server:'STAR Server (LAN)',groq:'GroqCloud',openrouter:'OpenRouter',gemini:'Gemini',cerebras:'Cerebras'}
const cloudProviders=providers.filter((x):x is CloudProvider=>x!=='local'&&x!=='star_server')

/** STAR Server on the owner's network is the brain: no model download is needed on this PC. */
export const usesStarServer=(settings?:{provider?:string}|null)=>settings?.provider==='star_server'
/** Teams and other private work may run on the on-device brain or on STAR Server, never on a cloud vendor. */
export const runsOnOwnHardware=(settings?:{provider?:string}|null)=>settings?.provider==='local'||usesStarServer(settings)
/** One status light for whichever brain is selected. A server that was never checked is not called offline. */
export function brainStatus(state:{settings?:{provider?:string}|null;brain_running?:boolean;server?:ServerStatus}):{online:boolean;label:string}{
 if(!usesStarServer(state.settings))return {online:!!state.brain_running,label:state.brain_running?'STAR Brain ready':'STAR Brain offline'}
 const checked=state.server?.ok
 return {online:checked===true,label:checked===true?'STAR Server ready':checked===false?'STAR Server needs attention':'STAR Server selected'}
}
export const formatStepTime=(ms:number)=>ms<1000?`${Math.max(0,Math.round(ms))} ms`:`${(ms/1000).toFixed(1)} s`
const stepNames:Record<string,string>={health:'Server reachable',models:'Key and model list',limits:'Context and slots',chat:'Real test reply'}
/** One readable line per connector. A connector that is off has no protocol yet ("Protocol: · disabled" before). */
export const connectorState=(info:{protocol:string;state:string})=>
 info.state==='disabled'||!info.protocol?'Off':`Protocol ${info.protocol} · ${info.state==='configured_not_tested'?'enabled, not tested yet':info.state.replace(/_/g,' ')}`
const failedReport=(message:string):ServerReport=>({ok:false,code:'error',message,steps:[],models:[],model:'',context_tokens:null,slots:null,first_token_ms:null,sample:''})

/** Runs the host's timed server check. With `settings`, they are saved first so the check uses what is on screen. */
function useServerTest(invoke:Invoke,disabled:boolean){
 const [testing,setTesting]=useState(false)
 const [report,setReport]=useState<ServerReport|null>(null)
 const pendingId=useRef('')
 useEffect(()=>onBackendEvent(event=>{
   if(!pendingId.current||event.requestId!==pendingId.current||event.kind==='progress')return
   pendingId.current='';setTesting(false)
   if(event.kind==='error'){setReport(failedReport(String(event.data||'The server test could not run.').slice(0,300)));return}
   const value=event.data as ServerReport|null
   setReport(value&&Array.isArray(value.steps)?value:failedReport('The server test returned no result.'))
 }),[])
 const run=async(settings?:AppSettings)=>{
   if(disabled||testing)return
   setTesting(true);setReport(null)
   if(settings){const saved=await invoke('saveSettings',{settings});if(!saved){setTesting(false);return}}
   const reply=await invoke('testServer') as {pending?:boolean;requestId?:string}|null
   if(reply?.pending&&reply.requestId)pendingId.current=reply.requestId
   else setTesting(false)
 }
 return {testing,report,run}
}

function ServerReportView({report,current,onPickModel,onUseLimits}:{report:ServerReport;current?:string;onPickModel?:(id:string)=>void;onUseLimits?:(context:number,slots:number)=>void}){
 return <div role="status" aria-live="polite">
   <p className={report.ok?'integrated-confirm':'integrated-error'}><strong>{report.message}</strong></p>
   {report.steps.length>0&&<div className="integrated-notes"><strong>Server check</strong>
     {report.steps.map(step=><div className="integrated-note" key={step.name}>
       <span>{step.status==='ok'?<Check size={13} aria-label="Passed"/>:step.status==='failed'?<X size={13} aria-label="Failed"/>:<Minus size={13} aria-label="Skipped"/>} {stepNames[step.name]||step.name}: {step.detail}</span>
       <small>{formatStepTime(step.ms)}</small>
     </div>)}
   </div>}
   {report.ok&&report.sample&&<p className="integrated-help">Reply from {report.model}: {report.sample}{report.first_token_ms!==null?` (first words after ${formatStepTime(report.first_token_ms)})`:''}</p>}
   {report.models.length>0&&onPickModel&&<div className="integrated-actions" role="group" aria-label="Models on this server"><span>Models on this server:</span>
     {report.models.map(id=><button type="button" key={id} className={'integrated-chip '+(id===current?'active':'')} aria-pressed={id===current} onClick={()=>onPickModel(id)}>{id}</button>)}
   </div>}
   {report.context_tokens!==null&&<div className="integrated-actions"><span>Server reports {report.context_tokens} context tokens per request and {report.slots??1} parallel slot(s).</span>
     {onUseLimits&&<button type="button" className="secondary-button" onClick={()=>onUseLimits(report.context_tokens as number,report.slots??1)}>Use and save these limits</button>}
   </div>}
 </div>
}

/** Address, model and key for the owner's own server. The key goes straight to the OS keyring:
 *  it is read from the input element once and is never kept in React state or in settings. */
function ServerSetup({draft,onChange,credentials,invoke,disabled}:{draft:AppSettings;onChange:(settings:AppSettings)=>void;credentials:Record<string,boolean>;invoke:Invoke;disabled:boolean}){
 const keyInput=useRef<HTMLInputElement>(null)
 const [keyTyped,setKeyTyped]=useState(false)
 const [keyBusy,setKeyBusy]=useState(false)
 const [keyStored,setKeyStored]=useState<boolean|null>(null)
 const [note,setNote]=useState('')
 const [fileFound,setFileFound]=useState(false)
 const [fileError,setFileError]=useState('')
 const testedSettings=useRef<AppSettings|null>(null)
 useEffect(()=>{let live=true;void invoke('serverKeyFileStatus').then(result=>{
   if(live&&result&&typeof result==='object'&&'found' in result)setFileFound(Boolean(result.found))
 });return()=>{live=false}},[invoke])
 const {testing,report,run}=useServerTest(invoke,disabled)
 useEffect(()=>{
   if(!report)return
   const tested=testedSettings.current
   testedSettings.current=null
   if(!report.ok||draft.provider==='star_server'||!tested)return
   if(draft.server_endpoint!==tested.server_endpoint||draft.model!==tested.model){
     setNote('Server settings changed during the test. Test again before connecting.')
     return
   }
   const next:AppSettings={...draft,provider:'star_server'}
   void invoke('saveSettings',{settings:next}).then(saved=>{
     if(saved){onChange(next);setNote('Connected to STAR Server.')}
     else setNote('Server responded, but settings could not be saved.')
   })
 },[report,draft,onChange,invoke])
 const hasKey=keyStored??Boolean(credentials?.star_server)
 const change=(patch:Partial<AppSettings>)=>onChange({...draft,...patch})
 const saveKey=async()=>{
   const field=keyInput.current
   if(disabled||keyBusy||!field||!field.value.trim())return
   setKeyBusy(true);setNote('')
   try{
     const saved=await invoke('saveProviderKey',{provider:'star_server',key:field.value.trim()})
     if(saved){setKeyStored(true);setNote('Server key saved in Windows Credential Manager.')}
   }finally{field.value='';setKeyTyped(false);setKeyBusy(false)}
 }
 const importKey=async()=>{
   if(disabled||keyBusy)return
   setKeyBusy(true);setFileError('')
   try{
     const saved=await invoke('importServerKeyFile')
     if(saved){setKeyStored(true);setNote('Server key imported into the OS vault.')}
     else setFileError('Key file could not be read or saved securely.')
   }finally{setKeyBusy(false)}
 }
 const forgetKey=async()=>{
   if(disabled||keyBusy)return
   setKeyBusy(true);setNote('')
   try{const cleared=await invoke('clearProviderKey',{provider:'star_server'});if(cleared){setKeyStored(false);setNote('Stored server key removed.')}}
   finally{setKeyBusy(false)}
 }
 const useLimits=async(context:number,slots:number)=>{
   const next={...draft,server_context_tokens:context,server_parallel:Math.max(1,Math.min(4,slots))}
   onChange(next)
   const saved=await invoke('saveSettings',{settings:next})
   if(saved)setNote(`Saved: ${context} context tokens per request, ${next.server_parallel} parallel request(s).`)
 }
 return <div role="group" aria-label="STAR Server settings">
   <div className="integrated-heading"><Server size={18}/><div><strong>STAR Server on your network</strong><span>Your own server runs the AI. No model download is needed on this PC.</span></div></div>
   <div className="integrated-key-controls">
     <label className="integrated-field">Server address
       <input type="text" inputMode="url" spellCheck={false} autoComplete="off" disabled={disabled} value={draft.server_endpoint??''} placeholder="http://192.168.1.20:8080/v1" onChange={e=>change({server_endpoint:e.target.value.trim()})}/>
     </label>
     <label className="integrated-field">Server model ID
       <input list="star-server-model-ids" spellCheck={false} autoComplete="off" disabled={disabled} value={draft.model??''} placeholder="Test server to list its models" onChange={e=>change({model:e.target.value.trim()})}/>
     </label>
   </div>
   <label className="integrated-field"><input type="checkbox" disabled={disabled} checked={draft.allow_cgnat??false} onChange={e=>change({allow_cgnat:e.target.checked})}/> Allow Tailscale and carrier-grade NAT addresses</label>
   <p className="integrated-help">Turn this on only for a Tailscale (or similar VPN) address. On an ordinary carrier network this range is shared with other customers and the connection is not encrypted. Cloud metadata addresses stay blocked.</p>
   <datalist id="star-server-model-ids">{(report?.models??[]).map(id=><option key={id} value={id}/>)}</datalist>
   <div className="integrated-key-controls">
     <label className="integrated-field">Server key (stored in Windows Credential Manager)
       <input ref={keyInput} type="password" autoComplete="off" spellCheck={false} disabled={disabled||keyBusy} placeholder={hasKey?'A key is saved. Paste a new one to replace it.':'Paste the server key'} onInput={e=>setKeyTyped(Boolean(e.currentTarget.value.trim()))}/>
     </label>
     <div className="integrated-actions">
       <button type="button" className="secondary-button" disabled={disabled||keyBusy||!keyTyped} onClick={()=>void saveKey()}>{keyBusy?<LoaderCircle size={14} className="spin"/>:<Check size={14}/>} Save key</button>
       <button type="button" className="secondary-button" disabled={disabled||keyBusy||!hasKey} onClick={()=>void forgetKey()}><X size={14}/> Forget key</button>
       {hasKey&&<span className="integrated-connected"><ShieldCheck size={14}/> Key present in OS vault</span>}
     </div>
   </div>
   {fileFound&&<div className="integrated-actions"><span>A server key file was found on this PC</span><button type="button" className="secondary-button" disabled={disabled||keyBusy} onClick={()=>void importKey()}>Use it</button></div>}
   {fileError&&<p role="alert" className="integrated-error">{fileError}</p>}
   <p className="integrated-help">Use the private IP address of your server, ending in /v1. Prompts go only to that address, never to a cloud provider. Plain http is not encrypted, so use it only on a network you trust.</p>
   <details><summary className="integrated-help">Server limits (optional)</summary>
     <div className="integrated-key-controls">
       <label className="integrated-field">Wait per request (seconds)
         <input type="number" min={30} max={1800} step={30} disabled={disabled} value={draft.server_timeout??600} onChange={e=>change({server_timeout:Number(e.target.value)})}/>
       </label>
       <label className="integrated-field">Parallel requests (server slots)
         <input type="number" min={1} max={4} disabled={disabled} value={draft.server_parallel??1} onChange={e=>change({server_parallel:Number(e.target.value)})}/>
       </label>
       <label className="integrated-field">Context tokens per request (0 = ask the server)
         <input type="number" min={0} max={1048576} step={1024} disabled={disabled} value={draft.server_context_tokens??0} onChange={e=>change({server_context_tokens:Number(e.target.value)})}/>
       </label>
     </div>
   </details>
   <div className="integrated-actions">
     <button type="button" className="secondary-button" disabled={disabled||testing||!draft.server_endpoint} onClick={()=>{testedSettings.current={...draft};void run(draft)}}>{testing?<LoaderCircle size={14} className="spin"/>:<RefreshCcw size={14}/>} {testing?'Testing server…':'Test server'}</button>
     <span>Saves these settings, then checks the server, the key and a real reply.</span>
   </div>
   {note&&<p role="status" className="integrated-confirm">{note}</p>}
   {report&&<ServerReportView report={report} current={draft.model} onPickModel={id=>change({model:id})}
     onUseLimits={(context,slots)=>void useLimits(context,slots)}/>}
 </div>
}

/** Brain page card shown when STAR Server is selected, in place of any local download prompt. */
export function ServerBrainPanel({settings,status,invoke,disabled=false,openSettings}:{settings:AppSettings;status?:ServerStatus;invoke:Invoke;disabled?:boolean;openSettings:()=>void}){
 const {testing,report,run}=useServerTest(invoke,disabled)
 const ready=report?report.ok:status?.ok??null
 return <section className="integrated-panel" aria-label="STAR Server">
   <div className="integrated-heading"><Server size={19}/><div>
     <strong>STAR Server is your AI brain</strong>
     <span>{settings.model?`${settings.model} runs on your own server.`:'Choose a server model in Settings to start chatting.'} Nothing needs to be downloaded to this PC.</span>
   </div></div>
   <p className="integrated-help">Address: {settings.server_endpoint||'not set yet'} · Key: {status?.key_present?'saved':'not saved yet'} · Status: {ready===true?'ready':ready===false?'needs attention':'not checked yet'}</p>
   <ServerRoles roles={report?.roles?.length?report.roles:status?.roles}/>
   <div className="integrated-actions">
     <button type="button" className="secondary-button" disabled={disabled||testing||!settings.server_endpoint} onClick={()=>void run()}>{testing?<LoaderCircle size={14} className="spin"/>:<RefreshCcw size={14}/>} {testing?'Testing server…':'Test server'}</button>
     <button type="button" className="secondary-button" onClick={openSettings}><Settings2 size={14}/> Server settings</button>
   </div>
   {report&&<ServerReportView report={report}/>}
 </section>
}

/** Which server model does which job. Only shown once it says something: a role the server or the owner chose. */
export function ServerRoles({roles}:{roles?:ServerRole[]}){
 if(!roles?.some(role=>role.source!=='default'))return null
 return <p className="integrated-help" data-testid="server-roles">Models by job: {roles.map(role=>`${role.label}: ${role.model||'none'}${role.source==='manual'?' (set by you)':''}`).join(' · ')}. Start a message with /deep to ask the slow best-quality model, when the server offers one.</p>
}

/** With STAR Server selected the on-device brain is only a backup: keep it available, folded away, never a prompt. */
export function LocalBrainFallback({optional,children}:{optional:boolean;children:ReactNode}){
 if(!optional)return <>{children}</>
 return <details className="settings-expander brain-details"><summary><span><strong>Optional: on-device backup brain</strong><small>Not needed while STAR Server is selected. Set it up only if you want a local model as a fallback.</small></span><ChevronDown size={17}/></summary>
   <div className="settings-expander-body">{children}</div>
 </details>
}

export function ProviderPanel({draft,onChange,credentials,invoke,refresh,disabled=false}:{draft:AppSettings;onChange:(settings:AppSettings)=>void;credentials:Record<string,boolean>;invoke:Invoke;refresh:()=>void;disabled?:boolean}){
 const [selected,setSelected]=useState<CloudProvider>('groq')
 const [apiKey,setApiKey]=useState('')
 const [pending,setPending]=useState(false)
 const [message,setMessage]=useState('')
 const [connecting,setConnecting]=useState(false)
 const save=async()=>{
   if(disabled||pending||!apiKey.trim())return
   setPending(true);setMessage('')
   try{
     const r=await invoke('saveProviderKey',{provider:selected,key:apiKey})
     if(r){setApiKey('');setMessage('Credential saved in your operating system keyring.');refresh()}
   }finally{setApiKey('');setPending(false)}
 }
 const clear=async()=>{
   if(disabled||pending)return
   setPending(true)
   try{const r=await invoke('clearProviderKey',{provider:selected});if(r){setMessage('Stored credential cleared.');refresh()}}
   finally{setPending(false)}
 }
 return <section className="integrated-panel" aria-label="AI provider settings">
   <div className="integrated-heading"><KeyRound size={18}/><div><strong>Model & provider</strong><span>Local by default. STAR Server keeps everything on your own network. Cloud providers are optional and require your own key.</span></div></div>
   {!usesStarServer(draft)&&!connecting&&<button type="button" className="secondary-button" disabled={disabled} onClick={()=>setConnecting(true)}>Connect to STAR Server</button>}
   <label className="integrated-field">Inference provider
     <select value={connecting?'star_server':draft.provider||'local'} disabled={disabled} onChange={e=>{if(e.target.value==='star_server'){setConnecting(true)}else{setConnecting(false);onChange({...draft,provider:e.target.value as Provider})}}}>
       {providers.map(x=><option value={x} key={x}>{providerNames[x]}</option>)}
     </select>
   </label>
   <p className="integrated-help">After changing provider, save Settings. STAR sends your prompt only to the provider you explicitly selected; ordinary local chat never silently falls back to a cloud model.</p>
   <label className="integrated-switch"><input type="checkbox" disabled={disabled} checked={draft.luau_run_before_answer===true}
     onChange={e=>onChange({...draft,luau_run_before_answer:e.target.checked})}/><span>Run my Luau before answering</span></label>
   <p className="integrated-help">Off by default. Save Settings to run assertions in your STAR Knowledge sandbox before displaying code. Up to two repair rounds; this cannot validate Roblox services or Studio. The server must separately enable execution.</p>
   {(connecting||usesStarServer(draft))?<ServerSetup draft={draft} onChange={onChange} credentials={credentials} invoke={invoke} disabled={disabled}/>:<>
   <div className="integrated-key-controls">
     <label className="integrated-field">Cloud key provider
       <select value={selected} disabled={disabled||pending} onChange={e=>setSelected(e.target.value as CloudProvider)}>
         {cloudProviders.map(x=><option key={x} value={x}>{providerNames[x]}{credentials?.[x]?' — connected':''}</option>)}
       </select>
     </label>
     <label className="integrated-field">API key (never saved in STAR settings)
       <input type="password" autoComplete="off" disabled={disabled||pending} value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder="Paste a provider key"/>
     </label>
   </div>
   <div className="integrated-actions">
     <button type="button" className="secondary-button" disabled={disabled||pending||!apiKey.trim()} onClick={()=>void save()}>{pending?<LoaderCircle size={14} className="spin"/>:<Check size={14}/>} Save key</button>
     <button type="button" className="secondary-button" disabled={disabled||pending||!credentials?.[selected]} onClick={()=>void clear()}><X size={14}/> Forget key</button>
     {credentials?.[selected]&&<span className="integrated-connected"><ShieldCheck size={14}/> Key present in OS vault</span>}
   </div>
   {message&&<p role="status" className="integrated-confirm">{message}</p>}
   </>}
 </section>
}

const targets=[{name:'graphify_docs',flag:'mcp_graphify_docs',label:'Graphify documentation',note:'Fixed remote read-only Graphify documentation tools'},
 {name:'graphify_local',flag:'mcp_graphify_local',label:'Local Graphify MCP',note:'Explicit localhost Graphify MCP; read-only tools'},
 {name:'obsidian_live',flag:'mcp_obsidian_live',label:'Obsidian live MCP',note:'Existing local vault integration remains independently scoped'},
 {name:'github_repositories',flag:'mcp_github_repositories',label:'GitHub repositories',note:'Read your authorized repositories and their source. Stable repository IDs follow name changes.'}] as const

export function McpPanel({draft,onChange,status,invoke,disabled=false}:{draft:AppSettings;onChange:(settings:AppSettings)=>void;status?:McpStatus;invoke:Invoke;disabled?:boolean}){
 const [pending,setPending]=useState('')
 const [results,setResults]=useState<Record<string,string>>({})
 const pendingId=useRef('')
 useEffect(()=>onBackendEvent(event=>{
   if(!pendingId.current||event.requestId!==pendingId.current||event.kind==='progress')return
   setPending('');pendingId.current=''
   if(event.kind==='error'){setResults(prev=>({...prev,error:String(event.data||'Connection test failed').slice(0,240)}));return}
   const value=event.data as {name?:string;server?:string;read_tool_count?:number;protocol?:string;repository_count?:number;complete?:boolean}|null
   const name=value?.name||value?.server
   if(value&&name){
     if(name==='github_repositories'&&!(value.complete===true&&Number.isSafeInteger(value.repository_count)&&(value.repository_count??-1)>=0)){
       setResults(prev=>({...prev,github_repositories:'',error:'Repository access has not been fully checked. Check repositories again.'}));return
     }
     const detail=name==='github_repositories'
       ? String(value.repository_count)+' repositories visible to this credential / read-only'
       : String(value.read_tool_count??0)+' read tools / '+String(value.protocol||'unknown')
     setResults(prev=>({...prev,[name]:detail}))
   }
 }),[])
 const probe=async(name:string)=>{
   if(pending||disabled)return
   setPending(name)
   setResults(prev=>({...prev,[name]:'',error:''}))
   const reply=await invoke('testMcpConnection',{server:name}) as {pending?:boolean;requestId?:string}|null
   if(!reply){setPending('');return}
   if(reply.pending&&reply.requestId)pendingId.current=reply.requestId
   else setPending('')
 }
 return <section className="integrated-panel" aria-label="MCP integrations">
   <div className="integrated-heading"><Workflow size={18}/><div><strong>Connected research tools</strong><span>Read-only, explicitly enabled MCP connections. Never arbitrary public servers.</span></div></div>
   <div className="integrated-connectors">
     {targets.map(target=>{
       const active=Boolean(draft[target.flag]);const info=status?.servers?.find(s=>s.name===target.name)
       return <div className="integrated-connector" key={target.name}>
         <div><strong>{target.label}</strong><small>{target.note}</small>
           {target.name==='github_repositories'&&<label className="integrated-field">GitHub credential source
             <select disabled={disabled||pending===target.name} value={draft.github_repository_access_source??'gh'}
               onChange={e=>{setResults(prev=>({...prev,github_repositories:'',error:''}));onChange({...draft,github_repository_access_source:e.target.value as 'gh'|'env'})}}>
               <option value="gh">GitHub CLI account (gh)</option>
               <option value="env">Configured environment token</option>
             </select>
           </label>}
           {results[target.name]&&<small className="integrated-connected">{results[target.name]}</small>}
           {info&&<small>{connectorState(info)}</small>}
         </div>
         <div className="integrated-connector-actions">
           <label className="integrated-switch"><input type="checkbox" aria-label={target.name==='github_repositories'?'Enable GitHub repositories':undefined} disabled={disabled||(target.name==='github_repositories'&&pending===target.name)} checked={active} onChange={e=>{if(target.name==='github_repositories')setResults(prev=>({...prev,github_repositories:'',error:''}));onChange({...draft,[target.flag]:e.target.checked})}}/><span>Enable</span></label>
           <button type="button" className="secondary-button" disabled={disabled||!!pending||!active}
             onClick={()=>void probe(target.name)}>{pending===target.name?<LoaderCircle className="spin" size={14}/>:<RefreshCcw size={14}/>} {target.name==='github_repositories'?'Check repositories':'Test'}</button>
         </div>
       </div>
     })}
   </div>
   <label className="integrated-field">Local Graphify port
     <input type="number" min={1024} max={65535} disabled={disabled} value={draft.mcp_graphify_port} onChange={e=>onChange({...draft,mcp_graphify_port:Number(e.target.value)})}/>
   </label>
   {results.error&&<p role="alert" className="integrated-error">{results.error}</p>}
   <p className="integrated-help">Save connector settings before testing connections. GitHub checks list repositories visible to the saved credential source; each file read is verified separately. Other tests confirm read-only tool discovery.</p>
 </section>
}
