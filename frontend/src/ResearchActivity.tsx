import {memo, useId, useState} from 'react'
import {BookOpen, Check, ChevronDown, CircleHelp, ExternalLink, FileText, GitBranch, Search, X} from 'lucide-react'
import type {ResearchActivityState, ResearchQuery, ResearchSource} from './research-activity'
import {researchPhase, safeResearchUrl} from './research-activity'
import './research-activity.css'

/** Original STAR research mark. Inline paths keep it sharp and available offline. */
export function ResearchMark({size = 18}: {size?: number}) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    <circle cx="9.5" cy="9.5" r="6.5" />
    <path d="m14.3 14.3 6.2 6.2M9.5 6.2l1.1 2.2 2.2 1.1-2.2 1.1-1.1 2.2-1.1-2.2-2.2-1.1 2.2-1.1Z" />
  </svg>
}

const sourceState = (source: ResearchSource) => source.state === 'reading' ? 'Reading'
  : source.state === 'read' ? 'Read'
    : source.state === 'failed' ? 'Could not read'
      : source.state === 'cancelled' ? 'Stopped' : 'Not read'

function SourceCard({source}: {source: ResearchSource}) {
  const url = safeResearchUrl(source.url)
  const domain = url ? new URL(url).hostname : ''
  const reading = source.state === 'reading'
  const content = <>
    <span className="research-source-icon"><FileText size={16} aria-hidden="true" /></span>
    <span className="research-source-copy">
      <span className="research-source-title" dir="auto">{source.title}</span>
      {domain && <span className="research-source-domain" dir="ltr">{domain}</span>}
    </span>
    {url && <ExternalLink size={13} className="research-external" aria-hidden="true" />}
  </>
  return <li className={'research-source is-' + source.state}>
    {url ? <a className="research-source-link" href={url} target="_blank" rel="noopener noreferrer" title={url}>
      {content}<span className="sr-only"> (opens in a new tab)</span>
    </a> : <div className="research-source-link">{content}</div>}
    <div className="research-source-meta">
      <span className="research-source-id">{source.id}</span>
      <span className="research-source-state">
        {source.state === 'read' ? <Check size={12} aria-hidden="true" />
          : source.state === 'failed' ? <X size={12} aria-hidden="true" />
            : reading ? <BookOpen size={12} aria-hidden="true" /> : null}
        {sourceState(source)}
      </span>
    </div>
  </li>
}

function QueryRow({query}: {query: ResearchQuery}) {
  const state = query.state === 'running' ? 'Searching' : query.state === 'completed' ? 'Done' : query.state === 'cancelled' ? 'Stopped' : query.state === 'not_completed' ? 'Not finished' : 'Failed'
  return <li className={'research-query is-' + query.state}>
    <Search size={14} aria-hidden="true" />
    <span>Search {query.ordinal}</span>
    <span className="research-query-state">{state}</span>
  </li>
}

/** The parent owns disclosure, elapsed time and cancellation; this view only renders real research data. */
export const ResearchActivity = memo(function ResearchActivity({research}: {research: ResearchActivityState}) {
  const [allSources, setAllSources] = useState(false)
  const [allQueries, setAllQueries] = useState(false)
  const sourceListId = useId()
  const queryListId = useId()
  const sourceHeadingId = useId()
  const sources = allSources ? research.sources : research.sources.slice(0, 4)
  const queries = allQueries ? research.queries : research.queries.slice(-3)
  const PhaseIcon = research.phase === 'read' ? BookOpen : research.phase === 'followup' ? GitBranch : Search
  const incomplete = research.outcome !== 'running' && research.outcome !== 'completed'
  return <div className="research-activity">
    <div className={'research-phase' + (incomplete ? ' is-incomplete' : '')}>
      {incomplete ? <CircleHelp size={16} aria-hidden="true" />
        : research.outcome === 'completed' ? <Check size={16} aria-hidden="true" />
          : <PhaseIcon size={16} aria-hidden="true" />}
      <span>{researchPhase(research)}</span>
    </div>
    <dl className="research-counts" aria-label="Observed research activity">
      <div><dt>Found</dt><dd>{research.counts.found}</dd></div>
      <div><dt>Read</dt><dd>{research.counts.read}</dd></div>
      {research.counts.failed > 0 && <div><dt>Could not read</dt><dd>{research.counts.failed}</dd></div>}
    </dl>
    {research.queries.length > 0 && <div className="research-searches">
      <ol className="research-queries" id={queryListId} aria-label="Search activity">
        {queries.map(query => <QueryRow key={query.id} query={query} />)}
      </ol>
      {research.queries.length > 3 && <button className="research-more" type="button" aria-expanded={allQueries} aria-controls={queryListId} onClick={() => setAllQueries(!allQueries)}>
        {allQueries ? 'Show recent searches' : `Show all ${research.queries.length} searches`}
        <ChevronDown size={13} aria-hidden="true" />
      </button>}
    </div>}
    <section className="research-sources" aria-labelledby={sourceHeadingId}>
      <div className="research-sources-head"><h3 id={sourceHeadingId}>Sources</h3><span>Page reading status</span></div>
      {sources.length > 0 ? <ul className="research-source-list" id={sourceListId}>
        {sources.map(source => <SourceCard key={source.key} source={source} />)}
      </ul> : <p className="research-empty">{research.outcome === 'running' ? 'Source pages will appear as STAR begins reading them.' : 'No source pages were read.'}</p>}
      {research.sources.length > 4 && <button className="research-more" type="button" aria-expanded={allSources} aria-controls={sourceListId} onClick={() => setAllSources(!allSources)}>
        {allSources ? 'Show fewer sources' : `Show all ${research.sources.length} sources`}
        <ChevronDown size={13} aria-hidden="true" />
      </button>}
    </section>
    {research.citations && <section className="research-citations" aria-label="Citation reference checks">
      <div><FileText size={15} aria-hidden="true" /><strong>Citation references</strong></div>
      <p>{research.citations.checked} checked · {research.citations.invalid} unresolved</p>
      <p className="research-note">Checks references against this research session. Whether sources support each claim has not been checked.</p>
    </section>}
  </div>
})
