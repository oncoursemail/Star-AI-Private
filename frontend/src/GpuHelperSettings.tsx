/**
 * Settings > Model > "Use my GPU" (star/gpu_helper.py): STAR's code model on this PC's NVIDIA card, per request,
 * with STAR Server as the fallback for every failure.
 *
 * The switch is saved by the host at once (`gpuHelperSet`), like Discord's autostart, so it never waits for the
 * Save button and a later Save cannot undo it. The status line is what the host reports (`gpuHelperStatus`, every
 * few seconds while this panel is open); nothing is shown as on or ready before the host said so. The two file
 * paths and the idle minutes are ordinary settings, saved with the rest of the page.
 */
import {useCallback,useEffect,useId,useRef,useState} from 'react'
import {Cpu} from 'lucide-react'
import {request} from './bridge'
import {plainError} from './VoiceSettings'
import type {AppSettings,GpuHelperStatus} from './types'

const POLL_MS=3_000
const known=(value:unknown):value is GpuHelperStatus=>
  !!value&&typeof value==='object'&&typeof (value as GpuHelperStatus).state==='string'&&typeof (value as GpuHelperStatus).text==='string'

export function GpuHelperSettings({draft,set,disabled=false}:{draft:AppSettings;set:(patch:Partial<AppSettings>)=>void;disabled?:boolean}){
  const [status,setStatus]=useState<GpuHelperStatus|null>(null)
  const [busy,setBusy]=useState(false)
  const [problem,setProblem]=useState('')
  const mounted=useRef(true)
  const hintId=useId()
  const nightId=useId()

  const refresh=useCallback(async()=>{
    if(disabled)return
    const reply=await request('gpuHelperStatus')
    if(mounted.current&&reply.ok&&known(reply.data))setStatus(reply.data)
  },[disabled])

  useEffect(()=>{
    mounted.current=true
    void refresh()
    const timer=disabled?undefined:setInterval(()=>void refresh(),POLL_MS)
    return ()=>{mounted.current=false;if(timer)clearInterval(timer)}
  },[refresh,disabled])

  const toggle=async(on:boolean)=>{
    if(disabled||busy)return
    setBusy(true);setProblem('')
    const reply=await request('gpuHelperSet',{enabled:on})
    if(!mounted.current)return
    if(reply.ok&&known(reply.data)){setStatus(reply.data);set({use_my_gpu:on})}
    else setProblem(plainError(reply.error,'The switch could not be changed, so nothing was changed.'))
    setBusy(false)
  }

  const on=status?(status.switch??status.enabled):draft.use_my_gpu===true
  const serverProvider=draft.provider==='star_server'
  return <section className="panel settings-section" aria-label="Use my GPU">
    <div className="section-heading"><div><h3 className="settings-group-title">Use my GPU</h3>
      <p>Runs STAR's code model on this PC's NVIDIA graphics card, about three times faster than the server. Memory, tools and lessons stay exactly as they are; when the card is busy or anything fails, the server answers.</p></div><Cpu size={20} aria-hidden="true"/></div>
    <label className="setting-switch"><span><strong>Use my GPU</strong><small id={hintId}>Off by default. Pauses while a game or another program uses the card, and unloads after the idle minutes below.{serverProvider?'':' Works with STAR Server as the provider.'}</small></span>
      <input type="checkbox" aria-label="Use my GPU" aria-describedby={hintId} checked={on} disabled={disabled||busy} onChange={e=>void toggle(e.target.checked)}/></label>
    <label className="setting-switch"><span><strong>Automatically turn on at night</strong><small id={nightId}>On by default. Between 01:00 and 08:00 STAR may use this PC even when the switch above is off (night learning still waits until you are away and no game uses the card). At 08:00 it follows the switch again.</small></span>
      <input type="checkbox" aria-label="Automatically turn on at night" aria-describedby={nightId} checked={draft.use_my_pc_auto_night!==false} disabled={disabled} onChange={e=>set({use_my_pc_auto_night:e.target.checked})}/></label>
    <p className="voice-current" role="status">Status: <strong>{status?status.label:(disabled?'Open STAR Desktop to see this':'Reading…')}</strong>{status&&<> · {status.text}</>}</p>
    {problem&&<p role="alert" className="media-warning">{problem}</p>}
    {on&&<div className="field-grid">
      <label>llama-server.exe (CUDA build)<input value={draft.gpu_helper_server||''} onChange={e=>set({gpu_helper_server:e.target.value})} placeholder="Blank: the gpu-helper folder in STAR's data folder"/></label>
      <label>Model file (star-fast.gguf)<input value={draft.gpu_helper_model||''} onChange={e=>set({gpu_helper_model:e.target.value})} placeholder="Blank: the gpu-helper folder in STAR's data folder"/></label>
      <label>Unload after idle minutes<input type="number" min="1" max="240" value={draft.gpu_idle_minutes??10} onChange={e=>set({gpu_idle_minutes:Number(e.target.value)})}/></label>
    </div>}
  </section>
}
