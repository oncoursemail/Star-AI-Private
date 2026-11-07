// @vitest-environment jsdom
import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {afterEach,beforeAll,beforeEach,describe,expect,it,vi} from 'vitest'
import {initializeBridge} from './bridge'
import {installFakeDesktop,type FakeDesktop} from './fake-desktop'
import {BulkTasksPanel,type BulkBatch,type BulkCatalog,type BulkSummary,type BulkTarget} from './BulkTasksPanel'

let desktop:FakeDesktop
beforeAll(async()=>{desktop=installFakeDesktop();await initializeBridge()})
beforeEach(()=>desktop.reset())
afterEach(()=>{cleanup();vi.useRealTimers()})

const target=(id:string,name:string):BulkTarget=>({id,name,project:'STAR',workspace:'/work/'+id,
  provider:'local',model:'review-model',endpoint:'http://127.0.0.1:8080/v1',can_prompt:true,can_edit:true,credential_ready:true})
const brain1=target('brain-one','Brain 1')
const brain2=target('brain-two','Brain 2')
const catalog:BulkCatalog={enabled:true,targets:[brain1,brain2],max_targets:32}
const prepared=(overrides:Partial<BulkBatch>={}):BulkBatch=>({batch_id:'batch-preview-1',intent_sha256:'immutable-intent-1',
  action:'brain_prompt',status:'prepared',cancellation_requested:false,targets:[brain2.id],
  operations:[{operation_id:'operation-1',target_id:brain2.id,status:'pending'}],
  preview:{title:'Review selected task',items:[{target_id:brain2.id,label:brain2.name,prompt_chars:19}]},...overrides})
const summary=(batch:BulkBatch):BulkSummary=>({batch_id:batch.batch_id,action:batch.action,status:batch.status,cancellation_requested:batch.cancellation_requested})
const configure=(data:BulkCatalog=catalog,batches:BulkSummary[]=[])=>{
  desktop.onAction('bulkTaskCatalog',()=>({ok:true,data}))
  desktop.onAction('bulkTaskList',()=>({ok:true,data:{batches}}))
}
const ready=async()=>{
  await waitFor(()=>expect((screen.getByRole('checkbox',{name:'Enable bulk tasks'}) as HTMLInputElement).checked).toBe(true))
}
const draftPrompt=async()=>{
  await ready()
  await userEvent.click(screen.getByRole('checkbox',{name:'Select Brain 2'}))
  fireEvent.change(screen.getByRole('textbox',{name:'Prompt'}),{target:{value:'Review the settings'}})
}
const createPreview=async()=>{
  await userEvent.click(screen.getByRole('button',{name:'Preview selected tasks'}))
  return screen.findByRole('region',{name:'Review bulk task preview'})
}

