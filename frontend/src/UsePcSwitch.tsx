/**
 * "Use my PC": the composer-bar twin of Settings > Model > "Use my GPU" (star/gpu_helper.py, setting `use_my_gpu`).
 *
 * Same host calls as the Settings switch: `gpuHelperSet` saves at once and returns the status, `gpuHelperStatus`
 * is polled. Nothing is shown as on before the host said so. Flipping it never touches an answer in progress: the
 * host lets a running PC answer finish and sends every later request to the server.
 */
import {useCallback,useEffect,useRef,useState} from 'react'
import {Microchip} from 'lucide-react'
import {request} from './bridge'
import type {GpuHelperStatus} from './types'

const POLL_MS=5_000
const known=(value:unknown):value is GpuHelperStatus=>
  !!value&&typeof value==='object'&&typeof (value as GpuHelperStatus).state==='string'&&typeof (value as GpuHelperStatus).text==='string'

export function UsePcSwitch({saved,disabled=false,onChanged}:{saved:boolean;disabled?:boolean;onChanged:(on:boolean)=>void}){
  const [status,setStatus]=useState<GpuHelperStatus|null>(null)
  const [busy,setBusy]=useState(false)
  const [problem,setProblem]=useState('')
  const mounted=useRef(true)

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

  const on=status?status.enabled:saved
  const toggle=async()=>{
    if(disabled||busy)return
    setBusy(true);setProblem('')
    const want=!on
    const reply=await request('gpuHelperSet',{enabled:want})
    if(!mounted.current)return
    if(reply.ok&&known(reply.data)){setStatus(reply.data);onChanged(want)}
    else setProblem('Could not change this, so nothing changed.')
    setBusy(false)
  }
  const line=problem||(status?`Use my PC: ${status.label}. ${status.text}`:`Use my PC: ${on?'on':'off'}`)
  return <button type="button" role="switch" aria-checked={on} aria-label="Use my PC" title={line}
    className={'cmp-pc'+(on?' is-on':'')} disabled={disabled||busy} onClick={()=>void toggle()}>
    <Microchip size={14} aria-hidden="true"/>
    <span className="cmp-pc-label" aria-hidden="true">Use my PC</span>
    <span className="cmp-pc-track" aria-hidden="true"><span className="cmp-pc-knob"/></span>
    <span className="cmp-pc-state" aria-hidden="true">{on?'On':'Off'}</span>
  </button>
}
