/**
 * Media in the interface.
 *
 * `MediaPlaces` (Settings): for images, voice and video understanding the owner chooses between
 * "STAR Brains (servers)" and "This PC (your GPU)". Each option carries the host's own note, built
 * from measurements. An option that settings could make available (for example by connecting STAR
 * Server) is shown as unavailable with its reason and cannot be chosen. An option that cannot exist
 * on this install (the host marks it `fixable: false`, e.g. images on servers with no graphics card)
 * is not drawn as a dead choice: the capability says where it runs, and the reason sits behind
 * "Why not ...?". Below it: the image engine on this PC (state, start, give memory back).
 *
 * `ReferencesPanel` (Projects): the approved reference images pinned to the current project and
 * the "compare with reference" step (side by side, measured facts, the vision model's differences).
 *
 * Every text about speed or availability comes from the host (star/media_places.py); this file
 * never states a number of its own.
 */
import {useCallback,useEffect,useRef,useState} from 'react'
import {Columns2,Cpu,ImagePlus,Images,LoaderCircle,Pin,RefreshCw,Trash2} from 'lucide-react'
import {onBackendEvent} from './bridge'
import {EmptyState} from './states'
import type {AbPair,AbSummary,AppSettings,MediaCapability,MediaComparison,MediaReference,MediaStatus} from './types'
import './learning.css'
import './media.css'

type Invoke=(action:string,params?:Record<string,unknown>)=>Promise<unknown|null>
type Pending={pending?:boolean;requestId?:string}

/** "This PC (your GPU)" → "this PC (your GPU)", "STAR Brains (servers)" → "the STAR Brains (servers)": for "Runs on ...". */
export function inSentence(label:string):string{
 return /^this /i.test(label)?'this '+label.slice(5):'the '+label
}
/** "STAR Brains (servers)" → "the STAR Brains", "This PC (your GPU)" → "this PC": for "Why not ...?". */
export function placeName(label:string):string{
 const bare=label.replace(/\s*\(.*\)\s*$/,'').trim()||label
 return /^this /i.test(bare)?'this '+bare.slice(5):'the '+bare
}

/** Start a host action that answers later, and deliver its result (or its error text) once. */
function useLater(){
 const waiting=useRef(new Map<string,(kind:'result'|'error',data:unknown)=>void>())
 useEffect(()=>onBackendEvent(event=>{
   const done=waiting.current.get(event.requestId)
   if(!done||event.kind==='progress'||event.kind==='voice')return
   waiting.current.delete(event.requestId)
   done(event.kind,event.data)
 }),[])
 return useCallback(async(invoke:Invoke,action:string,params:Record<string,unknown>,done:(kind:'result'|'error',data:unknown)=>void)=>{
   const reply=await invoke(action,params) as Pending|null
   if(reply?.pending&&reply.requestId)waiting.current.set(reply.requestId,done)
   else done(reply?'result':'error',reply)
 },[])
}

