// @vitest-environment jsdom
/** The curated GitHub connector is opt-in, uses a saved credential source, and reports real inventory checks. */
import {useState} from 'react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {act,cleanup,render,screen} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {McpPanel} from './IntegrationPanels'
import {backendSettings} from './fake-desktop'
import type {AppSettings,BackendEvent} from './types'

const {watchers}=vi.hoisted(()=>({watchers:new Set<(event:BackendEvent)=>void>()}))
vi.mock('./bridge',()=>({onBackendEvent:(callback:(event:BackendEvent)=>void)=>{
 watchers.add(callback)
 return ()=>{watchers.delete(callback)}
}}))

const invoke=vi.fn(async(_action:string,_params?:Record<string,unknown>)=>({pending:true,requestId:'github-check'}))
const emit=(data:unknown,kind:BackendEvent['kind']='result',requestId='github-check')=>
 act(()=>{watchers.forEach(callback=>callback({requestId,kind,data}))})

function Harness({settings=backendSettings as AppSettings,disabled=false}:{settings?:AppSettings;disabled?:boolean}){
 const [draft,setDraft]=useState(settings)
 return <McpPanel draft={draft} onChange={setDraft} invoke={invoke} disabled={disabled}/>
}
const enabled={...backendSettings,mcp_github_repositories:true,github_repository_access_source:'gh'} as AppSettings

beforeEach(()=>{invoke.mockClear();watchers.clear()})
afterEach(()=>{cleanup();watchers.clear()})

it('starts off for an older profile and edits only the draft until Settings are saved',async()=>{
 const user=userEvent.setup()
 render(<Harness/>)
 const toggle=screen.getByRole('checkbox',{name:'Enable GitHub repositories'}) as HTMLInputElement
 const source=screen.getByRole('combobox',{name:'GitHub credential source'}) as HTMLSelectElement
 const check=screen.getByRole('button',{name:'Check repositories'}) as HTMLButtonElement
 expect(toggle.checked).toBe(false)
 expect(source.value).toBe('gh')
 expect(check.disabled).toBe(true)
 expect(screen.getByText(/Save connector settings before testing connections/)).toBeTruthy()
 await user.click(toggle)
 await user.selectOptions(source,'env')
 expect(toggle.checked).toBe(true)
 expect(source.value).toBe('env')
 expect(check.disabled).toBe(false)
 expect(invoke).not.toHaveBeenCalled()
 expect(screen.queryByRole('textbox')).toBeNull()
 await user.click(toggle)
 expect(check.disabled).toBe(true)
})

it('checks only the fixed GitHub connector and reports a complete credential-visible inventory',async()=>{
 const user=userEvent.setup()
 render(<Harness settings={enabled}/>)
 await user.click(screen.getByRole('button',{name:'Check repositories'}))
 expect(invoke).toHaveBeenCalledExactlyOnceWith('testMcpConnection',{server:'github_repositories'})
 const toggle=screen.getByRole('checkbox',{name:'Enable GitHub repositories'}) as HTMLInputElement
 const source=screen.getByRole('combobox',{name:'GitHub credential source'}) as HTMLSelectElement
 expect(toggle.disabled).toBe(true)
 expect(source.disabled).toBe(true)
 emit({name:'github_repositories',repository_count:1000,complete:true},'result','unrelated-check')
 emit('Checking GitHub','progress')
 expect(source.disabled).toBe(true)
 expect(screen.queryByText(/repositories visible to this credential/)).toBeNull()
 emit({name:'github_repositories',repository_count:29,complete:true,protocol:'internal-v1',read_tool_count:4})
 expect(screen.getByText('29 repositories visible to this credential / read-only')).toBeTruthy()
 expect(source.disabled).toBe(false)
 await user.selectOptions(source,'env')
 expect(screen.queryByText(/repositories visible to this credential/)).toBeNull()
 expect(invoke).toHaveBeenCalledTimes(1)
})

it('removes a previous success before a failed check and shows the failure',async()=>{
 const user=userEvent.setup()
 render(<Harness settings={enabled}/>)
 const check=screen.getByRole('button',{name:'Check repositories'})
 await user.click(check)
 emit({name:'github_repositories',repository_count:29,complete:true})
 await user.click(check)
 expect(screen.queryByText(/repositories visible to this credential/)).toBeNull()
 emit('GitHub credential is unavailable. Sign in with the selected source.','error')
 expect(screen.getByRole('alert').textContent).toContain('GitHub credential is unavailable')
 expect((check as HTMLButtonElement).disabled).toBe(false)
})

it('does not label an incomplete inventory as verified access',async()=>{
 const user=userEvent.setup()
 render(<Harness settings={enabled}/>)
 await user.click(screen.getByRole('button',{name:'Check repositories'}))
 emit({name:'github_repositories',repository_count:29,complete:false})
 expect(screen.queryByText(/repositories visible to this credential/)).toBeNull()
 expect(screen.getByRole('alert').textContent).toContain('has not been fully checked')
})

it('locks the GitHub controls while the desktop disallows connector changes',async()=>{
 const user=userEvent.setup()
 render(<Harness settings={enabled} disabled/>)
 expect((screen.getByRole('checkbox',{name:'Enable GitHub repositories'}) as HTMLInputElement).disabled).toBe(true)
 expect((screen.getByRole('combobox',{name:'GitHub credential source'}) as HTMLSelectElement).disabled).toBe(true)
 const check=screen.getByRole('button',{name:'Check repositories'}) as HTMLButtonElement
 expect(check.disabled).toBe(true)
 await user.click(check)
 expect(invoke).not.toHaveBeenCalled()
})

it('keeps tool-discovery results for the existing connectors',async()=>{
 const user=userEvent.setup()
 render(<Harness settings={{...enabled,mcp_graphify_docs:true}}/>)
 await user.click(screen.getAllByRole('button',{name:'Test'})[0])
 expect(invoke).toHaveBeenCalledWith('testMcpConnection',{server:'graphify_docs'})
 emit({name:'graphify_docs',protocol:'2025-03-26',read_tool_count:3})
 expect(screen.getByText('3 read tools / 2025-03-26')).toBeTruthy()
})
