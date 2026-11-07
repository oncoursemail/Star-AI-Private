// @vitest-environment jsdom
/** Chat navigation answers carry only the chat part of the state (react_shell._chat_state). */
import {afterEach,beforeAll,beforeEach,expect,it} from 'vitest'
import {cleanup,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {installFakeDesktop,type FakeDesktop} from './fake-desktop'

let bridge:FakeDesktop
beforeAll(async()=>{bridge=installFakeDesktop();await import('./Desktop')},60000)
beforeEach(()=>bridge.reset())
afterEach(cleanup)

const chats=[
 {id:'chat-1',title:'Test chat',created:'2026-10-11T12:00:00Z',updated:'2026-10-11T12:00:00Z'},
 {id:'chat-2',title:'Other chat',created:'2026-10-11T12:00:00Z',updated:'2026-10-11T12:00:00Z'}
]
const chatPart=(active:string,messages:unknown[])=>({project:'STAR',projects:['STAR'],active_chat:active,chats,retry:null,messages})

it('opening another chat with a chat-only reply keeps the rest of the app state',async()=>{
 bridge.host({chats})
 bridge.onAction('switchChat',call=>({ok:true,data:chatPart(String(call.payload.chatId),
  [{id:'saved-0',role:'user',text:'How do doors open?',created:'2026-10-11T12:00:00Z'}])}))
 const user=userEvent.setup()
 render(<App/>)
 await screen.findByRole('textbox',{name:/message star/i})
 await user.click(screen.getByRole('button',{name:'Other chat'}))
 expect(await screen.findByText('How do doors open?')).toBeTruthy()
 // Version and settings came from the start-up state, not from the chat reply.
 expect(screen.getByRole('button',{name:/^Settings/}).textContent).toContain('v2.0.0')
 expect(screen.getByRole('textbox',{name:/message star/i})).toBeTruthy()
})

it('a new chat with a chat-only reply clears the thread and keeps the app usable',async()=>{
 bridge.host({chats})
 bridge.onAction('newChat',()=>({ok:true,data:chatPart('chat-3',[])}))
 const user=userEvent.setup()
 render(<App/>)
 await screen.findByRole('textbox',{name:/message star/i})
 await user.click(screen.getAllByRole('button',{name:/new chat/i})[0])
 await waitFor(()=>expect(bridge.sent('newChat')).toHaveLength(1))
 expect(screen.getByRole('button',{name:/^Settings/}).textContent).toContain('v2.0.0')
})
