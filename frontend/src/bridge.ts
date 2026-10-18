import type { BackendEvent } from './types'

declare global {
  interface Window {
    qt?: { webChannelTransport: unknown }
    QWebChannel?: new (transport: unknown, callback:(channel: {objects: {starBridge: QtBridge}}) => void) => void
    starBridge?: QtBridge
  }
}
interface QtBridge {
  invoke: (serialized:string, callback:(result:string) => void) => void
  event: { connect:(callback:(event:string) => void) => void }
}

let bridge:QtBridge|null = null
let initializing:Promise<boolean>|null = null
const watchers = new Set<(event:BackendEvent) => void>()
export const isDesktop = () => bridge !== null

export function onBackendEvent(fn:(event:BackendEvent)=>void) {
  watchers.add(fn)
  return () => { watchers.delete(fn) }
}
function parseEvent(raw:string) {
  try { const event = JSON.parse(raw) as BackendEvent; watchers.forEach(fn=>fn(event)) }
  catch { /* Invalid native events cannot crash the React render tree. */ }
}
/** StrictMode and fast reloads must not establish duplicate WebChannel subscriptions. */
export function initializeBridge():Promise<boolean>{
  if(bridge)return Promise.resolve(true)
  if(!window.qt?.webChannelTransport)return Promise.resolve(false)
  if(initializing)return initializing
  initializing=new Promise(resolve=>{
    const finish=(ready:boolean)=>{
      if(!ready)initializing=null
      resolve(ready)
    }
    const connect=()=>{
      if(!window.QWebChannel){finish(false);return}
      try{
        new window.QWebChannel(window.qt!.webChannelTransport,channel=>{
          const native=channel.objects?.starBridge
          if(!native){finish(false);return}
          bridge=native
          window.starBridge=native
          native.event.connect(parseEvent)
          finish(true)
        })
      }catch{finish(false)}
    }
    if(window.QWebChannel)connect()
    else{
      const script=document.createElement('script')
      script.src='qrc:///qtwebchannel/qwebchannel.js'
      script.async=true
      script.onload=connect
      script.onerror=()=>finish(false)
      document.head.append(script)
    }
  })
  return initializing
}

export type BackendReply<T> = {ok:boolean;data?:T; pending?:boolean;requestId?:string;error?:string}

/** Native file dialogs wait on the user, not the model. Do not falsely report a
 *  broken desktop connection if choosing a file takes over 30 seconds. */
export function requestTimeoutMs(action:string):number {
  return action==='pickFiles'||action==='selectFolder'||action==='clipChooseFolder'||action==='exportReviewBundle'||action==='exportLessons'||action==='musicChooseWav'||action==='musicChooseFpcalc'||action==='qualityChooseFile'
    ? 10*60*1000 : 30*1000
}
export function request<T=unknown>(action:string, payload:Record<string,unknown>={}, providedId?:string):Promise<BackendReply<T>> {
  if(!bridge)return Promise.resolve({ok:false,error:'Open STAR Desktop to use your local AI. This website is only a preview.'})
  return new Promise(resolve=>{
    const requestId=providedId||crypto.randomUUID()
    let settled=false
    const finish=(response:BackendReply<T>)=>{
      if(settled)return
      settled=true
      window.clearTimeout(timeout)
      resolve(response)
    }
    const timeout=window.setTimeout(()=>finish({ok:false,error:'STAR local bridge did not respond. Restart the desktop app and try again.'}),requestTimeoutMs(action))
    try{
      bridge!.invoke(JSON.stringify({requestId,action,...payload}),raw=>{
        try{finish(JSON.parse(raw) as BackendReply<T>)}
        catch{finish({ok:false,error:'STAR returned an invalid desktop response.'})}
      })
    }catch{finish({ok:false,error:'STAR desktop connection is unavailable.'})}
  })
}