describe('Bulk tasks through the desktop bridge',()=>{
  it('keeps the website preview completely offline and the feature off',()=>{
    render(<BulkTasksPanel disabled/>)
    expect(desktop.calls).toHaveLength(0)
    expect((screen.getByRole('checkbox',{name:'Enable bulk tasks'}) as HTMLInputElement).checked).toBe(false)
    expect(screen.getByRole('button',{name:'Preview selected tasks'}).hasAttribute('disabled')).toBe(true)
    expect(screen.getByText('Open STAR Desktop to configure targets and send tasks.')).toBeTruthy()
  })

  it('requires enabling and captures only the current configuration without selecting it automatically',async()=>{
    let state:BulkCatalog={enabled:false,targets:[],max_targets:32}
    desktop.onAction('bulkTaskCatalog',()=>({ok:true,data:state}))
    desktop.onAction('bulkTaskList',()=>({ok:true,data:{batches:[]}}))
    desktop.onAction('bulkTaskSetEnabled',call=>{state={...state,enabled:call.payload.enabled===true};return {ok:true,data:state}})
    desktop.onAction('bulkTaskCapture',()=>{state={...state,targets:[brain1]};return {ok:true,data:brain1}})
    render(<BulkTasksPanel/>)
    const enable=screen.getByRole('checkbox',{name:'Enable bulk tasks'})
    await waitFor(()=>expect(enable.hasAttribute('disabled')).toBe(false))
    expect((enable as HTMLInputElement).checked).toBe(false)
    expect(screen.getByRole('button',{name:'Preview selected tasks'}).hasAttribute('disabled')).toBe(true)
    await userEvent.click(enable)
    await ready()
    fireEvent.change(screen.getByRole('textbox',{name:'Target name'}),{target:{value:'  Brain 1  '}})
    await userEvent.click(screen.getByRole('checkbox',{name:'Allow bulk edits for this target'}))
    await userEvent.click(screen.getByRole('button',{name:'Save current target'}))
    const saved=await screen.findByRole('checkbox',{name:'Select Brain 1'})
    expect((saved as HTMLInputElement).checked).toBe(false)
    expect(desktop.sent('bulkTaskSetEnabled')[0].payload).toEqual({enabled:true})
    expect(desktop.sent('bulkTaskCapture')[0].payload).toEqual({name:'Brain 1',allow_edit:true})
    expect(desktop.sent('bulkTaskPreview')).toHaveLength(0)
    expect(desktop.sent('bulkTaskSend')).toHaveLength(0)
  })

  it('sends only selected targets, invalidates edited previews and binds send to the reviewed hash',async()=>{
    configure()
    desktop.onAction('bulkTaskPreview',()=>({ok:true,data:prepared()}))
    desktop.onAction('bulkTaskSend',()=>({ok:true,data:prepared({status:'running'})}))
    render(<BulkTasksPanel/>)
    await ready()
    expect((screen.getByRole('checkbox',{name:'Select Brain 1'}) as HTMLInputElement).checked).toBe(false)
    expect((screen.getByRole('checkbox',{name:'Select Brain 2'}) as HTMLInputElement).checked).toBe(false)
    expect(screen.getByRole('button',{name:'Preview selected tasks'}).hasAttribute('disabled')).toBe(true)
    await draftPrompt()
    await createPreview()
    expect(desktop.sent('bulkTaskPreview')[0].payload).toEqual({kind:'brain_prompt',targetIds:[brain2.id],prompt:'Review the settings',
      concurrency:1,canarySize:1,failureCutoff:1,idempotencyKey:expect.any(String)})
    expect(desktop.sent('bulkTaskSend')).toHaveLength(0)
    fireEvent.change(screen.getByRole('textbox',{name:'Prompt'}),{target:{value:'Review the settings again'}})
    expect(screen.queryByRole('button',{name:'Send reviewed batch'})).toBeNull()
    await createPreview()
    expect(desktop.sent('bulkTaskPreview')[1].payload.idempotencyKey).not.toBe(desktop.sent('bulkTaskPreview')[0].payload.idempotencyKey)
    await userEvent.click(screen.getByRole('button',{name:'Send reviewed batch'}))
    await waitFor(()=>expect(desktop.sent('bulkTaskSend')).toHaveLength(1))
    expect(desktop.sent('bulkTaskSend')[0].payload).toEqual({batchId:'batch-preview-1',intentHash:'immutable-intent-1'})
    expect(screen.queryByRole('button',{name:'Send reviewed batch'})).toBeNull()
    expect(within(screen.getByRole('region',{name:'Bulk batch results'})).getByText('Running')).toBeTruthy()
    expect(screen.queryByText('Succeeded')).toBeNull()
  })

  it('ignores unrelated events and rejects a preview completed after its draft changed',async()=>{
    configure()
    desktop.onAction('bulkTaskPreview',()=>({ok:true,pending:true}))
    render(<BulkTasksPanel/>)
    await draftPrompt()
    await userEvent.click(screen.getByRole('button',{name:'Preview selected tasks'}))
    await waitFor(()=>expect(desktop.sent('bulkTaskPreview')).toHaveLength(1))
    desktop.emitRaw('another-request','result',prepared())
    expect(screen.queryByRole('button',{name:'Send reviewed batch'})).toBeNull()
    fireEvent.change(screen.getByRole('textbox',{name:'Prompt'}),{target:{value:'A different task'}})
    desktop.emitRaw(desktop.requestOf('bulkTaskPreview'),'result',prepared())
    expect(await screen.findByText('The task changed while the preview was prepared. Create a new preview.')).toBeTruthy()
    expect(screen.queryByRole('region',{name:'Review bulk task preview'})).toBeNull()
    expect(desktop.sent('bulkTaskSend')).toHaveLength(0)
  })

  it('shows refused previews and never treats pending send or cancellation as completion',async()=>{
    configure()
    desktop.onAction('bulkTaskPreview',()=>({ok:false,error:'This target no longer permits this task.'}))
    render(<BulkTasksPanel/>)
    await draftPrompt()
    await userEvent.click(screen.getByRole('button',{name:'Preview selected tasks'}))
    expect(await screen.findByText('This target no longer permits this task.')).toBeTruthy()
    expect(screen.queryByRole('button',{name:'Send reviewed batch'})).toBeNull()
    desktop.onAction('bulkTaskPreview',()=>({ok:true,data:prepared()}))
    desktop.onAction('bulkTaskSend',()=>({ok:true,pending:true}))
    await createPreview()
    await userEvent.click(screen.getByRole('button',{name:'Send reviewed batch'}))
    await waitFor(()=>expect(desktop.sent('bulkTaskSend')).toHaveLength(1))
    expect(screen.queryByText('Succeeded')).toBeNull()
    desktop.emitRaw(desktop.requestOf('bulkTaskSend'),'result',prepared({status:'running'}))
    const cancel=await screen.findByRole('button',{name:'Request cancellation'})
    desktop.onAction('bulkTaskCancel',()=>({ok:true,data:prepared({status:'running',cancellation_requested:true})}))
    await userEvent.click(cancel)
    expect(await screen.findByText(/Cancellation requested\. Running operations may still finish/)).toBeTruthy()
    expect(within(screen.getByRole('region',{name:'Bulk batch results'})).getByText('Running')).toBeTruthy()
    expect(screen.queryByText('Cancelled')).toBeNull()
    expect(desktop.sent('bulkTaskCancel')[0].payload).toEqual({batchId:'batch-preview-1'})
    desktop.onAction('bulkTaskStatus',()=>({ok:true,data:prepared({status:'outcome_unknown',cancellation_requested:true,
      operations:[{operation_id:'operation-1',target_id:brain2.id,status:'failed',error:'Verifier exited with code 7.',result:{exit_code:7}}]})}))
    await userEvent.click(screen.getByRole('button',{name:'Refresh batch status'}))
    expect(await screen.findByText('Verifier exited with code 7.')).toBeTruthy()
    expect(screen.getByText('Outcome unknown')).toBeTruthy()
    expect(screen.queryByText('Succeeded')).toBeNull()
  })

  it('recovers a running saved batch on remount, polls only that batch and stops at its terminal result',async()=>{
    const running=prepared({batch_id:'running-saved',status:'running'})
    const older=prepared({batch_id:'older-failed',status:'failed'})
    let result=running
    configure(catalog,[summary(older),summary(running)])
    desktop.onAction('bulkTaskStatus',()=>({ok:true,data:result}))
    vi.useFakeTimers()
    const view=render(<BulkTasksPanel/>)
    await act(async()=>{await vi.advanceTimersByTimeAsync(0)})
    expect(screen.getByRole('button',{name:'Request cancellation'})).toBeTruthy()
    expect(desktop.sent('bulkTaskStatus')[0].payload).toEqual({batchId:'running-saved'})
    await act(async()=>{await vi.advanceTimersByTimeAsync(2000)})
    expect(desktop.sent('bulkTaskStatus')).toHaveLength(2)
    result={...running,status:'succeeded',operations:[{operation_id:'operation-1',target_id:brain2.id,status:'succeeded',result:'A recorded analysis.'}]}
    await act(async()=>{await vi.advanceTimersByTimeAsync(2000)})
    expect(screen.getByText('A recorded analysis.')).toBeTruthy()
    const reads=desktop.sent('bulkTaskStatus').length
    await act(async()=>{await vi.advanceTimersByTimeAsync(10000)})
    expect(desktop.sent('bulkTaskStatus')).toHaveLength(reads)
    view.unmount()
    vi.useRealTimers()
    render(<BulkTasksPanel/>)
    expect(await screen.findByText('A recorded analysis.')).toBeTruthy()
    expect(desktop.sent('bulkTaskSend')).toHaveLength(0)
  })

  it.each(['succeeded','partial','outcome_unknown'])('requires a separate reviewed undo for completed targets in a %s edit batch',async status=>{
    const edit=prepared({batch_id:'edit-complete',action:'workspace_edit',status,operations:[
      {operation_id:'edit-op',target_id:brain2.id,status:'succeeded'},
      ...(status==='succeeded'?[]:[{operation_id:'unfinished-op',target_id:brain1.id,status:'partial'}]),
    ]})
    const undo=prepared({batch_id:'undo-prepared',intent_sha256:'undo-intent',action:'workspace_undo',
      preview:{title:'Review undo',items:[{target_id:brain2.id,label:brain2.name,files:[{path:'src/config.ts',diff:'-const count = 2\n+const count = 1',before_sha256:'after-edit',after_sha256:'before-edit'}]}]}})
    configure(catalog,[summary(edit)])
    desktop.onAction('bulkTaskStatus',()=>({ok:true,data:edit}))
    desktop.onAction('bulkTaskUndoPreview',()=>({ok:true,data:undo}))
    desktop.onAction('bulkTaskSend',()=>({ok:true,data:{...undo,status:'running'}}))
    render(<BulkTasksPanel/>)
    await userEvent.click(await screen.findByRole('button',{name:'Preview undo'}))
    expect(screen.getByText(/Undo includes only fully completed targets/)).toBeTruthy()
    const review=await screen.findByRole('region',{name:'Review bulk task preview'})
    expect(within(review).getByLabelText('Changes to src/config.ts').textContent).toContain('+const count = 1')
    expect(desktop.sent('bulkTaskUndoPreview')[0].payload).toEqual({batchId:'edit-complete'})
    expect(desktop.sent('bulkTaskSend')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button',{name:'Apply reviewed undo'}))
    await waitFor(()=>expect(desktop.sent('bulkTaskSend')).toHaveLength(1))
    expect(desktop.sent('bulkTaskSend')[0].payload).toEqual({batchId:'undo-prepared',intentHash:'undo-intent'})
  })

  it('offers no automatic undo for a target with only partial or unknown outcomes',async()=>{
    const edit=prepared({action:'workspace_edit',status:'outcome_unknown',operations:[
      {operation_id:'partial-op',target_id:brain1.id,status:'partial'},
      {operation_id:'unknown-op',target_id:brain2.id,status:'outcome_unknown'},
    ]})
    configure(catalog,[summary(edit)])
    desktop.onAction('bulkTaskStatus',()=>({ok:true,data:edit}))
    render(<BulkTasksPanel/>)
    await screen.findByRole('region',{name:'Bulk batch results'})
    expect(screen.queryByRole('button',{name:'Preview undo'})).toBeNull()
    expect(desktop.sent('bulkTaskUndoPreview')).toHaveLength(0)
  })

  it('previews only explicitly selected context files and invalidates a changed or oversized file selection',async()=>{
    configure({...catalog,targets:[{...brain1,can_prompt:false,credential_ready:false},brain2]})
    desktop.onAction('bulkTaskPreview',()=>({ok:true,data:prepared()}))
    render(<BulkTasksPanel/>)
    await draftPrompt()
    expect(screen.getAllByText(brain2.endpoint)).toHaveLength(2)
    expect(screen.getByText('Saved credential unavailable. Remove this target, set the key in Settings, then capture it again.')).toBeTruthy()
    expect(screen.getByRole('textbox',{name:'Prompt'}).getAttribute('maxlength')).toBe('5000')
    const files=screen.getByRole('textbox',{name:'Context files (optional, one relative path per line)'})
    fireEvent.change(files,{target:{value:'docs/notes.md\n\nsrc/config.ts'}})
    const review=await createPreview()
    expect(desktop.sent('bulkTaskPreview')[0].payload).toMatchObject({kind:'brain_prompt',targetIds:[brain2.id],
      prompt:'Review the settings',paths:['docs/notes.md','src/config.ts']})
    expect(within(review).getByLabelText('Context files to send').textContent).toBe('docs/notes.md\nsrc/config.ts')
    fireEvent.change(files,{target:{value:'docs/notes.md\ndocs/notes.md'}})
    expect(screen.queryByRole('button',{name:'Send reviewed batch'})).toBeNull()
    expect(screen.getByRole('button',{name:'Preview selected tasks'}).hasAttribute('disabled')).toBe(true)
    expect(screen.getByText('Choose up to 16 unique relative file paths, with no more than 500 characters per path.')).toBeTruthy()
    fireEvent.change(files,{target:{value:Array.from({length:17},(_,index)=>'file-'+index+'.ts').join('\n')}})
    expect(screen.getByRole('button',{name:'Preview selected tasks'}).hasAttribute('disabled')).toBe(true)
    fireEvent.change(files,{target:{value:'a'.repeat(501)}})
    expect(screen.getByRole('button',{name:'Preview selected tasks'}).hasAttribute('disabled')).toBe(true)
    expect(desktop.sent('bulkTaskSend')).toHaveLength(0)
  })

  it('marks shortened diffs and the actual match strategy without claiming an exact text edit',async()=>{
    configure()
    desktop.onAction('bulkTaskPreview',()=>({ok:true,data:prepared({action:'workspace_edit',targets:[brain1.id],
      preview:{title:'Workspace text edits',items:[{target_id:brain1.id,label:brain1.name,files:[{
        path:'src/config.ts',diff:'-old\n+new',diff_truncated:true,replacements:3,match_strategy:'whitespace',
        before_sha256:'before',after_sha256:'after',
      }]}]},
    })}))
    render(<BulkTasksPanel/>)
    await ready()
    await userEvent.selectOptions(screen.getByRole('combobox',{name:'Task type'}),'workspace_edit')
    await userEvent.click(screen.getByRole('checkbox',{name:'Select Brain 1'}))
    fireEvent.change(screen.getByRole('textbox',{name:'Files (one relative path per line)'}),{target:{value:'src/config.ts'}})
    fireEvent.change(screen.getByRole('textbox',{name:'Find text'}),{target:{value:'old'}})
    expect(screen.getByRole('textbox',{name:'Find text'}).getAttribute('maxlength')).toBe('12000')
    expect(screen.getByRole('textbox',{name:'Replace with'}).getAttribute('maxlength')).toBe('12000')
    expect(screen.getByRole('checkbox',{name:'Replace every match in each file'})).toBeTruthy()
    const review=await createPreview()
    expect(within(review).getByText('Diff truncated: only part of this file’s changes is shown. Inspect the file or narrow the edit before sending.')).toBeTruthy()
    expect(within(review).getByText('3 replacements · Whitespace normalized')).toBeTruthy()
    expect(within(review).getByLabelText('Changes to src/config.ts').textContent).toBe('-old\n+new')
    expect(desktop.sent('bulkTaskSend')).toHaveLength(0)
  })

  it('keeps workspace edits separate, allows empty replacement and refuses invalid target limits',async()=>{
    configure({...catalog,targets:[brain1,{...brain2,can_edit:false}]})
    desktop.onAction('bulkTaskPreview',()=>({ok:true,data:prepared({action:'workspace_edit',targets:[brain1.id]})}))
    render(<BulkTasksPanel/>)
    await ready()
    await userEvent.selectOptions(screen.getByRole('combobox',{name:'Task type'}),'workspace_edit')
    expect(screen.getByRole('checkbox',{name:'Select Brain 2'}).hasAttribute('disabled')).toBe(true)
    await userEvent.click(screen.getByRole('checkbox',{name:'Select Brain 1'}))
    fireEvent.change(screen.getByRole('textbox',{name:'Files (one relative path per line)'}),{target:{value:'src/one.ts\n\nsrc/two.ts'}})
    fireEvent.change(screen.getByRole('textbox',{name:'Find text'}),{target:{value:'REMOVE_THIS'}})
    fireEvent.change(screen.getByRole('spinbutton',{name:'Canary targets'}),{target:{value:'2'}})
    expect(screen.getByRole('button',{name:'Preview selected tasks'}).hasAttribute('disabled')).toBe(true)
    fireEvent.change(screen.getByRole('spinbutton',{name:'Canary targets'}),{target:{value:'1'}})
    await createPreview()
    expect(desktop.sent('bulkTaskPreview')[0].payload).toEqual({kind:'workspace_edit',targetIds:[brain1.id],paths:['src/one.ts','src/two.ts'],
      oldString:'REMOVE_THIS',newString:'',replaceAll:false,concurrency:1,canarySize:1,failureCutoff:1,idempotencyKey:expect.any(String)})
    expect(desktop.sent('bulkTaskSend')).toHaveLength(0)
  })
})