export function MediaPlaces({settings,invoke,disabled=false,refresh}:{settings:AppSettings;invoke:Invoke;disabled?:boolean;refresh?:()=>void}){
 const [status,setStatus]=useState<MediaStatus|null>(null)
 const [busy,setBusy]=useState('')
 const [notice,setNotice]=useState('')
 const [folder,setFolder]=useState(settings.comfy_home||'')
 const [ffmpeg,setFfmpeg]=useState(settings.ffmpeg_dir||'')
 const [imageServer,setImageServer]=useState(settings.media_images_server||'')
 const later=useLater()
 const load=useCallback(()=>{
   if(disabled)return
   setBusy(b=>b||'status')
   void later(invoke,'mediaStatus',{},(kind,data)=>{
     setBusy(b=>b==='status'?'':b)
     if(kind==='result'&&data)setStatus(data as MediaStatus)
   })
 },[disabled,invoke,later])
 useEffect(()=>{load()},[load])
 useEffect(()=>{setFolder(settings.comfy_home||'');setFfmpeg(settings.ffmpeg_dir||'');setImageServer(settings.media_images_server||'')},[settings.comfy_home,settings.ffmpeg_dir,settings.media_images_server])
 const save=async(changes:Record<string,unknown>)=>{
   if(disabled)return
   setNotice('')
   const saved=await invoke('saveSettings',{settings:changes})
   if(saved){refresh?.();load()}
 }
 const run=(action:'mediaStartComfy'|'mediaFreeMemory',label:string)=>{
   if(disabled||busy)return
   setBusy(action);setNotice(label)
   void later(invoke,action,{},(kind,data)=>{
     setBusy('')
     const info=(data||{}) as {message?:string;freed?:boolean}
     setNotice(kind==='error'?String(data||'That did not work.').slice(0,400):action==='mediaFreeMemory'?(info.freed?'ComfyUI unloaded its models; the graphics memory is free again.':'ComfyUI did not confirm.'):String(info.message||'Done.'))
     load()
   })
 }
 const chooseFolder=async()=>{
   const picked=await invoke('selectFolder') as {path?:string}|null
   if(picked?.path){setFolder(picked.path);await save({comfy_home:picked.path})}
 }
 const engine=status?.images
 return <section className="learn" aria-label="Where STAR generates">
   <div className="learn-head"><Cpu size={20}/><div className="learn-title"><h2>Where STAR generates</h2>
     <p>Where each kind of work runs: on the STAR Brains (your servers) or on this PC's graphics card. The notes are measurements from your own hardware; where a number is an estimate it says so. A place that is not available is never silently replaced by the other one.</p></div></div>
   {!status&&<p className="learn-help">{disabled?'Open STAR Desktop to see and change this.':'Reading the current state…'}</p>}
   {status?.places.map((capability:MediaCapability)=>{
     // A place this install can never offer is explained, not drawn as a dead choice (unless it is the saved one).
     const never=capability.options.filter(option=>!option.available&&option.fixable===false&&option.id!==capability.chosen)
     const choices=capability.options.filter(option=>!never.includes(option))
     const only=choices.length===1&&choices[0].id===capability.chosen&&choices[0].available?choices[0]:null
     const why=never.map(option=><details key={option.id} className="media-why"><summary>Why not {placeName(option.label)}?</summary><p>{option.reason}</p></details>)
     if(only)return <div key={capability.id} className="media-capability" role="group" aria-label={capability.title}>
       <h3>{capability.title}</h3>
       <div className="media-options"><div className="media-option is-chosen is-fixed">
         <span className="media-option-text"><strong>Runs on {inSentence(only.label)}</strong>{only.note&&<small>{only.note}</small>}</span>
       </div></div>
       {why}
     </div>
     return <div key={capability.id} className="media-capability" role="radiogroup" aria-label={capability.title}>
     <h3>{capability.title}</h3>
     <div className="media-options">
       {choices.map(option=>{
         const chosen=capability.chosen===option.id
         return <label key={option.id} className={'media-option'+(chosen?' is-chosen':'')+(option.available?'':' is-unavailable')}>
           <input type="radio" name={'media-'+capability.id} checked={chosen} disabled={disabled||!option.available} onChange={()=>void save({[capability.field]:option.id})}/>
           <span className="media-option-text"><strong>{option.label}{option.available?'':' (unavailable)'}</strong>
             {option.reason&&<small className="media-unavailable">{option.reason}</small>}
             {option.note&&<small>{option.note}</small>}</span>
         </label>
       })}
     </div>
     {capability.options.some(option=>option.id===capability.chosen&&!option.available)&&<p className="media-warning">The chosen place is not available, so {capability.title.toLowerCase()} will stop with that explanation until you choose the other one.</p>}
     {why}
   </div>})}
   {status&&<div className="media-capability">
     <h3>Image engine on this PC</h3>
     <div className="media-engine">
       <span className={'media-engine-state'+(engine?.ready?' is-ready':'')}>{engine?.ready?`Ready: ${engine.model}${engine.version?' on ComfyUI '+engine.version:''}.`:engine?.message||'Not checked yet.'}</span>
       <button type="button" className="learn-button" disabled={disabled||!!busy} onClick={load}>{busy==='status'?<LoaderCircle size={14} className="spin"/>:<RefreshCw size={14}/>} Check again</button>
       {!engine?.running&&<button type="button" className="learn-button is-primary" disabled={disabled||!!busy||!status.can_start} title={status.can_start?'':'Set the ComfyUI folder below first'} onClick={()=>run('mediaStartComfy','Starting ComfyUI on this PC. The first start can take a minute…')}>{busy==='mediaStartComfy'&&<LoaderCircle size={14} className="spin"/>} Start ComfyUI</button>}
       {engine?.running&&<button type="button" className="learn-button" disabled={disabled||!!busy} onClick={()=>run('mediaFreeMemory','Asking ComfyUI to unload its models…')}>Free graphics memory</button>}
     </div>
     <div className="media-fields">
       <label className="media-field">ComfyUI folder (the one that contains main.py)
         <input type="text" value={folder} placeholder={status.detected_home?'Found automatically (see below)':'Not set: start ComfyUI yourself'} onChange={event=>setFolder(event.target.value)} onBlur={()=>{if(folder!==(settings.comfy_home||''))void save({comfy_home:folder.trim()})}}/>
         <small><button type="button" className="learn-button" disabled={disabled} onClick={()=>void chooseFolder()}>Choose folder</button> STAR starts it for this PC only (127.0.0.1) and stops it when STAR closes.{!folder.trim()&&status.detected_home&&<> Found automatically: {status.detected_home}. STAR uses it until you choose another folder.</>}</small></label>
       <label className="media-field">Image service on the servers
         <input type="text" value={imageServer} placeholder="Not set, for example http://<server address>:8095" onChange={event=>setImageServer(event.target.value)} onBlur={()=>{if(imageServer!==(settings.media_images_server||''))void save({media_images_server:imageServer.trim()})}}/>
         <small>Address of STAR's image service on your home network (it uses the STAR Server key). Needed for Images on the STAR Brains or Automatic.</small></label>
       <label className="media-field">FFmpeg folder (for video files)
         <input type="text" value={ffmpeg} placeholder="Not set: FFmpeg is looked up on PATH" onChange={event=>setFfmpeg(event.target.value)} onBlur={()=>{if(ffmpeg!==(settings.ffmpeg_dir||''))void save({ffmpeg_dir:ffmpeg.trim()})}}/>
         <small>{status.ffmpeg.message}</small></label>
       <label className="media-field">Picture size the brain reads
         <select value={String(settings.picture_max_side??1280)} disabled={disabled} onChange={event=>void save({picture_max_side:Number(event.target.value)})}>
           <option value="1024">1024 pixels (fastest)</option><option value="1280">1280 pixels (default)</option><option value="1920">1920 pixels (more detail, slower)</option><option value="0">Full size (slowest)</option></select>
         <small>Longer side of an attached picture as the STAR Server or the on-device brain reads it. Your file is never changed.</small></label>
       <label className="learn-switch"><span><strong>Use this project's visual references</strong><small>Pinned reference images are given to image generation, and to chat turns about how something looks.</small></span>
         <input type="checkbox" checked={settings.media_use_references!==false} disabled={disabled} onChange={event=>void save({media_use_references:event.target.checked})}/></label>
       <label className="learn-switch"><span><strong>Careful pictures</strong><small>STAR expands your request into a full prompt, draws a draft, and lets the vision model check it blind (legs, hands, text). A clearly good first draft is taken at once; otherwise up to the number of drafts below are drawn, and a flawed spot is repainted on its own. Words on a sign are read back and must match exactly, or STAR draws them itself. Slower; off draws one picture straight from your words.</small></span>
         <input type="checkbox" checked={settings.image_quality!==false} disabled={disabled} onChange={event=>void save({image_quality:event.target.checked})}/></label>
       <label className="media-field">Most drafts per picture
         <select value={String(settings.image_drafts??3)} disabled={disabled||settings.image_quality===false} onChange={event=>void save({image_drafts:Number(event.target.value)})}>
           <option value="1">1 (fastest)</option><option value="2">2</option><option value="3">3 (default)</option><option value="4">4</option><option value="5">5 (slowest)</option></select></label>
       <label className="media-field">Picture model
         <select value={settings.image_engine??'auto'} disabled={disabled} onChange={event=>void save({image_engine:event.target.value as 'auto'|'klein'|'zimage'})}>
           <option value="auto">Automatic (Z-Image Turbo when installed, else klein)</option><option value="klein">FLUX.2 klein 4B (about 6x faster)</option><option value="zimage">Z-Image Turbo</option></select></label>
     </div>
   </div>}
   {notice&&<p className="learn-notice" role="status">{notice}</p>}
 </section>
}

