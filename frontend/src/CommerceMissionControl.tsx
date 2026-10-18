import {useMemo, useState} from 'react'
import {Activity, ArrowRight, Check, CircleAlert, FolderKanban, LockKeyhole, Pause, Play, Plus, Search, ShieldCheck, X} from 'lucide-react'
import './commerce-mission.css'

export type MissionBusiness = {
  id: string; name: string; niche: string; channel: string; paused: boolean
  candidate_count: number; queued_checks: number; created_at: string
}
export type PreflightJob = {
  id: string; business_id: string; idea_id: string; title: string
  status: 'queued'|'review_ready'|'needs_evidence'|'stale'|'cancelled'
  blockers: string[]; created_at: string; checked_at: string|null
}
export type MissionActivity = {
  action: string; at: string; business_id: string|null; job_id: string|null
}
export type MissionCounts = {
  queued: number; review_ready: number; needs_evidence: number
  stale: number; cancelled: number
}
export type MissionSnapshot = {
  businesses?: MissionBusiness[]
  preflight_jobs?: PreflightJob[]
  job_counts?: MissionCounts
  recent_activity?: MissionActivity[]
  mission_control?: {
    scope: string; execution_mode: string; auto_start: false
    marketplace_write_access: false; real_sales_feed: false
    maximum_businesses: number; maximum_checks_per_batch: number
  }
}

const channels = ['etsy','shopify','fiverr','payhip','gumroad','printify'] as const
const label = (id: string) => id[0]?.toUpperCase() + id.slice(1)
const taskStatus: Record<PreflightJob['status'],string> = {
  queued: 'Queued',
  review_ready: 'Checklist ready',
  needs_evidence: 'Needs evidence',
  stale: 'Source changed',
  cancelled: 'Cancelled',
}

type Props = {
  board: MissionSnapshot | null
  preview: boolean
  busy: boolean
  selectedBusinessId: string
  onSelectBusiness: (id: string) => void
  onAction: (name: string, data: Record<string, unknown>, message: string) => void
}

