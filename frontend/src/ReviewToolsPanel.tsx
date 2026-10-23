import {BookOpen,Check,LoaderCircle,RefreshCcw,Search,ShieldCheck,Workflow,X} from 'lucide-react'
import type {AppSettings,CustomToolRecipe,WorkshopStatus} from './types'
import './integrated-tools.css'
import {EmptyState} from './states'

type Props = {
  settings: AppSettings
  onChange:(value:AppSettings)=>void
  status?:WorkshopStatus
  recipes:CustomToolRecipe[]
  query:string
  onQuery:(value:string)=>void
  preview:string
  busy:string
  disabled:boolean
  refresh:()=>void
  runPreview:(id:number)=>void
  approve:(id:number)=>void
  disable:(id:number)=>void
}

/** Native human-review actions. Model text can only propose; cannot approve. */
export function ReviewToolsPanel({settings,onChange,status,recipes,query,onQuery,preview,busy,disabled,
  refresh,runPreview,approve,disable}:Props){
  const isOff=!settings.tool_workshop_enabled
  // With STAR Server the specialists run on the server: this PC's graphics memory has nothing to do with it.
  const onServer=settings.provider==='star_server'
  return <section className="integrated-panel" aria-label="Custom tools and Roblox research">
    <div className="integrated-heading"><Workflow size={18}/><div>
      <strong>STAR Tool Workshop</strong>
      <span>Compose approved read-only research sources. Test before explicit activation.</span>
    </div></div>
    <p className="integrated-help">Ask STAR in Agent chat to propose a new research tool. The proposed recipe is inactive until you preview and approve it here. No arbitrary Python scripts, shell commands or unapproved Studio writes.</p>
    <div className="integrated-connectors">
      <label className="integrated-switch"><input type="checkbox" disabled={disabled}
        checked={Boolean(settings.tool_workshop_enabled)}
        onChange={e=>onChange({...settings,tool_workshop_enabled:e.target.checked})}/>
        <span>Enable reviewed custom tools</span>
      </label>
      <label className="integrated-switch"><input type="checkbox" disabled={disabled}
        checked={Boolean(settings.roblox_research_enabled)}
        onChange={e=>onChange({...settings,roblox_research_enabled:e.target.checked})}/>
        <span>Enable public Roblox game, docs, forum and Poly Haven asset research</span>
      </label>
      <label className="integrated-switch"><input type="checkbox" disabled={disabled}
        checked={settings.asset_forge_enabled===true}
        onChange={e=>onChange({...settings,asset_forge_enabled:e.target.checked})}/>
        <span>Enable experimental Asset Forge planning (off by default; Poly Haven metadata needs public research enabled)</span>
      </label>
      <label className="integrated-switch"><input type="checkbox" disabled={disabled}
        checked={settings.commerce_enabled===true}
        onChange={e=>onChange({...settings,commerce_enabled:e.target.checked})}/>
        <span>Enable Business tools: product research and drafts. Orders, listings, spending, public posts and customer messages always wait for your approval.</span>
      </label>
      <label className="integrated-switch"><input type="checkbox" disabled={disabled}
        checked={Boolean(settings.specialists_enabled)}
        onChange={e=>onChange({...settings,specialists_enabled:e.target.checked})}/>
        <span>Enable scoped research specialists</span>
      </label>
      <label className="integrated-field">{onServer?'Specialist concurrency':'Local specialist concurrency'}
        <select disabled={disabled} value={settings.specialist_parallelism??1}
          onChange={e=>onChange({...settings,specialist_parallelism:Number(e.target.value)})}>
          <option value={1}>{onServer?'1 specialist at a time':'1 specialist (recommended for 8 GB VRAM)'}</option>
          <option value={2}>{onServer?'2 specialists at a time (needs 2 free server slots)':'2 specialists (requires measurement)'}</option>
        </select>
      </label>
    </div>
    <p className="integrated-help">{status?.approved??0} approved · {status?.pending??0} awaiting review · {recipes.length} displayed for this project</p>
    <div className="integrated-key-controls">
      <label className="integrated-field">Test query<input value={query} disabled={disabled||isOff} maxLength={200}
        onChange={e=>onQuery(e.target.value)} placeholder="e.g. Roblox HUD reference"/></label>
      <button type="button" className="secondary-button" onClick={refresh} disabled={disabled||isOff||!!busy}>
        <RefreshCcw size={14}/> Refresh recipes
      </button>
    </div>
    {recipes.map(tool=><div className="integrated-connector" key={tool.id}>
      <div><strong>{tool.name}</strong><small>{tool.description}</small>
        <small>{tool.status} · {tool.tests} successful preview(s) · {tool.sources.join(' / ')}</small>
      </div>
      <div className="integrated-connector-actions">
        {tool.status==='pending'&&<>
          <button type="button" className="secondary-button" disabled={disabled||!!busy||!query.trim()}
            onClick={()=>runPreview(tool.id)}>{busy==='previewCustomTool:'+tool.id?<LoaderCircle className="spin" size={14}/>:<Search size={14}/>} Preview</button>
          <button type="button" className="secondary-button" disabled={disabled||!!busy||tool.tests<1}
            onClick={()=>approve(tool.id)}><Check size={14}/> Approve</button>
        </>}
        {tool.status!=='disabled'&&<button type="button" className="secondary-button"
          disabled={disabled||!!busy} onClick={()=>disable(tool.id)}><X size={14}/> Disable</button>}
      </div>
    </div>)}
    {!recipes.length&&<EmptyState compact icon={<Workflow size={15}/>} title="No proposals yet." description="Ask STAR to design a read-only tool that searches your approved project knowledge."/>}
    {preview&&<div role="status" className="integrated-confirm"><BookOpen size={15}/><strong>Latest preview evidence</strong>
      <pre className="tool-output">{preview}</pre></div>}
    <p className="integrated-help"><ShieldCheck size={14}/> Save Settings before requesting these integrations. Public Roblox stats are snapshots, not revenue, player retention or proof of game mechanics.</p>
  </section>
}
