import {useCallback,useEffect,useRef,useState} from 'react'
import {ArrowUpRight,Check,Clipboard,FileInput,LockKeyhole,PackageSearch,RefreshCw,ShieldAlert,Sparkles,TrendingUp} from 'lucide-react'
import {request} from './bridge'
import './commerce-dropshipping.css'
import {CommercePilot} from './CommercePilot'

type Offer = {
  sku:string;supplier:string;title:string;category:string;url:string
  unit_cost_cents:number;shipping_cents:number;price_cents:number
  stock:number;delivery_days:number;contribution_before_ads_cents:number
  estimated_contribution_ratio:number;break_even_cpa_cents:number;break_even_roas:number|null
  status:'cost_preflight_candidate'|'needs_evidence';blockers:string[]
  source_label:string;observed_at:string
}
type Signal = {sku:string;source:string;metric:string;value:number;observed_on:string}
type Support = {
  intent:string;draft:string;review_required:true;auto_send_allowed:false
  mailbox_connected:false;order_or_identity_verified:false;note:string
}
type Board = {
  business_id:string;business_name:string;mode:string;catalog_total:number;cost_preflight_candidates:number
  offers:Offer[];signals:Signal[];policy:{shipping:string;returns:string;contact:string;approved_at:string}|null
  marketing:{channel:string;route:string;state:string}[]
  fee_assumption:string;import_result?:{added?:number;updated?:number;unchanged?:number;changed?:number}
  support_draft?:Support;marketplace_connected:false;supplier_connected:false;gmail_connected:false
}
const offerHeader='supplier,sku,title,category,product_url,unit_cost,shipping_cost,target_price,stock,delivery_days,returns_supported,sample_reviewed'
const signalHeader='sku,source,metric,value,observed_on'
const money=(c:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(c/100)

export function CommerceDropshipping({businessId,project,preview}:{
  businessId:string;project:string;preview:boolean
}) {
  const [board,setBoard]=useState<Board|null>(null)
  const [loading,setLoading]=useState(false)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [tab,setTab]=useState<'products'|'research'|'support'|'autopilot'>('products')
  const [csv,setCsv]=useState('')
  const [source,setSource]=useState('Owner-authorized supplier catalog')
  const [ownerConfirmed,setConfirmed]=useState(false)
  const [customerInquiry,setCustomerInquiry]=useState('')
  const [shipping,setShipping]=useState('')
  const [returns,setReturns]=useState('')
  const [contact,setContact]=useState('')
  const [draft,setDraft]=useState<Support|null>(null)
  const generation=useRef(0)
  const usable=!!businessId&&!preview

  const refresh=useCallback(async()=>{
    const id=++generation.current
    if(!usable){setBoard(null);setLoading(false);return}
    setBoard(null);setLoading(true);setError('')
    const response=await request<Board>('commerceDropship',{business_id:businessId})
    if(id!==generation.current)return
    if(response.ok&&response.data?.business_id===businessId) {
      setBoard(response.data)
      setShipping(response.data.policy?.shipping||'')
      setReturns(response.data.policy?.returns||'')
      setContact(response.data.policy?.contact||'')
    } else setError(response.error||'Could not read dropshipping workspace.')
    setLoading(false)
  },[businessId,usable])
  useEffect(()=>{void refresh();return()=>{generation.current++}},[refresh,project])
  useEffect(()=>{
    setCsv('');setConfirmed(false);setDraft(null);setCustomerInquiry('')
    setNotice('');setTab('products');setBusy(false);setError('')
  },[businessId,project])

  async function run(action:string,payload:Record<string,unknown>,success:string) {
    if(!usable||busy)return false
    const id=generation.current
    setBusy(true);setError('');setNotice('')
    const response=await request<Board>(action,{business_id:businessId,...payload})
    if(id!==generation.current)return false
    if(response.ok&&response.data?.business_id===businessId){
      setBoard(response.data)
      setNotice(success)
      if(action==='commerceDropshipImportOffers'||action==='commerceDropshipImportSignals'){
        setCsv('');setConfirmed(false)
      }
      if(action==='commerceDropshipDraftReply')setDraft(response.data.support_draft||null)
      setBusy(false)
      return true
    }
    setError(response.error||'This local operation could not be completed.')
    setBusy(false)
    return false
  }

  const screened=board?.offers.filter(x=>x.status==='cost_preflight_candidate')||[]
  return <section className="commerce-ds" aria-label="Dropshipping intelligence">
    <header className="commerce-ds-head">
      <div>
        <p className="commerce-kicker">03 / DROPSHIPPING INTELLIGENCE</p>
        <h2>Source products. Measure the downside.</h2>
        <p>Supplier evidence, pricing, demand signals and customer assistance inside STAR. Live store, advertising and Gmail connections are not configured.</p>
      </div>
      <button className="commerce-action-secondary" type="button" disabled={!usable||busy||loading} onClick={()=>void refresh()}>
        <RefreshCw size={15}/> Refresh
      </button>
    </header>
    {!usable ? <div className="commerce-ds-empty"><PackageSearch size={26}/>
      <strong>{preview?'Private supplier information is unavailable in the website preview':'Choose a Shopify business above'}</strong>
      <p>Supplier candidates and customer inquiries stay in your private STAR desktop workspace.</p>
    </div> : <>
      {error&&<p className="commerce-ds-message is-error" role="alert"><ShieldAlert size={16}/>{error}</p>}
      {notice&&<p className="commerce-ds-message" role="status"><Check size={16}/>{notice}</p>}
      <div className="commerce-ds-status"><LockKeyhole size={15}/>
        <span>LOCAL ANALYSIS ONLY · No live supplier feed · No verified sales imported here · No email sending or ad spending</span>
      </div>
      <div className="commerce-ds-statgrid">
        <div><small>SUPPLIER OFFERS</small><strong>{loading?'…':board?.catalog_total??0}</strong><span>Owner-provided, unverified</span></div>
        <div><small>COST PREFLIGHT</small><strong>{loading?'…':board?.cost_preflight_candidates??0}</strong><span>Not approved listings</span></div>
        <div><small>AD BUDGET</small><strong>OFF</strong><span>External advertising disabled</span></div>
        <div><small>EMAIL AUTOSEND</small><strong>OFF</strong><span>Drafts only; no mailbox connected</span></div>
      </div>
      <nav className="commerce-ds-tabs" aria-label="Dropshipping sections">
        <button type="button" aria-current={tab==='products'?'page':undefined} onClick={()=>setTab('products')}>Product sourcing</button>
        <button type="button" aria-current={tab==='research'?'page':undefined} onClick={()=>setTab('research')}>Demand & distribution</button>
        <button type="button" aria-current={tab==='support'?'page':undefined} onClick={()=>setTab('support')}>Support desk</button>
        <button type="button" aria-current={tab==='autopilot'?'page':undefined} onClick={()=>setTab('autopilot')}>Autopilot</button>
      </nav>
      {tab==='products'&&<>
        <div className="commerce-ds-section-head"><div><h3>Supplier catalog</h3>
          <p>Every imported offer receives an immediate cost, lead-time, sample, returns and compliance preflight.</p></div>
          <span className="commerce-ds-small">USD estimates</span>
        </div>
        <form className="commerce-ds-import" onSubmit={event=>{event.preventDefault();void run('commerceDropshipImportOffers',
          {csv_text:csv,source_label:source,owner_confirmed:true},'Supplier offers analyzed locally. Nothing was listed or purchased.')}} >
          <label className="commerce-field">Catalog source
            <input value={source} maxLength={100} onChange={event=>setSource(event.target.value)} required/>
          </label>
          <label className="commerce-field">Authorized supplier CSV (up to 150 rows per import)
            <textarea rows={4} spellCheck={false} maxLength={90000} value={csv} placeholder={offerHeader}
              onChange={event=>setCsv(event.target.value)} required/>
          </label>
          <code className="commerce-ds-csv">{offerHeader}</code>
          <label className="commerce-ds-checkbox"><input type="checkbox" checked={ownerConfirmed}
            onChange={event=>setConfirmed(event.target.checked)}/>
            <span>I have permission to use this catalog; costs and stock are supplier-reported, not independently verified.</span>
          </label>
          <button className="commerce-action-primary" type="submit" disabled={busy||!csv.trim()||!ownerConfirmed||!source.trim()}>
            <FileInput size={15}/> {busy?'Validating…':'Import & screen offers'}
          </button>
        </form>
        <div className="commerce-ds-results">
          {!screened.length&&!(board?.offers.length)&&<div className="commerce-ds-empty"><PackageSearch size={22}/>
            <strong>No supplier products yet</strong><p>Import an authorized supplier export to calculate real input-based cost estimates. STAR does not invent winning products.</p></div>}
          {board?.offers.map(o=><article className="commerce-ds-product" key={o.supplier+'_'+o.sku}>
            <div className="commerce-ds-product-main">
              <div className="commerce-ds-product-title"><span className={'commerce-ds-dot'+(o.blockers.length?' is-blocked':'')}/>
                <strong>{o.title}</strong></div>
              <small>{o.supplier} · {o.sku} · {o.delivery_days} day supplier estimate · {o.stock} supplier-reported units</small>
              <span className="commerce-ds-source">Source: {o.source_label} · {o.observed_at.slice(0,10)}</span>
              {o.blockers.length>0&&<ul>{o.blockers.map(x=><li key={x}>{x}</li>)}</ul>}
              {!o.blockers.length&&<p className="commerce-ds-good">Cost checklist candidate only. Verify rights, supplier, product safety and delivery before listing.</p>}
            </div>
            <div className="commerce-ds-product-math">
              <div><span>Target retail</span><strong>{money(o.price_cents)}</strong></div>
              <div><span>Unit + shipping</span><strong>{money(o.unit_cost_cents+o.shipping_cents)}</strong></div>
              <div><span>Est. contribution before ads</span><strong>{money(o.contribution_before_ads_cents)}</strong></div>
              <div><span>Break-even ROAS, modeled</span><strong>{o.break_even_roas?.toFixed(2)??'—'}×</strong></div>
              <a href={o.url} target="_blank" rel="noopener noreferrer">Source details <ArrowUpRight size={13}/></a>
            </div>
          </article>)}
        </div>
        <p className="commerce-ds-assumption">{board?.fee_assumption||'Modeled fees and returns are placeholders, not a profit report.'}</p>
      </>}
      {tab==='research'&&<>
        <div className="commerce-ds-section-head"><div><h3>Demand evidence</h3>
          <p>Keep sampled Google Trends indexes, search-volume estimates and Merchant Center clicks separate. None represent verified orders.</p></div><TrendingUp size={20}/>
        </div>
        <form className="commerce-ds-import" onSubmit={event=>{event.preventDefault();void run(
          'commerceDropshipImportSignals',{csv_text:csv,owner_confirmed:true},
          'Demand signals saved privately. These observations are not sales.')}}>
          <label className="commerce-field">Demand signal CSV
            <textarea rows={4} spellCheck={false} maxLength={90000} value={csv} placeholder={signalHeader}
              onChange={event=>setCsv(event.target.value)} required/>
          </label>
          <code className="commerce-ds-csv">{signalHeader}</code>
          <p className="commerce-ds-help">Allowed source/metric pairs: google_trends/trends_index, google_ads_keyword_planner/monthly_searches, merchant_center/merchant_clicks. SKU must match an imported supplier product.</p>
          <label className="commerce-ds-checkbox"><input type="checkbox" checked={ownerConfirmed}
            onChange={event=>setConfirmed(event.target.checked)}/>
            <span>These values came from research data I am authorized to use, not fabricated competitor orders.</span>
          </label>
          <button className="commerce-action-primary" type="submit" disabled={busy||!csv.trim()||!ownerConfirmed}><TrendingUp size={15}/> Save signals</button>
        </form>
        <div className="commerce-ds-signals">{!board?.signals.length?<p>No imported demand research.</p>:
          board.signals.map(s=><div key={[s.sku,s.source,s.observed_on].join('_')}>
            <strong>{s.sku}</strong><span>{s.source.replaceAll('_',' ')} · {s.metric.replaceAll('_',' ')}</span>
            <b>{s.value.toLocaleString()}</b><small>{s.observed_on}</small>
          </div>)}</div>
        <div className="commerce-ds-section-head"><div><h3>Distribution network</h3>
          <p>Connection blueprint only. No ad account, pixel or Merchant Center is authorized inside STAR.</p></div></div>
        <div className="commerce-ds-channels">{board?.marketing.map(m=><div key={m.channel}>
          <span className="commerce-ds-channel-icon"><Sparkles size={15}/></span>
          <div><strong>{m.channel}</strong><small>{m.route}</small></div>
          <span className="commerce-ds-off">Not connected</span>
        </div>)}</div>
      </>}
      {tab==='support'&&<>
        <div className="commerce-ds-section-head"><div><h3>Verified-policy support</h3>
          <p>Store approved FAQ facts locally. Draft replies from those facts; never invent tracking, refund approval or delivery dates.</p></div>
          <LockKeyhole size={18}/>
        </div>
        <form className="commerce-ds-import" onSubmit={event=>{event.preventDefault();void run(
          'commerceDropshipSavePolicy',{shipping,returns,contact,owner_confirmed:true},'Support policies saved for this business.')}}>
          <label className="commerce-field">Published shipping policy<textarea rows={2} value={shipping} maxLength={1200} onChange={e=>setShipping(e.target.value)} required/></label>
          <label className="commerce-field">Published return/refund policy<textarea rows={2} value={returns} maxLength={1200} onChange={e=>setReturns(e.target.value)} required/></label>
          <label className="commerce-field">Published customer contact instructions<textarea rows={2} value={contact} maxLength={1200} onChange={e=>setContact(e.target.value)} required/></label>
          <button type="submit" className="commerce-action-secondary" disabled={busy||!shipping.trim()||!returns.trim()||!contact.trim()}>
            <Check size={14}/> Save approved policies
          </button>
        </form>
        <div className="commerce-ds-inbox">
          <label className="commerce-field">Customer question (processed in memory only; do not paste passwords or payment details)
            <textarea rows={4} maxLength={2500} value={customerInquiry} onChange={e=>setCustomerInquiry(e.target.value)} placeholder="Ask a general shipping, return or product question…" />
          </label>
          <button type="button" className="commerce-action-primary" disabled={busy||!customerInquiry.trim()}
            onClick={()=>void run('commerceDropshipDraftReply',{message:customerInquiry},'Draft prepared. No email was sent.')}>
            <Clipboard size={14}/> Prepare support draft
          </button>
          {draft&&<div className="commerce-ds-draft" role="status"><small>ROUTING · {draft.intent.replaceAll('_',' ')}</small>
            <p>{draft.draft}</p>
            <span>Owner review required. Order identity not verified. Gmail not connected. No email sent.</span></div>}
        </div>
      </>}
      {tab==='autopilot'&&<CommercePilot businessId={businessId} project={project} preview={preview}/>}
    </>}
  </section>
}
