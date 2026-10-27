// @vitest-environment jsdom
import {afterEach,describe,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {ModelFleetPanel,type ModelTeamReport} from './ModelFleetPanel'
import {backendSettings,installFakeDesktop} from './fake-desktop'
import type {AppSettings} from './types'
import type {ComponentProps} from 'react'

afterEach(cleanup)
type Props=ComponentProps<typeof ModelFleetPanel>
const settings=(change:Partial<AppSettings>={}):AppSettings=>({...backendSettings,...change} as AppSettings)
const panelProps=(over:Partial<Props>={}):Props=>({
 draft:settings(),onChange:vi.fn(),models:[],routerRunning:false,brainRunning:false,
 disabled:false,busy:false,routerBusy:false,teamChecking:false,teamResult:null,
 chooseFolder:vi.fn(),startRouter:vi.fn(),stopBrain:vi.fn(),testTeam:vi.fn(),...over
})

describe('model fleet settings',()=>{
 it('updates only the edited specialist, including the maximum documented context value',()=>{
  const changes:AppSettings[]=[]
  render(<ModelFleetPanel {...panelProps({onChange:next=>changes.push(next)})}/>)
  fireEvent.change(screen.getByRole('combobox',{name:'Fast answers'}),{target:{value:'fast-model'}})
  expect(changes.at(-1)).toMatchObject({fast_model:'fast-model',reasoning_model:'',model:'qwen-test'})
  fireEvent.change(screen.getByRole('spinbutton',{name:'Context tokens'}),{target:{value:'32768'}})
  expect(changes.at(-1)?.router_context).toBe(32768)
  fireEvent.change(screen.getByRole('combobox',{name:'Fast answers'}),{target:{value:''}})
  expect(changes.at(-1)?.fast_model).toBe('')
 })
 it('does not start a local router without a folder or while the managed Brain is running',async()=>{
  const user=userEvent.setup()
  const start=vi.fn()
  const choose=vi.fn()
  const props=panelProps({startRouter:start,chooseFolder:choose})
  const {rerender}=render(<ModelFleetPanel {...props}/>)
  expect(screen.getByRole('button',{name:'Start router'})).toHaveProperty('disabled',true)
  await user.click(screen.getByRole('button',{name:'Choose folder'}))
  expect(choose).toHaveBeenCalledOnce()
  rerender(<ModelFleetPanel {...panelProps({startRouter:start,chooseFolder:choose,draft:settings({router_models_dir:'C:\\Models'}),brainRunning:true})}/>)
  expect(screen.getByRole('button',{name:'Start router'})).toHaveProperty('disabled',true)
  rerender(<ModelFleetPanel {...panelProps({startRouter:start,chooseFolder:choose,draft:settings({router_models_dir:'C:\\Models'})})}/>)
  await user.click(screen.getByRole('button',{name:'Start router'}))
  expect(start).toHaveBeenCalledOnce()
 })
 it('hides PC-only router controls on STAR Server but keeps an available model test',async()=>{
  const user=userEvent.setup()
  const testTeam=vi.fn()
  render(<ModelFleetPanel {...panelProps({draft:settings({provider:'star_server'}),testTeam})}/>)
  expect(screen.getByText(/STAR Server manages its own models/)).toBeTruthy()
  expect(screen.queryByRole('button',{name:'Start router'})).toBeNull()
  expect(screen.queryByRole('button',{name:'Choose folder'})).toBeNull()
  await user.click(screen.getByRole('button',{name:'Test team'}))
  expect(testTeam).toHaveBeenCalledOnce()
 })
 it('reports failed specialist checks truthfully rather than claiming all models passed',()=>{
  const report:ModelTeamReport={all_text_ready:false,note:'One role could not load',
   roles:{fast:{model:'fast-model',ok:true},vision:{model:'vision-model',ok:false,error_type:'ModelUnavailable'}}}
  render(<ModelFleetPanel {...panelProps({teamResult:report})}/>)
  const result=screen.getByRole('status')
  expect(within(result).getByText('One or more models failed the text test')).toBeTruthy()
  expect(result.textContent).toContain('ModelUnavailable')
  expect(result.textContent).toContain('Text response OK')
  expect(within(result).queryByText('Text responses verified')).toBeNull()
 })
 it('sends edited fleet settings through the real Settings page and fake desktop bridge',async()=>{
  const desktop=installFakeDesktop()
  desktop.reset()
  desktop.onAction('saveSettings',call=>{
   const next={...backendSettings,...(call.payload.settings as Record<string,unknown>)}
   desktop.host({settings:next})
   return {ok:true,data:next}
  })
  await import('./Desktop')
  const user=userEvent.setup()
  render(<App/>)
  await screen.findByRole('textbox',{name:/message star/i})
  await user.click(screen.getByRole('button',{name:/^settings/i}))
  await user.click(await screen.findByRole('tab',{name:'Advanced'}))
  const fleet=within(await screen.findByRole('region',{name:'STAR model fleet'}))
  fireEvent.change(fleet.getByRole('combobox',{name:'Fast answers'}),{target:{value:'fast-specialist'}})
  await user.click(screen.getByRole('button',{name:'Save settings'}))
  await waitFor(()=>expect(desktop.sent('saveSettings').some(call=>(call.payload.settings as Record<string,unknown>)?.fast_model==='fast-specialist')).toBe(true))
  expect(desktop.snapshot().settings.fast_model).toBe('fast-specialist')
 },60_000)
})
