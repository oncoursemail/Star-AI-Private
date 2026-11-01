// @vitest-environment jsdom
/** Real App/Desktop toggle through the Qt fake bridge, not a mocked Settings panel. */
import {afterEach,beforeAll,beforeEach,expect,it,vi} from 'vitest'
import {cleanup,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {backendSettings,installFakeDesktop,type FakeDesktop} from './fake-desktop'

let desktop:FakeDesktop
beforeAll(async()=>{
 desktop=installFakeDesktop()
 await import('./Desktop')
},60000)
beforeEach(()=>{
 desktop.reset()
 localStorage.clear()
 desktop.host({settings:{...backendSettings,worked_examples_enabled:false}})
})
afterEach(()=>{cleanup();vi.restoreAllMocks();localStorage.clear()})

it('only enables worked-example retrieval after a saved opt-in, and preserves revocation',async()=>{
 let saved=false
 desktop.onAction('saveSettings',call=>{
  saved=(call.payload.settings as {worked_examples_enabled?:boolean}).worked_examples_enabled===true
  desktop.host({settings:{...backendSettings,worked_examples_enabled:saved}})
  return {ok:true,data:{saved:true}}
 })
 const user=userEvent.setup()
 const view=render(<App/>)
 await screen.findByRole('textbox',{name:/message star/i})
 await user.click(screen.getByRole('button',{name:/^settings/i}))
 await user.click(await screen.findByRole('tab',{name:'Advanced'}))
 const option=screen.getByRole('checkbox',{name:'Use checked practice examples'}) as HTMLInputElement
 expect(option.checked).toBe(false)
 expect(screen.getByText(/untrusted local references, never training data/)).toBeTruthy()
 await user.click(option)
 expect(option.checked).toBe(true)
 expect(saved).toBe(false)
 expect(desktop.sent('saveSettings')).toHaveLength(0)
 await user.click(screen.getByRole('button',{name:'Save settings'}))
 await waitFor(()=>expect(saved).toBe(true))
 view.unmount()
 const again=render(<App/>)
 await screen.findByRole('textbox',{name:/message star/i})
 await user.click(screen.getByRole('button',{name:/^settings/i}))
 await user.click(await screen.findByRole('tab',{name:'Advanced'}))
 const stored=screen.getByRole('checkbox',{name:'Use checked practice examples'}) as HTMLInputElement
 expect(stored.checked).toBe(true)
 await user.click(stored)
 await user.click(screen.getByRole('button',{name:'Save settings'}))
 await waitFor(()=>expect(saved).toBe(false))
 again.unmount()
})
