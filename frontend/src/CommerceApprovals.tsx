import {Check, CircleAlert, Play, ShieldCheck, X} from 'lucide-react'

export type Approval = {
  id: string
  kind: string
  kind_label: string
  title: string
  payload: Record<string, unknown>
  amount_cents: number | null
  status: 'pending' | 'approved' | 'rejected' | 'executing' | 'executed' | 'failed'
  proposed_by: string
  result: {executed?: boolean; reason?: string; error?: string}
  created_at: string
}

const money = (cents: number | null) => cents === null ? '' : '$' + (cents / 100).toFixed(2)

/** The one gate: STAR drafts these, only the owner's click approves or runs them. */
export function CommerceApprovals({approvals, busy, onAct}: {
  approvals: Approval[]; busy: boolean
  onAct: (action: 'commerceApprovalDecide' | 'commerceApprovalExecute', payload: Record<string, unknown>, message: string) => void
}) {
  const waiting = approvals.filter(a => a.status === 'pending')
  const approved = approvals.filter(a => a.status === 'approved')
  const past = approvals.filter(a => !['pending', 'approved'].includes(a.status)).slice(0, 8)
  return <section className="commerce-approvals" aria-label="Actions waiting for your approval">
    <div className="commerce-section-heading"><div>
      <p className="commerce-kicker">APPROVALS</p>
      <h2>{waiting.length ? waiting.length + ' waiting for you' : 'Nothing waiting'}</h2>
    </div></div>
    <p className="commerce-footnote">STAR researches and drafts on its own. Anything that spends money, places or changes an order, lists or prices a product, posts publicly, messages a customer or changes an account waits here until you approve it.</p>
    {approvals.length === 0 && <p className="commerce-empty"><ShieldCheck size={18}/> No proposed actions yet.</p>}
    {[...waiting, ...approved].map(item => <article className="commerce-approval-card" key={item.id}>
      <header>
        <strong>{item.title}</strong>
        <span className="commerce-count">{item.kind_label}{item.amount_cents !== null ? ' · ' + money(item.amount_cents) : ''}</span>
      </header>
      <pre className="commerce-approval-details">{JSON.stringify(item.payload, null, 2)}</pre>
      {item.status === 'pending' ? <div className="commerce-approval-actions">
        <button type="button" className="commerce-action-primary" disabled={busy}
          onClick={() => onAct('commerceApprovalDecide', {id: item.id, decision: 'approve', owner_confirmed: true},
            'Approved. Nothing has run yet.')}><Check size={15}/> Approve{item.amount_cents ? ' ' + money(item.amount_cents) : ''}</button>
        <button type="button" className="commerce-action-secondary" disabled={busy}
          onClick={() => onAct('commerceApprovalDecide', {id: item.id, decision: 'reject', owner_confirmed: true},
            'Rejected. It will not run.')}><X size={15}/> Reject</button>
      </div> : <div className="commerce-approval-actions">
        <button type="button" className="commerce-action-primary" disabled={busy}
          onClick={() => onAct('commerceApprovalExecute', {id: item.id}, 'Run requested.')}><Play size={15}/> Run approved action</button>
        {item.result.reason && <span className="commerce-footnote"><CircleAlert size={14}/> {item.result.reason}</span>}
      </div>}
    </article>)}
    {past.length > 0 && <ul className="commerce-approval-history" aria-label="Recent decisions">
      {past.map(item => <li key={item.id}>{item.status}: {item.title}{item.result.error ? ' (' + item.result.error + ')' : ''}</li>)}
    </ul>}
  </section>
}
