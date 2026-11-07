import {useCallback,useEffect,useRef,useState} from 'react'
import {Activity,Check,Clock3,LockKeyhole,Pause,Play,RefreshCw,ShieldAlert,ShieldCheck} from 'lucide-react'
import {request} from './bridge'
import './commerce-pilot.css'

type Finding = {
  id:string;supplier:string;sku:string;code:string
  severity:'critical'|'warning';detail:string
  state:'open'|'dismissed'|'resolved';created_at:string;updated_at:string
}
type PilotReport = {
  project:string;business_id:string;business_name:string;business_paused:boolean
  monitoring:{
    enabled:boolean;minimum_stock:number;minimum_margin_pct:number
    maximum_delivery_days:number;stale_after_days:number;interval_minutes:number
    last_run:string|null;last_scanned:number
  }
  finding_counts:{open:number;dismissed:number;resolved:number}
  findings:Finding[]
  audit:{event:string;at:string}[]
  scan_result?:{state:string;scanned:number;opened:number;closed:number;external_actions?:0}
  execution:'deterministic_local_records_only'
  requires_desktop_running:true
  external_connectors_active:false;automatic_supplier_refresh:false
  auto_send:false;auto_publish:false;auto_spend:false;auto_fulfill:false
}
type Policy = Pick<PilotReport['monitoring'],
  'minimum_stock'|'minimum_margin_pct'|'maximum_delivery_days'|'stale_after_days'|'interval_minutes'>