/** Multi-business operation desk using actual private STAR records, never demo income. */
export function CommerceMissionControl({board, preview, busy, selectedBusinessId, onSelectBusiness, onAction}: Props) {
  const [isAdding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [niche, setNiche] = useState('')
  const [channel, setChannel] = useState<string>('etsy')
  const [search, setSearch] = useState('')
  const [showActivity, setShowActivity] = useState(false)
  const businesses = useMemo(() => board?.businesses ?? [], [board?.businesses])
  const jobs = board?.preflight_jobs ?? []
  const jobCounts = board?.job_counts
  const activity = board?.recent_activity ?? []
  const visible = businesses.filter(b =>
    !search.trim() || (b.name + ' ' + b.niche + ' ' + b.channel).toLowerCase().includes(search.trim().toLowerCase()))
  const active = businesses.find(b => b.id === selectedBusinessId)
  const runnable = businesses.some(b => !b.paused && b.queued_checks > 0)
  const actionDisabled = preview || busy

  return <section className="commerce-mission" aria-label="Business Mission Control">
    <div className="commerce-mission-head">
      <div>
        <p className="commerce-kicker">01 / PORTFOLIO CONTROL</p>
        <h2>Every business. One view.</h2>
        <p>Each business is a private planning record until you connect and verify its real seller account.</p>
      </div>
      <div className="commerce-mission-actions">
        <span className="commerce-mission-capacity">{businesses.length}<span> / 100</span> local records</span>
        <button type="button" className="commerce-action-secondary" disabled={actionDisabled || businesses.length>=100}
          onClick={() => setAdding(open => !open)}>
          {isAdding ? <X size={15}/> : <Plus size={15}/>}
          {isAdding ? 'Close' : 'Add business'}
        </button>
      </div>
    </div>

    {isAdding && !preview && <form className="commerce-mission-create" onSubmit={event => {
      event.preventDefault()
      onAction('commerceCreateBusiness',{name,niche,channel},'Business added privately with local checks paused.')
      setAdding(false); setName(''); setNiche('')
    }}>
      <div><h3>New business</h3><p>No shop is created on Etsy, Shopify or other platforms by this form.</p></div>
      <label className="commerce-field">Business name
        <input value={name} onChange={event => setName(event.target.value)} required maxLength={90} placeholder="e.g. Northline Creator Kits"/>
      </label>
      <label className="commerce-field">Customer niche
        <input value={niche} onChange={event => setNiche(event.target.value)} required maxLength={300} placeholder="Who is the product for?"/>
      </label>
      <label className="commerce-field">Planned marketplace
        <select value={channel} onChange={event => setChannel(event.target.value)} aria-label="Planned marketplace">
          {channels.map(x => <option key={x} value={x}>{label(x)}</option>)}
        </select>
      </label>
      <button type="submit" className="commerce-action-primary" disabled={busy || !name.trim() || !niche.trim()}>
        Save locally <ArrowRight size={15}/>
      </button>
    </form>}

    <div className="commerce-portfolio-layout">
      <div className="commerce-portfolio-main">
        <div className="commerce-portfolio-tools">
          <label className="commerce-portfolio-search">
            <Search size={15} aria-hidden="true"/>
            <span className="sr-only">Find business</span>
            <input type="search" placeholder="Find business, niche, marketplace" value={search} onChange={event => setSearch(event.target.value)}/>
          </label>
          <span className="commerce-portfolio-count">{visible.length} visible</span>
        </div>
        {businesses.length === 0 ? <div className="commerce-portfolio-empty">
          <FolderKanban size={25} strokeWidth={1.5}/>
          <h3>No businesses in this workspace</h3>
          <p>Add one to track original products, inspect local work and safely pause its checklist queue.</p>
        </div> : visible.length === 0 ? <p className="commerce-portfolio-empty">No businesses match your search.</p> :
        <div className="commerce-portfolio-list">
          {visible.map(b => <div key={b.id} className={'commerce-portfolio-entry'+(b.id===selectedBusinessId?' is-selected':'')}>
            <button type="button" className="commerce-portfolio-select" aria-pressed={b.id===selectedBusinessId}
              onClick={() => onSelectBusiness(b.id===selectedBusinessId?'':b.id)}
              aria-label={'Filter candidates for ' + b.name}>
              <span className="commerce-portfolio-monogram" aria-hidden="true">{b.name.slice(0,2).toUpperCase()}</span>
              <span className="commerce-portfolio-description">
                <strong>{b.name}</strong>
                <small>{label(b.channel)} · {b.niche}</small>
              </span>
              <span className="commerce-portfolio-meta">{b.candidate_count} drafts</span>
            </button>
            <span className={'commerce-portfolio-state'+(b.paused?' is-paused':'')}>
              {b.paused?'Paused':'Local QA on'}
            </span>
            <button type="button" className="commerce-portfolio-toggle" disabled={actionDisabled}
              title={b.paused?'Resume manual local checks':'Pause local checks'}
              aria-label={(b.paused?'Resume checks for ':'Pause checks for ')+b.name}
              onClick={() => onAction('commercePauseBusiness',{id:b.id,paused:!b.paused},
                b.paused?'Local checks enabled for this business.':'Local checks paused for this business.')}>
              {b.paused?<Play size={15}/>:<Pause size={15}/>}
            </button>
          </div>)}
        </div>}
      </div>
      <aside className="commerce-portfolio-health" aria-label="Operational boundaries">
        <div className="commerce-health-head"><ShieldCheck size={19}/><strong>Operations</strong></div>
        <p>{active ? active.name : 'Entire portfolio'}</p>
        <div className="commerce-health-metric"><span>Queued checks</span><strong>{active?active.queued_checks:(jobCounts?.queued??0)}</strong></div>
        <div className="commerce-health-metric"><span>Checklist ready</span><strong>{jobCounts?.review_ready ?? 0}</strong></div>
        <div className="commerce-health-metric"><span>Blocked / needs evidence</span><strong>{jobCounts?.needs_evidence ?? 0}</strong></div>
        <div className="commerce-health-line"><LockKeyhole size={14}/> External selling remains disconnected</div>
        <p className="commerce-health-note">A green checklist only confirms the supplied evidence fields are present. It does not prove copyright ownership, product quality or sales.</p>
      </aside>
    </div>

    <div className="commerce-queue-head">
      <div>
        <p className="commerce-kicker">02 / ACTIVITY &amp; QUALITY</p>
        <h2>Local preflight queue</h2>
        <p>Manual, bounded checks. No AI worker, marketplace upload or payment runs here.</p>
      </div>
      <button type="button" className="commerce-action-secondary" disabled={actionDisabled || !runnable}
        onClick={() => onAction('commerceRunPreflight',{limit:8},'Processed up to 8 local evidence checklists. Nothing was published.')}>
        <Play size={15}/> Run up to 8 checks
      </button>
    </div>
    <div className="commerce-queue-list" role="region" aria-label="Local quality check jobs">
      {jobs.length===0 ? <div className="commerce-queue-empty"><Activity size={20}/><p>No quality-check jobs yet. Assign a candidate to a business, then queue its checklist from the approval desk.</p></div> :
        jobs.slice(0,18).map(j => <div className="commerce-queue-job" key={j.id}>
          <div className="commerce-queue-status-icon">{j.status==='review_ready'?<Check size={17}/>:<CircleAlert size={17}/>}</div>
          <div className="commerce-queue-copy">
            <strong>{j.title}</strong>
            <small>{taskStatus[j.status]} · {businesses.find(b => b.id===j.business_id)?.name || 'Business unavailable'}</small>
            {j.status==='needs_evidence' && <span>{j.blockers.length} evidence checks outstanding</span>}
          </div>
          {j.status==='queued' && <button type="button" disabled={actionDisabled}
            className="commerce-queue-cancel" aria-label={'Cancel checklist for '+j.title}
            onClick={() => onAction('commerceCancelPreflight',{id:j.id},'Pending checklist cancelled locally.')}>
            <X size={15}/> Cancel
          </button>}
        </div>)}
    </div>
    <div className="commerce-activity-footer">
      <button type="button" className="commerce-activity-toggle" aria-expanded={showActivity}
        onClick={() => setShowActivity(p => !p)}>
        <Activity size={15}/> {showActivity?'Hide':'Show'} local audit history <ArrowRight size={14}/>
      </button>
      {showActivity && <div className="commerce-activity-list" role="region" aria-label="Local audit history">
        {activity.length ? activity.map((entry,index) => <div key={index}>
          <span>{entry.action.replaceAll('_',' ')}</span><time>{entry.at}</time>
        </div>) : <p>No operations have been recorded yet.</p>}
      </div>}
    </div>
  </section>
}
