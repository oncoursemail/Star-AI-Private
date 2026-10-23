import {useEffect,useRef,useState} from 'react'
import {motion,useSpring} from 'motion/react'
import {useStarReducedMotion} from './MotionPolicy'
import {usePageVisible} from './usePageVisible'

/** The owner-approved Star art (frontend/public/assets/mascot), relative so the packaged app can load it from a file. */
const faces='./assets/mascot/faces/'

/** What Star is doing, in the conversation's terms. Each mood maps to one approved face. */
export type StarMood='idle'|'listening'|'thinking'|'writing'|'happy'|'oops'|'stopped'|'looking'
const FACE:Record<StarMood,string>={
 idle:'normal',listening:'happy',thinking:'thinking',writing:'focused',happy:'happy',oops:'nervous',stopped:'surprised',looking:'puppy-eyes',
}
export const starFaceSource=(mood:StarMood)=>faces+FACE[mood]+'.png'
/** Faces whose eyes line up with the closed-eye "content" face, so a blink can be composited over them. */
const BLINKS:ReadonlySet<StarMood>=new Set(['idle','listening','looking'])

/**
 * Star, the mascot, as a small living face.
 *
 * Motion has a job here: it says STAR is present and what it is doing. A slow breath while
 * idle, a blink every few seconds, a tilt while thinking, one soft pop when an answer lands,
 * and (only where `follow` is set, i.e. the empty chat) a gentle lean toward the pointer on a
 * spring. Expressions cross-fade with a 2px blur so two faces never read as two objects.
 * Reduced motion (OS or STAR's own setting) shows the right face and nothing moves.
 */
export function StarFace({mood='idle',size=64,follow=false,className='',label}:{mood?:StarMood;size?:number;follow?:boolean;className?:string;label?:string}){
 const reduced=useStarReducedMotion()
 const visible=usePageVisible()
 const still=reduced||!visible
 const [{shown,leaving},setFrame]=useState<{shown:StarMood;leaving:StarMood|null}>({shown:mood,leaving:null})
 const previousMood=useRef(mood)
 const [failed,setFailed]=useState(false)
 const root=useRef<HTMLSpanElement>(null)
 const tiltX=useSpring(0,{stiffness:120,damping:16,mass:0.6})
 const tiltY=useSpring(0,{stiffness:120,damping:16,mass:0.6})
 const turn=useSpring(0,{stiffness:120,damping:16,mass:0.6})
 // Cross-fade between expressions; the old face leaves while the new one settles in.
 useEffect(()=>{
  const previous=previousMood.current
  previousMood.current=mood
  if(still){setFrame({shown:mood,leaving:null});return}
  if(mood===previous)return
  setFrame({shown:mood,leaving:previous})
  // The displayed frame is deliberately not an effect dependency: updating it must
  // not clean up the timeout that removes the outgoing expression.
  const timer=window.setTimeout(()=>setFrame(frame=>({...frame,leaving:null})),240)
  return ()=>window.clearTimeout(timer)
 },[mood,still])
 // Warm the cache for the faces a conversation moves through, so a change never flashes empty.
 useEffect(()=>{
  for(const next of ['thinking','focused','happy','normal'] as const){const image=new Image();image.src=faces+next+'.png'}
 },[])
 useEffect(()=>{
  if(!follow||still){tiltX.set(0);tiltY.set(0);turn.set(0);return}
  let frame=0
  const onMove=(event:PointerEvent)=>{
   cancelAnimationFrame(frame)
   frame=requestAnimationFrame(()=>{
    const box=root.current?.getBoundingClientRect()
    if(!box)return
    const dx=(event.clientX-(box.left+box.width/2))/Math.max(320,window.innerWidth/2)
    const dy=(event.clientY-(box.top+box.height/2))/Math.max(320,window.innerHeight/2)
    const clamp=(v:number)=>Math.max(-1,Math.min(1,v))
    tiltX.set(clamp(dx)*4);tiltY.set(clamp(dy)*3);turn.set(clamp(dx)*5)
   })
  }
  const settle=()=>{tiltX.set(0);tiltY.set(0);turn.set(0)}
  window.addEventListener('pointermove',onMove,{passive:true})
  document.addEventListener('pointerleave',settle)
  return ()=>{cancelAnimationFrame(frame);window.removeEventListener('pointermove',onMove);document.removeEventListener('pointerleave',settle)}
 },[follow,still,tiltX,tiltY,turn])
 if(failed)return null
 return <span ref={root} className={'star-face '+className} data-mood={shown} data-still={still||undefined}
  style={{width:size,height:size}} role={label?'img':undefined} aria-label={label} aria-hidden={label?undefined:true}>
  <motion.span className="star-face-lean" style={{x:tiltX,y:tiltY,rotate:turn}}>
   <span className="star-face-body" key={still?'still':shown==='happy'?'pop':'calm'}>
    {leaving&&<img className="star-face-img is-leaving" src={starFaceSource(leaving)} alt="" draggable={false}/>}
    <img className={'star-face-img'+(leaving?' is-entering':'')} src={starFaceSource(shown)} alt="" draggable={false} onError={()=>setFailed(true)}/>
    {!still&&BLINKS.has(shown)&&!leaving&&<img className="star-face-img star-face-blink" src={faces+'content.png'} alt="" draggable={false}/>}
   </span>
  </motion.span>
 </span>
}