const POLICY_DEFAULT:Policy={
  minimum_stock:3,minimum_margin_pct:25,maximum_delivery_days:14,
  stale_after_days:7,interval_minutes:60,
}
const controlFields:{
  key:keyof Policy;name:string;description:string;min:number;max:number;step:number
}[]=[
  {key:'minimum_stock',name:'Low-stock buffer',description:'Reported units',min:0,max:500,step:1},
  {key:'minimum_margin_pct',name:'Minimum contribution',description:'Modeled percentage before ads',min:5,max:70,step:1},
  {key:'maximum_delivery_days',name:'Maximum shipping window',description:'Supplier-estimated days',min:1,max:30,step:1},
  {key:'stale_after_days',name:'Supplier evidence expires',description:'Days since last changed import',min:1,max:90,step:1},
  {key:'interval_minutes',name:'Local check interval',description:'Minutes while desktop runs',min:15,max:1440,step:15},
]
const timeLabel=(value:string|null)=>{
  if(!value)return 'Never'
  const time=new Date(value)
  return Number.isNaN(time.valueOf())?'Unrecognized timestamp':time.toLocaleString()
}
export function CommercePilot({businessId,project,preview}:{
  businessId:string;project:string;preview:boolean
}) {
  const [report,setReport]=useState<PilotReport|null>(null)
  const [policy,setPolicy]=useState<Policy>(POLICY_DEFAULT)
  const [confirmed,setConfirmed]=useState(false)
  const [busy,setBusy]=useState(false)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [showHistory,setShowHistory]=useState(false)
  const generation=useRef(0)
  const available=!!businessId&&!preview

  const accept=(next:PilotReport)=>{
    setReport(next)
    const m=next.monitoring
    setPolicy({
      minimum_stock:m.minimum_stock,minimum_margin_pct:m.minimum_margin_pct,
      maximum_delivery_days:m.maximum_delivery_days,stale_after_days:m.stale_after_days,
      interval_minutes:m.interval_minutes,
    })
  }
  const refresh=useCallback(async()=>{
    const id=++generation.current
    if(!available){setReport(null);setLoading(false);return}
    setLoading(true);setError('')
    const reply=await request<PilotReport>('commercePilot',{business_id:businessId})
    if(id!==generation.current)return
    if(reply.ok&&reply.data?.business_id===businessId)accept(reply.data)
    else setError(reply.error||'Could not load the local safety monitor.')
    setLoading(false)
  },[businessId,available])
  useEffect(()=>{void refresh();return()=>{generation.current++}},[refresh,project])
  useEffect(()=>{setReport(null);setConfirmed(false);setError('');setNotice('');setBusy(false);setShowHistory(false)},[businessId,project])

  async function mutate(action:string,body:Record<string,unknown>,success:string){
    if(!available||busy||!confirmed)return
    const id=generation.current
    setBusy(true);setError('');setNotice('')
    const reply=await request<PilotReport>(action,{business_id:businessId,...body,owner_confirmed:true})
    if(id!==generation.current)return
    if(reply.ok&&reply.data?.business_id===businessId){
      accept(reply.data)
      const result=reply.data.scan_result
      setNotice(result
        ? result.state==='local_only_completed'
          ? 'Checked '+result.scanned+' imported offers; '+result.opened+' new review findings. No external actions.'
          : 'No scan performed: '+result.state.replaceAll('_',' ')+'.'
        : success)
      setConfirmed(false)
    }else setError(reply.error||'Operation was refused; no changes were saved.')
    setBusy(false)
  }
  const eligible=Object.entries(policy).every(([key,value])=>{
    const spec=controlFields.find(f=>f.key===key)
    return !!spec&&Number.isInteger(value)&&value>=spec.min&&value<=spec.max
  })
  const enabled=report?.monitoring.enabled===true
  const open=report?.findings.filter(f=>f.state==='open')??[]

  return <section className="commerce-pilot" aria-label="Commerce Pilot automation">
    <header className="commerce-pilot-top">
      <div><p className="commerce-kicker">STAR / LOCAL AUTOPILOT</p>
        <h2>Let the system watch the details.</h2>
        <p>Check supplier evidence, inventory risk, shipping, samples and hypothetical margins on a schedule—without making a financial or customer-facing decision.</p>
      </div>
      <button type="button" className="commerce-action-secondary" disabled={!available||loading||busy}
        onClick={()=>void refresh()} aria-label="Refresh Commerce Pilot"><RefreshCw size={15}/> Refresh</button>
    </header>
    {!available?<p className="commerce-pilot-empty">Choose a Shopify business in STAR Desktop to configure its private automation.</p>:<>
      <div className="commerce-pilot-trust" role="status"><LockKeyhole size={16}/>
        <span>All actions are local. Supplier feeds do not refresh automatically. Email, ads, publishing and purchases remain disconnected.</span>
      </div>
      {error&&<p className="commerce-ds-message is-error" role="alert"><ShieldAlert size={16}/>{error}</p>}
      {notice&&<p className="commerce-ds-message" role="status"><Check size={16}/>{notice}</p>}
      <div className="commerce-pilot-numbers" aria-label="Pilot status">
        <div><span>MONITORING</span><strong>{loading?'…':enabled?'ON':'OFF'}</strong><small>{report?.business_paused?'Business paused':enabled?'Opted in on this PC':'Needs owner opt-in'}</small></div>
        <div><span>REVIEW FINDINGS</span><strong>{report?.finding_counts.open??0}</strong><small>Unresolved imported-source risks</small></div>
        <div><span>LAST CHECK</span><strong className="is-time">{report?.monitoring.last_run?timeLabel(report.monitoring.last_run):'Not run'}</strong><small>{report?.monitoring.last_scanned??0} supplier offers checked</small></div>
      </div>
      <div className="commerce-pilot-columns">
        <div className="commerce-pilot-settings">
          <div className="commerce-pilot-section-head"><ShieldCheck size={17}/><h3>Monitoring policy</h3></div>
          <div className="commerce-pilot-field-grid">
            {controlFields.map(field=><label className="commerce-pilot-field" key={field.key}>
              <span>{field.name}</span><small>{field.description}</small>
              <input type="number" min={field.min} max={field.max} step={field.step}
                value={policy[field.key]} onChange={event=>setPolicy(current=>({
                  ...current,[field.key]:event.target.value===''?-1:Number(event.target.value),
                }))}/>
            </label>)}
          </div>
          <label className="commerce-ds-checkbox commerce-pilot-consent">
            <input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>
            <span>I authorize STAR to change private local monitoring settings and run checks, not to contact anyone, spend money, publish listings or purchase stock.</span>
          </label>
          <div className="commerce-pilot-controls">
            <button type="button" className="commerce-action-primary" disabled={!report||busy||!confirmed||!eligible}
              onClick={()=>void mutate('commercePilotConfigure',{...policy,enabled:!enabled},
                enabled?'Local automatic checks disabled.':'Local automatic checks enabled while STAR Desktop runs.')}>
              {enabled?<Pause size={15}/>:<Play size={15}/>}
              {enabled?'Save policy & switch off':'Save policy & switch on'}
            </button>
            <button type="button" className="commerce-action-secondary" disabled={!report||busy||!confirmed||!!report.business_paused}
              onClick={()=>void mutate('commercePilotScan',{},
                'Private supplier evidence scan completed.')}>
              <Activity size={15}/> Run a local check
            </button>
          </div>
          <p className="commerce-pilot-footnote"><Clock3 size={13}/>
            This automation runs only when STAR Desktop is open, the business is unpaused and monitoring is enabled. It rechecks the last authorized imported evidence, not live supplier inventory.</p>
        </div>
        <aside className="commerce-pilot-issues">
          <div className="commerce-pilot-section-head"><ShieldAlert size={17}/><h3>Exceptions to review</h3><span>{open.length} shown</span></div>
          {open.length===0?<div className="commerce-pilot-empty">
            <strong>No open findings</strong>
            <p>{report?.monitoring.last_run?'No current flags under the configured local rules. This is not supplier approval.':'Run a check after importing real supplier evidence. Empty does not mean safe to sell.'}</p>
          </div>:<div className="commerce-pilot-findings">
            {open.slice(0,24).map(item=><article key={item.id} className="commerce-pilot-finding">
              <div className="commerce-pilot-finding-head">
                <span className={'commerce-pilot-severity is-'+item.severity}>{item.severity}</span>
                <small>{item.supplier} · {item.sku}</small>
              </div><p>{item.detail}</p>
              <button type="button" disabled={busy||!confirmed}
                onClick={()=>void mutate('commercePilotDismiss',{id:item.id},
                  'Finding dismissed. It reopens when the evidence changes.')}>Mark reviewed</button>
            </article>)}
            {open.length>24&&<small>Showing the first 24 findings. Additional items remain in the local review queue.</small>}
          </div>}
          <button type="button" className="commerce-pilot-history-toggle" aria-expanded={showHistory}
            onClick={()=>setShowHistory(current=>!current)}>{showHistory?'Hide':'Show'} audit activity</button>
          {showHistory&&<div className="commerce-pilot-history">
            {report?.audit.length?report.audit.map((event,index)=><div key={index}>
              <span>{event.event.replaceAll('_',' ')}</span><time>{timeLabel(event.at)}</time>
            </div>):<p>No local monitoring decisions recorded.</p>}
          </div>}
        </aside>
      </div>
    </>}
  </section>
}
