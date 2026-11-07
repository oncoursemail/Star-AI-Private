// @vitest-environment jsdom
/** Opt-in Settings > Interface switches: the workbench home (#418) and the STAR Clips / Game Lab panels (#427, #429). */
import {afterEach,beforeAll,beforeEach,describe,expect,it,vi} from 'vitest'
import {cleanup,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {installFakeDesktop,type FakeDesktop} from './fake-desktop'

let desktop:FakeDesktop
beforeAll(async()=>{desktop=installFakeDesktop();await import('./Desktop')},60000)
beforeEach(()=>{desktop.reset();localStorage.clear()})
afterEach(()=>{cleanup();vi.restoreAllMocks();localStorage.clear()})

async function openChat(){
 const user=userEvent.setup()
 const view=render(<App/>)
 await screen.findByRole('textbox',{name:/message star/i})
 await waitFor(()=>expect(desktop.sent('bootstrap').length).toBeGreaterThan(0))
 return {user,view}
}

describe('Workbench home setting',()=>{
 it('shows the classic home by default and the workbench only after the Settings switch',async()=>{
  const {user,view}=await openChat()
  expect(screen.getByRole('heading',{name:'What are we making?'})).toBeTruthy()
  expect(document.querySelector('.is-crafted-home')).toBeNull()
  expect(localStorage.getItem('star.home.workbench')).toBe('off')
  await user.click(screen.getByRole('button',{name:/^settings/i}))
  await user.click(await screen.findByRole('tab',{name:'Appearance'}))
  const toggle=screen.getByRole('checkbox',{name:'Workbench home screen'})
  expect(toggle).toHaveProperty('checked',false)
  await user.click(toggle)
  expect(localStorage.getItem('star.home.workbench')).toBe('on')
  await user.click(screen.getByRole('button',{name:'Chat'}))
  await waitFor(()=>expect(document.querySelector('.is-crafted-home')).not.toBeNull())
  view.unmount()
  await openChat()
  expect(document.querySelector('.is-crafted-home')).not.toBeNull()
 })
 it('hides STAR Clips and Game Lab on Tools until the Settings switch is on',async()=>{
  const {user}=await openChat()
  await user.click(screen.getByRole('button',{name:/^Tools/}))
  await screen.findByRole('heading',{name:'Connect your tools'})
  expect(screen.queryByRole('heading',{name:'STAR Clips'})).toBeNull()
  expect(localStorage.getItem('star.clips.panels')).toBe('off')
  expect(desktop.sent('clipStatus')).toHaveLength(0)
  await user.click(screen.getByRole('button',{name:/^settings/i}))
  await user.click(await screen.findByRole('tab',{name:'Advanced'}))
  const toggle=screen.getByRole('checkbox',{name:'STAR Clips and Game Lab'})
  expect(toggle).toHaveProperty('checked',false)
  await user.click(toggle)
  expect(localStorage.getItem('star.clips.panels')).toBe('on')
  await user.click(screen.getByRole('button',{name:/^Tools/}))
  expect(await screen.findByRole('heading',{name:'STAR Clips'})).toBeTruthy()
 })
})
