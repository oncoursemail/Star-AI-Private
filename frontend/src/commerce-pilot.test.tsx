// @vitest-environment jsdom
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {CommercePilot} from './CommercePilot'
import {request} from './bridge'

vi.mock('./bridge',()=>({request:vi.fn()}))
afterEach(cleanup)
beforeEach(()=>{vi.resetAllMocks()})
const shop='a'.repeat(32)
const clean={
  project:'STAR',business_id:shop,business_name:'Store',business_paused:false,
  monitoring:{
    enabled:false,minimum_stock:3,minimum_margin_pct:25,
    maximum_delivery_days:14,stale_after_days:7,interval_minutes:60,
    last_run:null,last_scanned:0,
  },
  finding_counts:{open:0,dismissed:0,resolved:0},
  findings:[],audit:[],execution:'deterministic_local_records_only',
  requires_desktop_running:true,external_connectors_active:false,
  automatic_supplier_refresh:false,auto_send:false,auto_publish:false,
  auto_spend:false,auto_fulfill:false,
}
describe('STAR Commerce Pilot',()=>{
  it('does not connect or read private data in browser preview',()=>{
    render(<CommercePilot businessId={shop} project="test" preview={true}/>)
    expect(screen.getByText(/Choose a Shopify business in STAR Desktop/)).toBeTruthy()
    expect(request).not.toHaveBeenCalled()
  })
  it('requires consent to enable local checks and never claims ad spending',async()=>{
    vi.mocked(request).mockResolvedValueOnce({ok:true,data:clean})
      .mockResolvedValueOnce({ok:true,data:{...clean,monitoring:{...clean.monitoring,enabled:true}}})
    render(<CommercePilot businessId={shop} project="test" preview={false}/>)
    await waitFor(()=>expect(request).toHaveBeenCalledWith('commercePilot',{business_id:shop}))
    expect(screen.getByText('All actions are local.',{exact:false})).toBeTruthy()
    const toggle=screen.getByRole('button',{name:'Save policy & switch on'})
    expect((toggle as HTMLButtonElement).disabled).toBe(true)
    await userEvent.setup().click(screen.getByRole('checkbox',{name:/authorize STAR/}))
    expect((toggle as HTMLButtonElement).disabled).toBe(false)
    await userEvent.setup().click(toggle)
    await waitFor(()=>expect(request).toHaveBeenCalledWith('commercePilotConfigure',{
      business_id:shop,owner_confirmed:true,enabled:true,minimum_stock:3,minimum_margin_pct:25,
      maximum_delivery_days:14,stale_after_days:7,interval_minutes:60,
    }))
    expect(screen.getByRole('button',{name:'Save policy & switch off'})).toBeTruthy()
    expect(screen.getByText(/Local automatic checks enabled while STAR Desktop runs/)).toBeTruthy()
  })
  it('rejects invalid monitoring limits and does not fire additional requests',async()=>{
    vi.mocked(request).mockResolvedValue({ok:true,data:clean})
    render(<CommercePilot businessId={shop} project="test" preview={false}/>)
    await waitFor(()=>expect(request).toHaveBeenCalledTimes(1))
    await userEvent.setup().click(screen.getByRole('checkbox',{name:/authorize STAR/}))
    fireEvent.change(screen.getByRole('spinbutton',{name:/Minimum contribution/}),{target:{value:'2'}})
    expect((screen.getByRole('button',{name:'Save policy & switch on'}) as HTMLButtonElement).disabled).toBe(true)
    expect(request).toHaveBeenCalledTimes(1)
  })
  it('renders only measured findings and prepares one explicit dismissal',async()=>{
    const flagged={...clean,finding_counts:{open:1,dismissed:0,resolved:0},
      findings:[{id:'b'.repeat(32),supplier:'Approved Seller',sku:'SKU1',code:'stock_zero',
        severity:'critical',detail:'Supplier-reported stock is zero.',
        state:'open',created_at:'2026-10-18T00:00:00Z',updated_at:'2026-10-18T00:00:00Z'}],
      audit:[{event:'finding_opened',at:'2026-10-18T00:00:00Z'}],
    }
    vi.mocked(request).mockResolvedValueOnce({ok:true,data:flagged})
      .mockResolvedValueOnce({ok:true,data:{...flagged,
        finding_counts:{open:0,dismissed:1,resolved:0},
        findings:[{...flagged.findings[0],state:'dismissed'}],
      }})
    render(<CommercePilot businessId={shop} project="test" preview={false}/>)
    await waitFor(()=>expect(screen.getByText('Supplier-reported stock is zero.')).toBeTruthy())
    expect((screen.getByRole('button',{name:'Mark reviewed'}) as HTMLButtonElement).disabled).toBe(true)
    await userEvent.setup().click(screen.getByRole('checkbox',{name:/authorize STAR/}))
    await userEvent.setup().click(screen.getByRole('button',{name:'Mark reviewed'}))
    await waitFor(()=>expect(request).toHaveBeenCalledWith('commercePilotDismiss',{
      business_id:shop,id:'b'.repeat(32),owner_confirmed:true,
    }))
    expect(screen.queryByText('Supplier-reported stock is zero.')).toBeNull()
  })
})
