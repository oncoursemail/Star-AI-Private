import {useEffect, useState, type ReactNode} from 'react'
import {ChevronDown, FolderOpen} from 'lucide-react'
import {StarFace, type StarMood} from './StarFace'
import './studio.css'

/** Only the layout changes with the viewport; the chat and composer keep their identity. */
export function useCompactStudio() {
  const [compact, setCompact] = useState(() => typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 1179px)').matches)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const media = window.matchMedia('(max-width: 1179px)')
    const update = () => setCompact(media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  return compact
}

export function StudioFrame({enabled = true, children, companion, compact, companionVisible}: {
  enabled?: boolean
  children: ReactNode
  companion: ReactNode
  compact: boolean
  companionVisible: boolean
}) {
  if (!enabled) return <>{children}</>
  return <div className="studio-frame" data-compact={compact} data-companion-visible={companionVisible}>
    <div className="studio-workspace">{children}</div>
    <div className="studio-companion-region">{companion}</div>
  </div>
}

export function StudioProjectSwitch({project, onOpen}: {project: string; onOpen: () => void}) {
  return <button className="studio-project-switch" type="button" aria-label="Choose workspace" onClick={onOpen}>
    <span className="studio-project-symbol" aria-hidden="true"><FolderOpen size={18}/></span>
    <span className="studio-project-copy"><small>Workspace</small><strong dir="auto" title={project}>{project}</strong></span>
    <ChevronDown size={14} aria-hidden="true"/>
  </button>
}

export function StudioWelcome({mood}: {mood: StarMood}) {
  return <section className="studio-welcome" aria-labelledby="studio-welcome-heading">
    <div className="studio-welcome-signature">
      <StarFace mood={mood} size={66} follow className="thread-hello-star" label="Star, STAR's mascot"/>
      <span>A fresh conversation</span>
    </div>
    <h2 id="studio-welcome-heading">What are we making?</h2>
    <p>Bring a question, a rough idea, or a piece of code.</p>
  </section>
}

export function StudioInputHint() {
  return <div className="studio-input-hint"><span><kbd>Enter</kbd> to send</span><span><kbd>Shift + Enter</kbd> for a new line</span></div>
}
