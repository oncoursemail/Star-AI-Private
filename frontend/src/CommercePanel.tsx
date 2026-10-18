import {useCallback, useEffect, useMemo, useState} from 'react'
import {ArrowRight, Check, CircleAlert, ClipboardCheck, FilePenLine, FolderOpen, LockKeyhole, Plus, RefreshCw, ShieldCheck, Store, X} from 'lucide-react'
import {request} from './bridge'
import './commerce.css'

type Channel = 'etsy' | 'shopify' | 'fiverr' | 'payhip' | 'gumroad' | 'printify'
type Evidence = {
  rights_evidence?: string
  visual_qa_evidence?: string
  buyer_brief?: string
  customization_evidence?: string
  sample_evidence?: string
  ai_disclosed?: boolean
  accurate_mockup_reviewed?: boolean
  buyer_allows_ai?: boolean
  partner_disclosed?: boolean
}
type Candidate = {
  id: string
  channel: Channel
  title: string
  concept: string
  status: 'draft' | 'changes_requested' | 'approved_for_export'
  evidence: Evidence
  review: {ready: boolean; blockers: string[]; owner_approval_required: boolean; external_actions_performed: false}
  created_at: string
  updated_at: string
}
type Board = {
  project: string
  data_source: 'local_app_data_only'
  automation: {state: string; description: string}
  counts: {candidates: number; review_ready: number; approved_for_export: number; live_listings: 0; verified_sales: null}
  platforms: {id: Channel; label: string; connection: string; note: string}[]
  ideas: Candidate[]
}

const platforms: {id: Channel; label: string}[] = [
  {id: 'etsy', label: 'Etsy'},
  {id: 'shopify', label: 'Shopify'},
  {id: 'fiverr', label: 'Fiverr'},
  {id: 'payhip', label: 'Payhip'},
  {id: 'gumroad', label: 'Gumroad'},
  {id: 'printify', label: 'Printify'},
]
const emptyEvidence: Evidence = {
  rights_evidence: '', visual_qa_evidence: '', buyer_brief: '', customization_evidence: '',
  sample_evidence: '', ai_disclosed: false, accurate_mockup_reviewed: false,
  buyer_allows_ai: false, partner_disclosed: false,
}
const statusText: Record<Candidate['status'], string> = {
  draft: 'Draft',
  changes_requested: 'Needs changes',
  approved_for_export: 'Approved for export',
}

function Field({title, value, onChange, hint}: {
  title: string; value: string; onChange: (next: string) => void; hint?: string
}) {
  return <label className="commerce-field">
    <span>{title}</span>
    {hint && <small>{hint}</small>}
    <textarea rows={2} maxLength={2000} value={value} onChange={event => onChange(event.target.value)} />
  </label>
}

function CheckField({title, checked, onChange}: {
  title: string; checked: boolean; onChange: (checked: boolean) => void
}) {
  return <label className="commerce-check">
    <input type="checkbox" checked={checked} onChange={event => onChange(event.target.checked)}/>
    <span>{title}</span>
  </label>
}

/** Real STAR desktop reads/writes only its private app-data DB, via the narrow Qt bridge.
 * Browser preview deliberately shows zero private data and cannot save or publish.
 */
