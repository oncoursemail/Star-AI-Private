// @vitest-environment jsdom
import {afterEach,beforeAll,beforeEach,describe,expect,it} from 'vitest'
import {cleanup,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {CommerceSeasonality} from './CommerceSeasonality'
import {initializeBridge} from './bridge'
import {installFakeDesktop,type FakeDesktop} from './fake-desktop'

let backend: FakeDesktop
const id='a'.repeat(32)
const zero={
  project:'STAR',business_id:id,business_name:'Atlas Store',channel:'etsy',
  data_quality:'owner_supplied_aggregates_unverified_by_platform',has_live_feed:false,
  verified_revenue_cents:null,imported_daily_rows:0,currency:null,report_timezone:null,
  date_span:null,recent_coverage:0,sessions_all_reported:false,shopify_measurement_break:false,
  last_365_days:{days:0,months:0,orders:0,sessions:null,orders_per_100_sessions:null,
    net_contribution_cents:null,session_days:0,complete_cost_data:false},
  time_of_month:['early','middle','late'].map(label=>({label,days:0,months:0,orders:0,
    sessions:null,orders_per_100_sessions:null,net_contribution_cents:null,session_days:0,complete_cost_data:false})),
  weekday:[],month_of_year:[],last_import:null,
  signal:{status:'insufficient_evidence',window:null,recommendation:null,
    reason:'Need additional daily observations',auto_apply:false},
}
const monthly = {
  ...zero,imported_daily_rows:75,currency:'USD',report_timezone:'America/Chicago',
  date_span:['2026-08-01','2026-10-14'],recent_coverage:1,
  last_365_days:{days:75,months:3,orders:26,sessions:2500,orders_per_100_sessions:1.04,
    net_contribution_cents:null,session_days:75,complete_cost_data:false},
  time_of_month:[
    {...zero.time_of_month[0],days:25,orders:13,sessions:800,orders_per_100_sessions:1.63},
    {...zero.time_of_month[1],days:25,orders:9,sessions:900,orders_per_100_sessions:1},
    {...zero.time_of_month[2],days:25,orders:4,sessions:800,orders_per_100_sessions:0.5},
  ],
  signal:{...zero.signal,reason:'Not enough completed months for a holdout check.'},
  last_import:{rows_added:75,rows_replaced:0,source_label:'Owner-prepared report',inserted_at:'2026-10-18'},
}

beforeAll(async()=>{backend=installFakeDesktop();await initializeBridge()})
beforeEach(()=>backend.reset())
afterEach(cleanup)

describe('STAR seasonal selling analysis',()=>{
  it('shows an honest empty state without a business or in preview',()=>{
    render(<CommerceSeasonality businessId="" project="STAR" preview={false}/>)
    expect(screen.getByText(/Select a business above/)).toBeTruthy()
    expect(backend.sent('commerceLearning')).toHaveLength(0)
    cleanup()
    render(<CommerceSeasonality businessId={id} project="STAR" preview/>)
    expect(screen.getByText(/No private seller data in browser preview/)).toBeTruthy()
    expect(backend.sent('commerceLearning')).toHaveLength(0)
    expect(screen.queryByRole('button',{name:/Import daily figures/})).toBeNull()
  })

  it('opens the owner-only local learning report and never invents sales',async()=>{
    backend.onAction('commerceLearning',()=>({ok:true,data:zero}))
    render(<CommerceSeasonality businessId={id} project="STAR" preview={false}/>)
    await screen.findByText('No sales observations imported')
    expect(backend.sent('commerceLearning')).toHaveLength(1)
    expect(backend.sent('commerceLearning')[0].payload.business_id).toBe(id)
    expect(screen.getByText(/Owner-supplied metrics/)).toBeTruthy()
    expect(screen.queryByText(/\$[0-9]/)).toBeNull()
    expect(backend.sent('commercePublish')).toHaveLength(0)
  })

  it('requires explicit authorization before importing a cleaned CSV',async()=>{
    backend.onAction('commerceLearning',()=>({ok:true,data:zero}))
    backend.onAction('commerceImportDailyMetrics',()=>({ok:true,data:{
      ...monthly,import_status:'owner_aggregate_imported',added:75,replaced:0,
    }}))
    const user=userEvent.setup()
    render(<CommerceSeasonality businessId={id} project="STAR" preview={false}/>)
    await screen.findByText('No sales observations imported')
    await user.click(screen.getByRole('button',{name:'Import daily figures'}))
    const save=screen.getByRole('button',{name:'Validate and save aggregates'})
    expect(save.hasAttribute('disabled')).toBe(true)
    const text=screen.getByRole('textbox',{name:'Paste daily aggregate rows'})
    await user.type(text,
      'date,sessions,orders,gross_sales,refunds,platform_fees,fulfillment_costs,ad_spend\n2026-09-01,120,3,30.00,0.00,3.00,1.00,2.00')
    expect(save.hasAttribute('disabled')).toBe(true)
    await user.click(screen.getByRole('checkbox',{name:/I am authorized to use these seller records/}))
    await user.click(save)
    await waitFor(()=>expect(backend.sent('commerceImportDailyMetrics')).toHaveLength(1))
    const payload=backend.sent('commerceImportDailyMetrics')[0].payload
    expect(payload).toMatchObject({business_id:id,owner_confirmed:true,currency:'USD',
      replace_existing:false,report_timezone:'America/Chicago'})
    expect(String(payload.csv_text)).toContain('2026-09-01')
    expect(backend.sent('commercePublish')).toHaveLength(0)
    expect(backend.sent('commerceBuyAds')).toHaveLength(0)
    expect(await screen.findByText(/Saved 75 new daily records/)).toBeTruthy()
  })

  it('displays historical calendar comparisons as unverified observed data',async()=>{
    backend.onAction('commerceLearning',()=>({ok:true,data:monthly}))
    const user=userEvent.setup()
    render(<CommerceSeasonality businessId={id} project="STAR" preview={false}/>)
    await screen.findByText('Calendar observations')
    expect(screen.getByText('1.63/100')).toBeTruthy()
    expect(screen.getByText(/Not profit; unknown if costs missing/)).toBeTruthy()
    expect(screen.getByText(/Keep observing/)).toBeTruthy()
    await user.click(screen.getByRole('button',{name:'Weekdays'}))
    expect(screen.getByRole('button',{name:'Weekdays'}).getAttribute('aria-pressed')).toBe('true')
    await user.click(screen.getByRole('button',{name:'Year'}))
    expect(screen.getByRole('button',{name:'Year'}).getAttribute('aria-pressed')).toBe('true')
  })

  it('never calls a seasonal correlation a guaranteed sales improvement',async()=>{
    backend.onAction('commerceLearning',()=>({ok:true,data:{
      ...monthly,signal:{status:'candidate_for_controlled_experiment',window:'early',
        recommendation:'Test original creator-kit launches on days 1–10 with a control.',
        reason:'Direction repeated in later months; correlation only.',auto_apply:false},
    }}))
    render(<CommerceSeasonality businessId={id} project="STAR" preview={false}/>)
    await screen.findByText('Candidate for a controlled experiment')
    expect(screen.getByText(/Test original creator-kit launches/)).toBeTruthy()
    expect(screen.getByText(/No automated price changes/)).toBeTruthy()
    expect(backend.sent('commercePublish')).toHaveLength(0)
  })

  it('warns about the changed Shopify sessions method',async()=>{
    backend.onAction('commerceLearning',()=>({ok:true,data:{
      ...monthly,channel:'shopify',shopify_measurement_break:true,
    }}))
    render(<CommerceSeasonality businessId={id} project="STAR" preview={false}/>)
    await screen.findByText(/Shopify changed its session measurement/)
    expect(screen.getByText(/blocks cross-change/)).toBeTruthy()
  })
})
