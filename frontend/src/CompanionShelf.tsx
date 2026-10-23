import {useEffect, useId, useRef, useState} from 'react'
import {Check, ChevronDown, EyeOff, Pause, Play, Sparkle, X} from 'lucide-react'
import type {PetState} from './StarPet'
import {useStarReducedMotion} from './MotionPolicy'
import {usePageVisible} from './usePageVisible'
import {COMPANIONS, companionCharacter, companionImage, companionWorkLabel} from './companion-catalog'
import type {CompanionPreferences} from './companion-catalog'
import './companion-shelf.css'

export type CompanionShelfProps = {
  state: PetState
  reducedMotion: boolean
  preferences: CompanionPreferences
  onPreferencesChange: (preferences: CompanionPreferences) => void
  /** Collapses the stage to a disclosure on small windows; no hidden animation runs. */
  compact?: boolean
  className?: string
}

type CompanionControlProps = Pick<CompanionShelfProps, 'preferences' | 'onPreferencesChange' | 'reducedMotion' | 'className'>

function CompanionChoices({preferences, onPreferencesChange, legend = false}: Pick<CompanionControlProps, 'preferences' | 'onPreferencesChange'> & {legend?: boolean}) {
  const id = useId()
  return <fieldset className="companion-choices">
    <legend className={legend ? 'companion-controls__label' : 'sr-only'}>{legend ? 'Character' : 'Choose your companion'}</legend>
    {COMPANIONS.map(item => <label key={item.id} data-character={item.id} className={'companion-choice' + (preferences.character === item.id ? ' is-selected' : '')}>
      <input type="radio" name={id + '-character'} value={item.id} checked={preferences.character === item.id}
        onChange={() => onPreferencesChange({...preferences, character: item.id})}/>
      <span className="companion-choice__portrait" aria-hidden="true"><img src={item.image} alt="" draggable={false} loading="lazy" decoding="async"/></span>
      <span className="companion-choice__name">{item.name}</span>
      {preferences.character === item.id && <Check className="companion-choice__check" size={11} aria-hidden="true"/>}
    </label>)}
  </fieldset>
}

/** The same local preferences can be edited from the workbench Appearance drawer. */
export function CompanionControls({preferences, onPreferencesChange, reducedMotion, className = ''}: CompanionControlProps) {
  const policyReduced = useStarReducedMotion()
  const id = useId()
  return <div className={'companion-controls ' + className}>
    <label className="companion-controls__visibility">
      <span>Show companions</span>
      <input type="checkbox" checked={preferences.visible} onChange={event => onPreferencesChange({...preferences, visible: event.target.checked})}/>
    </label>
    <CompanionChoices preferences={preferences} onPreferencesChange={onPreferencesChange} legend/>
    <label className="companion-controls__motion" htmlFor={id + '-motion'}>
      <span>Companion motion</span>
      <select id={id + '-motion'} value={preferences.motion} aria-describedby={reducedMotion || policyReduced ? id + '-note' : undefined}
        onChange={event => onPreferencesChange({...preferences, motion: event.target.value === 'still' ? 'still' : 'subtle'})}>
        <option value="subtle">Subtle reactions</option>
        <option value="still">Still</option>
      </select>
    </label>
    {(reducedMotion || policyReduced) && <p id={id + '-note'} className="companion-controls__note">Your reduced-motion preference keeps companions still.</p>}
  </div>
}

