import {useCallback,useEffect,useMemo,useRef,useState} from 'react'
import {Activity,CalendarDays,ChartNoAxesColumn,Check,FileInput,Info,LockKeyhole,RefreshCw,ShieldAlert,X} from 'lucide-react'
import {request} from './bridge'
import './commerce-seasonality.css'

type Bucket = {
  label?:string;month?:string;years_seen?:number
  days:number;months:number;sessions:number|null;orders:number
  orders_per_100_sessions:number|null;net_contribution_cents:number|null
  session_days:number;complete_cost_data:boolean
}
type LearningReport = {
  project:string;business_id:string;business_name:string;channel:string
  data_quality:'owner_supplied_aggregates_unverified_by_platform'
  has_live_feed:false;verified_revenue_cents:null
  imported_daily_rows:number;report_timezone:string|null;currency:string|null
  date_span:[string,string]|null;recent_coverage:number;sessions_all_reported:boolean
  shopify_measurement_break:boolean
  last_365_days:Bucket;time_of_month:Bucket[];weekday:Bucket[];month_of_year:Bucket[]
  last_import:{rows_added:number;rows_replaced:number;source_label:string;inserted_at:string}|null
  signal:{status:'insufficient_evidence'|'candidate_for_controlled_experiment'
    window:string|null;recommendation:string|null;reason:string;auto_apply:false}
  import_status?:'identical_no_changes'|'owner_aggregate_imported'
  added?:number;replaced?:number
}

const TEMPLATE='date,sessions,orders,gross_sales,refunds,platform_fees,fulfillment_costs,ad_spend'
const currencyLabel=(cents:number|null,currency:string|null)=>{
  if(cents===null||!currency)return 'Not available'
  try {return new Intl.NumberFormat('en-US',{style:'currency',currency,maximumFractionDigits:2}).format(cents/100)}
  catch {return 'Not available'}
}

