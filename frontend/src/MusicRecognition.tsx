/**
 * Song recognition (star/music_recognition.py), shown only while Settings > Song recognition is on.
 * The dialog identifies a WAV the owner picks or one short recording they start; SongLookupRow approves one
 * lookup of a WAV attached to a chat message. Nothing is sent before the owner ticks the line that says what
 * goes where. Keys never pass through React: the desktop only reports whether one is saved.
 */
import {useEffect,useRef,useState} from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import {AudioLines,FileAudio,FolderOpen,LoaderCircle,Music2,X} from 'lucide-react'
import {isDesktop,onBackendEvent,request} from './bridge'
import './music-recognition.css'

export type SongProvider='audd'|'acoustid'
export type SongLookup={file:string;provider:SongProvider}
export type SongStatus={enabled:boolean;file:string;duration_seconds:number|null;busy:boolean;audd_key:boolean;acoustid_key:boolean;fpcalc_found:boolean}
type Result={status:'match'|'no_match'|'not_configured'|'not_installed';candidates?:{song:string;score:number|null}[];sent?:string;note:string}
type Device={index:number;kind:string;name:string;default:boolean}
export const MAX_SECONDS:Record<SongProvider,number>={audd:12,acoustid:30}
const LABEL:Record<SongProvider,string>={audd:'AudD',acoustid:'AcoustID'}

/** What one lookup sends where (the same facts as music_recognition.disclosure). */
export function songDisclosure(provider:SongProvider,seconds=MAX_SECONDS[provider]):string{
 return provider==='audd'
  ?`Uploads a ${seconds} s clip of this audio to AudD (api.audd.io), a third-party service that may charge your AudD account.`
  :`Sends a fingerprint of ${seconds} s of this audio to AcoustID (api.acoustid.org). The audio stays on this PC.`
}

export function readyToIdentify(status:SongStatus|null,provider:SongProvider,source:'file'|'mic',consent:boolean,micConsent:boolean,seconds:number):boolean{
 if(!status?.enabled||status.busy||!consent||!Number.isInteger(seconds)||seconds<4||seconds>MAX_SECONDS[provider])return false
 if(source==='file'&&!status.file)return false
 if(source==='mic'&&!micConsent)return false
 return provider==='audd'?status.audd_key:status.acoustid_key
}

/** Composer line for a WAV attached to this message: ticking it approves one lookup with the chosen catalog. */
export function SongLookupRow({files,lookup,onLookup,disabled=false}:{files:string[];lookup:SongLookup|null;onLookup:(value:SongLookup|null)=>void;disabled?:boolean}){
 const [provider,setProvider]=useState<SongProvider>('audd')
 const wav=files.find(path=>path.toLowerCase().endsWith('.wav'))
 if(!wav)return null
 const active=lookup?.file===wav
 return <div className="music-chat-row">
   <label><input type="checkbox" checked={active} disabled={disabled} onChange={e=>onLookup(e.target.checked?{file:wav,provider}:null)}/>
     <span>Identify the song. {songDisclosure(provider)}</span></label>
   {/* A different catalog sends something else somewhere else: changing it withdraws the approval. */}
   <select aria-label="Song catalog" value={provider} disabled={disabled} onChange={e=>{setProvider(e.target.value as SongProvider);onLookup(null)}}>
     <option value="audd">AudD</option><option value="acoustid">AcoustID</option>
   </select>
 </div>
}

export function MusicRecognitionButton({disabled=false}:{disabled?:boolean}){
 const [open,setOpen]=useState(false)
 if(!isDesktop())return null
 return <>
   <button type="button" className="cmp-icon-button cmp-song" title="Identify a song" aria-label="Identify a song" disabled={disabled} onClick={()=>setOpen(true)}>
     <Music2 size={17} aria-hidden="true"/>
   </button>
   {open&&<MusicRecognitionDialog onClose={()=>setOpen(false)}/>}
 </>
}

