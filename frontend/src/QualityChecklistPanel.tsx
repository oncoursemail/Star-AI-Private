/**
 * Read-only human-quality workbench. It never offers a "pass this check"
 * button: real native receipts and owner approvals must come from a trusted
 * verifier, not a React payload or a generated checklist.
 */
import {useCallback,useEffect,useState} from 'react'
import {Check,FileCheck2,FolderOpen,RefreshCw,ShieldCheck,TriangleAlert} from 'lucide-react'
import {request} from './bridge'
import './quality-checklist.css'

type Kind='software'|'interface'|'animation'|'game'|'music'|'research'
type FileInfo={name:string;bytes:number;artifact_sha256:string;syntax:{status:string;kind:string;note:string;line?:number|null}}
type CheckItem={id:string;category?:string;critical?:boolean;state?:string;native_required?:boolean;owner_review?:boolean;accepted_kinds?:string[]}
type NextAction={criterion_id:string;action:string;next_attempt:number|null}
type QualityReport={
 selected:boolean;category:Kind;artifact?:FileInfo;state:string;checks_total?:number;checks_passed?:number;
 criteria?:CheckItem[];requirements?:CheckItem[];next_actions?:NextAction[];note:string
}
const KINDS:ReadonlyArray<{id:Kind;label:string}>=[
 {id:'software',label:'Code & functionality'},
 {id:'interface',label:'UI & visual quality'},
 {id:'game',label:'Gameplay'},
 {id:'animation',label:'Animation'},
 {id:'music',label:'Music & audio'},
 {id:'research',label:'Research accuracy'},
]
function showAction(action:string):string{
 if(action==='run_independent_evidence_check')return 'Run independent test'
 if(action==='request_owner_review')return 'Request human review'
 if(action==='repair_then_retest')return 'Repair and retest'
 if(action==='escalate_to_owner')return 'Needs manual intervention'
 return action.replace(/_/g,' ')
}

export function QualityChecklistPanel({disabled=false}:{disabled?:boolean}){
 const [kind,setKind]=useState<Kind>('interface')
 const [report,setReport]=useState<QualityReport|null>(null)
 const [busy,setBusy]=useState(false)
 const [error,setError]=useState('')
 const [notice,setNotice]=useState('')
 const reload=useCallback(async(category:Kind)=>{
   if(disabled)return
   const reply=await request<QualityReport>('qualityPreview',{kind:category})
   if(reply.ok&&reply.data)setReport(reply.data)
   else setError(reply.error||'Could not load the quality checklist.')
 },[disabled])
 useEffect(()=>{void reload(kind)},[reload,kind])

 async function choose(){
   if(disabled||busy)return
   setBusy(true);setError('');setNotice('')
   const selected=await request<FileInfo&{cancelled?:boolean}>('qualityChooseFile')
   setBusy(false)
   if(!selected.ok){setError(selected.error||'Could not inspect artifact.');return}
   if(selected.data?.cancelled)return
   if(selected.data?.artifact_sha256){setNotice('Artifact content hashed locally. No code was executed or approved.');await reload(kind)}
 }
 async function clear(){
   if(disabled||busy)return
   setBusy(true)
   const r=await request('qualityClear')
   setBusy(false)
   if(r.ok){setReport(null);setNotice('Selected quality artifact cleared.');await reload(kind)}
   else setError(r.error||'Could not clear the artifact.')
 }

 const rows=report?.criteria??report?.requirements??[]
 return <section className="quality-panel" aria-label="STAR human-quality review">
   <div className="quality-heading">
     <div className="quality-mark"><ShieldCheck size={20} aria-hidden="true"/></div>
     <div><h2>Quality verification</h2><p>Evidence-first review: functionality, visual states, playtesting, safety, and your approval.</p></div>
   </div>
   <div className="quality-controls">
     <label>What are you checking?
       <select value={kind} disabled={disabled||busy} onChange={e=>{setKind(e.target.value as Kind);setError('')}}>
         {KINDS.map(x=><option value={x.id} key={x.id}>{x.label}</option>)}
       </select>
     </label>
     <button type="button" className="quality-button" disabled={disabled||busy} onClick={()=>void choose()}><FolderOpen size={15}/> Choose local artifact</button>
     <button type="button" className="quality-icon" disabled={disabled||busy} aria-label="Refresh quality checklist" onClick={()=>void reload(kind)}><RefreshCw size={15}/></button>
   </div>
   {report?.artifact&&<div className="quality-artifact">
     <FileCheck2 size={17} aria-hidden="true"/><div><strong title={report.artifact.name}>{report.artifact.name}</strong>
     <small>SHA-256 {report.artifact.artifact_sha256.slice(0,12)}… · {Math.ceil(report.artifact.bytes/1024)} KB</small>
     <span>{report.artifact.syntax.status==='failed'?'Static syntax failed':report.artifact.syntax.status==='passed_static_only'?'Static syntax parsed; execution unverified':'Native tools have not checked this file type'}</span></div>
     <button aria-label="Clear quality artifact" disabled={disabled||busy} type="button" onClick={()=>void clear()}>Clear</button>
   </div>}
   <div className="quality-summary">
     <span><TriangleAlert size={15} aria-hidden="true"/> {report?.state==='unverified'?'No artifact selected':(report?.state||'Not loaded').replace(/_/g,' ')}</span>
     <strong>{report?.checks_passed??0} / {report?.checks_total??rows.length} evidenced</strong>
   </div>
   <ol className="quality-items">
     {rows.map(check=><li key={check.id}><span className="quality-item-mark">{check.state==='passed'?<Check size={13}/>:<span aria-hidden="true">·</span>}</span>
       <span><strong>{check.id.replace(/_/g,' ')}</strong><small>
         {check.state?check.state.replace(/_/g,' '):'Evidence required'}
         {check.native_required?' · Native test required':''}
         {check.owner_review?' · Human approval required':''}
       </small></span></li>)}
   </ol>
   {(report?.next_actions?.length??0)>0&&<details className="quality-next"><summary>Next verification steps</summary>
     <ul>{report?.next_actions?.map(action=><li key={action.criterion_id}>{action.criterion_id.replace(/_/g,' ')} — {showAction(action.action)}</li>)}</ul>
   </details>}
   {notice&&<p className="quality-notice" role="status">{notice}</p>}
   {error&&<p className="quality-error" role="alert">{error}</p>}
   <p className="quality-footnote">This checklist is a plan, not a pass certificate. STAR cannot self-approve an artifact: actual logs, screenshots, native tests, independent checks, and owner judgments remain separate evidence.</p>
 </section>
}
