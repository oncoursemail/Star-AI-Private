// @vitest-environment jsdom
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {CommerceDropshipping} from './CommerceDropshipping'
import {request} from './bridge'

vi.mock('./bridge',()=>({request:vi.fn()}))
const shop='a'.repeat(32)
const empty={
  business_id:shop,business_name:'Studio Market',mode:'local_analysis_only',
  catalog_total:0,cost_preflight_candidates:0,offers:[],signals:[],policy:null,
  marketing:[{channel:'Google Merchant Center',route:'Free product listings',state:'not_connected'}],
  fee_assumption:'Modeled transaction cost and 5% return reserve',
  marketplace_connected:false,supplier_connected:false,gmail_connected:false,
}
beforeEach(()=>{vi.resetAllMocks()})
afterEach(cleanup)

describe('STAR dropshipping desk',()=>{
  it('keeps browser preview empty, inert and truthful',()=>{
    render(<CommerceDropshipping businessId={shop} project="test" preview={true}/>)
    expect(screen.getByText(/Private supplier information is unavailable/)).toBeTruthy()
    expect(screen.queryByText('SUPPLIER OFFERS')).toBeNull()
    expect(request).not.toHaveBeenCalled()
  })

  it('displays real zero state and imports only owner-confirmed supplier data',async()=>{
    vi.mocked(request).mockResolvedValueOnce({ok:true,data:empty})
      .mockResolvedValueOnce({ok:true,data:{...empty,catalog_total:1,
        import_result:{added:1,updated:0,unchanged:0}}})
    render(<CommerceDropshipping businessId={shop} project="test" preview={false}/>)
    await waitFor(()=>expect(request).toHaveBeenCalledWith('commerceDropship',{business_id:shop}))
    expect(screen.getByText('No supplier products yet')).toBeTruthy()
    expect(screen.getByText('No live supplier feed', {exact:false})).toBeTruthy()
    expect(screen.getByText('OFF',{selector:'strong'})).toBeTruthy()
    const text='supplier,sku,title,category,product_url,unit_cost,shipping_cost,target_price,stock,delivery_days,returns_supported,sample_reviewed\nVendor,A1,Notebook,stationery,https://vendor.example/p/1,10.00,3.00,29.00,5,8,yes,yes'
    fireEvent.change(screen.getByRole('textbox',{name:/Authorized supplier CSV/}),{target:{value:text}})
    const button=screen.getByRole('button',{name:/Import & screen offers/})
    expect((button as HTMLButtonElement).disabled).toBe(true)
    await userEvent.setup().click(screen.getByRole('checkbox',{name:/permission to use this catalog/}))
    expect((button as HTMLButtonElement).disabled).toBe(false)
    await userEvent.setup().click(button)
    await waitFor(()=>expect(request).toHaveBeenCalledWith('commerceDropshipImportOffers',{
      business_id:shop,csv_text:text,source_label:'Owner-authorized supplier catalog',owner_confirmed:true,
    }))
    expect(screen.getByText(/Nothing was listed or purchased/)).toBeTruthy()
  })

  it('separates Gmail support drafts from sending emails',async()=>{
    vi.mocked(request).mockResolvedValueOnce({ok:true,data:empty})
      .mockResolvedValueOnce({ok:true,data:{...empty,support_draft:{
        intent:'shipping_or_tracking',draft:'We can check the order once verified.',
        review_required:true,auto_send_allowed:false,mailbox_connected:false,
        order_or_identity_verified:false,note:'Nothing was sent.',
      }}})
    render(<CommerceDropshipping businessId={shop} project="test" preview={false}/>)
    await waitFor(()=>expect(request).toHaveBeenCalled())
    await userEvent.setup().click(screen.getByRole('button',{name:'Support desk'}))
    fireEvent.change(screen.getByRole('textbox',{name:/Customer question/}),
      {target:{value:'Where is my order?'}})
    await userEvent.setup().click(screen.getByRole('button',{name:/Prepare support draft/}))
    await waitFor(()=>expect(request).toHaveBeenCalledWith('commerceDropshipDraftReply',{
      business_id:shop,message:'Where is my order?',
    }))
    expect(screen.getByText('We can check the order once verified.')).toBeTruthy()
    expect(screen.getByText(/No email sent/)).toBeTruthy()
    expect(request).toHaveBeenCalledTimes(2)
  })
})