export function CommerceSeasonality({businessId,project,preview}:{businessId:string;project:string;preview:boolean}) {
  const [report,setReport]=useState<LearningReport|null>(null)
  const [loading,setLoading]=useState(false)
  const [busy,setBusy]=useState(false)
  const [showImport,setShowImport]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [period,setPeriod]=useState<'month'|'weekday'|'annual'>('month')
  const [csvText,setCsvText]=useState('')
  const [currency,setCurrency]=useState('USD')
  const [reportTimezone,setReportTimezone]=useState('America/Chicago')
  const [source,setSource]=useState('Owner-prepared seller daily report')
  const [confirmed,setConfirmed]=useState(false)
  const [replace,setReplace]=useState(false)
  const requestGeneration=useRef(0)
  const canUse=!preview&&!!businessId

  const refresh=useCallback(async()=>{
    const generation=++requestGeneration.current
    if(!canUse){setReport(null);setError('');setLoading(false);return}
    setLoading(true);setReport(null)
    const answer=await request<LearningReport>('commerceLearning',{business_id:businessId})
    if(generation!==requestGeneration.current)return
    if(answer.ok&&answer.data&&answer.data.business_id===businessId){
      setReport(answer.data)
      setCurrency(answer.data.currency||'USD')
      setReportTimezone(answer.data.report_timezone||'America/Chicago')
      setError('')
    }else setError(answer.error||'Unable to open a matching business learning report.')
    setLoading(false)
  },[businessId,canUse])
  useEffect(()=>{void refresh();return()=>{requestGeneration.current++}},[refresh,project])
  useEffect(()=>{setCsvText('');setNotice('');setError('');setShowImport(false);setConfirmed(false);setReplace(false);setBusy(false)},[businessId,project])

  async function importRows(){
    if(!canUse||busy||!confirmed||!csvText.trim())return
    const generation=requestGeneration.current
    setBusy(true);setError('');setNotice('')
    const answer=await request<LearningReport>('commerceImportDailyMetrics',{
      business_id:businessId,csv_text:csvText,currency:currency.trim().toUpperCase(),
      report_timezone:reportTimezone.trim(),source_label:source.trim(),
      replace_existing:replace,owner_confirmed:true,
    })
    if(generation!==requestGeneration.current)return
    if(answer.ok&&answer.data&&answer.data.business_id===businessId){
      setReport(answer.data)
      setNotice(answer.data.import_status==='identical_no_changes'
        ?'Identical daily records already exist; nothing changed.'
        :'Saved '+(answer.data.added??0)+' new daily records and corrected '+(answer.data.replaced??0)+' locally.')
      setCsvText('');setConfirmed(false);setReplace(false);setShowImport(false)
    }else setError(answer.error||'The daily import was refused. Existing records were not changed.')
    setBusy(false)
  }

  const groups=useMemo(()=>period==='month'?report?.time_of_month:period==='weekday'?report?.weekday:report?.month_of_year,[period,report])
  const maxRate=Math.max(...(groups||[]).map(group=>group.orders_per_100_sessions??0),0)

  return <section className="commerce-seasonality" aria-label="Real-world sales learning">
    <div className="commerce-seasonality-heading">
      <div>
        <p className="commerce-kicker">02 / BUYER BEHAVIOR</p>
        <h2>Learn from actual selling periods.</h2>
        <p>Watch early-month, mid-month, end-month and seasonal patterns. A calendar coincidence is not proof of demand.</p>
      </div>
      {canUse&&<button className="commerce-action-secondary" type="button" onClick={()=>setShowImport(p=>!p)} disabled={busy}>
        {showImport?<X size={15}/>:<FileInput size={15}/>}
        {showImport?'Close import':'Import daily figures'}
      </button>}
    </div>
    {!canUse?<div className="commerce-seasonality-unselected">
      <CalendarDays size={24}/>
      <div><strong>{preview?'No private seller data in browser preview':'Select a business above to see sales learning'}</strong>
        <p>STAR never invents buyers, revenue or a profitable calendar window.</p></div>
    </div>:<>
      <div className="commerce-learning-provenance" role="status">
        <LockKeyhole size={16}/>
        <span><strong>Owner-supplied metrics — not platform verified.</strong> No marketplace sales API is connected; imports stay in private STAR app data.</span>
        <button type="button" aria-label="Refresh sales learning" disabled={loading||busy} onClick={()=>void refresh()}><RefreshCw size={16}/></button>
      </div>
      {showImport&&<form className="commerce-learning-form" onSubmit={e=>{e.preventDefault();void importRows()}}>
        <h3>Import a daily performance summary</h3>
        <p>Use authorized shop analytics, manually aggregated to <strong>one row per date</strong>, including zero-order dates. Never paste buyer names, emails, addresses, order IDs or raw order-level exports.</p>
        <label className="commerce-field">Report source label
          <input value={source} maxLength={100} onChange={e=>setSource(e.target.value)} required/>
        </label>
        <div className="commerce-learning-form-grid">
          <label className="commerce-field">Report currency
            <input value={currency} maxLength={3} onChange={e=>setCurrency(e.target.value.toUpperCase())} required/>
          </label>
          <label className="commerce-field">Seller account reporting timezone
            <input value={reportTimezone} maxLength={64} onChange={e=>setReportTimezone(e.target.value)} required/>
          </label>
        </div>
        <div className="commerce-learning-csv-head"><strong>Required CSV header</strong><code>{TEMPLATE}</code></div>
        <label className="commerce-field">Paste daily aggregate rows
          <textarea className="commerce-learning-paste" rows={6} value={csvText} maxLength={80000}
            spellCheck={false} placeholder={TEMPLATE+'\nYYYY-MM-DD,visits,orders,amounts in shop currency…'}
            onChange={e=>setCsvText(e.target.value)} required/>
        </label>
        <p className="commerce-learning-form-help">Sessions can be blank if unknown. Missing fees or costs must stay blank, not zero. Use gross sales before refunds, excluding taxes and shipping, and avoid counting the same adjustment twice. This is STAR's normalized template, not a direct Shopify or Etsy CSV format.</p>
        <label className="commerce-learning-checkbox"><input type="checkbox" checked={replace} onChange={e=>setReplace(e.target.checked)}/>
          <span>Replace conflicting existing dates with corrected daily totals</span>
        </label>
        <label className="commerce-learning-checkbox"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>
          <span>I am authorized to use these seller records. They contain aggregated figures only, with no customer information, and I understand STAR cannot verify them independently.</span>
        </label>
        <button className="commerce-action-primary" type="submit"
          disabled={busy||!confirmed||!csvText.trim()||!source.trim()||!currency.trim()||!reportTimezone.trim()}>
          <Check size={15}/>{busy?'Validating…':'Validate and save aggregates'}
        </button>
      </form>}
      {error&&<div className="commerce-learning-error" role="alert"><ShieldAlert size={17}/>{error}</div>}
      {notice&&<div className="commerce-learning-confirmation" role="status"><Check size={16}/>{notice}</div>}
      {loading?<p className="commerce-learning-loading" role="status">Reading local observations…</p>:
        !report||report.imported_daily_rows===0?<div className="commerce-learning-empty">
          <ChartNoAxesColumn size={27}/><strong>No sales observations imported</strong>
          <p>STAR cannot learn a selling pattern without historical shop measurements. Start with daily totals from your own reports, including days with no sales.</p>
        </div>:<>
          <div className="commerce-learning-facts" role="group" aria-label="Learning data coverage">
            <div><span>Daily records</span><strong>{report.imported_daily_rows}</strong><small>{report.date_span?.[0]} – {report.date_span?.[1]}</small></div>
            <div><span>Period coverage</span><strong>{Math.round(100*report.recent_coverage)}%</strong><small>Observed date range</small></div>
            <div><span>Recent orders</span><strong>{report.last_365_days.orders}</strong><small>Unverified owner aggregates</small></div>
            <div><span>Contribution after reported costs</span><strong className="commerce-learning-financial">{currencyLabel(report.last_365_days.net_contribution_cents,report.currency)}</strong><small>Not profit; unknown if costs missing</small></div>
          </div>
          {report.shopify_measurement_break&&<p className="commerce-learning-warning"><Info size={16}/> Shopify changed its session measurement in September 2026. STAR blocks cross-change seasonal conclusions.</p>}
          <div className="commerce-learning-bucket-head">
            <div><h3>Calendar observations</h3><p>Orders per 100 reported sessions when every day has a denominator. This is not unique-buyer conversion or proof of cause.</p></div>
            <div className="commerce-learning-periods" role="group" aria-label="Calendar period">
              <button type="button" aria-pressed={period==='month'} onClick={()=>setPeriod('month')}>Month thirds</button>
              <button type="button" aria-pressed={period==='weekday'} onClick={()=>setPeriod('weekday')}>Weekdays</button>
              <button type="button" aria-pressed={period==='annual'} onClick={()=>setPeriod('annual')}>Year</button>
            </div>
          </div>
          <div className="commerce-learning-bars" role="list" aria-label="Calendar comparison">
            {(groups||[]).map((item,i)=>{
              const name=item.label||item.month||'Period '+i,rate=item.orders_per_100_sessions
              return <div className="commerce-learning-bar" role="listitem" key={name}>
                <span className="commerce-learning-bar-name">{name}</span>
                <span className="commerce-learning-track" aria-hidden="true">
                  <span style={{width:rate===null||!maxRate?'0%':String(Math.max(2,rate/maxRate*100))+'%'}}/>
                </span>
                <span className="commerce-learning-bar-rate">{rate===null?'No rate':rate.toFixed(2)+'/100'}</span>
                <span className="commerce-learning-bar-detail">{item.orders} orders · {item.days} days{period==='annual'?' · '+(item.years_seen||0)+' yrs':''}</span>
              </div>
            })}
          </div>
          <div className={'commerce-learning-insight'+(report.signal.status==='candidate_for_controlled_experiment'?' is-suggested':'')}>
            <div><Activity size={18}/><h3>{report.signal.status==='candidate_for_controlled_experiment'
              ?'Candidate for a controlled experiment':'Keep observing — insufficient evidence'}</h3></div>
            <p>{report.signal.reason}</p>
            {report.signal.recommendation&&<p className="commerce-learning-recommendation">{report.signal.recommendation}</p>}
            <small>No automated price changes, publication, ad spending or customer messaging.</small>
          </div>
          {report.last_import&&<p className="commerce-learning-last">Latest: {report.last_import.source_label}. Shop {report.business_name}; currency {report.currency}; timezone {report.report_timezone}.</p>}
        </>}
    </>}
  </section>
}