import {Fragment,useCallback,useEffect,useRef,useState} from 'react'
import {AnimatePresence,motion} from 'motion/react'
import {Activity,ArrowRight,BookOpen,Box,Boxes,Braces,BrainCircuit,Check,ChevronDown,ChevronRight,CircleAlert,Copy,Download,Ellipsis,Folder,FolderOpen,Gauge,GraduationCap,ImagePlus,Info,LayoutDashboard,LoaderCircle,MessageCircleMore,PanelLeftClose,PanelLeftOpen,Pencil,Plus,Search,Settings2,Shield,SquarePen,Trash2,Undo2,Workflow,X,Zap} from 'lucide-react'
import {AnalyticsView} from './Charts'
import {BrainOverview} from './BrainOverview'
import {Message,Panel,StarMark,Tag} from './components'
import {WEBSITE_RELEASES} from './constants'
import {onBackendEvent,request} from './bridge'
import type {Analytics,AppSettings,BackendEvent,BootData,ChatMessage,ChatState,ChatThread,CustomToolRecipe,CustomToolCatalog,LessonCounts,MediaStatus} from './types'
import './tokens.css'
import './stellar-ui.css'
import './chat.css'
import './learning.css'
import {McpPanel} from './IntegrationPanels'
import {BlenderPanel} from './BlenderPanel'
import {StudioConnectionPanel} from './StudioConnectionPanel'
import {LearningPanel} from './LearningPanel'
import {ResearchWatchPanel} from './ResearchWatchPanel'
import {ReferencesPanel} from './MediaPanel'
import {chatImageRequest} from './imageIntent'
import {ServerBrainPanel,LocalBrainFallback,brainStatus,runsOnOwnHardware,usesStarServer} from './IntegrationPanels'
import type {ModelTeamReport} from './ModelFleetPanel'
import {ReviewToolsPanel} from './ReviewToolsPanel'
import {SettingsPage,type UpdateInfo} from './SettingsPage'
import {Composer,type Availability,type ChatMode} from './Composer'
import {imageReadiness,webSearchAvailability} from './availability'
import {overLimitMessage,promptKind} from './promptLimits'
import {StarPet,type PetState} from './StarPet'
import {ClipPanel} from './ClipPanel'
import {GameLabPanel} from './GameLabPanel'
import {StarFace,type StarMood} from './StarFace'
import {StartCanvas} from './StartCanvas'
import {ChatRow} from './ChatRow'
import {ScreenConsent} from './ScreenConsent'
import {useDismiss} from './Composer'
import './redesign.css'
import './resilience.css'
import {EmptyState} from './states'
import './polish.css'
import './start-canvas.css'
import {ActivityTimeline,RunStatus} from './ActivityTimeline'
import {applyProgress,isRich,settleRun,startRun,type ActivityRun,type ProgressPayload} from './activity'
import {classifyFailure,connectionTarget,describeConnection,type LastOutcome} from './connection'
import {instant,pageFade} from './motion'
import {useDraftWarm} from './draftWarm'
import {MotionPolicy,useEffectiveReducedMotion} from './MotionPolicy'
import {MotionSurface} from './MotionSurface'
import type {Fixture,FixtureScript} from './previewFixtures'
import {StudioFrame,StudioInputHint,StudioProjectSwitch,StudioWelcome,useCompactStudio} from './StudioChrome'
import {AppearanceControls,AppearancePanel} from './AppearancePanel'
import {useAppearance} from './useAppearance'
import {CompanionControls,CompanionShelf} from './CompanionShelf'
import {useCompanionPreferences} from './companion-catalog'

type Tab='chat'|'projects'|'brain'|'brain-overview'|'analytics'|'tools'|'library'|'settings'
const sections:[Tab,string,typeof MessageCircleMore][]=[['chat','Chat',MessageCircleMore],['projects','Projects',Boxes],['library','Library',BookOpen],['tools','Tools',Workflow],['analytics','Analytics',Activity],['brain-overview','Brain',BrainCircuit],['brain','Model & connection',Gauge],['settings','Settings',Settings2]]
const truncate=(s:string,n=90)=>s.length>n?s.slice(0,n-1)+'…':s
const fileName=(path:string)=>path.split(/[\\/]/).pop()||path
const defaultSettings:AppSettings={endpoint:'http://127.0.0.1:8080/v1',provider:'local',model:'',fast_model:'',reasoning_model:'',roblox_model:'',vision_model:'',router_models_dir:'',router_context:4096,gpu_layers:25,instant_route_enabled:false,project:'STAR',workspace:'',studio_id:'',studio_target:'local_pc',studio_edit:false,workspace_edit:false,max_calls:12,context_chars:26000,reduced_motion:false,obsidian_vault:'',obsidian_enabled:false,skills_enabled:true,graphify_enabled:true,comfy_workflow:'',comfy_prompt_node:'6',comfy_port:8188,mcp_graphify_docs:false,mcp_graphify_local:false,mcp_graphify_port:8931,mcp_obsidian_live:false,mcp_github_repositories:false,github_repository_access_source:'gh',blender_enabled:false,blender_edit:false,blender_executable:'',roblox_research_enabled:true,asset_forge_enabled:false,tool_workshop_enabled:true,specialists_enabled:true,specialist_parallelism:1}
const makeMsg=(role:ChatMessage['role'],text:string,attachments?:string[]):ChatMessage=>({id:crypto.randomUUID(),role,text,created:new Date().toISOString(),attachments})
const emptyAnalytics:Analytics={started:0,succeeded:0,failed:0,tools:0,rejected:0,median_ms:null,messages:0,project:'STAR',period_days:14,trend:[],recent:[]}
const CHAT_ACTIONS=['sendMessage','generateImage','runTeam']
/** The sidebar lists this many recent chats; search covers all of them. */
const CHAT_WINDOW=60

/** Starter prompts for things STAR can really do. They fill the composer so you can finish the sentence. */
const starters=[
 {label:'Design a Roblox inventory UI',icon:LayoutDashboard,prompt:'Design a Roblox inventory UI for my game. Cover the layout, the instance hierarchy, component states and how it adapts to phones.'},
 {label:'Review my Luau script',icon:Braces,prompt:'Review this Luau script for bugs, exploitable remotes and performance problems:\n\n'},
 {label:'Research a Roblox game',icon:Search,prompt:'Research this Roblox game and tell me what is publicly known about it, with sources: '},
 {label:'Plan a Blender model',icon:Box,prompt:'Plan a Blender model of '},
]

function initialPreviewTab(preview:boolean):Tab {
 const value=new URLSearchParams(window.location.search).get('tab')
 if(preview&&value&&['chat','projects','brain','brain-overview','analytics','tools','library','settings'].includes(value))return value as Tab
 return 'chat'
}
/** Scripted fixtures exist only for the browser preview; the Qt desktop can never select one. */
function requestedFixture(preview:boolean):string {
 if(!preview||window.qt?.webChannelTransport)return ''
 return (new URLSearchParams(window.location.search).get('fixture')||'').replace(/[^a-z]/g,'').slice(0,20)
}
/** View preferences only (never chats, settings or secrets). Storage can be unavailable on file:// pages. */
function readPreference(key:string):string {try{return window.localStorage.getItem(key)||''}catch{return ''}}
function writePreference(key:string,value:string){try{window.localStorage.setItem(key,value)}catch{/* preference simply does not persist */}}
/** Recent chats grouped the way people look for them: by when they last touched them. */
function groupChats(chats:ChatThread[]):Array<{label:string;chats:ChatThread[]}> {
 const start=new Date();start.setHours(0,0,0,0)
 const today=start.getTime(),day=86400000
 const groups:Array<{label:string;chats:ChatThread[]}>=[{label:'Today',chats:[]},{label:'Yesterday',chats:[]},{label:'Previous 7 days',chats:[]},{label:'Older',chats:[]}]
 for(const chat of chats){
   const time=Date.parse(chat.updated||chat.created||'')
   const index=Number.isNaN(time)?3:time>=today?0:time>=today-day?1:time>=today-7*day?2:3
   groups[index].chats.push(chat)
 }
 return groups.filter(group=>group.chats.length)
}

