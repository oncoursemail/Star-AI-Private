import {useCallback,useEffect,useRef,useState} from 'react'
import {Layers,LoaderCircle,Plus,RefreshCcw,Send,Square,Trash2,Undo2} from 'lucide-react'
import {onBackendEvent,request,type BackendReply} from './bridge'
import {Tag} from './components'
import './bulk-tasks.css'

export type BulkTarget = {
  id:string;name:string;project:string;workspace:string;provider:string;model:string;endpoint:string
  can_prompt:boolean;can_edit:boolean;credential_ready:boolean
}
export type BulkCatalog = {enabled:boolean;targets:BulkTarget[];max_targets:number}
type BulkFile = {
  path:string;diff:string;before_sha256:string;after_sha256:string
  diff_truncated?:boolean;replacements?:number;match_strategy?:string
}
type BulkPreview = {title:string;items:Array<{target_id:string;label:string;files?:BulkFile[];prompt_chars?:number}>}
type BulkOperation = {operation_id:string;target_id:string;status:string;result?:unknown;error?:unknown}
export type BulkBatch = {
  batch_id:string;intent_sha256:string;action:string;status:string;cancellation_requested:boolean
  targets:string[];operations:BulkOperation[];preview?:BulkPreview;created_at?:number;updated_at?:number
}
export type BulkSummary = Pick<BulkBatch,'batch_id'|'action'|'status'|'cancellation_requested'|'created_at'|'updated_at'>&{counts?:Record<string,number>}
type TaskKind = 'brain_prompt'|'workspace_edit'
type Pending = {finish:(reply:BackendReply<unknown>)=>void;timer?:number}

const labels:Record<string,string> = {
  prepared:'Ready for review',running:'Running',succeeded:'Succeeded',partial:'Partially completed',
  failed:'Failed',cancelled:'Cancelled',expired:'Expired',stopped:'Stopped',outcome_unknown:'Outcome unknown',
  pending:'Pending',accepted:'Accepted',conflict:'Conflict',skipped:'Skipped',
}
const actionLabel=(value:string)=>value==='brain_prompt'?'Brain prompt':value==='workspace_edit'?'Workspace edit':value==='workspace_undo'?'Workspace undo':value
const statusLabel=(value:string)=>labels[value]||value
const statusKind=(value:string):'green'|'red'|'gold'|'neutral'=>value==='succeeded'?'green':['failed','conflict','outcome_unknown'].includes(value)?'red':['running','partial','stopped'].includes(value)?'gold':'neutral'
const isBatch=(value:unknown):value is BulkBatch=>!!value&&typeof value==='object'&&
  typeof (value as BulkBatch).batch_id==='string'&&typeof (value as BulkBatch).intent_sha256==='string'&&
  typeof (value as BulkBatch).status==='string'&&Array.isArray((value as BulkBatch).targets)&&Array.isArray((value as BulkBatch).operations)
const outputText=(value:unknown):string=>typeof value==='string'?value:JSON.stringify(value,null,2)??''
const integerIn=(value:string,max:number)=>/^\d+$/.test(value)&&Number(value)>=1&&Number(value)<=max
const matchLabels:Record<string,string>={exact:'Exact text match',line_endings:'Line endings normalized',whitespace:'Whitespace normalized'}
const canUndo=(value:BulkBatch|null)=>value?.action==='workspace_edit'&&
  ['succeeded','partial','failed','cancelled','expired','stopped','outcome_unknown'].includes(value.status)&&
  value.operations.some(operation=>operation.status==='succeeded')