export function ReferencesPanel({project,invoke,disabled=false}:{project:string;invoke:Invoke;disabled?:boolean}){
 const [items,setItems]=useState<MediaReference[]>([])
 const [limit,setLimit]=useState(12)
 const [busy,setBusy]=useState('')
 const [notice,setNotice]=useState('')
 const [comparison,setComparison]=useState<MediaComparison|null>(null)
 const [confirming,setConfirming]=useState('')
 const later=useLater()
 const load=useCallback(async()=>{
   if(disabled)return
   const found=await invoke('listReferences') as {references?:MediaReference[];limit?:number}|null
   if(found?.references){setItems(found.references);setLimit(found.limit||12)}
 },[disabled,invoke])
 useEffect(()=>{setComparison(null);setNotice('');void load()},[load,project])
 const pin=async()=>{
   if(disabled||busy)return
   const picked=await invoke('pickFiles',{kind:'image'}) as string[]|null
   if(!picked?.length)return
   setBusy('pin');setNotice('')
   try{
     let added=0
     for(const file of picked){
       const done=await invoke('pinReference',{file}) as {references?:MediaReference[]}|null
       if(done?.references){setItems(done.references);added+=1}
     }
     if(added)setNotice(`${added===1?'1 reference':added+' references'} pinned to ${project}. STAR will be given ${added===1?'it':'them'} for image and UI work in this project.`)
   }finally{setBusy('')}
 }
 const remove=async(id:string)=>{
   if(disabled||busy)return
   setBusy('remove:'+id)
   try{
     const done=await invoke('unpinReference',{id}) as {references?:MediaReference[]}|null
     if(done?.references){setItems(done.references);setConfirming('');setNotice('Reference removed from this project. Your own file was not touched.')}
   }finally{setBusy('')}
 }
 const compare=async(id:string,pick:boolean)=>{
   if(disabled||busy)return
   let file:string|undefined
   if(pick){
     const picked=await invoke('pickFiles',{kind:'image'}) as string[]|null
     if(!picked?.length)return
     file=picked[0]
   }
   setBusy('compare:'+id);setComparison(null)
   setNotice('Comparing. STAR measures the two pictures here, then the vision model lists what differs; on the servers that takes about a minute.')
   void later(invoke,'compareReference',{id,...(file?{file}:{})},(kind,data)=>{
     setBusy('')
     if(kind==='error'||!data){setNotice(String(data||'The comparison could not run.').slice(0,400));return}
     setNotice('');setComparison(data as MediaComparison)
   })
 }
 return <section className="learn" aria-label="Visual references">
   <div className="learn-head"><Images size={20}/><div className="learn-title"><h2>Visual references for {project}</h2>
     <p>Pin the images you have approved for this project: a UI design, a screenshot, a style sheet. STAR is given them when it creates an image or builds a UI here, and "Compare" puts its output next to a reference and lists the concrete differences. You decide whether it matches; STAR only shows and lists.</p></div></div>
   <div className="learn-tools">
     <button type="button" className="learn-button is-primary" disabled={disabled||!!busy||items.length>=limit} onClick={()=>void pin()}><Pin size={14}/> Pin an image</button>
     <span className="learn-help">{items.length} of {limit} pinned</span>
   </div>
   {items.length===0?<EmptyState compact icon={<Images size={15}/>} title="No references yet for this project." description="Pin an approved design or screenshot and STAR uses it when it makes images or UI here."/>:
   <ul className="reference-grid">
     {items.map(item=><li key={item.id} className="reference-card">
       <img src={item.preview} alt={'Reference: '+item.label}/>
       <strong title={item.label}>{item.label}</strong>
       <small>{item.width} x {item.height}{item.note?' · '+item.note:''}</small>
       <div className="learn-tools">
         <button type="button" className="learn-button" disabled={disabled||!!busy} onClick={()=>void compare(item.id,false)}>{busy==='compare:'+item.id?<LoaderCircle size={14} className="spin"/>:<ImagePlus size={14}/>} Compare latest image</button>
         <button type="button" className="learn-button" disabled={disabled||!!busy} onClick={()=>void compare(item.id,true)}>Compare a file</button>
         {confirming===item.id
           ?<button type="button" className="learn-button is-danger" disabled={disabled||!!busy} onClick={()=>void remove(item.id)}>Remove for good</button>
           :<button type="button" className="learn-button" aria-label={'Remove reference '+item.label} disabled={disabled||!!busy} onClick={()=>setConfirming(item.id)}><Trash2 size={14}/></button>}
       </div>
     </li>)}
   </ul>}
   {notice&&<p className="learn-notice" role="status">{notice}</p>}
   {comparison&&<div className="reference-compare" aria-label="Comparison with the reference">
     <img src={comparison.image} alt={`Reference ${comparison.reference.label} beside STAR's output ${comparison.candidate}`}/>
     <h3>Differences the vision model sees{comparison.model?` (${comparison.model}, ${comparison.seconds} s)`:''}</h3>
     {comparison.model_error
       ?<p className="media-warning">The vision model could not be asked ({comparison.model_error}). The measured differences below still stand.</p>
       :<ul>{comparison.differences.map((line,index)=><li key={index}>{line}</li>)}</ul>}
     <h3>Measured on this PC</h3>
     <ul>{comparison.measured.lines.map((line,index)=><li key={index}>{line}</li>)}</ul>
     <p className="learn-help">Saved in your STAR data folder under comparisons/{comparison.saved}.</p>
   </div>}
 </section>
}