export function CompanionShelf({state, reducedMotion, preferences, onPreferencesChange, compact = false, className = ''}: CompanionShelfProps) {
  const pageVisible = usePageVisible()
  const policyReduced = useStarReducedMotion()
  const id = useId()
  const heading = useRef<HTMLHeadingElement>(null)
  const shelf = useRef<HTMLElement>(null)
  const reopen = useRef<HTMLButtonElement>(null)
  const hadShelfFocus = useRef(false)
  const [expanded, setExpanded] = useState(false)
  const [failedSource, setFailedSource] = useState<string | null>(null)
  const [reaction, setReaction] = useState<'greet' | 'focus' | 'complete' | null>(null)
  const previous = useRef({character: preferences.character, state})
  const restoreFocus = useRef(false)
  const character = companionCharacter(preferences.character)
  const source = companionImage(character, state)
  const open = preferences.visible && (!compact || expanded)
  const still = reducedMotion || policyReduced || preferences.motion === 'still' || !pageVisible || !open

  useEffect(() => {
    const characterChanged = previous.current.character !== character.id
    const stateChanged = previous.current.state !== state
    previous.current = {character: character.id, state}
    if (still) { setReaction(null); return }
    if (characterChanged) setReaction('greet')
    else if (stateChanged) setReaction(state === 'finished' ? 'complete' : state === 'thinking' || state === 'streaming' ? 'focus' : 'greet')
  }, [character.id, state, still])
  useEffect(() => {
    // A responsive collapse can remove the focused radio or close control.
    // Restore only focus that belonged to this region, never the draft/composer.
    const lostShelfFocus = hadShelfFocus.current && !shelf.current?.contains(document.activeElement)
    if (!restoreFocus.current && !lostShelfFocus) return
    restoreFocus.current = false
    if (open) heading.current?.focus()
    else reopen.current?.focus()
    hadShelfFocus.current = open
  }, [open, compact])
  useEffect(() => {
    if (!compact) setExpanded(false)
  }, [compact])

  const show = () => {
    restoreFocus.current = true
    if (!preferences.visible) onPreferencesChange({...preferences, visible: true})
    if (compact) setExpanded(true)
  }
  const hide = () => {
    restoreFocus.current = true
    setExpanded(false)
    onPreferencesChange({...preferences, visible: false})
  }
  if (!open) return <button ref={reopen} type="button" className={'companion-reopen ' + (preferences.visible ? 'is-compact ' : 'is-hidden ') + className} onClick={show}
    aria-expanded={false} aria-label={preferences.visible ? 'Open companions' : 'Show companions'}>
    <span className="companion-reopen__portrait" data-character={character.id} aria-hidden="true"><img src={character.image} alt="" draggable={false}/></span>
    <span className="companion-reopen__copy">{preferences.visible ? <><strong>{character.name}</strong><span>Companion</span></> : 'Show companions'}</span><ChevronDown size={14} aria-hidden="true"/>
  </button>

  return <section ref={shelf} className={'companion-shelf ' + (compact ? 'is-compact ' : '') + className} aria-labelledby={id + '-title'}
    onFocusCapture={() => { hadShelfFocus.current = true }} onBlurCapture={event => {
      if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) hadShelfFocus.current = false
    }}
    data-character={character.id} data-still={still || undefined} data-work-state={state}>
    <header className="companion-shelf__header">
      <h2 id={id + '-title'} ref={heading} tabIndex={-1}>Companions</h2>
      <div className="companion-shelf__controls">
        <button type="button" className="companion-icon-button"
          aria-label={preferences.motion === 'still' ? 'Allow subtle companion motion' : 'Keep companions still'}
          aria-pressed={preferences.motion === 'still'}
          title={reducedMotion || policyReduced ? 'Reduced motion is active' : preferences.motion === 'still' ? 'Allow subtle motion' : 'Keep still'}
          onClick={() => onPreferencesChange({...preferences, motion: preferences.motion === 'still' ? 'subtle' : 'still'})}>
          {preferences.motion === 'still' ? <Play size={15} aria-hidden="true"/> : <Pause size={15} aria-hidden="true"/>}
        </button>
        {compact ? <button type="button" className="companion-icon-button" aria-label="Close companions" onClick={() => {
          restoreFocus.current = true; setExpanded(false)
        }}><X size={15} aria-hidden="true"/></button> : null}
        <button type="button" className="companion-icon-button" aria-label="Hide companions" title="Hide companions" onClick={hide}>
          <EyeOff size={15} aria-hidden="true"/>
        </button>
      </div>
    </header>
    <div className="companion-shelf__stage" aria-hidden="true">
      {failedSource === source ? <div className="companion-shelf__missing"><Sparkle size={38}/><span>Portrait unavailable</span></div> :
        <img className="companion-shelf__character" src={source} alt="" draggable={false} decoding="async"
          data-reaction={still ? undefined : reaction ?? undefined}
          onAnimationEnd={event => { if (event.target === event.currentTarget) setReaction(null) }}
          onError={() => setFailedSource(source)}/>}
      <span className="companion-shelf__floor"/>
    </div>
    <div className="companion-shelf__identity">
      <strong>{character.name}</strong>
      <p>{companionWorkLabel(state)}</p>
      {(reducedMotion || policyReduced) && <span className="companion-shelf__motion-note">Reduced motion is on</span>}
    </div>
    <CompanionChoices preferences={preferences} onPreferencesChange={onPreferencesChange}/>
    <p className="companion-shelf__caption">A little company for your workspace.</p>
  </section>
}
