/**
 * What STAR learned this week, and the owner's corrections that may become regression tests.
 *
 * Lessons here come from night school's reviewed bundle (star/learned_week.py). A text lesson goes
 * live only when it beat the current set on held-out practice (the paired gate); it stays for 14 days
 * unless the owner keeps it, and Undo stops it at once. Corrections (thumbs-down plus what was wrong,
 * or `wrong: ...` on Discord) wait here; only "Make it a test" adds one to the corrections suite
 * (star/corrections.py), which is never the blind exam. Every button is an explicit owner action.
 */
import {useCallback,useEffect,useState} from 'react'
import {Check,ClipboardList,FlaskConical,GraduationCap,LoaderCircle,RotateCcw,Undo2,X} from 'lucide-react'
import {Tag} from './components'
import {EmptyState,ErrorState,LoadingState} from './states'
import type {CorrectionItem,CorrectionListing,LearnedItem,LearnedWeek,SelfAuditReport} from './types'
import './learning.css'

type Invoke=(action:string,params?:Record<string,unknown>)=>Promise<unknown|null>

const kindNames:Record<LearnedItem['kind'],string>={lesson:'Lesson',example:'Checked example'}
const causeNames:Record<string,string>={
 'wrong logic':'wrong logic','required feature missing':'something was missing','self-check error left unrepaired':'an error was left in',
 'answer cut off':'the answer was cut off','invented API name':'a made-up or outdated API',
}
export function stateText(item:LearnedItem):string{
 if(item.state==='kept')return 'Kept for good'
 if(item.state==='undone')return 'Undone: STAR does not use it'
 if(item.state==='expired')return 'Its 14 days ended: STAR no longer uses it'
 const days=item.days_left??0
 return `In use · ${days===1?'1 day':days+' days'} left`
}
function gateText(item:LearnedItem):string{
 const g=item.gate||{}
 if(item.kind==='example')return 'Passed night school’s automated Luau checks (not a Roblox Studio test).'
 if(g.decision!=='PROMOTE')return ''
 return `Beat the current lessons on held-out practice: ${g.wins} wins, ${g.losses} losses over ${g.tasks} tasks (k=${g.k})${typeof g.p_better==='number'?`, p=${g.p_better}`:''}.`
}

