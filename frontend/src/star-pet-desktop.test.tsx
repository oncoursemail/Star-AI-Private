// @vitest-environment jsdom
/** Mascot wiring through the real app and Qt contract, without mocking Desktop or StarPet. */
import {afterEach,beforeAll,beforeEach,describe,expect,it,vi} from 'vitest'
import {act,cleanup,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {installFakeDesktop,type FakeDesktop} from './fake-desktop'
import type {BootData} from './types'

let desktop:FakeDesktop
let Desktop:typeof import('./Desktop')['Desktop']
beforeAll(async()=>{desktop=installFakeDesktop();({Desktop}=await import('./Desktop'))},60000)
beforeEach(()=>{desktop.reset();localStorage.clear()})
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.useRealTimers();localStorage.clear()})

const pet=()=>screen.queryByTestId('star-pet')
const petState=()=>pet()?.getAttribute('data-state')
async function openChat(){
 const user=userEvent.setup()
 const view=render(<App/>)
 await screen.findByRole('textbox',{name:/message star/i})
 await waitFor(()=>expect(desktop.sent('bootstrap').length).toBeGreaterThan(0))
 return {user,view}
}
async function openPreferences(user:ReturnType<typeof userEvent.setup>){
 await user.click(screen.getByRole('button',{name:/^settings/i}))
 await user.click(await screen.findByRole('tab',{name:'Companions'}))
 return screen.getByRole('checkbox',{name:'Show Star'})
}
async function startAnswer(user:ReturnType<typeof userEvent.setup>){
 await user.type(screen.getByRole('textbox',{name:/message star/i}),'Explain a checkpoint')
 expect(petState()).toBe('typing')
 await user.keyboard('{Enter}')
 return waitFor(()=>desktop.requestOf('sendMessage'))
}

describe('Desktop mascot preference and activity',()=>{
 it('defaults off, supports the Settings toggle, and persists explicit choices across mounts',async()=>{
  const {user,view}=await openChat()
  expect(pet()).toBeNull()
  expect(localStorage.getItem('star.pet.visible')).toBe('off')
  const toggle=await openPreferences(user)
  expect(toggle).toHaveProperty('checked',false)
  expect(screen.getByText(/Shows the Star mascot over the chat/)).toBeTruthy()
  await user.click(toggle)
  expect(localStorage.getItem('star.pet.visible')).toBe('on')
  expect(pet()).toBeNull() // Settings never has the chat overlay.
  await user.click(screen.getByRole('button',{name:'Chat'}))
  expect(petState()).toBe('idle')
  view.unmount()
  const reopened=await openChat()
  expect(petState()).toBe('idle')
  await reopened.user.click(await openPreferences(reopened.user))
  expect(localStorage.getItem('star.pet.visible')).toBe('off')
  await reopened.user.click(screen.getByRole('button',{name:'Chat'}))
  expect(pet()).toBeNull()
  reopened.view.unmount()
  await openChat()
  expect(pet()).toBeNull()
 })
 it.each(['off','invalid'])('does not opt in for the stored value %s',async value=>{
  localStorage.setItem('star.pet.visible',value)
  await openChat()
  expect(pet()).toBeNull()
  expect(localStorage.getItem('star.pet.visible')).toBe('off')
 })
 it('maps typing, busy, streaming and completion and stays awake after a long answer',async()=>{
  localStorage.setItem('star.pet.visible','on')
  const {user}=await openChat()
  const id=await startAnswer(user)
  expect(petState()).toBe('thinking')
  vi.useFakeTimers()
  act(()=>vi.advanceTimersByTime(720000))
  expect(petState()).toBe('thinking')
  desktop.delta(id,'A checkpoint')
  expect(petState()).toBe('streaming')
  desktop.complete(id,'A checkpoint saves progress.')
  await act(async()=>{}) // Flush the bootstrap reply, not a wall-clock wait.
  expect(petState()).toBe('finished')
  act(()=>vi.advanceTimersByTime(2100))
  expect(petState()).toBe('idle')
  act(()=>vi.advanceTimersByTime(30000))
  expect(petState()).toBe('idle')
 })
 it.each(['failed','cancelled'] as const)('maps a backend %s outcome to the pet',async outcome=>{
  localStorage.setItem('star.pet.visible','on')
  const {user}=await openChat()
  const id=await startAnswer(user)
  if(outcome==='cancelled')await user.click(screen.getByRole('button',{name:/stop/i}))
  desktop.fail(id,outcome==='cancelled'?'Request cancelled.':'The request could not finish.',outcome)
  expect(petState()).toBe(outcome==='cancelled'?'cancelled':'error')
 })
 it('shows error when the host refuses to start a turn',async()=>{
  localStorage.setItem('star.pet.visible','on')
  desktop.onAction('sendMessage',()=>({ok:false,error:'The request could not start.'}))
  const {user}=await openChat()
  await startAnswer(user)
  await waitFor(()=>expect(petState()).toBe('error'))
 })
 it('starts the idle clock only in visible live chat and cleans it up on navigation',async()=>{
  const interval=vi.spyOn(window,'setInterval')
  const clear=vi.spyOn(window,'clearInterval')
  const hidden=await openChat()
  expect(interval.mock.calls.filter(([,delay])=>delay===30000)).toHaveLength(0)
  hidden.view.unmount()
  localStorage.setItem('star.pet.visible','on')
  const live=await openChat()
  const index=interval.mock.calls.findIndex(([,delay])=>delay===30000)
  expect(index).toBeGreaterThanOrEqual(0)
  const timer=interval.mock.results[index].value
  await live.user.click(screen.getByRole('button',{name:/^settings/i}))
  expect(pet()).toBeNull()
  expect(clear).toHaveBeenCalledWith(timer)
  live.view.unmount()
  interval.mockClear()
  render(<Desktop initial={desktop.snapshot() as BootData} preview/>)
  expect(petState()).toBe('idle')
  expect(interval.mock.calls.filter(([,delay])=>delay===30000)).toHaveLength(0)
 })
})
