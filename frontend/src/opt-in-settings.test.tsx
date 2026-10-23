// @vitest-environment jsdom
/** Settings switches for three opt-in behaviours (#372, #373, #379): off by default, saved only on Save. */
import {afterEach,beforeAll,beforeEach,expect,it,vi} from 'vitest'
import {cleanup,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {backendSettings,installFakeDesktop,type FakeDesktop} from './fake-desktop'

let desktop:FakeDesktop
beforeAll(async()=>{desktop=installFakeDesktop();await import('./Desktop')},60000)
beforeEach(()=>{desktop.reset();localStorage.clear();desktop.host({settings:{...backendSettings}})})
afterEach(()=>{cleanup();vi.restoreAllMocks();localStorage.clear()})

const SWITCHES=[
 {tab:'Roblox & Studio',label:'Show example Studio tool calls',key:'studio_tool_examples',hint:/Permissions do not change/},
 {tab:'Roblox & Studio',label:'Retry a failed Luau fix with more thinking',key:'luau_retry_ladder',hint:/Answers can take longer/},
 {tab:'Roblox & Studio',label:'Repair a failed tool step before going on',key:'incremental_repair',hint:/at most two focused fixes/},
 {tab:'Knowledge & search',label:"Follow my workspace's project rules",key:'project_rules_enabled',hint:/Conventions only, never permissions/},
] as const

it('each switch starts off, explains itself, and is saved only with Save settings',async()=>{
 const saves:Record<string,unknown>[]=[]
 desktop.onAction('saveSettings',call=>{saves.push(call.payload.settings as Record<string,unknown>);return {ok:true,data:{saved:true}}})
 const user=userEvent.setup()
 render(<App/>)
 await screen.findByRole('textbox',{name:/message star/i})
 await user.click(screen.getByRole('button',{name:/^settings/i}))
 for(const item of SWITCHES){
  await user.click(await screen.findByRole('tab',{name:item.tab}))
  const box=screen.getByRole('checkbox',{name:item.label}) as HTMLInputElement
  expect(box.checked).toBe(false)
  expect(screen.getByText(item.hint)).toBeTruthy()
  await user.click(box)
  expect(box.checked).toBe(true)
 }
 expect(saves).toHaveLength(0)
 await user.click(screen.getByRole('button',{name:'Save settings'}))
 await waitFor(()=>expect(saves).toHaveLength(1))
 for(const item of SWITCHES)expect(saves[0][item.key]).toBe(true)
})

it('settings search finds the new switches',async()=>{
 const user=userEvent.setup()
 render(<App/>)
 await screen.findByRole('textbox',{name:/message star/i})
 await user.click(screen.getByRole('button',{name:/^settings/i}))
 await user.type(await screen.findByRole('searchbox'),'agents.md')
 expect(await screen.findByRole('checkbox',{name:"Follow my workspace's project rules"})).toBeTruthy()
})