export function LearnedThisWeek({invoke,disabled=false,project}:{invoke:Invoke;disabled?:boolean;project:string}){
 const [week,setWeek]=useState<LearnedWeek|null>(null)
 const [fixes,setFixes]=useState<CorrectionListing|null>(null)
 const [audit,setAudit]=useState<SelfAuditReport|null>(null)
 const [pending,setPending]=useState('')
 const [notice,setNotice]=useState('')
 // First read: '' until it answers, then 'ok' or 'failed' (a failed read is not "nothing learned").
 const [read,setRead]=useState<''|'ok'|'failed'>('')
 const load=useCallback(async()=>{
   if(disabled)return
   const found=await invoke('learnedThisWeek') as LearnedWeek|null
   if(found&&Array.isArray(found.items))setWeek(found)
   setRead(current=>found&&Array.isArray(found.items)?'ok':current==='ok'?'ok':'failed')
   const listed=await invoke('listCorrections') as CorrectionListing|null
   if(listed&&Array.isArray(listed.corrections))setFixes(listed)
   const audited=await invoke('selfAudit') as {report?:SelfAuditReport|null}|null
   if(audited?.report&&Array.isArray(audited.report.strengths))setAudit(audited.report)
 },[disabled,invoke])
 useEffect(()=>{void load()},[load,project])
 const change=async(op:'undo'|'restore'|'keep',item:LearnedItem)=>{
   if(disabled||pending)return
   setPending(op+':'+item.id);setNotice('')
   try{
     // `approved` is this click; the host refuses an undo, restore or keep without it.
     const done=await invoke('learnedItem',{op,id:item.id,approved:true}) as LearnedWeek|null
     if(done&&Array.isArray(done.items)){
       setWeek(done)
       setNotice({undo:'Undone. STAR stopped using it.',restore:'Restored exactly as it was.',keep:'Kept for good. It no longer expires.'}[op])
     }
   }finally{setPending('')}
 }
 const review=async(op:'approve'|'dismiss',item:CorrectionItem)=>{
   if(disabled||pending)return
   setPending('fix-'+op+':'+item.id);setNotice('')
   try{
     const done=await invoke('reviewCorrection',{op,id:item.id,approved:true}) as CorrectionListing|null
     if(done&&Array.isArray(done.corrections)){
       setFixes(done)
       setNotice(op==='approve'?`Added to the corrections suite (${done.suite}). It is a development test, never the blind exam.`:'Dismissed.')
     }
   }finally{setPending('')}
 }
 const items=week?.items??[]
 const waiting=(fixes?.corrections??[]).filter(c=>c.status==='candidate')
 const tested=(fixes?.corrections??[]).filter(c=>c.status==='approved').slice(0,5)
 return <section className="learn-week" aria-label="What STAR learned this week">
   <div className="learn-head">
     <GraduationCap size={18} aria-hidden="true"/>
     <div className="learn-title"><h3>What STAR learned this week</h3><p>From night school’s reviewed bundle. A text lesson is used only after it beat the current lessons on held-out practice; it stays for 14 days unless you keep it. Undo stops it at once.</p></div>
     <Tag kind={items.some(i=>i.state==='live')?'gold':'neutral'}>{items.filter(i=>i.state==='live').length} in use</Tag>
   </div>
   {items.length===0?(disabled?<EmptyState compact title="Open STAR Desktop to see what it learned."/>
     :read===''?<LoadingState compact label="Loading what STAR learned this week" lines={2}/>
     :read==='failed'?<ErrorState compact title="This week's lessons could not be loaded." description="STAR Desktop did not answer. Try again in a moment." action={<button type="button" className="learn-button" onClick={()=>void load()}>Try again</button>}/>
     :<EmptyState compact title="Nothing new this week." description="When night school learns something that passes its checks, it appears here with its evidence."/>)
   :<ul className="learn-list">{items.map(item=>{
     const busy=pending.endsWith(':'+item.id)&&!pending.startsWith('fix-')
     return <li key={item.id} className="lesson learned-item">
       <div className="lesson-top"><span className="lesson-kind">{kindNames[item.kind]}</span><span className="lesson-origin">{stateText(item)}{item.uses?` · sent with ${item.uses} ${item.uses===1?'answer':'answers'}`:''}</span></div>
       <p className="lesson-text">{item.title}</p>
       {gateText(item)&&<p className="learn-help">{gateText(item)}</p>}
       {item.evidence&&<details className="lesson-evidence"><summary>Evidence</summary><p>{item.evidence}</p></details>}
       <div className="lesson-actions">
         {item.state==='live'&&<button type="button" className="learn-button" disabled={busy||disabled} onClick={()=>void change('undo',item)}>{busy?<LoaderCircle className="spin" size={14}/>:<Undo2 size={14} aria-hidden="true"/>} Undo</button>}
         {item.state==='undone'&&(item.days_left??0)>0&&<button type="button" className="learn-button" disabled={busy||disabled} onClick={()=>void change('restore',item)}><RotateCcw size={14} aria-hidden="true"/> Restore</button>}
         {item.state!=='kept'&&<button type="button" className="learn-button is-primary" disabled={busy||disabled} onClick={()=>void change('keep',item)}><Check size={14} aria-hidden="true"/> Keep for good</button>}
       </div>
     </li>})}</ul>}
   <div className="learn-head learn-subhead">
     <FlaskConical size={18} aria-hidden="true"/>
     <div className="learn-title"><h3>Your corrections</h3><p>When you mark an answer as not helpful and say what was wrong (here or with <code>wrong: …</code> on Discord), STAR keeps the question, its answer and your words. Make it a test to add it to the corrections suite; nothing is added without you.</p></div>
     <Tag kind={waiting.length?'gold':'neutral'}>{waiting.length} waiting</Tag>
   </div>
   {waiting.length===0?(read==='ok'||disabled?<EmptyState compact title="No corrections are waiting."/>:null)
   :<ul className="learn-list">{waiting.map(item=>{
     const busy=pending.endsWith(':'+item.id)&&pending.startsWith('fix-')
     return <li key={item.id} className="lesson correction-item">
       <div className="lesson-top"><span className="lesson-kind">{item.source==='discord'?'From Discord':'From a chat'}</span><span className="lesson-origin">Looks like {causeNames[item.cause]||item.cause}</span></div>
       <p className="lesson-text">{item.correction}</p>
       <details className="lesson-evidence"><summary>Question and STAR’s answer</summary><p>{item.prompt}</p><p>{item.answer}</p></details>
       <div className="lesson-actions">
         <button type="button" className="learn-button is-primary" disabled={busy||disabled} onClick={()=>void review('approve',item)}>{busy?<LoaderCircle className="spin" size={14}/>:<FlaskConical size={14} aria-hidden="true"/>} Make it a test</button>
         <button type="button" className="learn-button" disabled={busy||disabled} onClick={()=>void review('dismiss',item)}><X size={14} aria-hidden="true"/> Dismiss</button>
       </div>
     </li>})}</ul>}
   {tested.length>0&&<p className="learn-help">In the corrections suite: {tested.map(c=>c.task_id).join(', ')}{fixes?.counts?.approved&&fixes.counts.approved>tested.length?` and ${fixes.counts.approved-tested.length} more`:''}.</p>}
   {audit&&<>
     <div className="learn-head learn-subhead">
       <ClipboardList size={18} aria-hidden="true"/>
       <div className="learn-title"><h3>STAR’s weekly self-audit</h3><p>Measured from stored eval results, practice mistakes, lessons and what STAR did not know. No model was asked. Written {audit.generated.slice(0,10)}; a new one follows every 7 days.</p></div>
     </div>
     <div className="learn-audit">
       <h4>Strengths</h4>
       {audit.strengths.length?<ul>{audit.strengths.slice(0,6).map(t=><li key={t}>{t}</li>)}</ul>:<p className="learn-help">None measured yet.</p>}
       <h4>Weaknesses</h4>
       {audit.weaknesses.length?<ul>{audit.weaknesses.slice(0,6).map(t=><li key={t}>{t}</li>)}</ul>:<p className="learn-help">None measured.</p>}
       {(audit.missing?.length??0)>0&&<p className="learn-help">No data on this PC for: {audit.missing!.join(', ')}.</p>}
     </div>
   </>}
   {notice&&<p className="learn-notice" role="status">{notice}</p>}
 </section>
}
