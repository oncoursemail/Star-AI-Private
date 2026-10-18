/**
 * STAR's owner-triggered "What song is this?" UI.
 *
 * The desktop, never the model, chooses the real audio source and approves
 * network disclosure. No raw waveform, credential or local filename path is
 * sent through React, and provider suggestions are not presented as truth.
 */
import {useEffect,useRef,useState} from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import {AudioLines,Check,FileAudio,FolderOpen,LoaderCircle,Mic,Music2,Shield,Square,X} from 'lucide-react'
import {isDesktop,onBackendEvent,request} from './bridge'
import './music-recognition.css'

type Provider='audd'|'acoustid'
type Source='file'|'mic'
type Consent={upload:boolean;billing:boolean;fingerprint:boolean;noncommercial:boolean;mic:boolean}
type Status={
 selected:boolean;file:string;duration_seconds:number|null;sha256:string|null;
 audd_configured:boolean;acoustid_configured:boolean;fpcalc_selected:boolean;busy:boolean
}
type Device={index:number;kind:string;name:string;default:boolean}
type Match={title:string;artist:string;album?:string;score:number|null;score_meaning:string;provider:string}
type Result={status:'candidate_matches'|'no_match';provider:string;candidates:Match[];duration_seconds:number;transferred:string;human_verified:boolean;note:string}
const EMPTY:Consent={upload:false,billing:false,fingerprint:false,noncommercial:false,mic:false}
const MAX_DURATION:Record<Provider,number>={audd:12,acoustid:30}

export function canIdentify(status:Status|null,provider:Provider,source:Source,consent:Consent,seconds:number,hasFpcalc:boolean):boolean{
 if(!status||status.busy||!Number.isInteger(seconds)||seconds<4||seconds>MAX_DURATION[provider])return false
 if(source==='file'&&(!status.selected||!status.duration_seconds||status.duration_seconds<4))return false
 if(source==='mic'&&!consent.mic)return false
 if(provider==='audd')return status.audd_configured&&consent.upload&&consent.billing
 return status.acoustid_configured&&hasFpcalc&&consent.fingerprint&&consent.noncommercial
}

export function MusicRecognitionButton({disabled=false}:{disabled?:boolean}){
 const [open,setOpen]=useState(false)
 if(!isDesktop())return null
 return <>
   <button type="button" className="cmp-icon-button cmp-song" title="Identify music in a clip or microphone" aria-label="Identify song" disabled={disabled} onClick={()=>setOpen(true)}>
     <Music2 size={17} aria-hidden="true"/>
   </button>
   {open&&<MusicRecognitionDialog onClose={()=>setOpen(false)}/>}
 </>
}