/**
 * The owner's blind A/B test of the old and the new picture pipeline. Two pictures of one prompt, sides at random (decided
 * and stored by the host, never revealed here); the owner picks the better one or says they look the same. The summary is
 * the host's: counts, the new pipeline's win rate and a plain verdict from a sign test.
 */
export function ImageAbPanel({invoke,disabled=false}:{invoke:Invoke;disabled?:boolean}){
 const [pair,setPair]=useState<AbPair|null>(null)
 const [summary,setSummary]=useState<AbSummary|null>(null)
 const [busy,setBusy]=useState('')
 const [notice,setNotice]=useState('')
 const [prompt,setPrompt]=useState('')
 const later=useLater()
 const load=useCallback(async()=>{
   if(disabled)return
   const next=await invoke('imageAbNext') as {pair?:AbPair|null;summary?:AbSummary}|null
   if(next){setPair(next.pair??null);if(next.summary)setSummary(next.summary)}
 },[disabled,invoke])
 useEffect(()=>{void load()},[load])
 const pick=async(side:'left'|'right'|'tie')=>{
   if(disabled||busy||!pair)return
   setBusy('pick');setNotice('')
   try{
     const done=await invoke('imageAbPick',{id:pair.id,side}) as {summary?:AbSummary}|null
     if(done?.summary)setSummary(done.summary)
     await load()
   }finally{setBusy('')}
 }
 const make=()=>{
   const text=prompt.trim()
   if(disabled||busy||!text)return
   setBusy('make');setNotice('Drawing the same prompt with the old and the new pipeline. This takes about five minutes; you can leave this page.')
   void later(invoke,'imageAbMake',{prompt:text},(kind,data)=>{
     setBusy('')
     if(kind==='error'||!data){setNotice(String(data||'The comparison could not be made.').slice(0,400));return}
     setNotice('A new pair is ready.');setPrompt('');void load()
   })
 }
 return <section className="learn" aria-label="Picture quality blind test">
   <div className="learn-head"><Columns2 size={20}/><div className="learn-title"><h2>Picture quality: blind test</h2>
     <p>Two pictures of the same prompt, one from the old pipeline and one from the new, in random order. Pick the one you like better, or say they look the same. STAR keeps your picks and tells you at the end whether the new pipeline really is better; it does not show which is which until then.</p></div></div>
   {pair
     ?<div className="ab-pair" aria-label={'Which picture is better for: '+pair.prompt}>
       <p className="ab-prompt">{pair.prompt}</p>
       <div className="ab-images">
         <figure><img src={pair.left} alt="Left picture"/><button type="button" className="learn-button is-primary" disabled={disabled||!!busy} onClick={()=>void pick('left')}>Left is better</button></figure>
         <figure><img src={pair.right} alt="Right picture"/><button type="button" className="learn-button is-primary" disabled={disabled||!!busy} onClick={()=>void pick('right')}>Right is better</button></figure>
       </div>
       <div className="learn-tools"><button type="button" className="learn-button" disabled={disabled||!!busy} onClick={()=>void pick('tie')}>They look the same</button>
         <span className="learn-help">{pair.waiting} pair{pair.waiting===1?'':'s'} waiting</span></div>
     </div>
     :<EmptyState compact icon={<Columns2 size={15}/>} title="No pair waiting." description="Draw a new pair below. STAR makes the same prompt twice, once with each pipeline."/>}
   {summary&&summary.picked>0&&<div className="ab-summary" role="status" aria-label="Blind test result">
     <p><strong>{summary.verdict}</strong></p>
     <p className="learn-help">{summary.picked} picked · new {summary.new} · old {summary.old} · same {summary.tie}{summary.new_rate!==null?` · new wins ${Math.round(summary.new_rate*100)}% of the decided pairs`:''}</p>
   </div>}
   <div className="learn-tools ab-make">
     <input type="text" value={prompt} maxLength={400} disabled={disabled||!!busy} placeholder="A prompt for a new pair, for example a horse galloping across a field" aria-label="Prompt for a new pair" onChange={event=>setPrompt(event.target.value)}/>
     <button type="button" className="learn-button" disabled={disabled||!!busy||!prompt.trim()} onClick={make}>{busy==='make'?<LoaderCircle size={14} className="spin"/>:<ImagePlus size={14}/>} Draw a new pair</button>
   </div>
   {notice&&<p className="learn-notice" role="status">{notice}</p>}
 </section>
}
