import {useEffect,useState} from 'react'
import {request} from './bridge'
import './BrainOverview.css'
import {MachineLoad} from './MachineLoad'
import {BulkTasksPanel} from './BulkTasksPanel'

export type BrainSnapshot = {
 provider: string
 models: string[]
 configured_models?: string[]
 roles: Array<{role:string;label:string;model:string;source:string}>
 knowledge: Array<{name:string;connected:boolean}>
 skills: {enabled:boolean;count:number;names:string[]}
 lessons: {candidate:number;accepted:number;retired:number}
 tools: string[]
 evaluation: null|Record<string,string|number|boolean>
}

const empty:BrainSnapshot={provider:'',models:[],roles:[],knowledge:[],skills:{enabled:false,count:0,names:[]},lessons:{candidate:0,accepted:0,retired:0},tools:[],evaluation:null}
function Card({title,count,facts}:{title:string;count:number|null;facts:string[]}) {
 return <section className="brain-overview-card" aria-label={title}><h3>{title}</h3><strong>{count===null?'not set up':count}</strong><ul>{facts.filter(Boolean).slice(0,3).map(item=><li key={item}>{item}</li>)}{!facts.some(Boolean)&&<li>not set up</li>}</ul></section>
}
export function BrainOverview({snapshot,load=true}:{snapshot?:BrainSnapshot;load?:boolean}) {
 const [data,setData]=useState<BrainSnapshot>(snapshot||empty)
 const [error,setError]=useState('')
 useEffect(()=>{
  if(!load)return
  let active=true
  void request<BrainSnapshot>('brainSnapshot').then(result=>{if(!active)return;if(result.ok&&result.data){setData(result.data);setError('')}else setError('Brain information could not be loaded.')})
  return ()=>{active=false}
 },[load])
 const connected=data.knowledge.filter(x=>x.connected)
 const lessons=data.lessons.candidate+data.lessons.accepted+data.lessons.retired
 const roles=data.roles.filter(x=>x.model)
 const configured=data.configured_models||[]
 const skillCount=data.skills.enabled?data.skills.count:0
 return <><section className="brain-overview" aria-label="STAR Brain overview">
  <header><h2>Inside STAR</h2><p>Current configuration and local records · read only</p></header>
  {error&&<p role="alert">{error}</p>}
  <div className="brain-overview-grid">
   <Card title="Thinking" count={data.models.length||configured.length||null} facts={[data.provider?`Provider: ${data.provider}`:'',data.models.length?`${data.models.length} discovered`:(configured.length?`${configured.length} configured (not verified)`:''),...roles.slice(0,1).map(r=>`${r.label}: ${r.model}`)]}/>
   <Card title="Knowledge" count={data.knowledge.length?connected.length:null} facts={connected.map(x=>x.name)}/>
   <Card title="Skills" count={data.skills.enabled?skillCount:null} facts={[data.skills.enabled?'Enabled':'Off',...data.skills.names.slice(0,2)]}/>
   <div className="brain-overview-center"><span>STAR</span><small>Local-first assistant</small></div>
   <Card title="Memory" count={lessons||null} facts={lessons?[`${data.lessons.candidate} candidate`,`${data.lessons.accepted} accepted`,`${data.lessons.retired} retired`]:[]}/>
   <Card title="Hands" count={data.tools.length||null} facts={data.tools.slice(0,3)}/>
   <Card title="Senses" count={data.evaluation?Object.keys(data.evaluation).length:null} facts={data.evaluation?Object.entries(data.evaluation).slice(0,3).map(([k,v])=>`${k}: ${v}`):[]}/>
  </div>
  <MachineLoad load={load}/>
 </section><BulkTasksPanel disabled={!load}/></>
}
