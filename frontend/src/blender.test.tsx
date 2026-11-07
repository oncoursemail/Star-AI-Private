// @vitest-environment jsdom
import {afterEach,describe,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {BlenderPanel} from './BlenderPanel'
import {backendSettings} from './fake-desktop'
import type {AppSettings} from './types'

afterEach(cleanup)
const settings=(extra:Partial<AppSettings>={}):AppSettings=>({...backendSettings,...extra} as AppSettings)

describe('Brain 2 Blender MCP setup',()=>{
 it('is off by default and cannot permit writes before enabling the connector',()=>{
   const change=vi.fn()
   render(<BlenderPanel draft={settings()} onChange={change} invoke={async()=>null}/>)
   expect((screen.getByRole('checkbox',{name:'Use Blender on this PC'}) as HTMLInputElement).checked).toBe(false)
   // Plain words for the owner: no internal server names or protocol jargon in the heading.
   expect(screen.getByText('Blender')).toBeTruthy()
   expect(screen.queryByText(/Brain 2|MCP/)).toBeNull()
   expect((screen.getByRole('checkbox',{name:'Allow Blender scene creation'}) as HTMLInputElement).disabled).toBe(true)
   expect((screen.getByRole('button',{name:'Test local Blender'}) as HTMLButtonElement).disabled).toBe(true)
   fireEvent.click(screen.getByRole('checkbox',{name:'Use Blender on this PC'}))
   expect(change).toHaveBeenCalledWith(expect.objectContaining({blender_enabled:true,blender_edit:false}))
 })
 it('allows an owner to enable only new scene creation after enabling Blender',()=>{
   const change=vi.fn()
   render(<BlenderPanel draft={settings({blender_enabled:true})} onChange={change} invoke={async()=>null}/>)
   fireEvent.click(screen.getByRole('checkbox',{name:'Allow Blender scene creation'}))
   expect(change).toHaveBeenCalledWith(expect.objectContaining({blender_enabled:true,blender_edit:true}))
   fireEvent.change(screen.getByRole('textbox',{name:'Blender executable path'}),{target:{value:'C:\\Blender\\blender.exe'}})
   expect(change).toHaveBeenCalledWith(expect.objectContaining({blender_executable:'C:\\Blender\\blender.exe'}))
 })
 it('offers the animation motion check only after enabling Blender, off by default',()=>{
   const change=vi.fn()
   const {unmount}=render(<BlenderPanel draft={settings()} onChange={change} invoke={async()=>null}/>)
   const off=screen.getByRole('checkbox',{name:'Check animation motion'}) as HTMLInputElement
   expect(off.checked).toBe(false)
   expect(off.disabled).toBe(true)
   unmount()
   render(<BlenderPanel draft={settings({blender_enabled:true})} onChange={change} invoke={async()=>null}/>)
   fireEvent.click(screen.getByRole('checkbox',{name:'Check animation motion'}))
   expect(change).toHaveBeenCalledWith(expect.objectContaining({blender_enabled:true,blender_motion_qa:true}))
 })
 it('does not claim an executable probe completed based solely on presence on disk',()=>{
   render(<BlenderPanel draft={settings({blender_enabled:true})} onChange={()=>{}}
     status={{enabled:true,installed:true,edit_enabled:false,executable:'C:\\Blender\\blender.exe',
       connection:'local-stdio-mcp',ready:true,note:'available'}}
     invoke={async()=>({pending:true,requestId:'test-id'})}/>)
   expect(screen.getByText(/version not yet verified/)).toBeTruthy()
   expect(screen.queryByText(/Local Blender 4/)).toBeNull()
 })
})
