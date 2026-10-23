import {useEffect,useRef,useState} from 'react'
import {Box,LoaderCircle,RefreshCcw} from 'lucide-react'
import {onBackendEvent} from './bridge'
import type {AppSettings,BlenderStatus} from './types'

type Invoke=(action:string,params?:Record<string,unknown>)=>Promise<unknown|null>

export function BlenderPanel({draft,onChange,status,invoke,disabled=false}:{
 draft:AppSettings;onChange:(settings:AppSettings)=>void;status?:BlenderStatus;
 invoke:Invoke;disabled?:boolean
}){
 const [pending,setPending]=useState(false)
 const [result,setResult]=useState('')
 const activeRequest=useRef('')
 useEffect(()=>onBackendEvent(event=>{
   if(!activeRequest.current||event.requestId!==activeRequest.current||event.kind==='progress')return
   activeRequest.current=''
   setPending(false)
   if(event.kind==='error'){
     setResult('Blender test failed. Check the executable path and install.')
   }else{
     const report=event.data as {ready?:boolean;version?:string}|null
     setResult(report?.ready?'Local Blender '+String(report.version||'')+' verified':'Blender did not report ready.')
   }
 }),[])
 const probe=async()=>{
   if(pending||disabled||!draft.blender_enabled)return
   setPending(true);setResult('')
   const response=await invoke('testBlender') as {pending?:boolean;requestId?:string}|null
   if(response?.pending&&response.requestId){activeRequest.current=response.requestId}
   else setPending(false)
 }
 return <section className="integrated-panel" aria-label="Blender">
   <div className="integrated-heading"><Box size={18}/><div>
     <strong>Blender</strong>
     <span>Lets STAR build editable 3D scenes in the Blender on this PC and export them as models Roblox Studio can import.</span>
   </div></div>
   <div className="integrated-connectors">
     <div className="integrated-connector">
       <div><strong>Use Blender on this PC</strong><small>No cloud account or add-on needed. Uses a Blender you installed and trust.</small></div>
       <label className="integrated-switch">
         <input type="checkbox" aria-label="Use Blender on this PC" checked={!!draft.blender_enabled}
           disabled={disabled} onChange={e=>onChange({...draft,blender_enabled:e.target.checked,
             blender_edit:e.target.checked?!!draft.blender_edit:false})}/>
         <span>Enable</span>
       </label>
     </div>
     <div className="integrated-connector">
       <div><strong>Permit creating new Blender scenes</strong>
         <small>STAR only writes new files of its own. It never changes your existing Blender files and cannot run arbitrary code in Blender.</small></div>
       <label className="integrated-switch">
         <input type="checkbox" aria-label="Allow Blender scene creation" checked={!!draft.blender_edit}
           disabled={disabled||!draft.blender_enabled}
           onChange={e=>onChange({...draft,blender_edit:e.target.checked})}/>
         <span>Create</span>
       </label>
     </div>
     <div className="integrated-connector">
       <div><strong>Check animation motion</strong>
         <small>Lets STAR measure joint speed, sharp jumps and loop seams in an animation plan, and compare it with an approved clip. Reads the plan only; Blender does not start.</small></div>
       <label className="integrated-switch">
         <input type="checkbox" aria-label="Check animation motion" checked={!!draft.blender_motion_qa}
           disabled={disabled||!draft.blender_enabled}
           onChange={e=>onChange({...draft,blender_motion_qa:e.target.checked})}/>
         <span>Check</span>
       </label>
     </div>
   </div>
   <label className="integrated-field">Blender executable (optional; blank searches installed Blender)
     <input aria-label="Blender executable path" type="text" spellCheck={false}
       placeholder="C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
       value={draft.blender_executable??''} disabled={disabled}
       onChange={e=>onChange({...draft,blender_executable:e.target.value})}/>
   </label>
   <div className="integrated-actions">
     <button type="button" className="secondary-button" disabled={disabled||pending||!draft.blender_enabled}
       onClick={()=>void probe()}>
       {pending?<LoaderCircle className="spin" size={14}/>:<RefreshCcw size={14}/>}
       {pending?'Checking Blender…':'Test local Blender'}
     </button>
   </div>
   {result&&<p className="integrated-help" role="status">{result}</p>}
   <p className="integrated-help">Saved setup: {status?.ready?'Blender found, version not yet verified.':status?.enabled?'Blender is not found.':'Off.'}
     {' '}Save settings before testing. STAR uses Blender only when a request needs it, and only after you turn it on here.
     Exported models (.glb) still need to be imported and checked in Roblox Studio.</p>
 </section>
}