/** Native state owns targets, previews and execution. Leaving this page never resends a batch. */
export function BulkTasksPanel({disabled=false}:{disabled?:boolean}) {
  const [catalog,setCatalog]=useState<BulkCatalog|null>(null)
  const [history,setHistory]=useState<BulkSummary[]>([])
  const [selected,setSelected]=useState<string[]>([])
  const [kind,setKind]=useState<TaskKind>('brain_prompt')
  const [prompt,setPrompt]=useState('')
  const [paths,setPaths]=useState('')
  const [oldString,setOldString]=useState('')
  const [newString,setNewString]=useState('')
  const [replaceAll,setReplaceAll]=useState(false)
  const [concurrency,setConcurrency]=useState('1')
  const [canarySize,setCanarySize]=useState('1')
  const [failureCutoff,setFailureCutoff]=useState('1')
  const [name,setName]=useState('')
  const [allowEdit,setAllowEdit]=useState(false)
  const [review,setReview]=useState<BulkBatch|null>(null)
  const [reviewPrompt,setReviewPrompt]=useState('')
  const [reviewContextPaths,setReviewContextPaths]=useState<string[]>([])
  const [batch,setBatch]=useState<BulkBatch|null>(null)
  const [busy,setBusy]=useState('')
  const [message,setMessage]=useState('')
  const [pollMessage,setPollMessage]=useState('')
  const [pollVersion,setPollVersion]=useState(0)
  const pending=useRef(new Map<string,Pending>())
  const lifecycle=useRef(0)
  const inactive=useRef(disabled)
  inactive.current=disabled
  const revision=useRef(0)
  const idempotencyKey=useRef('')
  const reviewRef=useRef<BulkBatch|null>(null)
  const viewedId=useRef('')
  const current=(generation:number)=>generation===lifecycle.current&&!inactive.current

  useEffect(()=>{
    lifecycle.current++
    const stop=onBackendEvent(event=>{
      if(event.kind!=='result'&&event.kind!=='error')return
      pending.current.get(event.requestId)?.finish(event.kind==='result'?{ok:true,data:event.data}:
        {ok:false,error:typeof event.data==='string'?event.data:'The bulk task request failed.'})
    })
    const waiting=pending.current
    return ()=>{
      lifecycle.current++
      stop()
      waiting.forEach(entry=>entry.finish({ok:false,error:'The panel was closed. Check saved batches when you return.'}))
    }
  },[])

  // Subscribe before invoking: a native worker can finish before its pending reply arrives.
  const invoke=useCallback(<T,>(action:string,payload:Record<string,unknown>={}):Promise<BackendReply<T>>=>{
    if(inactive.current)return Promise.resolve({ok:false,error:'Open STAR Desktop to use bulk tasks.'})
    const id=crypto.randomUUID()
    return new Promise(resolve=>{
      let settled=false
      const entry:Pending={finish:reply=>{
        if(settled)return
        settled=true
        window.clearTimeout(entry.timer)
        pending.current.delete(id)
        resolve(reply as BackendReply<T>)
      }}
      pending.current.set(id,entry)
      void request<T>(action,payload,id).then(reply=>{
        if(settled)return
        if(!reply.ok||!reply.pending)entry.finish(reply)
        else entry.timer=window.setTimeout(()=>entry.finish({ok:false,error:'The host has not confirmed this request. Refresh saved batch status before trying again.'}),120000)
      }).catch(()=>entry.finish({ok:false,error:'The bulk task request could not be confirmed.'}))
    })
  },[])

  const showBatch=useCallback(async(batchId:string)=>{
    const generation=lifecycle.current
    viewedId.current=batchId
    reviewRef.current=null;setReview(null)
    setBatch(null);setPollMessage('')
    const reply=await invoke<BulkBatch>('bulkTaskStatus',{batchId})
    if(generation!==lifecycle.current||inactive.current||viewedId.current!==batchId)return
    if(reply.ok&&isBatch(reply.data)&&reply.data.batch_id===batchId)setBatch(reply.data)
    else setPollMessage(reply.error||'This batch could not be loaded. Refresh its saved status.')
  },[invoke])

  const loadCatalog=useCallback(async()=>{
    const generation=lifecycle.current
    const reply=await invoke<BulkCatalog>('bulkTaskCatalog')
    if(generation!==lifecycle.current||inactive.current)return
    if(reply.ok&&reply.data&&typeof reply.data.enabled==='boolean'&&Array.isArray(reply.data.targets))setCatalog(reply.data)
    else setMessage(reply.error||'Bulk tasks are not available on this desktop yet.')
  },[invoke])

  const loadHistory=useCallback(async(restore=false)=>{
    const generation=lifecycle.current
    const reply=await invoke<{batches:BulkSummary[]}>('bulkTaskList')
    if(generation!==lifecycle.current||inactive.current)return
    if(reply.ok&&reply.data&&Array.isArray(reply.data.batches)){
      setHistory(reply.data.batches)
      const latest=reply.data.batches.find(item=>item.status==='running')||reply.data.batches[0]
      if(restore&&!viewedId.current&&latest)void showBatch(latest.batch_id)
    }else setMessage(reply.error||'Saved bulk task history could not be loaded.')
  },[invoke,showBatch])

  useEffect(()=>{
    if(disabled)return
    void loadCatalog()
    void loadHistory(true)
  },[disabled,loadCatalog,loadHistory])

  // Only the displayed running batch is polled, without overlapping requests. Stop after five minutes or an error.
  useEffect(()=>{
    if(disabled||busy||batch?.status!=='running')return
    const batchId=batch.batch_id
    let live=true,attempts=0
    let timer:number
    const poll=async()=>{
      const reply=await invoke<BulkBatch>('bulkTaskStatus',{batchId})
      if(!live||viewedId.current!==batchId)return
      if(!reply.ok||!isBatch(reply.data)||reply.data.batch_id!==batchId){
        setPollMessage(reply.error||'Automatic updates paused. Refresh this batch for its latest status.')
        return
      }
      setBatch(reply.data)
      if(reply.data.status!=='running'){void loadHistory();return}
      if(++attempts>=150){setPollMessage('Automatic updates paused after five minutes. Refresh this batch for its latest status.');return}
      timer=window.setTimeout(()=>void poll(),2000)
    }
    timer=window.setTimeout(()=>void poll(),2000)
    return ()=>{live=false;window.clearTimeout(timer)}
  },[disabled,busy,batch?.batch_id,batch?.status,pollVersion,invoke,loadHistory])

  const invalidate=()=>{
    revision.current++
    idempotencyKey.current=''
    if(reviewRef.current)setMessage('The task changed. Create a new preview before sending.')
    reviewRef.current=null;setReview(null)
  }
  const enabled=catalog?.enabled===true
  const locked=disabled||!enabled
  const targets=catalog?.targets||[]
  const eligible=(target:BulkTarget)=>kind==='brain_prompt'?target.can_prompt&&target.credential_ready:target.can_edit&&!!target.workspace
  const chosen=selected.map(id=>targets.find(target=>target.id===id))
  const filePaths=paths.split(/\r?\n/).map(path=>path.trim()).filter(Boolean)
  const validTargets=selected.length>0&&selected.length<=Math.min(catalog?.max_targets||32,32)&&chosen.every(target=>target&&eligible(target))
  const validPaths=filePaths.length<=16&&new Set(filePaths).size===filePaths.length&&filePaths.every(path=>path.length<=500)
  const validTask=validPaths&&(kind==='brain_prompt'?!!prompt.trim()&&prompt.length<=5000:
    filePaths.length>0&&!!oldString&&oldString.length<=12000&&newString.length<=12000)
  const validLimits=integerIn(concurrency,4)&&integerIn(canarySize,selected.length)&&integerIn(failureCutoff,selected.length)
  const canPreview=!locked&&!busy&&validTargets&&validTask&&validLimits

  const setEnabled=async(value:boolean)=>{
    if(disabled||busy)return
    const generation=lifecycle.current
    invalidate();setBusy('enable');setMessage('')
    const reply=await invoke('bulkTaskSetEnabled',{enabled:value})
    if(!current(generation))return
    if(reply.ok){setSelected([]);await loadCatalog()}
    else setMessage(reply.error||'The bulk task setting could not be changed.')
    if(current(generation))setBusy('')
  }
  const capture=async()=>{
    if(locked||busy||!name.trim())return
    const generation=lifecycle.current
    invalidate();setBusy('capture');setMessage('')
    const reply=await invoke('bulkTaskCapture',{name:name.trim(),allow_edit:allowEdit})
    if(!current(generation))return
    if(reply.ok){setName('');setAllowEdit(false);await loadCatalog();if(current(generation))setMessage('Target saved. Select it below when you are ready.')}
    else setMessage(reply.error||'The current configuration could not be saved as a target.')
    if(current(generation))setBusy('')
  }
  const remove=async(targetId:string)=>{
    if(locked||busy)return
    const generation=lifecycle.current
    invalidate();setBusy('remove');setMessage('')
    const reply=await invoke('bulkTaskRemove',{targetId})
    if(!current(generation))return
    if(reply.ok){setSelected(ids=>ids.filter(id=>id!==targetId));await loadCatalog()}
    else setMessage(reply.error||'The target could not be removed.')
    if(current(generation))setBusy('')
  }
  const prepare=async()=>{
    if(!canPreview)return
    const generation=lifecycle.current,draftRevision=revision.current
    if(!idempotencyKey.current)idempotencyKey.current=crypto.randomUUID()
    reviewRef.current=null;setReview(null);setBusy('preview');setMessage('Preparing the selected targets…')
    const reply=await invoke<BulkBatch>('bulkTaskPreview',{
      kind,targetIds:[...selected],concurrency:Number(concurrency),canarySize:Number(canarySize),
      failureCutoff:Number(failureCutoff),idempotencyKey:idempotencyKey.current,
      ...(kind==='brain_prompt'?{prompt,...(filePaths.length?{paths:filePaths}:{})}:{paths:filePaths,oldString,newString,replaceAll}),
    })
    if(!current(generation))return
    setBusy('')
    if(draftRevision!==revision.current){setMessage('The task changed while the preview was prepared. Create a new preview.');return}
    if(reply.ok&&isBatch(reply.data)&&reply.data.status==='prepared'&&reply.data.preview){
      reviewRef.current=reply.data;setReview(reply.data);setReviewPrompt(kind==='brain_prompt'?prompt:'')
      setReviewContextPaths(kind==='brain_prompt'?filePaths:[])
      setMessage('Review the selected targets and displayed content below. Nothing has been sent.')
      void loadHistory()
    }else setMessage(reply.error||'The host did not return a sendable preview. No batch was sent.')
  }
  const send=async()=>{
    const prepared=reviewRef.current
    if(locked||busy||!prepared||prepared.status!=='prepared')return
    const generation=lifecycle.current
    // A lost acknowledgement must lead to status reconciliation, never another automatic send.
    reviewRef.current=null;setReview(null);setBusy('send');setMessage('Waiting for the host to acknowledge this batch…')
    viewedId.current=prepared.batch_id;setBatch(prepared);setPollMessage('')
    const reply=await invoke<BulkBatch>('bulkTaskSend',{batchId:prepared.batch_id,intentHash:prepared.intent_sha256})
    if(!current(generation))return
    if(reply.ok&&isBatch(reply.data)&&reply.data.batch_id===prepared.batch_id){
      setBatch(reply.data);setMessage(reply.data.status==='prepared'?'The host has not started this batch. Refresh its saved status.':'The host recorded this batch. Follow each target’s result below.')
    }else setMessage((reply.error||'The send was not confirmed.')+' Refresh this batch before attempting another send.')
    setBusy('');void loadHistory()
  }
  const refreshBatch=async()=>{
    const batchId=viewedId.current
    if(disabled||busy||!batchId)return
    const generation=lifecycle.current
    setBusy('status');setPollMessage('')
    const reply=await invoke<BulkBatch>('bulkTaskStatus',{batchId})
    if(!current(generation)||viewedId.current!==batchId)return
    if(reply.ok&&isBatch(reply.data)&&reply.data.batch_id===batchId){setBatch(reply.data);setPollVersion(value=>value+1)}
    else setPollMessage(reply.error||'The batch status could not be confirmed.')
    setBusy('')
  }
  const cancel=async()=>{
    if(disabled||busy||batch?.status!=='running'||batch.cancellation_requested)return
    const generation=lifecycle.current,batchId=batch.batch_id
    setBusy('cancel');setMessage('Requesting cancellation…')
    const reply=await invoke<BulkBatch>('bulkTaskCancel',{batchId})
    if(!current(generation))return
    if(reply.ok&&isBatch(reply.data)&&reply.data.batch_id===viewedId.current){setBatch(reply.data);setMessage('Cancellation response received. Completed changes are still recorded below.')}
    else setMessage(reply.error||'Cancellation was not confirmed. Refresh this batch.')
    setBusy('');void loadHistory()
  }
  const prepareUndo=async()=>{
    if(locked||busy||!batch||!canUndo(batch))return
    const generation=lifecycle.current
    invalidate()
    const draftRevision=revision.current
    setBusy('undo');setMessage('Preparing an undo preview…')
    const reply=await invoke<BulkBatch>('bulkTaskUndoPreview',{batchId:batch.batch_id})
    if(!current(generation))return
    setBusy('')
    if(draftRevision!==revision.current){setMessage('The task changed. Request the undo preview again.');return}
    if(reply.ok&&isBatch(reply.data)&&reply.data.action==='workspace_undo'&&reply.data.status==='prepared'&&reply.data.preview){
      reviewRef.current=reply.data;setReview(reply.data);setReviewPrompt('');setReviewContextPaths([]);setMessage('Review the undo changes before applying them.')
    }else setMessage(reply.error||'An undo preview could not be prepared.')
  }

  const renderPreview=(value:BulkBatch)=><div className="bulk-preview-content">
    <p>{value.targets.length} target{value.targets.length===1?'':'s'} · {actionLabel(value.action)}</p>
    {value.preview?.items.map(item=><section className="bulk-preview-target" key={item.target_id} aria-label={'Preview '+item.label}>
      <h4>{item.label}</h4>
      {item.prompt_chars!==undefined&&<p>{item.prompt_chars} prompt characters</p>}
      {item.files?.map(file=><details key={file.path} open><summary>{file.path}</summary>
        {(file.replacements!==undefined||file.match_strategy)&&<p className="bulk-help">{file.replacements!==undefined&&<>{file.replacements} replacement{file.replacements===1?'':'s'}</>}{file.replacements!==undefined&&file.match_strategy&&' · '}{file.match_strategy&&(matchLabels[file.match_strategy]||file.match_strategy)}</p>}
        {file.diff_truncated&&<p className="bulk-warning">Diff truncated: only part of this file’s changes is shown. Inspect the file or narrow the edit before sending.</p>}
        <pre tabIndex={0} aria-label={'Changes to '+file.path}>{file.diff||(file.diff_truncated?'No diff text fits in this preview.':'No text difference.')}</pre>
      </details>)}
    </section>)}
  </div>

  return <section className="panel settings-section bulk-tasks" aria-label="Bulk tasks">
    <div className="bulk-heading"><Layers size={20} aria-hidden="true"/><div><h2>Bulk tasks</h2><p>Send a prompt to saved brains or review the same text edit across selected workspaces.</p></div><Tag kind={enabled?'gold':'neutral'}>{enabled?'On':'Off'}</Tag></div>
    <label className="bulk-check"><input type="checkbox" checked={enabled} disabled={disabled||!catalog||!!busy} onChange={event=>void setEnabled(event.target.checked)}/> Enable bulk tasks</label>
    {disabled?<p className="bulk-help">Open STAR Desktop to configure targets and send tasks.</p>:!enabled&&<p className="bulk-help">Enable this when you want to prepare a batch. Each send requires a reviewed preview and explicit target selection.</p>}
    <details className="bulk-capture" open={targets.length===0?true:undefined}>
      <summary>Save the current brain and workspace as a target</summary>
      <p className="bulk-help">Choose the project, model connection and workspace in existing Settings, then capture that configuration here. Configure another connection in Settings to add another target. Saved server credentials stay with their captured target when Settings changes.</p>
      <div className="bulk-capture-row"><label className="bulk-field">Target name<input value={name} maxLength={80} disabled={locked||!!busy} onChange={event=>setName(event.target.value)} placeholder="For example, Brain 1 · project tools"/></label><button className="secondary-button" type="button" disabled={locked||!!busy||!name.trim()||targets.length>=Math.min(catalog?.max_targets||32,32)} onClick={()=>void capture()}><Plus size={15} aria-hidden="true"/> Save current target</button></div>
      <label className="bulk-check"><input type="checkbox" checked={allowEdit} disabled={locked||!!busy} onChange={event=>setAllowEdit(event.target.checked)}/> Allow bulk edits for this target</label>
      <p className="bulk-help">Editing also requires workspace writes enabled in Settings. Saved targets do not enable Studio edits.</p>
    </details>

    <div className="bulk-editor">
      <label className="bulk-field">Task type<select value={kind} disabled={locked||!!busy&&busy!=='preview'} onChange={event=>{invalidate();setKind(event.target.value as TaskKind);setSelected([])}}><option value="brain_prompt">Send a brain prompt</option><option value="workspace_edit">Edit workspace text</option></select></label>
      <fieldset className="bulk-targets" disabled={locked||!!busy&&busy!=='preview'}><legend>Targets · {selected.length} selected</legend>
        {!targets.length&&<p className="bulk-help">No targets saved. Capture your current configuration above.</p>}
        {targets.map(target=><div className="bulk-target" key={target.id}>
          <label className="bulk-target-label"><input type="checkbox" aria-label={'Select '+target.name} checked={selected.includes(target.id)} disabled={!eligible(target)} onChange={event=>{invalidate();setSelected(ids=>event.target.checked?[...ids,target.id]:ids.filter(id=>id!==target.id))}}/><span><strong>{target.name}</strong><small>{target.project} · {target.model||'No model'} · {target.provider}</small><small>{target.endpoint}</small>{target.workspace&&<small>{target.workspace}</small>}{!eligible(target)&&<small>{kind==='workspace_edit'?'Bulk workspace edits are not enabled for this target.':!target.credential_ready?'Saved credential unavailable. Remove this target, set the key in Settings, then capture it again.':'This target cannot accept brain prompts.'}</small>}</span></label>
          <button className="secondary-button" type="button" aria-label={'Remove target '+target.name} disabled={locked||!!busy} onClick={()=>void remove(target.id)}><Trash2 size={14} aria-hidden="true"/></button>
        </div>)}
      </fieldset>
      {kind==='brain_prompt'?<>
        <label className="bulk-field">Prompt<textarea value={prompt} maxLength={5000} rows={5} disabled={locked||!!busy&&busy!=='preview'} onChange={event=>{invalidate();setPrompt(event.target.value)}} placeholder="Ask the selected brains to review or research a task…"/></label>
        <p className="bulk-help">Brain prompts return read-only analyses or proposals. They do not edit files or control Studio; workspace changes use the separate edit preview.</p>
        <label className="bulk-field">Context files (optional, one relative path per line)<textarea value={paths} maxLength={8016} rows={3} disabled={locked||!!busy&&busy!=='preview'} onChange={event=>{invalidate();setPaths(event.target.value)}} placeholder={'docs/notes.md\nsrc/settings.ts'}/></label>
        <p className="bulk-help">Send up to 16 selected files from each captured workspace as context, with at most 6,000 characters of file text combined. The prompt and context must fit 12,000 characters in total. Files changed after preview are refused.</p>
      </>:<>
        <label className="bulk-field">Files (one relative path per line)<textarea value={paths} maxLength={8016} rows={3} disabled={locked||!!busy&&busy!=='preview'} onChange={event=>{invalidate();setPaths(event.target.value)}} placeholder={'src/settings.ts\ndocs/notes.md'}/></label>
        <div className="bulk-two-fields"><label className="bulk-field">Find text<textarea value={oldString} maxLength={12000} rows={4} disabled={locked||!!busy&&busy!=='preview'} onChange={event=>{invalidate();setOldString(event.target.value)}}/></label><label className="bulk-field">Replace with<textarea value={newString} maxLength={12000} rows={4} disabled={locked||!!busy&&busy!=='preview'} onChange={event=>{invalidate();setNewString(event.target.value)}}/></label></div>
        <label className="bulk-check"><input type="checkbox" checked={replaceAll} disabled={locked||!!busy&&busy!=='preview'} onChange={event=>{invalidate();setReplaceAll(event.target.checked)}}/> Replace every match in each file</label>
        <p className="bulk-help">Use up to 16 explicit paths inside each saved workspace. Matching can normalize line endings or indentation; review the resulting diff and match method. A file changed since preview is refused.</p>
      </>}
      {!validPaths&&<p className="bulk-warning">Choose up to 16 unique relative file paths, with no more than 500 characters per path.</p>}
      <div className="bulk-limits">
        <label className="bulk-field">Concurrent targets<input type="number" min={1} max={4} value={concurrency} disabled={locked||!!busy&&busy!=='preview'} onChange={event=>{invalidate();setConcurrency(event.target.value)}}/></label>
        <label className="bulk-field">Canary targets<input type="number" min={1} max={Math.max(1,selected.length)} value={canarySize} disabled={locked||!!busy&&busy!=='preview'} onChange={event=>{invalidate();setCanarySize(event.target.value)}}/></label>
        <label className="bulk-field">Stop after failures<input type="number" min={1} max={Math.max(1,selected.length)} value={failureCutoff} disabled={locked||!!busy&&busy!=='preview'} onChange={event=>{invalidate();setFailureCutoff(event.target.value)}}/></label>
      </div>
      <p className="bulk-help">The canary runs the first selected targets before the rest. Choose 1–4 concurrent targets; canary and failure limits must fit the selected count.</p>
      <div className="bulk-actions"><button className="secondary-button" type="button" disabled={!canPreview} onClick={()=>void prepare()}>{busy==='preview'?<LoaderCircle size={15} className="spin" aria-hidden="true"/>:<Layers size={15} aria-hidden="true"/>} Preview selected tasks</button><button className="secondary-button" type="button" disabled={disabled||!!busy} onClick={()=>{invalidate();void loadCatalog();void loadHistory()}}><RefreshCcw size={15} aria-hidden="true"/> Refresh targets and history</button></div>
    </div>
    {message&&<p className="bulk-message" role="status">{message}</p>}

    {review&&<section className="bulk-review" aria-label="Review bulk task preview"><h3>{review.preview?.title||'Review the prepared batch'}</h3>{reviewPrompt&&<pre className="bulk-prompt" tabIndex={0} aria-label="Prompt to send">{reviewPrompt}</pre>}{reviewContextPaths.length>0&&<><p className="bulk-help">Selected context files from each captured workspace:</p><pre tabIndex={0} aria-label="Context files to send">{reviewContextPaths.join('\n')}</pre></>}{renderPreview(review)}<button className="primary-button" type="button" disabled={locked||!!busy} onClick={()=>void send()}><Send size={15} aria-hidden="true"/> {review.action==='workspace_undo'?'Apply reviewed undo':'Send reviewed batch'}</button></section>}

    <section className="bulk-history" aria-label="Saved bulk batches"><h3>Saved batches</h3>{!history.length&&<p className="bulk-help">No batches recorded on this device.</p>}<div className="bulk-history-list">{history.map(item=><button type="button" className="bulk-history-item" key={item.batch_id} aria-pressed={viewedId.current===item.batch_id} disabled={disabled||!!busy} onClick={()=>{invalidate();void showBatch(item.batch_id)}}><span>{actionLabel(item.action)} <small>{item.batch_id.slice(0,12)}</small></span><Tag kind={statusKind(item.status)}>{statusLabel(item.status)}</Tag></button>)}</div></section>
    {(batch||viewedId.current)&&<section className="bulk-results" aria-label="Bulk batch results">
      <div className="bulk-result-heading"><h3>{batch?actionLabel(batch.action):'Saved batch'}</h3>{batch&&<Tag kind={statusKind(batch.status)}>{statusLabel(batch.status)}</Tag>}</div>
      {batch?.cancellation_requested&&<p className="bulk-help">Cancellation requested. Running operations may still finish; completed changes remain recorded.</p>}
      {batch?.status==='outcome_unknown'&&<p className="bulk-help">The outcome was not confirmed. Inspect the target before starting another batch.</p>}
      {batch?.status==='prepared'&&<p className="bulk-help">This batch is prepared but has no confirmed run. To send a draft, create and review its preview above.</p>}
      {canUndo(batch)&&<p className="bulk-help">Undo includes only fully completed targets. Inspect partial or unknown target outcomes separately; they are not undone automatically.</p>}
      {batch?.preview&&<details><summary>Recorded preview</summary>{renderPreview(batch)}</details>}
      {batch?.operations.map(operation=><article className="bulk-operation" key={operation.operation_id} aria-label={'Result '+(targets.find(target=>target.id===operation.target_id)?.name||operation.target_id)}><div className="bulk-result-heading"><h4>{targets.find(target=>target.id===operation.target_id)?.name||operation.target_id}</h4><Tag kind={statusKind(operation.status)}>{statusLabel(operation.status)}</Tag></div>{operation.error!==undefined&&operation.error!==null&&operation.error!==''&&<p className="bulk-error">{outputText(operation.error)}</p>}{operation.result!==undefined&&operation.result!==null&&<pre tabIndex={0} aria-label="Recorded target result">{outputText(operation.result)}</pre>}</article>)}
      {pollMessage&&<p className="bulk-message" role="status">{pollMessage}</p>}
      <div className="bulk-actions"><button type="button" className="secondary-button" disabled={disabled||!!busy} onClick={()=>void refreshBatch()}><RefreshCcw size={15} aria-hidden="true"/> Refresh batch status</button>{batch?.status==='running'&&<button type="button" className="secondary-button" disabled={disabled||!!busy||batch.cancellation_requested} onClick={()=>void cancel()}><Square size={14} aria-hidden="true"/> Request cancellation</button>}{canUndo(batch)&&<button type="button" className="secondary-button" disabled={locked||!!busy} onClick={()=>void prepareUndo()}><Undo2 size={15} aria-hidden="true"/> Preview undo</button>}</div>
    </section>}
  </section>
}