export function Desktop({initial=null,preview=false}:{initial?:BootData|null;preview?:boolean}) {
 // Studio layout (workspace switch, Appearance menu, companion shelf): off until turned on in Settings > Interface.
 const [studioLayout,setStudioLayout]=useState(()=>readPreference('star.studio.layout')==='on')
 const {preferences:appearance,updateAppearance,resetAppearance,persisted:appearancePersisted}=useAppearance(studioLayout)
 const [companionPreferences,setCompanionPreferences]=useCompanionPreferences()
 const compactStudio=useCompactStudio()
 const [tab,setTab]=useState<Tab>(()=>initialPreviewTab(preview))
 const [data,setData]=useState<BootData>(initial??{version:'1.0.0',project:'STAR',projects:[],messages:[],active_chat:'',chats:[],settings:defaultSettings,brain_installed:false,brain_running:false,analytics:emptyAnalytics,release_url:WEBSITE_RELEASES,credentials:{}})
 const [messages,setMessages]=useState<ChatMessage[]>(initial?.messages??[])
 const [prompt,setPrompt]=useState('')
 const [showStar,setShowStar]=useState(()=>readPreference('star.pet.visible')==='on')
 const [newHome,setNewHome]=useState(()=>readPreference('star.home.workbench')==='on')
 const [clipsOn,setClipsOn]=useState(()=>readPreference('star.clips.panels')==='on')
 const [petTerminal,setPetTerminal]=useState<{kind:PetState;at:number}|null>(null)
 const [files,setFiles]=useState<string[]>([])
 const [busy,setBusy]=useState(false)
 const [stopping,setStopping]=useState(false)
 const [chatMode,setChatMode]=useState<ChatMode>('auto')
 const [research,setResearch]=useState(false)
 const [githubSource,setGithubSource]=useState(false)
 const [teamMode,setTeamMode]=useState(false)
 const [notice,setNotice]=useState('')
 const [run,setRun]=useState<ActivityRun|null>(null)
 const [lastRun,setLastRun]=useState<{chat:string;run:ActivityRun}|null>(null)
 const [lastOutcome,setLastOutcome]=useState<LastOutcome>(null)
 const [streamingText,setStreamingText]=useState('')
 const [chatSearch,setChatSearch]=useState('')
 const [showChatSearch,setShowChatSearch]=useState(false)
 const [retryText,setRetryText]=useState('')
 const [modelCheck,setModelCheck]=useState<{ok:boolean;model:string;sample:string}|null>(null)
 const [modelChecking,setModelChecking]=useState(false)
 const [routerBusy,setRouterBusy]=useState(false)
 const [teamChecking,setTeamChecking]=useState(false)
 const [teamResult,setTeamResult]=useState<ModelTeamReport|null>(null)
 const [customTools,setCustomTools]=useState<CustomToolRecipe[]>([])
 const [customBusy,setCustomBusy]=useState('')
 const [customQuery,setCustomQuery]=useState('')
 const [customPreview,setCustomPreview]=useState('')
 const [brainProgress,setBrainProgress]=useState<{phase:string;downloaded:number;total:number}|null>(null)
 const [update,setUpdate]=useState<UpdateInfo|null>(null)
 const [updateBusy,setUpdateBusy]=useState(false)
 const [updateProgress,setUpdateProgress]=useState<{phase:string;downloaded:number;total:number}|null>(null)
 const [draft,setDraft]=useState<AppSettings>(initial?.settings??defaultSettings)
 const [newProject,setNewProject]=useState('')
 const [leftOpen,setLeftOpen]=useState(false)
 const [sidebarCollapsed,setSidebarCollapsed]=useState(()=>readPreference('star.sidebar')==='collapsed')
 const [showJump,setShowJump]=useState(false)
 const [imageMode,setImageMode]=useState(false)
 // The image engine's real state, read when Create image is switched on: the composer offers setup only when it is not ready.
 const [imageStatus,setImageStatus]=useState<MediaStatus|null>(null)
 const imageStatusRequest=useRef('')
 const [imageSize,setImageSize]=useState('square')
 const [historySearchOpen,setHistorySearchOpen]=useState(false)
 const [historyQuery,setHistoryQuery]=useState('')
 const [modelList,setModelList]=useState<string[]>([])
 // Sidebar extras (Library, Analytics, Brain, Model) stay folded away unless the owner opens them.
 const [moreOpen,setMoreOpen]=useState(()=>readPreference('star.sidebar.more')==='open')
 // A deleted chat disappears at once and is only removed for good when Undo is not pressed in time.
 const [pendingDelete,setPendingDelete]=useState<ChatThread|null>(null)
 const deleteTimer=useRef<number|null>(null)
 const [chatMenu,setChatMenu]=useState(false)
 const [renamingTitle,setRenamingTitle]=useState(false)
 const chatMenuWrap=useRef<HTMLDivElement>(null)
 const chatMenuTrigger=useRef<HTMLButtonElement>(null)
 const [screenAsk,setScreenAsk]=useState(false)
 const [capturing,setCapturing]=useState(false)
 const consentConfirmed=useRef(false)
 const [previews,setPreviews]=useState<Record<string,string>>({})
 const [themeMotion,setThemeMotion]=useState(!initial?.settings?.reduced_motion)
 const reducedMotion=useEffectiveReducedMotion(!themeMotion)
 const [fixture]=useState(()=>requestedFixture(preview))
 const running=useRef<Map<string,string>>(new Map())
 const chatScroll=useRef<HTMLDivElement>(null)
 const followBottom=useRef(true)
 const composerRef=useRef<HTMLTextAreaElement>(null)
 const lastSent=useRef('')
 const lastFiles=useRef<string[]>([])
 const sending=useRef(false)
 const lastProject=useRef(data.project)
 const runRef=useRef<ActivityRun|null>(null)
 const streamRef=useRef('')
 // At most one streaming render per animation frame, however many deltas arrive in it.
 const streamFrame=useRef<number|null>(null)
 const chatRef=useRef(data.active_chat)
 const answeringChat=useRef('')
 const cancelRequested=useRef(false)
 const lastError=useRef('')
 const fresh=useRef<Set<string>>(new Set())
 const fixtureStop=useRef<(()=>void)|null>(null)
 const targetRef=useRef('')
 const askedTarget=useRef('')
 const inactive=preview||!initial
 useEffect(()=>{writePreference('star.pet.visible',showStar?'on':'off')},[showStar])
 useEffect(()=>{writePreference('star.home.workbench',newHome?'on':'off')},[newHome])
 useEffect(()=>{writePreference('star.studio.layout',studioLayout?'on':'off')},[studioLayout])
 useEffect(()=>{writePreference('star.clips.panels',clipsOn?'on':'off')},[clipsOn])
 useEffect(()=>{if(!petTerminal)return;const timer=setTimeout(()=>setPetTerminal(null),petTerminal.kind==='finished'?2000:4000);return ()=>clearTimeout(timer)},[petTerminal])
 // The collapsed sidebar is a view preference: it survives restarts.
 useEffect(()=>writePreference('star.sidebar',sidebarCollapsed?'collapsed':'open'),[sidebarCollapsed])
 useEffect(()=>writePreference('star.sidebar.more',moreOpen?'open':'closed'),[moreOpen])
 useDismiss(chatMenu,()=>setChatMenu(false),chatMenuWrap,chatMenuTrigger)
 chatRef.current=data.active_chat
 // What a request sent now would talk to. An answer or a failure is only evidence about that target.
 targetRef.current=connectionTarget(data.settings as AppSettings&Record<string,unknown>)
 const updateRun=useCallback((next:ActivityRun|null)=>{runRef.current=next;setRun(next)},[])
 const sync=useCallback(async()=>{
   if(inactive)return
   const r=await request<BootData>('bootstrap')
   if(r.ok&&r.data){setData(r.data);setDraft(r.data.settings);if(!sending.current&&!runRef.current)setMessages(r.data.messages);setThemeMotion(!r.data.settings.reduced_motion)}
 },[inactive])
 useEffect(()=>{if(!inactive) void sync()},[sync,inactive])
 /** Re-read only what the host knows about the connection. The conversation on screen is left alone. */
 const refreshConnection=useCallback(async()=>{
   if(inactive)return
   const r=await request<BootData>('bootstrap')
   if(r.ok&&r.data){const now=r.data;setData(d=>({...d,server:now.server,brain_running:now.brain_running,model_router_running:now.model_router_running,credentials:now.credentials}))}
 },[inactive])
 useEffect(()=>{
   const node=chatScroll.current
   if(tab==='chat'&&node&&followBottom.current){node.scrollTop=node.scrollHeight;setShowJump(false)}
 },[messages.length,streamingText,busy,run,tab,data.active_chat])
 const onChatScroll=()=>{
   const node=chatScroll.current
   if(!node)return
   const atBottom=node.scrollHeight-node.scrollTop-node.clientHeight<125
   followBottom.current=atBottom
   setShowJump(!atBottom)
 }
 const jumpToLatest=()=>{
   followBottom.current=true
   if(chatScroll.current)chatScroll.current.scrollTo({top:chatScroll.current.scrollHeight,behavior:reducedMotion?'auto':'smooth'})
   setShowJump(false)
 }
 const act=useCallback(async(action:string,params:Record<string,unknown>={})=>{
   if(inactive){setNotice('This preview is not connected. Open STAR Desktop to use models and tools.');return null}
   const requestId=crypto.randomUUID()
   running.current.set(requestId,action) // Subscribe before a very fast worker can respond.
   const result=await request<unknown>(action,params,requestId)
   if(!result.ok){
     running.current.delete(requestId)
     lastError.current=result.error||'STAR could not complete this action.'
     // A chat request that fails to start is explained inline, next to the message it belongs to.
     if(!CHAT_ACTIONS.includes(action)&&action!=='warmUp'&&action!=='warmDraft')setNotice(lastError.current)
     return null
   }
   if(result.pending)return result
   running.current.delete(requestId)
   return result.data
 },[inactive])
 /** Every backend event (and every preview-fixture event) goes through this one handler. */
 const handleEvent=useCallback((event:BackendEvent)=>{
   const action=running.current.get(event.requestId)
   if(!action)return
   if(action==='warmUp'){
     // The host's own background check: no notice, no chat row. Only the status light is re-read.
     if(event.kind!=='progress')running.current.delete(event.requestId)
     void refreshConnection()
     return
   }
   if(event.kind==='progress'){
     if(action==='installBrain'){
       const obj=(event.data||{}) as Record<string,unknown>
       setBrainProgress({phase:String(obj.phase||'Preparing your AI'),downloaded:Number(obj.overall_downloaded??obj.downloaded??0),total:Number(obj.overall_total??obj.total??0)})
     }else if(CHAT_ACTIONS.includes(action)){
       const info=(typeof event.data==='string'?event.data:(event.data||{})) as ProgressPayload|string
       // Text is appended to the one live message; it is never re-animated per token.
       if(typeof info!=='string'&&typeof info.delta==='string'&&info.delta){
         const first=streamRef.current===''
         streamRef.current+=info.delta
         // The first words show at once; later deltas are drawn once per frame.
         if(first)setStreamingText(streamRef.current)
         else if(streamFrame.current===null)streamFrame.current=window.requestAnimationFrame(()=>{streamFrame.current=null;setStreamingText(streamRef.current)})
       }
       if(runRef.current)updateRun(applyProgress(runRef.current,info,Date.now()))
     }else if(action==='testModelTeam'){
       const detail=(event.data||{}) as {phase?:string;model?:string}
       setNotice(String(detail.phase||'Testing models')+(detail.model?' · '+detail.model:''))
     }else if(action==='installUpdate'){
       const detail=(event.data||{}) as {phase?:string;downloaded?:number;total?:number}
       setUpdateProgress({phase:String(detail.phase||'Downloading update'),downloaded:Number(detail.downloaded||0),total:Number(detail.total||0)})
     }
     return
   }
   running.current.delete(event.requestId)
   const endRun=(outcome:'done'|'failed'|'cancelled')=>{
     const current=runRef.current
     if(current)setLastRun({chat:answeringChat.current,run:settleRun(current,outcome,Date.now())})
     updateRun(null)
   }
   if(event.kind==='error'){
     const msg=typeof event.data==='string'?event.data:String((event.data as {error?:string})?.error||'Task could not finish.')
     if(CHAT_ACTIONS.includes(action)){
       const found=classifyFailure(msg)
       const cancelled=cancelRequested.current||found.kind==='cancelled'
       cancelRequested.current=false
       endRun(cancelled?'cancelled':'failed')
       // The backend stores this outcome as a terminal record of the turn; the same row is shown now.
       // The unfinished draft is dropped, because it was not saved and would vanish on the next reload.
       streamRef.current='';sending.current=false
       const row:ChatMessage={...makeMsg('event',msg),status:cancelled?'cancelled':'failed'}
       fresh.current.add(row.id)
       if(chatRef.current===answeringChat.current){
         setMessages(m=>[...m,row])
         setRetryText(lastSent.current)
       }
       setBusy(false);setStopping(false);setStreamingText('')
       setPetTerminal({kind:cancelled?'cancelled':'error',at:Date.now()})
       if(!cancelled&&action!=='generateImage')setLastOutcome({ok:false,at:Date.now(),kind:found.kind,target:askedTarget.current})
       // The host has just recorded this failure; without this the Model page would still say "not checked yet".
       if(!cancelled)void refreshConnection()
     }else setNotice(msg)
     if(action==='testModel'){setModelChecking(false);setLastOutcome({ok:false,at:Date.now(),kind:classifyFailure(msg).kind,target:askedTarget.current});void refreshConnection()}
     if(action==='testModelTeam')setTeamChecking(false)
     if(['listCustomTools','previewCustomTool','approveCustomTool','disableCustomTool'].includes(action))setCustomBusy('')
     if(action==='startModelRouter'||action==='stopBrain')setRouterBusy(false)
     if(action==='checkUpdates'||action==='installUpdate'){setUpdateBusy(false);setUpdateProgress(null)}
     if(action==='installBrain'||action==='startBrain')setBrainProgress(null)
     return
   }
   const result=event.data as Record<string,unknown>
   if(CHAT_ACTIONS.includes(action)){
     cancelRequested.current=false
     const answeredBy=runRef.current?.model
     endRun('done')
     streamRef.current='';sending.current=false
     setBusy(false);setStopping(false);setStreamingText('');setRetryText('');setNotice('')
     setPetTerminal({kind:'finished',at:Date.now()})
     // What the turn taught is said once, plainly; the lesson itself is on the Projects page.
     const learned=result?.learned as {accepted?:number;candidates?:number;replaced?:number;not_kept?:number;capture_failed?:number}|undefined
     if(learned?.accepted)setNotice(`Noted for this project: ${learned.accepted===1?'1 lesson':learned.accepted+' lessons'} from what you said.${learned.replaced?' It replaced an older lesson on the same subject.':''} Review it under Projects.`)
     else if(learned?.candidates)setNotice(`${learned.candidates===1?'1 note is':learned.candidates+' notes are'} waiting for your review under Projects.`)
     // A statement the content rules turned away: say so, or the owner believes it was learned.
     else if(learned?.not_kept)setNotice('That was not kept as a lesson: it reads like a permission or setting, or contains something like a key. Lessons cannot hold those.')
     // The lesson store failed: learning stops until it is fixed, so never stay silent about it.
     else if(learned?.capture_failed)setNotice('STAR could not save what this turn taught: the lesson store had a problem. The answer is fine; details are in the STAR log.')
     if(action!=='generateImage')setLastOutcome({ok:true,at:Date.now(),target:askedTarget.current,...(answeredBy?{model:answeredBy}:{})})
     if(chatRef.current===answeringChat.current)setMessages(m=>[...m,{...makeMsg('assistant',String(result?.answer||'')),image:typeof result?.image==='string'?result.image:undefined}]);void sync()
   }else if(action==='installBrain'||action==='startBrain'){
     setBrainProgress(null);setNotice('The local model is running.');void sync()
   }else if(action==='testModel'){
     setModelChecking(false);setModelCheck(result as {ok:boolean;model:string;sample:string});setLastOutcome({ok:true,at:Date.now(),target:askedTarget.current});setNotice('The model answered a real test prompt.');void refreshConnection()
   }else if(action==='startModelRouter'){
     setRouterBusy(false);setModelList(Array.isArray(result.models)?result.models as string[]:[])
     setNotice('Local router is reachable; select a model and test its actual completion.');void sync()
   }else if(action==='stopBrain'){
     setRouterBusy(false);setNotice('The local model server stopped; chats and weights are preserved.');void sync()
   }else if(action==='testModelTeam'){
     setTeamChecking(false)
     const report=result as ModelTeamReport
     setTeamResult(report)
     setNotice(report.all_text_ready?'Configured model IDs passed text probes.':'Some model IDs failed text probes.')
   }else if(action==='listCustomTools'){
     setCustomBusy('')
     setCustomTools((result as unknown as CustomToolCatalog)?.tools||[])
   }else if(action==='previewCustomTool'){
     setCustomBusy('')
     const id=Number(result.tool_id||0)
     setCustomPreview(JSON.stringify({ok:result.ok,results:result.results,truncated:result.truncated||false},null,2).slice(0,3800))
     if(result.ok)setCustomTools(items=>items.map(t=>t.id===id?{...t,tests:t.tests+1}:t))
     setNotice(result.ok?'Preview completed. Inspect source evidence before approving.':'Custom tool preview failed. Check enabled sources.')
   }else if(action==='approveCustomTool'||action==='disableCustomTool'){
     setCustomBusy('')
     const id=Number(result.id||0)
     const status:'approved'|'disabled'=action==='approveCustomTool'?'approved':'disabled'
     setCustomTools(items=>items.map(t=>t.id===id?{...t,status}:t))
     setNotice(status==='approved'?'Tool approved for this project.':'Tool disabled.')
     void sync()
   }else if(action==='checkUpdates'){
     setUpdateBusy(false)
     setUpdate(result as unknown as UpdateInfo)
     if(result.requires_browser)setNotice(String(result.explanation||'Download this version from GitHub Releases.'))
     else setNotice(result.available?`STAR v${result.version} is ready to install.`:'STAR is up to date.')
   }else if(action==='installUpdate'){
     setUpdateBusy(false);setUpdateProgress(null)
     setNotice('Verified setup launched. STAR will restart after installation.')
   }
   else if(action==='discoverStudio'||action==='selectStudio')void sync()
   else if(action==='listModels')setModelList(Array.isArray(result.models)?result.models as string[]:[])
   else if(action==='transcribe')setPrompt(p=>p+(p?'\n':'')+String(result.text||''))
   else void sync()
 },[sync,updateRun,refreshConnection])
 useEffect(()=>onBackendEvent(handleEvent),[handleEvent])
 // Create image switched on: ask the host whether pictures can be made (the same checks it runs before making one).
 useEffect(()=>onBackendEvent(event=>{
   if(!imageStatusRequest.current||event.requestId!==imageStatusRequest.current||event.kind==='progress')return
   imageStatusRequest.current=''
   if(event.kind==='result'&&event.data&&typeof event.data==='object')setImageStatus(event.data as MediaStatus)
 }),[])
 useEffect(()=>{
   if(!imageMode||inactive)return
   let live=true
   const requestId=crypto.randomUUID()
   imageStatusRequest.current=requestId // Subscribe before a fast worker can answer.
   void request<MediaStatus>('mediaStatus',{},requestId).then(reply=>{
     if(!reply.ok||!reply.pending){if(imageStatusRequest.current===requestId)imageStatusRequest.current=''}
     if(live&&reply.ok&&!reply.pending&&reply.data&&typeof reply.data==='object')setImageStatus(reply.data)
   })
   return ()=>{live=false}
 },[imageMode,inactive])
 // Once per provider, model and address: the host checks the selected model server in the background and
 // lets it read the start of the conversation, so the status is truthful and the first message is not the slow one.
 const warmTarget=connectionTarget(data.settings as AppSettings&Record<string,unknown>)
 const warmedTarget=useRef('')
 useEffect(()=>{
   if(inactive||!data.settings.model||warmedTarget.current===warmTarget)return
   warmedTarget.current=warmTarget
   void act('warmUp')
 },[inactive,act,warmTarget,data.settings.model])
 // Settings > Start thinking while I type: after a pause the host lets the server read the draft (star/prefill_warm.py).
 useDraftWarm(data.settings.prefill_while_typing===true&&!inactive&&!busy&&!imageMode&&!teamMode&&files.length===0,prompt,
   text=>{void act('warmDraft',{prompt:text,mode:chatMode,research})})

 const beginRun=useCallback((value:string,attachments:string[],mode:'chat'|'team'|'image')=>{
   answeringChat.current=chatRef.current
   lastSent.current=value;lastFiles.current=attachments
   askedTarget.current=targetRef.current
   cancelRequested.current=false
   streamRef.current=''
   followBottom.current=true;setShowJump(false)
   setRetryText('');setStreamingText('');setChatSearch('');setShowChatSearch(false);setStopping(false)
   setPetTerminal(null)
   const mine=makeMsg('user',value,attachments.map(fileName))
   const thumbs=attachments.map(path=>previews[path]).filter(Boolean)
   if(thumbs.length)mine.previews=thumbs
   fresh.current.add(mine.id)
   setBusy(true);setNotice('');setTab('chat');setLastRun(null)
   updateRun(startRun(crypto.randomUUID(),mode,Date.now()))
   return mine
 },[updateRun,previews])

 const send=useCallback(async(text=prompt,attachments=files,retryMessageId?:number)=>{
   // `sending` closes the gap before React re-renders, so a fast double press cannot send twice.
   const value=text.trim();if(busy||sending.current||!value)return
   if(inactive){setNotice('This preview is not connected to a model. Open STAR Desktop to chat.');return}
   // Retry and Edit resend old text: the host would refuse it, so keep it in place with the reason instead.
   const tooLong=overLimitMessage(value,promptKind(imageMode,teamMode));if(tooLong){setNotice(tooLong);return}
   const selected=attachments.slice()
   if(imageMode&&selected.length>2){setNotice('To change a picture, attach the picture and, if you want, one mask. Remove the other attachments.');return}
   if(teamMode&&selected.length){setNotice('A team run is text only. Remove the attachments or turn Team off.');return}
   if(teamMode&&!runsOnOwnHardware(data.settings)){setNotice('STAR Teams runs on your own hardware. Choose Local or STAR Server in Settings.');return}
   sending.current=true
   // A plain picture request typed in the ordinary chat goes to the picture engine; everything else stays text.
   const intent=!teamMode&&!imageMode&&chatMode!=='agent'&&data.settings.media_chat_auto!==false?chatImageRequest(value,selected,messages,retryMessageId!==undefined):null
   const makeImage=imageMode||!!intent
   const mine=beginRun(value,selected,makeImage?'image':teamMode?'team':'chat')
   if(retryMessageId===undefined)setMessages(m=>[...m,mine]);setFiles([]);setPrompt('')
   const action=intent?'generateImage':imageMode?'generateImage':teamMode?'runTeam':'sendMessage'
   const res=await act(action,intent?{prompt:intent.prompt,display_prompt:value,files:selected,size:imageSize,followup:intent.followup,...(retryMessageId===undefined?{}:{retryMessageId})}:imageMode?{prompt:value,files:selected,size:imageSize}:teamMode?{prompt:value,research}:{prompt:value,files:selected,mode:chatMode,research,github:chatMode==='agent'&&githubSource,...(retryMessageId===undefined?{}:{retryMessageId})})
   if(!res){
     // The host refused before a turn started. Nothing was lost: the question stays with Retry and Edit.
     sending.current=false
     updateRun(null);setBusy(false);setRetryText(value)
     setPetTerminal({kind:'error',at:Date.now()})
     const row:ChatMessage={...makeMsg('event',lastError.current||'STAR could not start this request.'),status:'failed'}
     fresh.current.add(row.id)
     setMessages(m=>[...m,row])
   }
 },[prompt,busy,files,inactive,act,beginRun,updateRun,imageMode,imageSize,data.settings,chatMode,teamMode,research,githubSource,messages])

 const stop=useCallback(()=>{
   if(!busy||stopping)return
   cancelRequested.current=true
   setStopping(true)
   if(fixtureStop.current){fixtureStop.current();return}
   void act('cancelMessage')
 },[busy,stopping,act])

 // Browser preview only: play a scripted fixture through the same handler as real events.
 useEffect(()=>{
   if(!fixture)return
   let live=true
   const timers:number[]=[]
   const query=new URLSearchParams(window.location.search)
   const hold=Number(query.get('hold')||0)
   const speed=Math.max(0.05,Number(query.get('speed')||1))
   const play=(script:FixtureScript,base:ChatMessage[])=>{
     const requestId='fixture-'+crypto.randomUUID()
     running.current.set(requestId,script.action)
     if(script.mode)setChatMode(script.mode)
     setTeamMode(script.action==='runTeam')
     const mine=beginRun(script.prompt,[],script.action==='runTeam'?'team':script.action==='generateImage'?'image':'chat')
     setMessages([...base,mine])
     let delay=0
     const events=hold>0?script.events.slice(0,hold):script.events
     events.forEach(step=>{
       delay+=step.wait/speed
       timers.push(window.setTimeout(()=>{if(live)handleEvent({requestId,kind:step.kind,data:step.data})},delay))
     })
     fixtureStop.current=()=>{
       timers.forEach(timer=>window.clearTimeout(timer))
       window.setTimeout(()=>{if(live)handleEvent({requestId,kind:'error',data:'Request stopped. The draft answer has not been saved as a completed result.'})},180)
     }
   }
   void import('./previewFixtures').then(module=>{
     if(!live)return
     const chosen:Fixture|undefined=module.FIXTURES[fixture]
     if(!chosen)return
     const chats=chosen.chats||module.fixtureChats
     const open=chats[0]?.id||''
     setData(d=>({...d,chats,active_chat:open,project:chosen.project||d.project,projects:chosen.projects||d.projects,server:chosen.server||module.fixtureServer,retry:chosen.retry||null,settings:{...d.settings,...module.fixtureSettings,...chosen.settings}}))
     // The scripted turn belongs to the fixture chat from its first event (React has not re-rendered yet).
     chatRef.current=open
     setDraft(d=>({...d,...module.fixtureSettings,...chosen.settings}))
     setMessages(chosen.messages)
     if(chosen.finishedRun)setLastRun({chat:open,run:chosen.finishedRun})
     if(chosen.script)play(chosen.script,chosen.messages)
   })
   return ()=>{
     live=false
     timers.forEach(timer=>window.clearTimeout(timer))
     fixtureStop.current=null
     running.current.clear()
     updateRun(null);setBusy(false);setStreamingText('');streamRef.current=''
   }
 },[fixture,handleEvent,beginRun,updateRun])

 useEffect(()=>{
   const onShortcut=(e:KeyboardEvent)=>{
     const mod=e.ctrlKey||e.metaKey
     if(mod&&e.key.toLowerCase()==='k'){
       e.preventDefault();setTab('chat');composerRef.current?.focus()
     }else if(mod&&e.key===','){
       e.preventDefault();setTab('settings')
     }else if(e.key==='Escape'){
       setLeftOpen(false);setNotice('')
     }
   }
   window.addEventListener('keydown',onShortcut)
   return ()=>window.removeEventListener('keydown',onShortcut)
 },[])
 const attach=async()=>{const v=await act('pickFiles',imageMode?{kind:'image'}:{});if(Array.isArray(v))setFiles(f=>[...f,...v.map(String)].slice(0,imageMode?2:8))}
 const transcribe=async()=>{const r=await act('pickFiles',{kind:'audio'});if(Array.isArray(r)&&r[0])void act('transcribe',{file:r[0]})}
 /** Chat navigation answers carry only the chat part of the state (react_shell._chat_state); the rest stays. */
 const applyChat=(c:ChatState)=>{chatRef.current=c.active_chat;setData(d=>({...d,...c}));setMessages(c.messages);setChatSearch('');setShowChatSearch(false);setRetryText('');setLastRun(null);setStreamingText(c.active_chat===answeringChat.current?streamRef.current:'');followBottom.current=true;setShowJump(false);setTab('chat');setLeftOpen(false)}
 const applyBoot=(b:BootData)=>{applyChat(b);setData(b);setDraft(b.settings)}
 const changeProject=async(name:string)=>{if(busy)return;const v=await act('switchProject',{project:name});if(v){applyBoot(v as BootData);lastProject.current=name}setLeftOpen(false)}
 const startNewChat=async()=>{if(busy){setNotice('Stop the current answer before starting a new chat.');return}const v=await act('newChat');if(v){applyChat(v as ChatState);setPrompt('');setImageMode(false);setFiles([])}setTab('chat');composerRef.current?.focus()}
 const openChat=async(id:string)=>{if(id===data.active_chat){setTab('chat');setLeftOpen(false);return}const v=await act('switchChat',{chatId:id});if(v)applyChat(v as ChatState)}
 /** Rename: the sidebar shows the new title at once; a refusal puts the old one back. */
 const renameChat=async(id:string,title:string)=>{
   const before=data.chats.find(c=>c.id===id)?.title
   setData(d=>({...d,chats:d.chats.map(c=>c.id===id?{...c,title}:c)}))
   if(inactive)return
   const v=await act('renameChat',{chatId:id,title}) as {title?:string}|null
   if(!v){if(before!==undefined)setData(d=>({...d,chats:d.chats.map(c=>c.id===id?{...c,title:before}:c)}));return}
   if(v.title&&v.title!==title)setData(d=>({...d,chats:d.chats.map(c=>c.id===id?{...c,title:v.title as string}:c)}))
 }
 const commitDelete=useCallback(async(chat:ChatThread)=>{
   if(deleteTimer.current!==null){window.clearTimeout(deleteTimer.current);deleteTimer.current=null}
   setPendingDelete(current=>current?.id===chat.id?null:current)
   if(inactive){setData(d=>({...d,chats:d.chats.filter(c=>c.id!==chat.id)}));return}
   const v=await act('deleteChat',{chatId:chat.id}) as ChatState|null
   if(!v)return
   // Only the list changes, unless the host had to open another chat.
   if(v.active_chat!==chatRef.current)applyChat(v)
   else setData(d=>({...d,chats:v.chats}))
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[inactive,act])
 const deleteChat=async(chat:ChatThread)=>{
   if(busy&&answeringChat.current===chat.id){setNotice('Stop the answer in this chat before deleting it.');return}
   if(pendingDelete)void commitDelete(pendingDelete)
   setPendingDelete(chat)
   deleteTimer.current=window.setTimeout(()=>void commitDelete(chat),6000)
   // The row that held focus is gone; keep the keyboard somewhere useful.
   window.requestAnimationFrame(()=>composerRef.current?.focus())
   // Like ChatGPT: deleting the open chat leaves you on a fresh one straight away.
   if(chat.id===data.active_chat&&!busy){
     if(inactive){setMessages([]);setData(d=>({...d,active_chat:''}))}
     else{const v=await act('newChat');if(v){applyChat(v as ChatState);setPrompt('')}}
   }
 }
 const undoDelete=()=>{
   const chat=pendingDelete
   if(deleteTimer.current!==null){window.clearTimeout(deleteTimer.current);deleteTimer.current=null}
   setPendingDelete(null)
   if(chat&&inactive&&!data.active_chat)setData(d=>({...d,active_chat:chat.id}))
 }
 useEffect(()=>()=>{if(deleteTimer.current!==null)window.clearTimeout(deleteTimer.current)},[])
 /** "Look at my screen": only after the owner says yes in ScreenConsent, one screenshot is attached. */
 const lookAtScreen=async()=>{
   if(capturing)return
   setCapturing(true)
   const shot=await act('captureScreen',{consent:true}) as {path?:string;preview?:string}|null
   setCapturing(false);setScreenAsk(false)
   if(!shot?.path)return
   const path=shot.path
   setFiles(list=>[...list.filter(item=>item!==path),path].slice(0,8))
   if(shot.preview)setPreviews(map=>({...map,[path]:shot.preview as string}))
   if(!prompt.trim())setPrompt('What do you see on my screen?')
 }
 const chooseWorkflow=async()=>{const v=await act('pickFiles',{kind:'workflow'});if(Array.isArray(v)&&v[0])setDraft(d=>({...d,comfy_workflow:String(v[0])}))}
 const filteredChats=data.chats.filter(c=>c.id!==pendingDelete?.id&&c.title.toLowerCase().includes(historyQuery.toLowerCase()))
 const chatGroups=groupChats(filteredChats.slice(0,CHAT_WINDOW))
 const saveSettings=async()=>{const v=await act('saveSettings',{settings:draft});if(v){setNotice('Settings saved.');setModelCheck(null);void sync()}}
 /** Reduced motion applies at once and is stored straight away, not only on Save. */
 const setReducedMotion=(reduced:boolean)=>{
   setDraft(d=>({...d,reduced_motion:reduced}));setThemeMotion(!reduced)
   if(!inactive)void act('saveSettings',{settings:{reduced_motion:reduced}})
 }
 const testActualModel=async()=>{
   if(modelChecking)return
   askedTarget.current=targetRef.current
   setModelChecking(true);setModelCheck(null)
   const response=await act('testModel')
   if(!response)setModelChecking(false)
 }
 const startLocalRouter=async()=>{
   if(routerBusy||busy)return
   setRouterBusy(true);setNotice('Starting local model router…')
   const saved=await act('saveSettings',{settings:draft})
   if(!saved){setRouterBusy(false);return}
   const launched=await act('startModelRouter')
   if(!launched)setRouterBusy(false)
 }
 const stopLocalBrain=async()=>{
   if(routerBusy||busy)return
   setRouterBusy(true)
   const done=await act('stopBrain')
   if(!done)setRouterBusy(false)
 }
 const testSpecialists=async()=>{
   if(teamChecking||busy)return
   setTeamChecking(true);setTeamResult(null);setNotice('Testing configured models…')
   const saved=await act('saveSettings',{settings:draft})
   if(!saved){setTeamChecking(false);return}
   const result=await act('testModelTeam')
   if(!result)setTeamChecking(false)
 }
 const customAction=(action:'previewCustomTool'|'approveCustomTool'|'disableCustomTool',id:number)=>{
   if(customBusy||inactive)return
   setCustomBusy(action+':'+id);setCustomPreview('')
   void act(action,{id,...(action==='previewCustomTool'?{query:customQuery.trim()}: {})})
 }
 const refreshCustomTools=()=>{
   if(customBusy||inactive)return
   setCustomBusy('listCustomTools');void act('listCustomTools')
 }
 useEffect(()=>{if(tab==='tools'&&!inactive)void act('listCustomTools')},[tab,inactive,act])
 const selectRouterFolder=async()=>{
   const result=await act('selectFolder')
   if(result&&typeof result==='object'&&'path' in result&&typeof result.path==='string'&&result.path){
     setDraft(d=>({...d,router_models_dir:result.path as string}))
   }
 }
 /** A thumb on a saved answer. The host stores it and keeps a note for review; nothing is trusted from it. */
 const rate=async(mid:number,value:'up'|'down'|'')=>{
   const done=await act('messageFeedback',{messageId:mid,value}) as {counts?:LessonCounts}|null
   if(!done)return
   setMessages(list=>list.map(m=>m.mid===mid?{...m,feedback:value||undefined}:m))
   if(done.counts)setData(d=>({...d,learning:done.counts}))
 }
 /** What was wrong with an answer marked not helpful: kept as a correction candidate (star/corrections.py). */
 const correct=async(mid:number,text:string)=>{
   const done=await act('messageFeedback',{messageId:mid,value:'down',correction:text}) as {counts?:LessonCounts}|null
   if(!done)return false
   if(done.counts)setData(d=>({...d,learning:done.counts}))
   return true
 }
 const copyConversation=async()=>{
   if(!messages.length){setNotice('Nothing to copy yet.');return}
   const transcript=messages.map(m=>(m.role==='assistant'?'STAR':m.role==='user'?'You':'System')+':\n'+m.text).join('\n\n---\n\n')
   try{
     if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(transcript);setNotice('Conversation copied to clipboard.');return}
   }catch{/* Local Qt WebEngine clipboard may be unavailable; use native bridge below. */}
   const response=await act('copyText',{text:transcript})
   if(response)setNotice('Conversation copied to clipboard.')
 }
 const checkForUpdates=async()=>{
   if(updateBusy)return
   setUpdateBusy(true);setUpdateProgress(null)
   const response=await act('checkUpdates')
   if(!response)setUpdateBusy(false)
 }
 const installVerifiedUpdate=async()=>{
   if(updateBusy||!update?.available||update.requires_browser)return
   setUpdateBusy(true)
   setUpdateProgress({phase:'Checking trusted release details',downloaded:0,total:0})
   const response=await act('installUpdate')
   if(!response){setUpdateBusy(false);setUpdateProgress(null)}
 }
 // A notice belongs to the page where the action happened: it must not follow to another page and cover it.
 const nav=(id:Tab)=>{if(id!==tab)setNotice('');setTab(id);setLeftOpen(false);if(id==='analytics')void sync()}
 /** "What STAR learned this week" lives once, on the Projects page; the Model page links to it. */
 const openLearned=()=>{
   nav('projects')
   let tries=0
   const reveal=()=>{
     const found=document.querySelector('.learn-week')
     if(found){found.scrollIntoView({block:'start',behavior:reducedMotion?'auto':'smooth'});return}
     if(++tries<20)window.setTimeout(reveal,50)
   }
   window.setTimeout(reveal,0)
 }
 const extraPages:Tab[]=['library','analytics','brain-overview','brain']
 const showMore=moreOpen||extraPages.includes(tab)
 const fillComposer=(text:string)=>{
   setPrompt(text);setTab('chat')
   window.requestAnimationFrame(()=>{const node=composerRef.current;if(node){node.focus();node.setSelectionRange(text.length,text.length)}})
 }
 const narrow=()=>window.matchMedia('(max-width: 850px)').matches
 const wrapper='shell '+(!leftOpen?'':'shell-open')+(sidebarCollapsed?' shell-sidebar-collapsed':'')
 const query=chatSearch.trim().toLowerCase()
 const matchingMessages=query?messages.filter(m=>m.text.toLowerCase().includes(query)):messages
 const currentChat=data.chats.find(c=>c.id===data.active_chat&&c.id!==pendingDelete?.id)
 const chatTitle=currentChat?.title||'New chat'
 const serverMode=usesStarServer(data.settings)
 const serverDraft=usesStarServer(draft)
 const brain=brainStatus(data)
 const connection=describeConnection({settings:data.settings as AppSettings&Record<string,unknown>,brain,server:data.server,ownHardware:runsOnOwnHardware(data.settings),credentials:data.credentials||{},preview:inactive&&!fixture,last:lastOutcome})
 // STAR Server brings its own search (self-hosted SearXNG, server/searxng); a Brave/Tavily key also works.
 const web:Availability=webSearchAvailability(data.settings as AppSettings&Record<string,unknown>,data.credentials)
 const team:Availability=!runsOnOwnHardware(data.settings)?{ok:false,reason:'Own hardware only'}:files.length?{ok:false,reason:'Text only'}:{ok:true}
 const teamSlots=serverMode?Math.max(1,Math.min(2,Number(data.settings.server_parallel)||1)):2
 // The timeline belongs to the turn that started it: right after the last message you sent.
 const viewingAnswer=busy&&data.active_chat===answeringChat.current
 const shownRun=viewingAnswer?run:lastRun&&lastRun.chat===data.active_chat?lastRun.run:null
 const timeline=!query&&shownRun&&(isRich(shownRun)||!!shownRun.brain||shownRun.steps.some(step=>step.state==='waiting'))?shownRun:null
 let lastUser=-1,lastStar=-1
 messages.forEach((m,i)=>{if(m.role==='user')lastUser=i;else if(m.role==='assistant')lastStar=i})
 // The live answer is the last entry of the same keyed list, so finishing it never remounts the text.
 const turns:ChatMessage[]=viewingAnswer&&streamingText&&!query?[...matchingMessages,{id:'stream-live',role:'assistant',text:streamingText}]:matchingMessages
 const empty=!messages.length&&!viewingAnswer
 // The workbench home is opt-in (Settings > Interface); preview review can force either with ?home=classic|workbench.
 const homeParam=preview?new URLSearchParams(window.location.search).get('home'):null
 const classicHome=homeParam==='classic'||(homeParam!=='workbench'&&!newHome)
 // Retry survives a restart: this session's last prompt first, else what the backend says went unanswered.
 const pending=data.retry&&data.retry.prompt?data.retry:null
 const retryPrompt=retryText||pending?.prompt||''
 const lastMessage=messages[messages.length-1]
 const failedLast=!busy&&lastMessage?.role==='event'&&!!lastMessage.status
 // Nothing at all was recorded after the newest question (for example STAR was closed mid-reply).
 const interrupted=!busy&&!query&&!retryText&&pending?.status==='interrupted'&&lastMessage?.role==='user'?pending:null
 const retryNow=()=>void send(retryPrompt,retryText?lastFiles.current:[],!retryText&&pending?pending.message_id:undefined)
 // Star in the empty chat listens while you type and looks up when an answer has just finished.
 const faceMood:StarMood=capturing?'looking':prompt.trim()?'listening':petTerminal?.kind==='error'?'oops':'idle'
 // A Studio question gets the Studio shortcut; everything else keeps the dock quiet.
 const studioReady=data.studio?.state==='connected'&&!!data.studio.selected_valid
 const mentionsStudio=/\b(studio|roblox|place|luau|workspace|playtest)\b/i.test(prompt)
 const petState:PetState=update?.available?'update':busy?(streamingText?'streaming':'thinking'):petTerminal?.kind??(prompt.trim()?'typing':'idle')
 const announce=busy?'STAR is working on your message.':failedLast?classifyFailure(lastMessage.text).title:lastStar>lastUser&&lastStar>=0?'STAR replied.':''
 const timelineNode=timeline&&<ActivityTimeline key={'run-'+timeline.id} run={timeline} onStop={busy?stop:undefined} stopping={stopping}/>
 const companionSettings=<CompanionControls preferences={companionPreferences} onPreferencesChange={setCompanionPreferences} reducedMotion={reducedMotion}/>
 return <MotionPolicy reduced={reducedMotion}><div className={wrapper} data-star-studio={studioLayout||undefined} data-preview={preview} data-reduced-motion={reducedMotion}>
   <a className="skip-link" href="#star-main" onClick={e=>{e.preventDefault();const main=document.getElementById('star-main');main?.focus();if(tab==='chat')composerRef.current?.focus()}}>Skip to {tab==='chat'?'message box':'page content'}</a>
   <aside className="rail" aria-label="STAR navigation">
     <div className="rail-head">
       <button className="rail-brand" type="button" aria-label="STAR, back to chat" onClick={()=>nav('chat')}><StarMark size={20}/><span className="rail-brand-lockup"><strong>STAR</strong><small>Intelligence</small></span></button>
       <button className="rail-icon" type="button" aria-label="Hide sidebar" title="Hide sidebar" onClick={()=>{if(narrow())setLeftOpen(false);else setSidebarCollapsed(true)}}><PanelLeftClose size={17}/></button>
     </div>
     {studioLayout&&<StudioProjectSwitch project={data.project} onOpen={()=>nav('projects')}/>}
     <div className="rail-group">
       <button className="rail-item rail-new" type="button" onClick={()=>void startNewChat()}><SquarePen size={16}/><span>New chat</span></button>
       <button className="rail-item" type="button" aria-expanded={historySearchOpen} onClick={()=>{setHistorySearchOpen(v=>!v);setHistoryQuery('')}}><Search size={16}/><span>Search chats</span></button>
       {historySearchOpen&&<div className="rail-search"><input type="search" autoFocus aria-label="Find a conversation" placeholder="Find a chat" value={historyQuery} onChange={e=>setHistoryQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Escape'){e.stopPropagation();setHistorySearchOpen(false);setHistoryQuery('')}}}/><button type="button" aria-label="Close search" onClick={()=>{setHistorySearchOpen(false);setHistoryQuery('')}}><X size={14}/></button></div>}
     </div>
     <nav className="rail-group" aria-label="Workspace">
       {sections.filter(([id])=>id==='projects'||id==='tools').map(([id,name,Icon])=><button className={'rail-item '+(tab===id?'is-current':'')} type="button" key={id} aria-current={tab===id?'page':undefined} onClick={()=>nav(id)}><Icon size={16}/><span>{name}</span>{id==='projects'&&<small dir="auto" title={'Current project: '+data.project}>{data.project}</small>}</button>)}
       <button className="rail-item rail-more" type="button" aria-expanded={showMore} onClick={()=>setMoreOpen(v=>!v)}><ChevronRight size={16} className={showMore?'is-open':undefined}/><span>More</span></button>
       {showMore&&<div className="rail-more-group">
         {sections.filter(([id])=>extraPages.includes(id)).map(([id,name,Icon])=><button className={'rail-item '+(tab===id?'is-current':'')} type="button" key={id} aria-current={tab===id?'page':undefined} onClick={()=>nav(id)}><Icon size={16}/><span>{id==='brain'?'Model':name}</span></button>)}
       </div>}
     </nav>
     <div className="rail-chats" role="region" aria-label="Saved conversations">
       {chatGroups.length<=1&&<div className="rail-label">Chats</div>}
       {chatGroups.map(group=><Fragment key={group.label}>
         {chatGroups.length>1&&<div className="rail-sublabel">{group.label}</div>}
         <AnimatePresence initial={false}>
         {group.chats.map(chat=><motion.div key={chat.id} className="rail-chat-slot" layout={reducedMotion?false:'position'}
           initial={reducedMotion?false:{opacity:0,height:0}} animate={{opacity:1,height:'auto'}} exit={reducedMotion?{opacity:0}:{opacity:0,height:0}} transition={reducedMotion?instant:{duration:.18,ease:[0.23,1,0.32,1]}}>
           <ChatRow chat={chat} current={data.active_chat===chat.id&&tab==='chat'} disabled={busy&&answeringChat.current===chat.id}
             onOpen={()=>void openChat(chat.id)} onRename={title=>void renameChat(chat.id,title)} onDelete={()=>void deleteChat(chat)}/>
         </motion.div>)}
         </AnimatePresence>
       </Fragment>)}
       {!filteredChats.length&&<EmptyState compact title={historyQuery?'No chats match that search.':'Chats you start are saved here.'}/>}
       {filteredChats.length>CHAT_WINDOW&&<p className="rail-window-note">Showing the {CHAT_WINDOW} most recent chats. Search finds older ones.</p>}
     </div>
     <div className="rail-foot">
       <button className={'rail-item '+(tab==='settings'?'is-current':'')} type="button" aria-current={tab==='settings'?'page':undefined} onClick={()=>nav('settings')}><Settings2 size={16}/><span>Settings</span><small>v{data.version}</small></button>
     </div>
   </aside>
   <div className="shell-main">
     <header className="bar">
       <div className="bar-left">
         <button className="bar-action bar-reveal" type="button" aria-label="Show sidebar" title="Show sidebar" onClick={()=>{if(narrow())setLeftOpen(true);else setSidebarCollapsed(false)}}><PanelLeftOpen size={18}/></button>
         {tab==='chat'?<div className="bar-title"><span className="bar-crumb" dir="auto" title={data.project}>{data.project}</span><span className="bar-sep" aria-hidden="true">/</span>{renamingTitle&&currentChat?<input className="bar-rename" aria-label="Chat name" dir="auto" autoFocus defaultValue={chatTitle} maxLength={80}
             onBlur={event=>{const next=event.currentTarget.value.trim();setRenamingTitle(false);if(next&&next!==chatTitle)void renameChat(currentChat.id,next)}}
             onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();event.currentTarget.blur()}else if(event.key==='Escape'){event.preventDefault();event.stopPropagation();event.currentTarget.value=chatTitle;setRenamingTitle(false)}}}/>
           :<h1 dir="auto" title={chatTitle} onDoubleClick={()=>{if(currentChat)setRenamingTitle(true)}}>{chatTitle}</h1>}</div>
           :<div className="bar-title"><button className="bar-back" type="button" onClick={()=>nav('chat')}>Chat</button><span className="bar-sep" aria-hidden="true">/</span>{/* Pages with their own <h1> get a plain breadcrumb here; Brain draws no page title, so the bar keeps its h1. */}{tab==='brain-overview'?<h1>{sections.find(x=>x[0]===tab)?.[1]}</h1>:<span className="bar-page" aria-current="page">{sections.find(x=>x[0]===tab)?.[1]}</span>}</div>}
       </div>
       <div className="bar-right">
         {studioLayout&&<AppearancePanel preferences={appearance} onChange={updateAppearance} onReset={resetAppearance} companionSettings={companionSettings} persisted={appearancePersisted}/>}
         {tab==='chat'&&<>
           {showChatSearch&&<input className="bar-find" type="search" aria-label="Search messages in this chat" placeholder="Find in this chat" autoFocus value={chatSearch} onChange={e=>setChatSearch(e.target.value)} onKeyDown={e=>{if(e.key==='Escape'){e.stopPropagation();setShowChatSearch(false);setChatSearch('')}}}/>}
           <button className="bar-action" type="button" title="Find in this chat" aria-label="Find in this chat" aria-pressed={showChatSearch} disabled={!messages.length} onClick={()=>{setShowChatSearch(v=>!v);setChatSearch('')}}><Search size={17}/></button>
           <div className="bar-menu-wrap" ref={chatMenuWrap}>
             <button ref={chatMenuTrigger} className="bar-action" type="button" title="Chat options" aria-label="Chat options" aria-haspopup="menu" aria-expanded={chatMenu} disabled={!messages.length&&!currentChat} onClick={()=>setChatMenu(v=>!v)}><Ellipsis size={17}/></button>
             <AnimatePresence>
               {chatMenu&&<motion.div className="bar-menu" role="menu" aria-label="Chat options" initial={reducedMotion?false:{opacity:0,scale:.97,y:-4}} animate={{opacity:1,scale:1,y:0}} exit={{opacity:0,scale:.98,y:-2}} transition={reducedMotion?instant:{duration:.16,ease:[0.23,1,0.32,1]}}>
                 <button type="button" role="menuitem" className="bar-menu-item" disabled={!currentChat} onClick={()=>{setChatMenu(false);setRenamingTitle(true)}}><Pencil size={15} aria-hidden="true"/> Rename</button>
                 <button type="button" role="menuitem" className="bar-menu-item" disabled={!messages.length} onClick={()=>{setChatMenu(false);void copyConversation()}}><Copy size={15} aria-hidden="true"/> Copy conversation</button>
                 <button type="button" role="menuitem" className="bar-menu-item is-danger" disabled={!currentChat||busy} onClick={()=>{setChatMenu(false);if(currentChat)void deleteChat(currentChat)}}><Trash2 size={15} aria-hidden="true"/> Delete</button>
               </motion.div>}
             </AnimatePresence>
           </div>
           <button className="bar-action bar-reveal" type="button" title="New chat" aria-label="New chat" onClick={()=>void startNewChat()}><SquarePen size={17}/></button>
         </>}
       </div>
     </header>
     {preview&&<div className="preview-ribbon" role="region" aria-label="Preview notice"><Info size={14} aria-hidden="true"/><span>{fixture?'Preview fixture: scripted events for design review. No model is running.':'Interface preview. Chat needs STAR Desktop.'}</span></div>}
     <AnimatePresence mode="wait" initial={false}>
       <MotionSurface as="main" id="star-main" tabIndex={-1} key={tab} className="page-stage" variants={pageFade}>
         {tab==='chat'&&<StudioFrame enabled={studioLayout} compact={compactStudio} companionVisible={companionPreferences.visible}
           companion={<CompanionShelf state={petState} reducedMotion={reducedMotion} preferences={companionPreferences} onPreferencesChange={setCompanionPreferences} compact={compactStudio}/>}>
           <div className={'thread'+(empty?' is-empty':'')+(empty&&!classicHome?' is-crafted-home':'')}>
           <div className="thread-scroll" ref={chatScroll} onScroll={onChatScroll}>
             <div className="thread-column">
               {empty?(classicHome?(studioLayout?<StudioWelcome mood={faceMood}/>:<div className="thread-hello"><StarFace mood={faceMood} size={104} follow className="thread-hello-star" label="Star, STAR's mascot"/><h2>What are we making?</h2></div>):<StartCanvas project={data.project} mood={faceMood} onStart={fillComposer}/>)
               :<section className="thread-turns" role="log" aria-live="off" aria-label="Conversation">
                 {turns.map((m,index)=>{
                   const live=m.id==='stream-live'
                   const at=query?-1:index
                   const newest=at>=0&&at===messages.length-1&&!busy
                   // Only the newest unanswered turn offers Retry; older failure rows are history.
                   const recover=newest&&m.role==='event'&&!!m.status&&!!retryPrompt
                   return <Fragment key={data.active_chat+':'+(query?m.id:index)}>
                     <Message entry={m} animated={live||fresh.current.has(m.id)} partial={live} pinned={newest}
                       onEdit={m.role==='user'&&!busy?()=>fillComposer(m.text):recover?()=>fillComposer(retryPrompt):undefined}
                       onRetry={recover?retryNow:undefined}
                       onAskAgain={m.role==='assistant'&&at===lastStar&&at>lastUser&&!busy&&lastUser>=0?()=>void send(messages[lastUser].text,[]):undefined}
                       onFeedback={m.role==='assistant'&&typeof m.mid==='number'&&!live?value=>void rate(m.mid as number,value):undefined}
                       onCorrect={m.role==='assistant'&&typeof m.mid==='number'&&!live?text=>correct(m.mid as number,text):undefined}
                       onConnection={recover?()=>nav('brain'):undefined}/>
                     {at===lastUser&&timelineNode}
                   </Fragment>
                 })}
                 {query&&!matchingMessages.length&&<EmptyState compact icon={<Search size={16}/>} title={'No messages match “'+chatSearch.trim()+'”.'} description="Try a shorter word, or close search to see the whole chat."/>}
                 {busy&&run&&!timeline&&!streamingText&&<RunStatus run={run} label={stopping?'Stopping':undefined}/>}
                 {busy&&run?.mode==='image'&&viewingAnswer&&!stopping&&<div className={'image-pending is-'+imageSize} role="img" aria-label="Image being created"><span className="image-pending-sheen" aria-hidden="true"/><span className="image-pending-label"><ImagePlus size={15} aria-hidden="true"/> Your image will appear here</span></div>}
                 {interrupted&&<Message entry={{id:'interrupted',role:'event',text:interrupted.detail,status:'cancelled'}} animated={false} pinned onRetry={retryNow} onEdit={()=>fillComposer(interrupted.prompt)}/>}
               </section>}
             </div>
           </div>
           <div className="dock">
             {showJump&&messages.length>0&&<button className="chat-jump" type="button" onClick={jumpToLatest}><ChevronDown size={15} aria-hidden="true"/> Latest</button>}
             {(!inactive||!!fixture)&&!failedLast&&(connection.tone==='offline'||connection.tone==='attention')&&<div className={'dock-banner is-'+connection.tone} role="status"><CircleAlert size={15} aria-hidden="true"/><span><strong>{connection.state}.</strong> {connection.note}</span><button type="button" onClick={()=>nav('brain')}>Model &amp; connection</button></div>}
             {mentionsStudio&&!studioReady&&<div className="dock-hint"><button type="button" className="starter" onClick={()=>nav('tools')}><Workflow size={14} aria-hidden="true"/> Studio: {data.settings.studio_target==='host_launcher'?'practice host':'this PC'} · {data.studio?.state==='connected'&&data.studio.selected_valid?'selected':data.studio?.state==='connected'?'choose a place':data.studio?.state==='unavailable'?'unavailable':'connect & check MCP'}</button></div>}
             <Composer inputRef={composerRef} value={prompt} onChange={setPrompt} onSend={()=>void send()} onStop={stop} busy={busy} stopping={stopping}
               files={files} onRemoveFile={index=>setFiles(list=>list.filter((_,at)=>at!==index))} onAttach={()=>void attach()} onTranscribe={()=>void transcribe()}
               mode={chatMode} onMode={value=>{setChatMode(value);if(value!=='agent')setGithubSource(false)}}
               imageMode={imageMode} onImageMode={on=>{setImageMode(on);if(on){setFiles(f=>f.filter(p=>/\.(png|jpe?g|webp)$/i.test(p)).slice(0,2));setTeamMode(false)}composerRef.current?.focus()}} imageReady={imageReadiness(imageStatus)} onImageSetup={()=>nav('settings')} imageSize={imageSize} onImageSize={setImageSize}
               teamMode={teamMode} onTeamMode={on=>{setTeamMode(on);composerRef.current?.focus()}} team={team}
               research={research} onResearch={setResearch} web={web} githubSource={githubSource} onGithubSource={setGithubSource}
               connection={connection} onOpenConnection={()=>nav('brain')}
               onLookAtScreen={()=>{consentConfirmed.current=false;setScreenAsk(true)}} previews={previews}/>
             {empty?(classicHome?<div className="starters" role="group" aria-label="Starting points">{starters.map(item=><button key={item.label} type="button" className="starter" onClick={()=>fillComposer(item.prompt)}><item.icon size={15} aria-hidden="true"/><span>{item.label}</span></button>)}</div>:null)
               :<p className="dock-hint">{teamMode?`Team: four read-only stages on ${serverMode?'your STAR Server':'this PC'}, ${teamSlots===1?'one':'at most two'} at a time.${research?' Web search sends your objective and queries to your configured search provider.':''}`:'Review generated changes and tests before using them in your project.'}</p>}
             {studioLayout&&empty&&classicHome&&<StudioInputHint/>}
           </div>
           <div className="thread-rest" aria-hidden="true"/>
           <div className="sr-only" role="status" aria-live="polite">{announce}</div>
         </div></StudioFrame>}
          {tab==='analytics'&&<AnalyticsView data={data.analytics}/>}
         {tab==='brain-overview'&&<div className="scroll-region"><div className="page-wrap"><BrainOverview load={!inactive}/></div></div>}
         {tab==='projects'&&<div className="scroll-region"><div className="page-wrap"><PageTitle eyebrow="PROJECT MANAGEMENT" title="Your workspaces" description="Separate contexts, conversations, and design decisions for every project."/><div className="project-create"><input aria-label="New project name" value={newProject} onChange={e=>setNewProject(e.target.value)} placeholder="New project name" maxLength={60} onKeyDown={e=>{if(e.key==='Enter'&&newProject.trim()){void changeProject(newProject.trim());setNewProject('')}}}/><button className="primary-button" onClick={()=>{if(newProject.trim()){void changeProject(newProject.trim());setNewProject('')}}}><Plus size={17}/> New workspace</button></div><div className="project-grid">{[...new Set([data.project,...data.projects])].map(name=><button className={'project-card '+(name===data.project?'project-current':'')} key={name} type="button" aria-current={name===data.project?'page':undefined} aria-label={'Workspace '+name+(name===data.project?' — current workspace':'')} onClick={()=>changeProject(name)}><FolderOpen size={25}/><strong dir="auto" title={name}>{name}</strong><span>{name===data.project?'Current workspace':'Open workspace'}</span><ArrowRight size={18}/></button>)}</div><LearningPanel project={data.project} settings={data.settings} counts={data.learning} invoke={act} disabled={inactive} refresh={()=>void sync()}/><ReferencesPanel project={data.project} invoke={act} disabled={inactive}/></div></div>}
         {tab==='brain'&&<div className="scroll-region"><div className="page-wrap brain-page">
            <PageTitle eyebrow="MODEL" title="Model & connection" description="Which model STAR talks to, and whether it is answering."/>
            {serverMode&&<ServerBrainPanel settings={data.settings} status={data.server} invoke={act} disabled={inactive} openSettings={()=>nav('settings')}/>}
            {!serverMode&&<Panel className="conn-card">
              <div className="conn-head">
                <span className={'conn-dot is-'+connection.tone} aria-hidden="true"/>
                <div className="conn-copy"><h2>{connection.label}</h2><p>{connection.note}</p></div>
                <Tag kind={connection.tone==='ready'?'green':connection.tone==='offline'?'red':connection.tone==='attention'?'gold':'neutral'}>{connection.state}</Tag>
              </div>
              <dl className="conn-facts">
                <div><dt>Provider</dt><dd>{connection.provider}</dd></div>
                <div><dt>Model</dt><dd>{connection.model||'None selected'}</dd></div>
                {connection.endpoint&&<div><dt>Address</dt><dd>{connection.endpoint}</dd></div>}
              </dl>
              <div className="conn-actions">
                <button type="button" className="primary-button" disabled={modelChecking||inactive||!data.settings.model} onClick={()=>void testActualModel()}>{modelChecking?<LoaderCircle className="spin" size={16}/>:<Zap size={16}/>} {modelChecking?'Testing…':'Test connection'}</button>
                <button type="button" className="secondary-button" onClick={()=>nav('settings')}><Settings2 size={16}/> Connection settings</button>
              </div>
              {modelCheck&&<div className="health-result" role="status"><Check size={16}/><span>{modelCheck.sample}</span></div>}
            </Panel>}
            <LocalBrainFallback optional={serverMode}>
            <Panel className="conn-card conn-local">
              <h2>Model on this PC</h2>
              <p>{data.brain_running?'The local engine is running on this PC.':data.brain_installed?'A local model is installed but not started.':'No local model is installed. Installing downloads a verified model of a few gigabytes.'}</p>
              {!data.brain_running&&<button type="button" className="secondary-button" disabled={brainProgress!==null||inactive} onClick={()=>void act(data.brain_installed?'startBrain':'installBrain')}>{brainProgress?<LoaderCircle className="spin" size={16}/>:<Download size={16}/>} {brainProgress?'Preparing the local model…':data.brain_installed?'Start local model':'Download and start'}</button>}
              {brainProgress&&<div className="brain-progress"><p>{brainProgress.phase}</p><div className="progress-track"><motion.div animate={{width:brainProgress.total?Math.max(2,brainProgress.downloaded/brainProgress.total*100)+'%':'9%'}} transition={reducedMotion?instant:{duration:.2}}/></div></div>}
            </Panel>
            </LocalBrainFallback>
            <section className="learn learn-brain" aria-label="What STAR learned"><div className="learn-head"><GraduationCap size={18} aria-hidden="true"/><div className="learn-title"><h2>What STAR learned</h2><p>This week’s lessons and your corrections are on the Projects page.</p></div><button type="button" className="learn-button" onClick={openLearned}>Open <ArrowRight size={14} aria-hidden="true"/></button></div></section>
          </div></div>}
          {tab==='tools'&&<div className="scroll-region"><div className="page-wrap"><PageTitle eyebrow="DEVELOPER WORKSPACE" title="Connect your tools" description="Give STAR only the project access it needs, then inspect and build with evidence."/><div className="two-up"><StudioConnectionPanel settings={data.settings} status={data.studio} invoke={act} onSaved={()=>void sync()} disabled={inactive||busy}/><Panel className="settings-section"><div className="tool-icon"><Folder size={22}/></div><h2>Local workspace</h2><p>STAR can inspect a selected folder, and edit files only when you enable workspace write permissions.</p><Tag>{data.settings.workspace||'Not connected'}</Tag><button className="secondary-button" onClick={()=>nav('settings')}>Configure folder <ArrowRight size={14}/></button></Panel></div>{clipsOn&&<><ClipPanel disabled={inactive}/><GameLabPanel disabled={inactive}/></>}<div className="intelligence-heading"><div><span className="eyebrow">PROJECT INTELLIGENCE</span><h2>Knowledge, context & expert workflows</h2><p>Read only the information needed for your task. Nothing below grants shell access or runs downloaded skills.</p></div></div>
            <div className="intelligence-grid">
              <Panel className="settings-section integration-panel">
                <div className="integration-head"><div className="tool-icon"><BookOpen size={22}/></div><Tag kind={data.intelligence?.obsidian.enabled?'green':'neutral'}>{data.intelligence?.obsidian.enabled?'Read-only connected':'Off'}</Tag></div>
                <h2>Obsidian</h2><p>Search and read your local Markdown notes, design decisions and project research. Your vault stays on your PC.</p>
                <button className="secondary-button" onClick={()=>nav('settings')}>Configure vault <ArrowRight size={14}/></button>
              </Panel>
              <Panel className="settings-section integration-panel">
                <div className="integration-head"><div className="tool-icon"><Workflow size={22}/></div><Tag kind={data.intelligence?.graphify.export_detected?'green':'neutral'}>{data.intelligence?.graphify.export_detected?'Export detected':'No graph loaded'}</Tag></div>
                <h2>Graphify</h2><p>Trace the relationships between code, systems and dependencies from a generated <code>graphify-out/graph.json</code> file in your selected workspace.</p>
                <button className="secondary-button" onClick={()=>nav('settings')}>Project configuration <ArrowRight size={14}/></button>
              </Panel>
              <Panel className="settings-section integration-panel">
                <div className="integration-head"><div className="tool-icon"><BrainCircuit size={22}/></div><Tag kind={data.intelligence?.skills.enabled?'green':'neutral'}>{data.intelligence?.skills.enabled?'Available':'Off'}</Tag></div>
                <h2>Agent Skills</h2><p>{data.intelligence?.skills.count??0} local workflows discovered. STAR can load only the relevant instructions and references when a task requires them.</p>
                <button className="secondary-button" onClick={()=>nav('library')}>View knowledge library <ArrowRight size={14}/></button>
              </Panel>
            </div>
            <ResearchWatchPanel disabled={inactive||busy}
              autoCheck={!!data.settings.research_auto_check}
              onAutoChange={enabled=>{void (async()=>{
                const result=await act('saveSettings',{settings:{research_auto_check:enabled}})
                if(result)await sync()
              })()}}/>
            <Panel className="settings-section"><h2><Shield size={18}/> Scoped access</h2><p>GitHub updates and model downloads never require your AI to see your private credentials. Publishing and unrestricted PC control are not enabled by default.</p><div className="toggle-line"><span>Studio edits</span><Tag kind={data.settings.studio_edit?'gold':'neutral'}>{data.settings.studio_edit?'Enabled':'Read only'}</Tag></div><div className="toggle-line"><span>Workspace writes</span><Tag kind={data.settings.workspace_edit?'gold':'neutral'}>{data.settings.workspace_edit?'Enabled':'Read only'}</Tag></div></Panel><BlenderPanel draft={draft} onChange={setDraft} status={data.blender} invoke={act} disabled={inactive||busy}/><McpPanel draft={draft} onChange={setDraft} status={data.mcp} invoke={act} disabled={inactive}/>
           <ReviewToolsPanel settings={draft} onChange={setDraft} status={data.tool_workshop} recipes={customTools} query={customQuery} onQuery={setCustomQuery} preview={customPreview} busy={customBusy} disabled={inactive} refresh={refreshCustomTools} runPreview={id=>customAction('previewCustomTool',id)} approve={id=>customAction('approveCustomTool',id)} disable={id=>customAction('disableCustomTool',id)}/><button type="button" className="secondary-button" disabled={inactive} onClick={()=>void saveSettings()}><Check size={15}/> Save connector settings</button></div></div>}
         {tab==='library'&&<div className="scroll-region"><div className="page-wrap"><PageTitle eyebrow="PROJECT RESOURCES" title="Your library" description="Project references, verified decisions, conversation history, and generated files."/><div className="two-up"><Panel className="settings-section"><FolderOpen size={23} className="gold"/><h2>STAR data folder</h2><p>Local storage for saved conversations, checkpoints, images, and project knowledge.</p><button className="secondary-button" onClick={()=>void act('openDataFolder')}>Open local STAR files <ArrowRight size={15}/></button></Panel><Panel className="settings-section"><BookOpen size={23} className="gold"/><h2>Verified knowledge</h2><p>STAR only promotes reviewed, source-grounded knowledge into trusted project memory.</p><button className="secondary-button" onClick={()=>nav('projects')}>View projects <ArrowRight size={15}/></button></Panel></div><Panel className="settings-section"><h2>Created images & files</h2><p>Your generated images appear in the conversation where they were created. The originals are stored privately in your local STAR folder.</p><button type="button" className="secondary-button" onClick={()=>void act('openDataFolder')}><FolderOpen size={16}/> Open local files <ArrowRight size={15}/></button></Panel></div></div>}
         {tab==='settings'&&<div className="scroll-region"><div className="page-wrap settings-page"><SettingsPage data={data} draft={draft} setDraft={setDraft} act={act} sync={()=>void sync()} inactive={inactive} busy={busy} nav={nav} serverDraft={serverDraft}
           modelChecking={modelChecking} modelCheck={modelCheck} modelList={modelList} testActualModel={()=>void testActualModel()} routerBusy={routerBusy} teamChecking={teamChecking} teamResult={teamResult}
           selectRouterFolder={()=>void selectRouterFolder()} startLocalRouter={()=>void startLocalRouter()} stopLocalBrain={()=>void stopLocalBrain()} testSpecialists={()=>void testSpecialists()}
           imageMode={imageMode} chooseWorkflow={()=>void chooseWorkflow()} showStar={showStar} setShowStar={setShowStar} newHome={newHome} setNewHome={setNewHome} clipsOn={clipsOn} setClipsOn={setClipsOn} setReducedMotion={setReducedMotion}
           studioLayout={studioLayout} setStudioLayout={setStudioLayout}
           appearance={studioLayout&&<AppearanceControls preferences={appearance} onChange={updateAppearance} onReset={resetAppearance} companionSettings={companionSettings} persisted={appearancePersisted}/>}
           update={update} updateBusy={updateBusy} updateProgress={updateProgress} checkForUpdates={()=>void checkForUpdates()} installVerifiedUpdate={()=>void installVerifiedUpdate()} saveSettings={()=>void saveSettings()}
           initialSection={preview?new URLSearchParams(window.location.search).get('section')||undefined:undefined}/></div></div>}
       </MotionSurface>
     </AnimatePresence>
     <AnimatePresence>
       {pendingDelete&&<motion.div key={'undo-'+pendingDelete.id} role="status" className="undo-toast" initial={reducedMotion?false:{opacity:0,y:12,scale:.98}} animate={{opacity:1,y:0,scale:1}} exit={{opacity:0,y:8}} transition={reducedMotion?instant:{duration:.2,ease:[0.23,1,0.32,1]}}>
         <Trash2 size={15} aria-hidden="true"/><span title={pendingDelete.title}>Deleted <strong dir="auto">{pendingDelete.title}</strong></span>
         <button type="button" onClick={undoDelete}><Undo2 size={14} aria-hidden="true"/> Undo</button>
       </motion.div>}
     </AnimatePresence>
     <ScreenConsent open={screenAsk} busy={capturing} onCancel={()=>{if(!capturing)setScreenAsk(false)}} onConfirm={()=>{consentConfirmed.current=true;void lookAtScreen()}} onClosed={()=>{
       if(consentConfirmed.current)composerRef.current?.focus()
       else document.querySelector<HTMLButtonElement>('.cmp-icon-button[aria-label="Add files and tools"]')?.focus()
       consentConfirmed.current=false
     }}/>
     {notice&&<div role="status" className="toast" data-notice-region="page"><Info size={16} aria-hidden="true"/><span>{truncate(notice,240)}</span><button aria-label="Dismiss message" onClick={()=>setNotice('')}><X size={16}/></button></div>}
   </div>
   {tab==='chat'&&showStar&&<StarPet state={petState} reducedMotion={reducedMotion} idleEnabled={!inactive}/>}
   {leftOpen&&<button className="mobile-scrim" onClick={()=>setLeftOpen(false)} aria-label="Close navigation"/>}
 </div></MotionPolicy>
}
/** Page heading. The old uppercase eyebrow ("PREFERENCES", "DEVELOPER WORKSPACE") read as template chrome; it is kept
 * only as the accessible description's lead-in, not drawn. */
function PageTitle({title,description}:{eyebrow:string;title:string;description:string}) {return <div className="page-intro"><h1>{title}</h1><p>{description}</p></div>}
