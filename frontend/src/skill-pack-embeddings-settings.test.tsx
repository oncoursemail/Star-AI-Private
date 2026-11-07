// @vitest-environment jsdom
/** The opt-in switch for embedding-based skill-pack routing (star/skill_routing.py). */
import {afterEach,beforeAll,beforeEach,expect,it,vi} from 'vitest'
import {cleanup,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {backendSettings,installFakeDesktop,type FakeDesktop} from './fake-desktop'

let desktop:FakeDesktop
beforeAll(async()=>{desktop=installFakeDesktop();await import('./Desktop')},60000)
beforeEach(()=>{desktop.reset();localStorage.clear();desktop.host({settings:{...backendSettings}})})
afterEach(()=>{cleanup();vi.restoreAllMocks();localStorage.clear()})

it('starts off, explains itself and is saved only with Save settings',async()=>{
 const saves:Record<string,unknown>[]=[]
 desktop.onAction('saveSettings',call=>{saves.push(call.payload.settings as Record<string,unknown>);return {ok:true,data:{saved:true}}})
 const user=userEvent.setup()
 render(<App/>)
 await screen.findByRole('textbox',{name:/message star/i})
 await user.click(screen.getByRole('button',{name:/^settings/i}))
 await user.click(await screen.findByRole('tab',{name:'Advanced'}))
 const box=screen.getByRole('checkbox',{name:'Find guidance packs by meaning'}) as HTMLInputElement
 expect(box.checked).toBe(false)
 expect(screen.getByText(/falls back to word matching/)).toBeTruthy()
 await user.click(box)
 expect(saves).toHaveLength(0)
 await user.click(screen.getByRole('button',{name:'Save settings'}))
 await waitFor(()=>expect(saves).toHaveLength(1))
 expect(saves[0].skill_pack_embeddings).toBe(true)
})