export function MusicRecognitionDialog({onClose}:{onClose:()=>void}){
 const [status,setStatus]=useState<SongStatus|null>(null)
 const [provider,setProvider]=useState<SongProvider>('audd')
 const [source,setSource]=useState<'file'|'mic'>('file')
 const [seconds,setSeconds]=useState(12)
 const [start,setStart]=useState(0)
 const [consent,setConsent]=useState(false)
 const [micConsent,setMicConsent]=useState(false)
 const [devices,setDevices]=useState<Device[]>([])
 const [device,setDevice]=useState('')
 const [busy,setBusy]=useState(false)
 const [progress,setProgress]=useState('')
 const [error,setError]=useState('')
 const [result,setResult]=useState<Result|null>(null)
 const waiting=useRef<string|null>(null)
 const reset=()=>{setConsent(false);setMicConsent(false);setResult(null)}

 useEffect(()=>{
   void request<SongStatus>('musicStatus').then(reply=>{if(reply.ok&&reply.data)setStatus(reply.data);else setError(reply.error||'Song recognition is not available.')})
   void request<{devices:Device[]}>('voiceListDevices').then(reply=>{if(reply.ok&&Array.isArray(reply.data?.devices))setDevices(reply.data.devices.filter(d=>d.kind==='input'))})
 },[])

 useEffect(()=>onBackendEvent(event=>{
   if(!waiting.current||event.requestId!==waiting.current)return
   if(event.kind==='progress'){const phase=(event.data as {phase?:string}|null)?.phase;if(phase)setProgress(phase);return}
   if(event.kind!=='result'&&event.kind!=='error')return
   waiting.current=null;setBusy(false);setProgress('');setConsent(false);setMicConsent(false)   // approval is per lookup
   if(event.kind==='error')setError(typeof event.data==='string'?event.data:'The lookup did not finish.')
   else setResult(event.data as Result)
 }),[])

 async function call<T>(action:string,payload:Record<string,unknown>={}):Promise<T|null>{
   if(busy)return null
   setBusy(true);setError('');setResult(null)
   const id=crypto.randomUUID()
   waiting.current=id   // before the request: the worker may answer before `request` resolves
   const reply=await request<T>(action,payload,id)
   if(reply.ok&&reply.pending)return null
   waiting.current=null;setBusy(false)
   if(!reply.ok){setError(reply.error||'STAR could not do that.');return null}
   return reply.data??null
 }
 async function chooseWav(){
   const picked=await call<{file?:string;duration_seconds?:number;cancelled?:boolean}>('musicChooseWav')
   if(picked&&!picked.cancelled&&status){setStatus({...status,file:picked.file||'',duration_seconds:picked.duration_seconds??null});reset()}
 }
 async function clearWav(){
   if(await call('musicClear')&&status){setStatus({...status,file:'',duration_seconds:null});reset()}
 }
 function identify(){
   if(!readyToIdentify(status,provider,source,consent,micConsent,seconds))return
   void call('musicIdentify',{provider,source,seconds,startSeconds:source==='file'?start:0,consent,micConsent:source==='mic'&&micConsent,
     ...(source==='mic'&&device!==''?{deviceIndex:Number(device)}:{})})
 }
 const keySaved=provider==='audd'?status?.audd_key:status?.acoustid_key
 return <Dialog.Root open onOpenChange={open=>{if(!open&&!busy)onClose()}}>
   <Dialog.Portal>
     <Dialog.Overlay className="music-overlay"/>
     <Dialog.Content className="star-layer music-dialog" aria-describedby="music-intro" onEscapeKeyDown={e=>{if(busy)e.preventDefault()}} onInteractOutside={e=>{if(busy)e.preventDefault()}}>
       <div className="music-head">
         <div className="music-head-symbol"><AudioLines size={21} aria-hidden="true"/></div>
         <div><Dialog.Title>Identify a song</Dialog.Title><Dialog.Description id="music-intro">From a WAV file or one short recording. Results are catalog suggestions.</Dialog.Description></div>
         <button type="button" className="music-close" aria-label="Close" disabled={busy} onClick={onClose}><X size={17}/></button>
       </div>
       <div className="music-body">
         <fieldset className="music-switch"><legend>Audio</legend>
           <label><input type="radio" name="song-source" checked={source==='file'} disabled={busy} onChange={()=>{setSource('file');reset()}}/> WAV file</label>
           <label><input type="radio" name="song-source" checked={source==='mic'} disabled={busy} onChange={()=>{setSource('mic');reset()}}/> Record now</label>
         </fieldset>
         {source==='file'
           ?<div className="music-file">
              <button type="button" className="music-secondary" disabled={busy} onClick={()=>void chooseWav()}><FolderOpen size={15}/> Choose WAV</button>
              {status?.file&&<div className="music-picked"><FileAudio size={17}/><div><strong title={status.file}>{status.file}</strong><span>{status.duration_seconds?.toFixed(1)} s</span></div><button type="button" aria-label="Clear the chosen file" disabled={busy} onClick={()=>void clearWav()}><X size={15}/></button></div>}
              <label className="music-compact">Start at (s)<input type="number" min={0} max={116} step={1} value={start} disabled={busy} onChange={e=>{setStart(Math.max(0,Math.floor(Number(e.target.value)||0)));setConsent(false)}}/></label>
            </div>
           :<label className="music-compact music-input">Input (a microphone, Stereo Mix or a virtual cable for system audio)
              <select value={device} disabled={busy} onChange={e=>setDevice(e.target.value)}>
                <option value="">Default input</option>
                {devices.map(d=><option key={d.index} value={String(d.index)}>{d.name}{d.default?' (default)':''}</option>)}
              </select>
            </label>}
         <fieldset className="music-switch"><legend>Catalog</legend>
           {(['audd','acoustid'] as SongProvider[]).map(p=><label key={p}><input type="radio" name="song-provider" checked={provider===p} disabled={busy} onChange={()=>{setProvider(p);setSeconds(Math.min(seconds,MAX_SECONDS[p]));reset()}}/> {LABEL[p]}</label>)}
         </fieldset>
         <label className="music-compact">Length
           <select value={seconds} disabled={busy} onChange={e=>{setSeconds(Number(e.target.value));setConsent(false)}}>
             {[4,8,12,20,30].filter(v=>v<=MAX_SECONDS[provider]).map(v=><option key={v} value={v}>{v} s</option>)}
           </select>
         </label>
         {status&&!keySaved&&<p className="music-alert">Add your {LABEL[provider]} key in Settings &gt; Song recognition.</p>}
         {provider==='acoustid'&&status&&!status.fpcalc_found&&<p className="music-alert">Chromaprint fpcalc is not installed (not on PATH or at the Settings path).</p>}
         <div className="music-consents" role="group" aria-label="Approval for this lookup">
           {source==='mic'&&<label><input type="checkbox" checked={micConsent} disabled={busy} onChange={e=>setMicConsent(e.target.checked)}/><span>Record {seconds} s from this input once.</span></label>}
           <label><input type="checkbox" checked={consent} disabled={busy} onChange={e=>setConsent(e.target.checked)}/><span>{songDisclosure(provider,seconds)}</span></label>
         </div>
         {error&&<p className="music-error" role="alert">{error}</p>}
         {progress&&<p className="music-progress" role="status"><LoaderCircle size={15} className="spin"/> {progress}</p>}
         {result&&<section className="music-result" aria-label="Song lookup result">
           {result.status==='match'&&<><h3>Possible matches</h3><ol>{result.candidates?.map((c,i)=><li key={i}><strong>{c.song}</strong>{c.score!==null&&<small>Fingerprint score {c.score} (uncalibrated)</small>}</li>)}</ol></>}
           {result.status==='no_match'&&<h3>No match in the catalog</h3>}
           <p>{result.note}</p>
         </section>}
       </div>
       <div className="music-actions">
         <button type="button" className="music-primary" disabled={busy||!readyToIdentify(status,provider,source,consent,micConsent,seconds)} onClick={identify}>
           {busy?<LoaderCircle size={16} className="spin"/>:<Music2 size={16}/>} {busy?'Working…':'Identify'}
         </button>
       </div>
     </Dialog.Content>
   </Dialog.Portal>
 </Dialog.Root>
}