export function MusicRecognitionDialog({onClose}:{onClose:()=>void}){
 const [status,setStatus]=useState<Status|null>(null)
 const [provider,setProvider]=useState<Provider>('audd')
 const [source,setSource]=useState<Source>('file')
 const [consent,setConsent]=useState<Consent>(EMPTY)
 const [seconds,setSeconds]=useState(12)
 const [start,setStart]=useState(0)
 const [devices,setDevices]=useState<Device[]>([])
 const [device,setDevice]=useState('')
 const [busy,setBusy]=useState(false)
 const [progress,setProgress]=useState('')
 const [notice,setNotice]=useState('')
 const [error,setError]=useState('')
 const [result,setResult]=useState<Result|null>(null)
 const waiting=useRef<{id:string;action:string}|null>(null)

 useEffect(()=>{
   void request<Status>('musicStatus').then(reply=>{
     if(reply.ok&&reply.data)setStatus(reply.data)
     else setError(reply.error||'STAR song identification is not available in this desktop build.')
   })
   void request<{devices:Device[]}>('voiceListDevices').then(reply=>{
     if(reply.ok&&Array.isArray(reply.data?.devices))setDevices(reply.data.devices.filter(d=>d.kind==='input'))
   })
 },[])

 useEffect(()=>onBackendEvent(event=>{
   const pending=waiting.current
   if(!pending||event.requestId!==pending.id)return
   if(event.kind==='progress'){
     const payload=event.data as {phase?:string}|null
     if(payload?.phase)setProgress(payload.phase)
     return
   }
   if(event.kind!=='result'&&event.kind!=='error')return
   waiting.current=null
   setBusy(false)
   setProgress('')
   setConsent(EMPTY) // per-lookup, never sticky across captures/uploads
   if(event.kind==='error'){
     setError(typeof event.data==='string'?event.data:'Song identification could not complete.')
     return
   }
   setResult(event.data as Result)
 }),[])

 async function action<T>(kind:string,payload:Record<string,unknown>={}):Promise<T|null>{
   if(busy)return null
   setBusy(true);setError('');setNotice('');setResult(null)
   const id=crypto.randomUUID()
   // Subscribe before the native worker may emit even its first result.
   waiting.current={id,action:kind}
   const reply=await request<T>(kind,payload,id)
   if(!reply.ok){
     waiting.current=null;setBusy(false)
     setError(reply.error||'STAR could not complete that action.')
     return null
   }
   if(reply.pending){
     setProgress(source==='mic'?'Waiting for the selected microphone to finish recording…':'Matching the selected audio…')
     return null
   }
   waiting.current=null;setBusy(false)
   return reply.data??null
 }

 async function chooseWav(){
   const answer=await action<Status&{cancelled?:boolean}>('musicChooseWav')
   if(answer&&!answer.cancelled){setStatus(answer);setNotice('Recording selected locally. Nothing has been uploaded.')}
 }
 async function chooseFpcalc(){
   const answer=await action<Status&{cancelled?:boolean}>('musicChooseFpcalc')
   if(answer&&!answer.cancelled){setStatus(answer);setNotice('Local Chromaprint executable selected.')}
 }
 async function identify(){
   if(!canIdentify(status,provider,source,consent,seconds,status?.fpcalc_selected===true))return
   if(source==='file'&&status?.duration_seconds&&start+4>status.duration_seconds){setError('Choose a start time with at least four seconds remaining.');return}
   const answer=await action<Result>('musicIdentify',{
     provider,source,seconds,startSeconds:source==='file'?start:0,
     micConsent:source==='mic'&&consent.mic,
     uploadConsent:consent.upload,billingConsent:consent.billing,
     fingerprintConsent:consent.fingerprint,noncommercialConsent:consent.noncommercial,
     ...(device!==''&&source==='mic'?{deviceIndex:Number(device)}:{}),
   })
   if(answer){setResult(answer);setConsent(EMPTY)}
 }
 async function clear(){
   const answer=await action<Status>('musicClear')
   if(answer){setStatus(answer);setNotice('Song source cleared from this STAR session.')}
 }
 const configured=provider==='audd'?status?.audd_configured:status?.acoustid_configured
 const providerText=provider==='audd'
   ?'AudD receives the selected audio and can charge for requests. A provider token is needed.'
   :'AcoustID receives only a locally generated Chromaprint fingerprint. Its free service is noncommercial.'
 const sourceNote=source==='mic'
   ?'STAR records a single short microphone sample only when you press Identify. A chosen virtual input or Stereo Mix may carry game audio and other voices.'
   :'Choose a PCM16 WAV recording (8 MiB maximum). For game clips, extract a short WAV from an approved OBS/Medal video.'
 return <Dialog.Root open onOpenChange={value=>{if(!value&&!busy)onClose()}}>
   <Dialog.Portal>
     <Dialog.Overlay className="music-overlay"/>
     <Dialog.Content className="star-layer music-dialog" aria-describedby="music-intro" onEscapeKeyDown={e=>{if(busy)e.preventDefault()}} onInteractOutside={e=>{if(busy)e.preventDefault()}}>
       <div className="music-head">
         <div className="music-head-symbol"><AudioLines size={21} aria-hidden="true"/></div>
         <div><Dialog.Title>Identify a song</Dialog.Title><Dialog.Description id="music-intro">Listen to an approved clip. STAR reports catalog candidates, not guaranteed matches.</Dialog.Description></div>
         <button type="button" className="music-close" aria-label="Close song recognition" disabled={busy} onClick={onClose}><X size={17}/></button>
       </div>
       <div className="music-body">
         <fieldset className="music-switch"><legend>Audio source</legend>
           <label><input type="radio" name="song-source" value="file" disabled={busy} checked={source==='file'} onChange={()=>{setSource('file');setResult(null)}}/> File</label>
           <label><input type="radio" name="song-source" value="mic" disabled={busy} checked={source==='mic'} onChange={()=>{setSource('mic');setResult(null)}}/> Microphone / game mix</label>
         </fieldset>
         {source==='file'?
           <div className="music-file">
             <button className="music-secondary" type="button" disabled={busy} onClick={()=>void chooseWav()}><FolderOpen size={15}/> Choose WAV recording</button>
             {status?.selected&&<div className="music-picked"><FileAudio size={17}/><div><strong title={status.file}>{status.file}</strong><span>{status.duration_seconds?.toFixed(1)} seconds · Local only</span></div><button type="button" disabled={busy} aria-label="Clear selected recording" onClick={()=>void clear()}><X size={15}/></button></div>}
             <label className="music-compact">Start at (seconds)<input type="number" min={0} max={120} step={1} disabled={busy} value={start} onChange={e=>setStart(Number(e.target.value))}/></label>
           </div>
           :<label className="music-compact music-input">Input device
             <select disabled={busy} value={device} onChange={e=>setDevice(e.target.value)}>
               <option value="">System default microphone</option>
               {devices.map(d=><option value={String(d.index)} key={d.index}>{d.name}{d.default?' (default)':''}</option>)}
             </select>
           </label>
         }
         <p className="music-context">{sourceNote}</p>
         <fieldset className="music-switch"><legend>Recognition catalog</legend>
           <label><input name="music-provider" type="radio" value="audd" checked={provider==='audd'} disabled={busy} onChange={()=>{setProvider('audd');setSeconds(12);setResult(null);setConsent(EMPTY)}}/> AudD · Audio</label>
           <label><input name="music-provider" type="radio" value="acoustid" checked={provider==='acoustid'} disabled={busy} onChange={()=>{setProvider('acoustid');setSeconds(30);setResult(null);setConsent(EMPTY)}}/> AcoustID · Fingerprint</label>
         </fieldset>
         <p className="music-context">{providerText}</p>
         {provider==='acoustid'&&<button type="button" className="music-secondary" disabled={busy} onClick={()=>void chooseFpcalc()}>{status?.fpcalc_selected?<Check size={15}/>:<FolderOpen size={15}/>} {status?.fpcalc_selected?'Chromaprint selected':'Choose installed fpcalc executable'}</button>}
         {!configured&&<p className="music-alert">Provider key not configured. Set {provider==='audd'?'STAR_AUDD_API_TOKEN':'STAR_ACOUSTID_CLIENT_KEY'} in the desktop environment; no key is stored in the chat.</p>}
         <label className="music-compact">Clip length
           <select value={seconds} disabled={busy} onChange={e=>setSeconds(Number(e.target.value))}>
             {(provider==='audd'?[8,12]:[8,12,20,30]).map(v=><option key={v} value={v}>{v} seconds</option>)}
           </select>
         </label>
         <div className="music-consents" role="group" aria-label="Recording and network permissions">
           {source==='mic'&&<label><input type="checkbox" checked={consent.mic} disabled={busy} onChange={e=>setConsent(c=>({...c,mic:e.target.checked}))}/><span>I explicitly allow one microphone recording.</span></label>}
           {provider==='audd'?<>
             <label><input type="checkbox" checked={consent.upload} disabled={busy} onChange={e=>setConsent(c=>({...c,upload:e.target.checked}))}/><span>I approve sending this audio snippet to AudD.</span></label>
             <label><input type="checkbox" checked={consent.billing} disabled={busy} onChange={e=>setConsent(c=>({...c,billing:e.target.checked}))}/><span>I understand this may use paid AudD quota.</span></label>
           </>:<>
             <label><input type="checkbox" checked={consent.fingerprint} disabled={busy} onChange={e=>setConsent(c=>({...c,fingerprint:e.target.checked}))}/><span>Send a fingerprint to AcoustID (not the WAV).</span></label>
             <label><input type="checkbox" checked={consent.noncommercial} disabled={busy} onChange={e=>setConsent(c=>({...c,noncommercial:e.target.checked}))}/><span>This use complies with AcoustID's noncommercial terms.</span></label>
           </>}
         </div>
         {notice&&<p className="music-notice" role="status">{notice}</p>}
         {error&&<p className="music-error" role="alert">{error}</p>}
         {progress&&<p className="music-progress" role="status"><LoaderCircle size={15} className="spin"/> {progress}</p>}
         {result&&<section className="music-result" aria-label="Song lookup result">
           <h3>{result.candidates?.length?'Possible matches':'No confident catalog match'}</h3>
           {result.candidates?.length>0?<ol>{result.candidates.map((track,i)=><li key={i}>
             <strong>{track.title}</strong><span>{track.artist}{track.album?' · '+track.album:''}</span>
             {track.score!==null&&<small>Fingerprint score {track.score} (uncalibrated)</small>}
           </li>)}</ol>:<p>Try a clearer recording, longer fingerprint sample, or a different catalog with new consent.</p>}
           <p>{result.transferred} · {result.duration_seconds}s analyzed</p>
           <small>Unverified suggestions. Music, voices and game effects may overlap. STAR has not stored the waveform.</small>
         </section>}
       </div>
       <div className="music-actions">
         <span><Shield size={14}/> Consent resets after each lookup</span>
         <button type="button" className="music-primary" disabled={busy||!canIdentify(status,provider,source,consent,seconds,status?.fpcalc_selected===true)} onClick={()=>void identify()}>
           {busy?<LoaderCircle size={16} className="spin"/>:<Music2 size={16}/>}
           {busy?'Working…':'Identify song'}
         </button>
       </div>
     </Dialog.Content>
   </Dialog.Portal>
 </Dialog.Root>
}