export function CommercePanel({project, preview = false}: {project: string; preview?: boolean}) {
  const [board, setBoard] = useState<Board | null>(null)
  const [loading, setLoading] = useState(!preview)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [channel, setChannel] = useState<Channel>('etsy')
  const [filter, setFilter] = useState<Channel | 'all'>('all')
  const [title, setTitle] = useState('')
  const [concept, setConcept] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [evidence, setEvidence] = useState<Evidence>(emptyEvidence)
  const [showCreate, setShowCreate] = useState(false)

  const refresh = useCallback(async () => {
    if (preview) return
    setLoading(true)
    const answer = await request<Board>('commerceBoard')
    if (answer.ok && answer.data) {
      setBoard(answer.data)
      setError('')
    } else {
      setError(answer.error || 'Could not load the local Business workspace.')
    }
    setLoading(false)
  }, [preview])

  useEffect(() => {void refresh()}, [refresh, project])
  const selected = useMemo(
    () => board?.ideas.find(item => item.id === selectedId) ?? null,
    [board, selectedId],
  )
  useEffect(() => {
    setEvidence({...emptyEvidence, ...(selected?.evidence ?? {})})
  }, [selected])
  const ideas = board?.ideas.filter(item => filter === 'all' || item.channel === filter) ?? []
  const changeEvidence = <K extends keyof Evidence>(key: K, value: Evidence[K]) => {
    setEvidence(current => ({...current, [key]: value}))
  }

  async function mutate(action: string, payload: Record<string, unknown>, success: string) {
    if (preview || busy) return
    setBusy(true)
    setError('')
    const answer = await request<Board>(action, payload)
    if (answer.ok && answer.data) {
      setBoard(answer.data)
      setNotice(success)
      if (action === 'commerceCreate') {
        setTitle('')
        setConcept('')
        setShowCreate(false)
      }
    } else setError(answer.error || 'The local operation was not completed.')
    setBusy(false)
  }

  return <div className="commerce-layout">
    <header className="commerce-header">
      <div>
        <p className="commerce-kicker">STAR / BUSINESS</p>
        <h1>Products, before they go public.</h1>
        <p className="commerce-subtitle">A private production desk for concepts, source rights, technical quality and owner approval. It does not operate a marketplace account.</p>
      </div>
      <button className="commerce-action-primary" type="button" onClick={() => setShowCreate(value => !value)} disabled={preview || busy}>
        {showCreate ? <X size={16}/> : <Plus size={16}/>}
        {showCreate ? 'Close form' : 'New candidate'}
      </button>
    </header>

    {preview && <p className="commerce-connection" role="status"><LockKeyhole size={16}/> Browser preview only. Open the installed STAR desktop to save private product candidates.</p>}
    {!preview && error && <p className="commerce-error" role="alert"><CircleAlert size={16}/>{error}</p>}
    {!preview && notice && <p className="commerce-notice" role="status"><Check size={15}/>{notice}<button type="button" aria-label="Dismiss notice" onClick={() => setNotice('')}><X size={14}/></button></p>}

    <section className="commerce-summary" aria-label="Business workspace status">
      <div><span>LOCAL CANDIDATES</span><strong>{board?.counts.candidates ?? (loading ? '…' : 0)}</strong><small>Stored on this computer</small></div>
      <div><span>READY FOR REVIEW</span><strong>{board?.counts.review_ready ?? (loading ? '…' : 0)}</strong><small>Not published</small></div>
      <div><span>APPROVED FOR EXPORT</span><strong>{board?.counts.approved_for_export ?? (loading ? '…' : 0)}</strong><small>Seller uploads separately</small></div>
      <div><span>VERIFIED SALES</span><strong>—</strong><small>No sales feed connected</small></div>
    </section>

    <div className="commerce-workspace">
      <section className="commerce-main" aria-label="Product pipeline">
        {showCreate && !preview && <form className="commerce-create" onSubmit={event => {
          event.preventDefault()
          void mutate('commerceCreate', {title, concept, channel}, 'Candidate saved privately.')
        }}>
          <div className="commerce-section-heading"><div><p className="commerce-kicker">01 / CONCEPT</p><h2>Start with a real buyer problem</h2></div></div>
          <label className="commerce-field"><span>Marketplace</span>
            <select aria-label="Choose marketplace" value={channel} onChange={event => setChannel(event.target.value as Channel)}>
              {platforms.map(platform => <option value={platform.id} key={platform.id}>{platform.label}</option>)}
            </select>
          </label>
          <label className="commerce-field"><span>Original product or service title</span>
            <input value={title} onChange={event => setTitle(event.target.value)} maxLength={120} required placeholder="e.g. Editable indie streamer identity kit"/>
          </label>
          <label className="commerce-field"><span>Creative brief / customer problem</span>
            <textarea rows={4} value={concept} maxLength={3000} required onChange={event => setConcept(event.target.value)} placeholder="Who needs this? What exactly is different? What editable source files or service outcome will they receive?"/>
          </label>
          <button className="commerce-action-primary" type="submit" disabled={busy || !title.trim() || !concept.trim()}>Save candidate <ArrowRight size={15}/></button>
        </form>}

        <div className="commerce-section-heading">
          <div><p className="commerce-kicker">02 / PIPELINE</p><h2>Candidate library</h2></div>
          <button type="button" className="commerce-icon" disabled={preview || loading} aria-label="Refresh candidates" onClick={() => void refresh()}><RefreshCw size={17}/></button>
        </div>
        <div className="commerce-filters" role="group" aria-label="Filter candidates">
          <button type="button" aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All</button>
          {platforms.map(item => <button type="button" key={item.id} aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>{item.label}</button>)}
        </div>
        {loading ? <p className="commerce-empty">Loading your local records…</p> :
          ideas.length === 0 ? <div className="commerce-empty">
            <FilePenLine size={25} strokeWidth={1.5}/>
            <h3>{board?.ideas.length ? 'No candidates on this marketplace' : 'Nothing to publish yet'}</h3>
            <p>Create an original product brief to begin. STAR won't manufacture sales figures, upload unreviewed art or publish placeholder listings.</p>
          </div> :
          <div className="commerce-list">
            {ideas.map(item => <button className="commerce-item" aria-pressed={item.id === selectedId}
              key={item.id} type="button" onClick={() => setSelectedId(item.id)}>
              <span className="commerce-item-icon"><Store size={18}/></span>
              <span className="commerce-item-body">
                <strong>{item.title}</strong>
                <small>{platforms.find(p => p.id === item.channel)?.label} · {statusText[item.status]}</small>
              </span>
              <span className={item.review.ready ? 'commerce-done' : 'commerce-count'}>
                {item.review.ready ? 'Review ready' : item.review.blockers.length + ' checks'}
              </span>
              <ArrowRight size={15}/>
            </button>)}
          </div>}
      </section>

      <aside className="commerce-review" aria-label="Quality and permissions">
        {selected && !preview ? <>
          <p className="commerce-kicker">03 / APPROVAL DESK</p>
          <h2>{selected.title}</h2>
          <p className="commerce-concept">{selected.concept}</p>
          <div className="commerce-review-status">
            <ClipboardCheck size={17}/>
            <div><strong>{selected.review.ready ? 'Ready for owner review' : 'Evidence incomplete'}</strong><span>{statusText[selected.status]} · Not published</span></div>
          </div>
          {selected.review.blockers.length > 0 && <div className="commerce-blockers">
            <h3>Before this can be approved</h3>
            <ul>{selected.review.blockers.map(reason => <li key={reason}>{reason}</li>)}</ul>
          </div>}
          <div className="commerce-evidence">
            <Field title="Rights and originality record" hint="Record real sources and license review, not a guess." value={evidence.rights_evidence || ''} onChange={v => changeEvidence('rights_evidence', v)}/>
            <Field title="Visual and delivery QA record" hint="Describe inspected files, screenshots or corrections." value={evidence.visual_qa_evidence || ''} onChange={v => changeEvidence('visual_qa_evidence', v)}/>
            {selected.channel === 'fiverr' ? <>
              <Field title="Buyer brief and acceptance criteria" value={evidence.buyer_brief || ''} onChange={v => changeEvidence('buyer_brief', v)}/>
              <Field title="Meaningful customized work performed" value={evidence.customization_evidence || ''} onChange={v => changeEvidence('customization_evidence', v)}/>
              <CheckField title="Buyer permits AI-assisted work" checked={!!evidence.buyer_allows_ai} onChange={v => changeEvidence('buyer_allows_ai', v)}/>
            </> : <>
              <CheckField title="AI assistance disclosed in proposed listing" checked={!!evidence.ai_disclosed} onChange={v => changeEvidence('ai_disclosed', v)}/>
              <CheckField title="Mockup matches the actual deliverable" checked={!!evidence.accurate_mockup_reviewed} onChange={v => changeEvidence('accurate_mockup_reviewed', v)}/>
              {selected.channel === 'printify' && <>
                <CheckField title="Production partner and dispatch details disclosed" checked={!!evidence.partner_disclosed} onChange={v => changeEvidence('partner_disclosed', v)}/>
                <Field title="Physical sample and supplier cost review" value={evidence.sample_evidence || ''} onChange={v => changeEvidence('sample_evidence', v)}/>
              </>}
            </>}
            <button type="button" className="commerce-action-secondary" disabled={busy} onClick={() => void mutate('commerceEvidence', {id: selected.id, evidence}, 'Evidence saved. Prior approvals were reset.')}>Save evidence</button>
            <div className="commerce-approval-actions">
              <button type="button" disabled={busy || !selected.review.ready || selected.status === 'approved_for_export'}
                className="commerce-action-primary" onClick={() => void mutate('commerceReview',
                  {id: selected.id, decision: 'approve', owner_confirmed: true},
                  'Locally approved for export only; no marketplace action occurred.')}>
                <ShieldCheck size={16}/> Approve for export
              </button>
              <button type="button" disabled={busy} className="commerce-action-secondary" onClick={() => void mutate('commerceReview',
                {id: selected.id, decision: 'changes', owner_confirmed: true}, 'Changes requested in STAR.')}>Request changes</button>
            </div>
            <p className="commerce-footnote">Approval only changes your private STAR record. Seller identity verification, pricing, listing uploads, customer messages and transactions are not enabled.</p>
          </div>
        </> : <>
          <p className="commerce-kicker">03 / OPERATIONS</p>
          <h2>A safe default is an advantage.</h2>
          <p className="commerce-aside-copy">Every new candidate starts unpublished. A quality gate reviews disclosure, originality and evidence before export.</p>
          <div className="commerce-rule"><LockKeyhole size={18}/><div><strong>Marketplace accounts</strong><span>Not connected to this desktop module.</span></div></div>
          <div className="commerce-rule"><FolderOpen size={18}/><div><strong>Customer data</strong><span>Never stored in a public GitHub repository.</span></div></div>
          <div className="commerce-rule"><ShieldCheck size={18}/><div><strong>Publishing and spending</strong><span>No automatic execution or hidden account bots.</span></div></div>
          <p className="commerce-footnote">Current project: {project}. Browser preview and the installed desktop share a UI, not customer information.</p>
        </>}
      </aside>
    </div>
  </div>
}
